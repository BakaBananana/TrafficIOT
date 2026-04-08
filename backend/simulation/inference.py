import os
import csv
import time
import random
import numpy as np
import torch
import libsumo as traci  # Use 'import traci' for GUI, or 'import libsumo as traci' for fast CLI
from env_sumo import SumoGraphEnv
from models import STGAT_ActorCritic

def set_seed(seed=42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)

# ==========================================
# INFERENCE PARAMETERS
# ==========================================
TEST_EPISODES = 5        # How many evaluation runs to do
MAX_STEPS = 4500
FIXED_VEHICLES = 2500    # The ultimate stress test
K_HOPS = 3               # Must match your training architecture
TEMPERATURE = 0.2        # Sweet spot for Multi-Agent GATs
# ==========================================

def run_inference():
    set_seed(100) # Use a different seed than training to prove true generalization!

    # 1. Initialize Environment
    # NOTE: If you run this locally on your Windows PC, change gui=True to WATCH the AI!
    env = SumoGraphEnv(
        sumo_cfg_path="stc_simulation.sumocfg",
        net_file_path="patna_stc.net.xml",
        gui=True
    )
    num_nodes = env.num_nodes
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # 2. Load the GAT Brain
    model = STGAT_ActorCritic(feature_dim=4, hidden_dim=128, num_actions=2, k_hops=K_HOPS)
    model.to(device)

    # Load the BEST weights
    model_path = "stgat_ppo_best_real_actual_consistent.pth"
    if os.path.exists(model_path):
        print(f"Loading highly optimized brain: {model_path}...")
        checkpoint = torch.load(model_path, map_location=device)
        print(f"checkpoint_episode: {checkpoint.get('episode', 'Unknown')}")
        model.load_state_dict(checkpoint['model_state_dict'])
    else:
        print(f"ERROR: Could not find {model_path}! Are you in the right folder?")
        return

    # 3. SET TO EVALUATION MODE
    model.eval()
    
    # Fix the UserWarning by using clone().detach()
    adj_matrix = env.adjacency_matrix.clone().detach().to(device)

    print(f"\n--- STARTING OFFICIAL GAT INFERENCE EVALUATION ---")
    print(f"Running {TEST_EPISODES} episodes at ({FIXED_VEHICLES} vehicles).\n")

    eval_rewards = []
    
    # --- UPGRADE 1: CSV DATA LOGGER ---
    csv_filename = f"thesis_inference_results_T{TEMPERATURE}_Veh{FIXED_VEHICLES}.csv"
    
    with open(csv_filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Episode", "Step", "Total_Queue", "Max_Wait", "Throughput_This_Step", "Teleports_This_Step"])

        try:
            for episode in range(TEST_EPISODES):
                episode_seed = random.randint(200000, 300000)
                state = env.reset(seed=episode_seed, num_vehicles=FIXED_VEHICLES, spawn=3540)
                state = state.to(device)
                h_prev = torch.zeros(1, num_nodes, 128).to(device)
                
                episode_reward = 0.0
                total_arrived = 0
                total_teleports = 0
                action_changes = 0
                action_not_changes = 0
                
                # --- UPGRADE 2: ASYNCHRONOUS HARDWARE LOCK ARRAY ---
                # Tracks the remaining lock time for each intersection independently
                hardware_locks = np.zeros(num_nodes, dtype=int)
                time_since_last_update = np.ones(num_nodes, dtype=float)

                for step in range(MAX_STEPS):
                    state_batched = state.unsqueeze(0)

                    # NO GRADIENTS FOR INFERENCE
                    with torch.no_grad():
                        action_probs, _, h_new = model(state_batched, adj_matrix, h_prev)

                        # --- UPGRADE 3: TEMPERATURE SCALING ---
                        logits = torch.log(action_probs + 1e-8)
                        scaled_logits = logits # (Disabled scaling here based on your provided code)
                        sharpened_probs = torch.softmax(scaled_logits, dim=-1)
                        
                        m = torch.distributions.Categorical(sharpened_probs)
                        actions = m.sample().squeeze(0)
                        actions_flat = actions.cpu().numpy()

                        # Global zero-traffic safeguard
                        if state_batched.sum().item() == 0:
                            actions_flat = np.zeros(num_nodes, dtype=int)

                    # --- ASYNCHRONOUS HARDWARE EXECUTION & MASKING ---
                    switches_this_step = 0
                    
                    for i, tls in enumerate(env.tls_ids):
                        if hardware_locks[i] > 0:
                            # AI IS IGNORED. Hardware is locked.
                            hardware_locks[i] -= 1
                            
                            # Move from Yellow (3s) to Green (10s)
                            if hardware_locks[i] == 10:
                                current_phase = traci.trafficlight.getPhase(tls)
                                logic = traci.trafficlight.getCompleteRedYellowGreenDefinition(tls)[0]
                                num_phases = len(logic.phases)
                                new_green = (current_phase + 1) % num_phases
                                traci.trafficlight.setPhase(tls, new_green)
                                traci.trafficlight.setPhaseDuration(tls, 100000)
                        else:
                            # Hardware is READY. Will the AI switch?
                            if actions_flat[i] == 1:
                                # =========================================================
                                # THE NEW DEMAND-RESPONSIVE ACTION MASK
                                # Prevent the AI from switching if the cross-street is empty!
                                # =========================================================
                                controlled_links = traci.trafficlight.getControlledLinks(tls)
                                current_phase_state = traci.trafficlight.getRedYellowGreenState(tls)
                                
                                cross_traffic_queue = 0
                                checked_lanes = set() # Ensure we don't double count lanes
                                
                                for j, link_group in enumerate(controlled_links):
                                    # If the AI's requested switch would grant Green to this lane
                                    # (meaning it is CURRENTLY Red)
                                    if current_phase_state[j].lower() == 'r':
                                        if len(link_group) > 0:
                                            lane_id = link_group[0][0]
                                            if lane_id not in checked_lanes:
                                                cross_traffic_queue += traci.lane.getLastStepHaltingNumber(lane_id)
                                                checked_lanes.add(lane_id)
                                
                                # Evaluate the Mask
                                if cross_traffic_queue == 0:
                                    # VETO THE AI!
                                    actions_flat[i] = 0
                                    # Hardware locks are NOT set, phase does NOT change.
                                else:
                                    # Mask passes. Legitimate cross-traffic exists.
                                    switches_this_step += 1
                                    hardware_locks[i] = 13 # 3s yellow + 10s green
                                    
                                    # Trigger Yellow Phase
                                    current_phase = traci.trafficlight.getPhase(tls)
                                    logic = traci.trafficlight.getCompleteRedYellowGreenDefinition(tls)[0]
                                    num_phases = len(logic.phases)
                                    new_yellow = (current_phase + 1) % num_phases
                                    traci.trafficlight.setPhase(tls, new_yellow)
                                    traci.trafficlight.setPhaseDuration(tls, 100000)
                                # =========================================================

                    # Update action tracking after the mask has potentially modified actions_flat
                    action_changes += (actions_flat == 1).sum().item()
                    action_not_changes += (actions_flat == 0).sum().item()

                    # ---------------------------------------------
                    # STEP THE SIMULATION BY EXACTLY 1 SECOND
                    # ---------------------------------------------
                    traci.simulationStep()
                    
                    # Pull raw environment physics
                    next_state = env.get_state(elapsed_time=time_since_last_update)
                    arrived = traci.simulation.getArrivedNumber()
                    teleports = traci.simulation.getStartingTeleportNumber()
                    
                    total_arrived += arrived
                    total_teleports += teleports
                    
                    # Un-scale metrics for readable CSV tracking and rewards
                    step_queue_raw = (next_state[:, 0] * 50.0)
                    step_wait_raw = (next_state[:, 1] * 100.0)
                    
                    total_queue_val = step_queue_raw.sum().item()
                    sum_wait_val = step_wait_raw.sum().item()
                    max_wait_val = step_wait_raw.max().item()
                    
                    writer.writerow([episode+1, step, round(total_queue_val, 2), round(max_wait_val, 2), arrived, teleports])

                    # Manually calculate reward (matching your training function)
                    step_reward = -(total_queue_val + (0.5 * sum_wait_val)) - (switches_this_step * env.switching_penalty)
                    episode_reward += step_reward
                    
                    next_state = next_state.to(device)

                    # --- UPGRADE 4: GRU MEMORY FREEZING ---
                    lock_mask = torch.tensor(hardware_locks > 0, dtype=torch.bool, device=device).unsqueeze(0).unsqueeze(-1)
                    h_prev = torch.where(lock_mask, h_prev, h_new)
                    state = next_state
                    
                    for i in range(num_nodes):
                        if hardware_locks[i] > 0:
                            time_since_last_update[i] += 1.0
                        else:
                            time_since_last_update[i] = 1.0

                    if traci.simulation.getMinExpectedNumber() == 0:
                        print(f"  ✅ City cleared early at step {step}! | Arrived: {total_arrived} | Teleports: {total_teleports}")
                        break

                normalized_reward = episode_reward / FIXED_VEHICLES
                eval_rewards.append(normalized_reward)

                print(f"Test Ep {episode + 1}/{TEST_EPISODES} | Reward: {episode_reward:.2f} | Norm: {normalized_reward:.2f} | Teleports: {total_teleports} | action_changes: {action_changes}, action_not_changes: {action_not_changes}, episode_end_sumo_time: {traci.simulation.getTime()}")

        except KeyboardInterrupt:
            print("\n*** EVALUATION INTERRUPTED ***")

        finally:
            env.close()

            if len(eval_rewards) > 0:
                avg_norm_reward = sum(eval_rewards) / len(eval_rewards)
                print("\n==============================================")
                print(f"OFFICIAL GAT-PPO INFERENCE SCORE: {avg_norm_reward:.2f}")
                print(f"DATA SAVED TO: {csv_filename}")
                print("==============================================")

if __name__ == "__main__":
    run_inference()