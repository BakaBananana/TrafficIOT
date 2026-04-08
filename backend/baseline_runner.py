"""
baseline_runner.py
──────────────────
Runs SUMO with FIXED-TIMING control (no RL agent).
Traffic lights use their default phase cycles — no AI interventions.

Used to generate a baseline for comparison against the STGAT-PPO agent.
Same lifecycle and snapshot format as SumoInferenceRunner.
"""

import os
import sys
import random

SIM_DIR = os.path.join(os.path.dirname(__file__), "simulation")
if SIM_DIR not in sys.path:
    sys.path.insert(0, SIM_DIR)

import traci


class BaselineRunner:
    """
    Fixed-timing SUMO runner — no RL agent, just default phase cycles.
    Same step-by-step API as SumoInferenceRunner for easy comparison.
    """

    MAX_STEPS = 4500

    def __init__(self):
        self.env = None
        self.initialized = False

        self._episode = 0
        self._num_vehicles = 0
        self._step = 0
        self._cumulative_queue = 0.0
        self._cumulative_wait = 0.0
        self._episode_active = False
        self._max_steps = self.MAX_STEPS

    # ── Initialization ──────────────────────────────────────────────────
    def initialize(self, use_gui=False):
        if self.initialized:
            return

        sys.modules["libsumo"] = traci

        print(f"Hello from baseline_runner (gui={use_gui})")

        from env_sumo import SumoGraphEnv

        original_cwd = os.getcwd()
        os.chdir(SIM_DIR)
        try:
            cfg_path = "stc_simulation.sumocfg"
            net_path = "patna_stc.net.xml"
            self.env = SumoGraphEnv(
                sumo_cfg_path=cfg_path,
                net_file_path=net_path,
                gui=use_gui,
            )
        finally:
            os.chdir(original_cwd)

        self.initialized = True
        print(f"[BASE] Initialized — {self.env.num_nodes} intersections")

    # ── Episode lifecycle ────────────────────────────────────────────────
    def start_episode(self, episode: int, num_vehicles: int,
                      max_steps: int = 4500, spawn: int = 3540, seed: int = 42):
        if not self.initialized:
            self.initialize()

        self._episode = episode
        self._num_vehicles = num_vehicles
        self._step = 0
        self._cumulative_queue = 0.0
        self._cumulative_wait = 0.0
        self._episode_active = True
        self._max_steps = max_steps

        episode_seed = seed

        original_cwd = os.getcwd()
        os.chdir(SIM_DIR)
        try:
            self.env.reset(seed=episode_seed, num_vehicles=num_vehicles, spawn=spawn)
        finally:
            os.chdir(original_cwd)

        return {
            "type": "episode_start",
            "episode": episode,
            "num_vehicles": num_vehicles,
            "mode": "baseline",
        }

    def step(self) -> dict | None:
        """Run one SUMO second with NO agent — pure fixed timing."""
        if not self._episode_active:
            return None

        if self._step >= self._max_steps:
            return self._end_episode()

        # ── No agent — just advance the simulation ──────────────────────
        traci.simulationStep()

        # ── Read metrics directly via traci (avoid env.get_state which ──
        # freezes phases via setPhaseDuration!) ─────────────────────────
        pcu_weights = {
            "motorcycle_ind": 0.5, "car_ind": 1.0,
            "auto_ind": 1.0, "bus_ind": 3.0,
        }

        total_queue_val = 0.0
        total_wait_val  = 0.0
        intersections   = []

        for i, tls in enumerate(self.env.tls_ids):
            queue_pcu  = 0.0
            max_wait   = 0.0
            controlled = traci.trafficlight.getControlledLinks(tls)
            lanes      = set(link[0][0] for link in controlled if link)
            for lane in lanes:
                for veh in traci.lane.getLastStepVehicleIDs(lane):
                    try:
                        if traci.vehicle.getSpeed(veh) < 0.1:
                            vtype    = traci.vehicle.getTypeID(veh)
                            wait     = traci.vehicle.getAccumulatedWaitingTime(veh)
                            queue_pcu += pcu_weights.get(vtype, 1.0)
                            if wait > max_wait:
                                max_wait = wait
                    except Exception:
                        continue
            total_queue_val += queue_pcu
            total_wait_val  += max_wait
            current_phase = traci.trafficlight.getPhase(tls)
            intersections.append({
                "id":          tls,
                "index":       i,
                "queue_pcu":   round(queue_pcu, 2),
                "wait_time_s": round(max_wait, 2),
                "phase":       current_phase,
                "action":      0,
            })

        num_nodes    = self.env.num_nodes
        avg_wait_val = total_wait_val / num_nodes
        active_vehicles = traci.simulation.getMinExpectedNumber()

        self._cumulative_queue += total_queue_val
        self._cumulative_wait  += avg_wait_val

        snapshot = {
            "type":            "step",
            "mode":            "baseline",
            "episode":         self._episode,
            "step":            self._step,
            "timestamp_s":     self._step,
            "active_vehicles": active_vehicles,
            "total_queue_pcu": round(total_queue_val, 2),
            "avg_wait_s":      round(avg_wait_val, 2),
            "step_reward":     -(total_queue_val + 0.5 * total_wait_val),
            "switches":        0,
            "intersections":   intersections,
        }

        self._step += 1
        return snapshot

    def is_done(self) -> bool:
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
        return self._end_episode()

    def _end_episode(self) -> dict:
        self._episode_active = False
        avg_queue = self._cumulative_queue / max(self._step, 1)
        avg_wait  = self._cumulative_wait  / max(self._step, 1)
        return {
            "type":            "episode_end",
            "mode":            "baseline",
            "episode":         self._episode,
            "num_vehicles":    self._num_vehicles,
            "avg_queue_pcu":   round(avg_queue, 2),
            "avg_wait_s":      round(avg_wait, 2),
            "steps_completed": self._step,
        }

    def cleanup(self):
        if self.env:
            try:
                self.env.close()
            except Exception:
                pass
            try:
                traci.close()
            except Exception:
                pass
