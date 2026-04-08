import os
import csv
import random
import numpy as np
import torch
import torch.optim as optim
import torch.nn.functional as F
import libsumo as traci  # The high-speed C++ bridge for Ubuntu/Colab
from env_sumo import SumoGraphEnv
from models import STGAT_ActorCritic

# --- ADD THIS SEED FUNCTION ---
def set_seed(seed=42):
    """Locks all random number generators for perfect reproducibility."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    # If you ever move to a GPU, this locks that down too
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    # Forces PyTorch to use deterministic algorithms
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False

# --- Hyperparameters ---
NUM_EPISODES = 400        # How many times to restart the simulation
MAX_STEPS = 3600          # 1 hour of simulation per episode
LEARNING_RATE = 1.5e-4
GAMMA = 0.99              # Discount factor for future rewards
K_HOPS = 3                # How far the graph diffusion spreads

# --- PPO SPECIFICS ---
PPO_EPOCHS = 5           # Epochs to train on the memory buffer
PPO_CLIP = 0.2           # The Clipping Shock Absorber
GAE_LAMBDA = 0.95        # GAE Smoothing
ENTROPY_COEF = 0.01      # Encourages exploration
MINI_BATCH_SIZE = 256

def train():
    set_seed(42)
    env = SumoGraphEnv(
        sumo_cfg_path="stc_simulation.sumocfg",
        net_file_path="patna_stc.net.xml",
        gui=False
    )

    num_nodes = env.num_nodes

    model = STGAT_ActorCritic(feature_dim=4, hidden_dim=128, num_actions=2, k_hops=K_HOPS)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    # optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE)
    optimizer = optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4)
    # Decays the learning rate smoothly from 100% to 10% over 300 episodes
    scheduler = optim.lr_scheduler.LinearLR(optimizer, start_factor=1.0, end_factor=0.5, total_iters=NUM_EPISODES)

    adj_matrix = env.adjacency_matrix.clone().detach().to(device)

    print(f"Starting FINAL Real-World GAT Training on {num_nodes} nodes using {device}...")

    all_episode_rewards = []
    recent_rewards = []
    best_ma_reward = -float('inf')
    start_episode = 0

    # --- RESUME LOGIC ---
    if os.path.exists("stgat_ppo_latest_real.pth"):
        print("Found previous GAT session! Waking up...")
        checkpoint = torch.load("stgat_ppo_latest_real.pth", map_location=device)
        model.load_state_dict(checkpoint['model_state_dict'])
        optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        start_episode = checkpoint['episode']
        best_ma_reward = checkpoint.get('best_ma_reward', -float('inf'))
        print(f"Resuming safely from Episode {start_episode + 1}!")

    # if start_episode == 0:
    #     with open("training_log_ppo.csv", "w", newline="") as f:
    #         writer = csv.writer(f)
    #         writer.writerow(["Episode", "Vehicles", "Reward", "Normalized_Reward"])


    for episode in range(start_episode, NUM_EPISODES):
        episode_seed = random.randint(1, 100000)

        # Curriculum Learning Formula
        MIN_VEHICLES = 1000
        MAX_VEHICLES = 4100

        min_spawn = 3540
        max_spawn = 3540

        # 1. Calculate how far along in training we are (0.0 to 1.0)
        # We cap it at 0.8 so the last 20% of episodes are at maximum difficulty
        progress = min(1.0, episode / (NUM_EPISODES * 0.8))

        # 2. Gradually increase the base number of cars
        base_vehicles = int(MIN_VEHICLES + progress * (MAX_VEHICLES - MIN_VEHICLES))
        base_spawn = int(min_spawn + progress * (max_spawn - min_spawn))

        # 3. Add a little bit of randomness (±10%) so it doesn't overfit to an exact number
        noise = random.randint(-int(base_vehicles * 0.01), int(base_vehicles * 0.01))
        noise_spawn = random.randint(-int(base_spawn * 0.01), int(base_spawn * 0.01))
        episode_vehicles = base_vehicles + noise
        episode_spawn = base_spawn + noise_spawn

        # Ensure we don't accidentally go below the minimum or above the maximum
        episode_vehicles = max(MIN_VEHICLES, min(MAX_VEHICLES, episode_vehicles))
        episode_spawn = max(min_spawn, min(max_spawn, episode_spawn))

        state = env.reset(seed=episode_seed, num_vehicles=episode_vehicles, spawn=episode_spawn)
        state = state.to(device)
        h_prev = torch.zeros(1, num_nodes, 128).to(device)
        episode_reward = 0.0

        # --- 1. THE ROLLOUT BUFFER ---
        memory_states = []
        memory_actions = []
        memory_logprobs = []
        memory_rewards = []
        memory_values = []
        memory_h_prevs = []

        action_changes=0
        action_not_changes=0
        for step in range(MAX_STEPS):
            state_batched = state.unsqueeze(0)

            with torch.no_grad():
                # GAT Forward Pass: Pass adj_matrix instead of diffusion operators
                action_probs, state_value, h_new = model(
                    state_batched, adj_matrix, h_prev
                )
                actions, log_probs = model.sample_action(action_probs)

            actions_flat = actions.squeeze(0)

            action_changes += (actions_flat == 1).sum().item()
            action_not_changes += (actions_flat == 0).sum().item()

            next_state, rewards, done, action_changed = env.step(actions_flat)

            next_state = next_state.to(device)
            rewards = rewards.to(device)

            # Append to memory
            memory_states.append(state_batched)
            memory_actions.append(actions)
            memory_logprobs.append(log_probs)
            memory_rewards.append(rewards)
            memory_values.append(state_value.squeeze(-1)) # Shape becomes (1, N)
            memory_h_prevs.append(h_prev)

            episode_reward += rewards.sum().item()

            state = next_state
            h_prev = h_new.detach()

            if done:
                print(f"   City cleared early at step {step, action_changes, action_not_changes}!")
                break

        # --- 2. GENERALIZED ADVANTAGE ESTIMATION (GAE) ---
        advantages = []
        gae = torch.zeros(num_nodes, device=device)

        for step in reversed(range(len(memory_rewards))):
            if step == len(memory_rewards) - 1:
                next_val = torch.zeros(num_nodes, device=device)
            else:
                next_val = memory_values[step + 1].squeeze(0)

            current_val = memory_values[step].squeeze(0)

            delta = memory_rewards[step] + GAMMA * next_val - current_val
            gae = delta + GAMMA * GAE_LAMBDA * gae
            advantages.insert(0, gae.clone())

        # Convert memory lists to Tensors: Shape -> (Time, Nodes, Features)
        old_states = torch.cat(memory_states, dim=0).detach()
        old_actions = torch.cat(memory_actions, dim=0).detach()
        old_logprobs = torch.cat(memory_logprobs, dim=0).detach()
        old_h_prevs = torch.cat(memory_h_prevs, dim=0).detach()

        # Stack advantages and calculate returns
        advantages = torch.stack(advantages).detach()
        old_values = torch.cat(memory_values, dim=0).detach()
        returns = advantages + old_values

        # Normalize advantages for training stability
        advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        # --- 3. PPO UPDATE EPOCHS ---
        for _ in range(PPO_EPOCHS):
            # 1. Shuffle the 3600 steps randomly
            indices = np.arange(len(old_states))
            np.random.shuffle(indices)

            # 2. Break them into small chunks (Mini-batches)
            for start in range(0, len(old_states), MINI_BATCH_SIZE):
                end = start + MINI_BATCH_SIZE
                mb_idx = indices[start:end] # Get the shuffled indices

                # Extract the small chunks from the memory buffers
                mb_states = old_states[mb_idx]
                mb_actions = old_actions[mb_idx]
                mb_logprobs = old_logprobs[mb_idx]
                mb_h_prevs = old_h_prevs[mb_idx]
                mb_advantages = advantages[mb_idx]
                mb_returns = returns[mb_idx]

                # 3. Evaluate ONLY the mini-batch
                new_logprobs, state_values, dist_entropy = model.evaluate(
                    mb_states, adj_matrix, mb_h_prevs, mb_actions
                )

                # 4. Calculate PPO Loss
                ratios = torch.exp(new_logprobs - mb_logprobs)
                surr1 = ratios * mb_advantages
                surr2 = torch.clamp(ratios, 1.0 - PPO_CLIP, 1.0 + PPO_CLIP) * mb_advantages
                actor_loss = -torch.min(surr1, surr2).mean()

                critic_loss = F.mse_loss(state_values, mb_returns)
                total_loss = actor_loss + 0.5 * critic_loss - ENTROPY_COEF * dist_entropy.mean()

                # 5. Optimize the network using the mini-batch gradients!
                optimizer.zero_grad()
                total_loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=0.5)
                optimizer.step()

        # --- LOGGING & SAVING ---
        normalized_reward = episode_reward / episode_vehicles
        print(f"➡️ Episode {episode + 1}/{NUM_EPISODES} Complete! Reward: {episode_reward:.2f} | Norm: {normalized_reward:.2f} | LR: {scheduler.get_last_lr()[0]:.2e}")
        scheduler.step()

        all_episode_rewards.append((episode_vehicles,episode_reward))
        recent_rewards.append(episode_reward/episode_vehicles)

        # with open("training_log_ppo.csv", "a", newline="") as f:
        #     writer = csv.writer(f)
        #     writer.writerow([episode + 1, episode_vehicles, episode_reward, normalized_reward])

        if (episode==NUM_EPISODES-1):
            latest_checkpoint = {
                'episode': episode + 1,
                'model_state_dict': model.state_dict(),
                'optimizer_state_dict': optimizer.state_dict(),
                'best_ma_reward': best_ma_reward,
                'k_hops': K_HOPS
            }
            torch.save(latest_checkpoint, "stgat_ppo_latest_real_actual.pth")

        if len(recent_rewards) > 30:
            recent_rewards.pop(0)
        if len(recent_rewards) == 30:
            checkpoint = {
            'episode': episode + 1,
            'model_state_dict': model.state_dict(),
            'optimizer_state_dict': optimizer.state_dict(),
            'best_ma_reward': best_ma_reward,
            'k_hops': K_HOPS
        }
            current_ma = sum(recent_rewards) / 30.0
            if current_ma > best_ma_reward:
                best_ma_reward = current_ma
                torch.save(checkpoint, "stgat_ppo_best_real_actual_consistent.pth")
                print(f"*** New Best PPO Policy Saved! (30-Ep MA: {best_ma_reward:.2f}) ***")

    env.close()

    with open("training_log_real_good.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["episode", "num_vehicles", "cumulative_reward", "normalized_reward"])
        for i, (num_vehicles, cumulative_reward) in enumerate(all_episode_rewards):
            writer.writerow([i + 1, num_vehicles, cumulative_reward, cumulative_reward/num_vehicles])
    print("Training data saved to training_log_gat_real.csv")


if __name__=="__main__": 
    train()
