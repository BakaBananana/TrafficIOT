"""
sumo_inference.py
─────────────────
Wraps SumoGraphEnv + STGAT-PPO model for step-by-step inference,
designed to be called from the FastAPI WebSocket handler.

Each `step()` call runs exactly one SUMO simulation second and returns
a snapshot dict matching the dashboard's JSON protocol.
"""

import os
import sys
import random
import numpy as np
import torch

# Add the simulation directory to sys.path so we can import env / models
SIM_DIR = os.path.join(os.path.dirname(__file__), "simulation")
if SIM_DIR not in sys.path:
    sys.path.insert(0, SIM_DIR)

# We use traci (subprocess mode) — SUMO runs as a separate process,
# which is cleaner for the async backend (easy to terminate, no global state).
# The env_sumo.py uses `libsumo as traci` by default. We need to handle that.
# We'll import our own traci and monkey-patch the env if needed.
import traci


class SumoInferenceRunner:
    """
    Step-by-step SUMO inference runner for the dashboard WebSocket.

    Lifecycle:
        runner = SumoInferenceRunner()
        runner.initialize()                    # loads model + env (once)
        runner.start_episode(episode, n_vehs)  # resets SUMO
        for _ in range(max_steps):
            snapshot = runner.step()            # one sim second → dict
            if snapshot is None: break         # episode done
        runner.cleanup()                       # close SUMO
    """

    # ── Configuration ──────────────────────────────────────────────────
    K_HOPS = 3
    HIDDEN_DIM = 128
    MODEL_FILENAME = "stgat_ppo_best_real_actual_consistent.pth"
    MAX_STEPS = 4500

    def __init__(self):
        self.env = None
        self.model = None
        self.device = None
        self.adj_matrix = None
        self.initialized = False

        # Episode state
        self._episode = 0
        self._num_vehicles = 0
        self._step = 0
        self._h_prev = None
        self._state = None
        self._hardware_locks = None
        self._time_since_update = None
        self._cumulative_reward = 0.0
        self._total_switches = 0
        self._episode_active = False
        self._max_steps = self.MAX_STEPS

    # ── Initialization ─────────────────────────────────────────────────
    def initialize(self, use_gui=False):
        """Load the model and initialize the environment (run once)."""
        if self.initialized:
            return

        # We need to handle the import conflict: env_sumo.py imports
        # `libsumo as traci` at module level. We'll patch sys.modules
        # so that `import libsumo` actually returns the `traci` module,
        # letting env_sumo.py work with subprocess-mode traci.
        sys.modules["libsumo"] = traci

        from env_sumo import SumoGraphEnv
        from models import STGAT_ActorCritic

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # env_sumo.py uses relative paths for generate_demand.py and
        # traci.start(sumo_cmd). We must chdir into simulation/ so
        # those relative references resolve correctly.
        original_cwd = os.getcwd()
        os.chdir(SIM_DIR)

        try:
            # Initialize environment — starts/stops SUMO to read topology
            cfg_path = "stc_simulation.sumocfg"
            net_path = "patna_stc.net.xml"

            self.env = SumoGraphEnv(
                sumo_cfg_path=cfg_path,
                net_file_path=net_path,
                gui=use_gui,
            )
        finally:
            os.chdir(original_cwd)

        # Load model
        model_path = os.path.join(SIM_DIR, self.MODEL_FILENAME)
        self.model = STGAT_ActorCritic(
            feature_dim=4,
            hidden_dim=self.HIDDEN_DIM,
            num_actions=2,
            k_hops=self.K_HOPS,
        )
        self.model.to(self.device)

        if os.path.exists(model_path):
            checkpoint = torch.load(model_path, map_location=self.device)
            self.model.load_state_dict(checkpoint["model_state_dict"])
            ep = checkpoint.get("episode", "?")
            print(f"[SUMO] Loaded model from {model_path} (trained episode: {ep})")
        else:
            raise FileNotFoundError(
                f"Model checkpoint not found: {model_path}"
            )

        self.model.eval()
        self.adj_matrix = self.env.adjacency_matrix.clone().detach().to(self.device)
        self.initialized = True
        print(f"[SUMO] Initialized — {self.env.num_nodes} intersections detected")

    # ── Episode lifecycle ──────────────────────────────────────────────
    def start_episode(self, episode: int, num_vehicles: int, max_steps: int = 4500, spawn: int = 3540, seed: int = 42):
        """Reset SUMO and prepare for a new episode."""
        if not self.initialized:
            self.initialize()

        self._episode = episode
        self._num_vehicles = num_vehicles
        self._step = 0
        self._cumulative_reward = 0.0
        self._total_switches = 0
        self._episode_active = True
        self._max_steps = max_steps

        num_nodes = self.env.num_nodes

        # Set seed for reproducibility
        episode_seed = seed

        # env.reset() calls subprocess.run(["python", "generate_demand.py", ...])
        # with a relative path, so we must chdir into the simulation directory.
        original_cwd = os.getcwd()
        os.chdir(SIM_DIR)
        try:
            self._state = self.env.reset(
                seed=episode_seed,
                num_vehicles=num_vehicles,
                spawn=spawn,
            ).to(self.device)
        finally:
            os.chdir(original_cwd)

        self._h_prev = torch.zeros(1, num_nodes, self.HIDDEN_DIM).to(self.device)
        self._hardware_locks = np.zeros(num_nodes, dtype=int)
        self._time_since_update = np.ones(num_nodes, dtype=float)

        return {
            "type": "episode_start",
            "episode": episode,
            "num_vehicles": num_vehicles,
        }

    def step(self) -> dict | None:
        """
        Execute one simulation second and return a snapshot dict.
        Returns None if the episode is finished.
        """
        if not self._episode_active:
            return None

        if self._step >= self._max_steps:
            return self._end_episode()

        num_nodes = self.env.num_nodes
        state_batched = self._state.unsqueeze(0)

        # ── 1. Model inference (no gradients) ──────────────────────────
        with torch.no_grad():
            action_probs, _, h_new = self.model(
                state_batched, self.adj_matrix, self._h_prev
            )

            logits = torch.log(action_probs + 1e-8)
            sharpened_probs = torch.softmax(logits, dim=-1)

            m = torch.distributions.Categorical(sharpened_probs)
            actions = m.sample().squeeze(0)
            actions_flat = actions.cpu().numpy()

            # Global zero-traffic safeguard
            if state_batched.sum().item() == 0:
                actions_flat = np.zeros(num_nodes, dtype=int)

        # ── 2. Asynchronous hardware execution & action masking ────────
        switches_this_step = 0

        for i, tls in enumerate(self.env.tls_ids):
            if self._hardware_locks[i] > 0:
                # Hardware is locked — AI is ignored
                self._hardware_locks[i] -= 1

                # Transition from yellow → green at the right moment
                if self._hardware_locks[i] == 10:
                    current_phase = traci.trafficlight.getPhase(tls)
                    logic = traci.trafficlight.getCompleteRedYellowGreenDefinition(tls)[0]
                    num_phases = len(logic.phases)
                    new_green = (current_phase + 1) % num_phases
                    traci.trafficlight.setPhase(tls, new_green)
                    traci.trafficlight.setPhaseDuration(tls, 100000)
            else:
                # Hardware is ready — will the AI switch?
                if actions_flat[i] == 1:
                    # ── Demand-responsive action mask ──────────────
                    controlled_links = traci.trafficlight.getControlledLinks(tls)
                    current_phase_state = traci.trafficlight.getRedYellowGreenState(tls)

                    cross_traffic_queue = 0
                    checked_lanes = set()

                    for j, link_group in enumerate(controlled_links):
                        if j < len(current_phase_state) and current_phase_state[j].lower() == "r":
                            if len(link_group) > 0:
                                lane_id = link_group[0][0]
                                if lane_id not in checked_lanes:
                                    cross_traffic_queue += traci.lane.getLastStepHaltingNumber(lane_id)
                                    checked_lanes.add(lane_id)

                    if cross_traffic_queue == 0:
                        # VETO — no cross traffic to serve
                        actions_flat[i] = 0
                    else:
                        # Legitimate switch
                        switches_this_step += 1
                        self._hardware_locks[i] = 13  # 3s yellow + 10s green

                        current_phase = traci.trafficlight.getPhase(tls)
                        logic = traci.trafficlight.getCompleteRedYellowGreenDefinition(tls)[0]
                        num_phases = len(logic.phases)
                        new_yellow = (current_phase + 1) % num_phases
                        traci.trafficlight.setPhase(tls, new_yellow)
                        traci.trafficlight.setPhaseDuration(tls, 100000)

        # ── 3. Step SUMO by 1 second ──────────────────────────────────
        traci.simulationStep()

        # ── 4. Read new state ─────────────────────────────────────────
        next_state = self.env.get_state(elapsed_time=self._time_since_update)
        active_vehicles = traci.simulation.getMinExpectedNumber()

        # Un-scale metrics for the dashboard
        step_queue_raw = (next_state[:, 0] * 50.0)
        step_wait_raw = (next_state[:, 1] * 100.0)

        total_queue_val = step_queue_raw.sum().item()
        sum_wait_val = step_wait_raw.sum().item()
        avg_wait_val = sum_wait_val / num_nodes

        # Calculate reward (matching training function)
        step_reward = -(total_queue_val + (0.5 * sum_wait_val)) - (
            switches_this_step * self.env.switching_penalty
        )
        self._cumulative_reward += step_reward
        self._total_switches += switches_this_step

        # ── 5. Build per-intersection snapshot ────────────────────────
        intersections = []
        for i, tls in enumerate(self.env.tls_ids):
            current_phase = traci.trafficlight.getPhase(tls)
            intersections.append({
                "id": tls,
                "index": i,
                "queue_pcu": round(step_queue_raw[i].item(), 2),
                "wait_time_s": round(step_wait_raw[i].item(), 2),
                "phase": current_phase,
                "action": int(actions_flat[i]),
            })

        snapshot = {
            "type": "step",
            "episode": self._episode,
            "step": self._step,
            "timestamp_s": self._step,
            "active_vehicles": active_vehicles,
            "total_queue_pcu": round(total_queue_val, 2),
            "avg_wait_s": round(avg_wait_val, 2),
            "step_reward": round(step_reward, 2),
            "switches": switches_this_step,
            "intersections": intersections,
        }

        # ── 6. Update recurrent state ─────────────────────────────────
        next_state = next_state.to(self.device)

        lock_mask = torch.tensor(
            self._hardware_locks > 0,
            dtype=torch.bool,
            device=self.device,
        ).unsqueeze(0).unsqueeze(-1)
        self._h_prev = torch.where(lock_mask, self._h_prev, h_new)
        self._state = next_state

        for i in range(num_nodes):
            if self._hardware_locks[i] > 0:
                self._time_since_update[i] += 1.0
            else:
                self._time_since_update[i] = 1.0

        self._step += 1

        # Check if simulation is done
        if active_vehicles == 0:
            return snapshot  # caller should check and call end_episode next

        return snapshot

    def is_done(self) -> bool:
        """Check if the current episode is finished."""
        if not self._episode_active:
            return True
        try:
            return (
                self._step >= self._max_steps
                or traci.simulation.getMinExpectedNumber() == 0
            )
        except Exception:
            return True

    def end_episode(self) -> dict:
        """Return episode summary and mark episode as inactive."""
        return self._end_episode()

    def _end_episode(self) -> dict:
        self._episode_active = False
        norm_reward = (
            self._cumulative_reward / self._num_vehicles
            if self._num_vehicles > 0
            else 0.0
        )
        return {
            "type": "episode_end",
            "episode": self._episode,
            "num_vehicles": self._num_vehicles,
            "cumulative_reward": round(self._cumulative_reward, 2),
            "normalized_reward": round(norm_reward, 4),
            "total_switches": self._total_switches,
            "steps_completed": self._step,
        }

    def cleanup(self):
        """Close SUMO process."""
        if self.env:
            try:
                self.env.close()
            except Exception:
                pass
            # Also try to close traci directly in case env.close() missed it
            try:
                traci.close()
            except Exception:
                pass
