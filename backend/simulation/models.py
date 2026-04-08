import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.distributions as dist

class GraphShiftOperator(nn.Module):
    """
    Calculates the transition probabilities for traffic flow between intersections.
    """
    def __init__(self):
        super(GraphShiftOperator, self).__init__()

    def forward(self, adjacency_matrix):
        """
        Args:
            adjacency_matrix: A square tensor of shape (N, N)
        Returns:
            forward_transition: W^T * (D_out)^-1
            reverse_transition: W * (D_in)^-1
        """
        # Small epsilon to prevent division by zero for dead-end nodes
        eps = 1e-8
        
        # Calculate out-degrees and in-degrees
        out_degrees = adjacency_matrix.sum(dim=1)
        in_degrees = adjacency_matrix.sum(dim=0)
        
        # Create diagonal inverse matrices
        d_out_inv = torch.diag(1.0 / (out_degrees + eps))
        d_in_inv = torch.diag(1.0 / (in_degrees + eps))
        
        # Calculate transition matrices (The Graph Shift Operators)
        forward_transition = torch.matmul(adjacency_matrix.t(), d_out_inv)
        reverse_transition = torch.matmul(adjacency_matrix, d_in_inv)
        
        return forward_transition, reverse_transition


class DiffusionAggregator(nn.Module):
    """
    Diffuses the local traffic state across the network with ADAPTIVE HOP WEIGHTING.
    """
    def __init__(self, k_hops):
        super(DiffusionAggregator, self).__init__()
        self.k_hops = k_hops
        
        # --- THE UPGRADE ---
        # Create a learnable parameter for each hop (Local, 1-Hop, 2-Hop, etc.)
        # The AI will adjust these numbers during backpropagation to find the optimal balance.
        self.hop_weights = nn.Parameter(torch.ones(k_hops))

    def forward(self, x, forward_trans, reverse_trans):
        # batch_size, n_nodes, feature_dim = x.shape
        agg_sequence = [x] 
        curr_f = forward_trans
        curr_r = reverse_trans
        
        # Calculate the raw spatial diffusion
        for k in range(1, self.k_hops):
            shift_operator = curr_f + curr_r
            y_k = torch.einsum('ij,bjk->bik', shift_operator, x)
            agg_sequence.append(y_k)
            
            curr_f = torch.matmul(curr_f, forward_trans)
            curr_r = torch.matmul(curr_r, reverse_trans)
            
        # --- APPLYING THE ADAPTIVE WEIGHTS ---
        # Use softmax so the weights always sum to exactly 1.0 (e.g., [0.7, 0.2, 0.1])
        normalized_weights = F.softmax(self.hop_weights, dim=0)
        
        weighted_sequence = []
        for k in range(self.k_hops):
            # Multiply the traffic data at hop 'k' by the AI's learned importance weight
            weighted_hop = agg_sequence[k] * normalized_weights[k]
            weighted_sequence.append(weighted_hop)
            
        return torch.stack(weighted_sequence, dim=2)


class DiffGRUCell(nn.Module):
    """
    A custom Gated Recurrent Unit that processes the diffused spatial sequence
    to maintain a memory of how traffic is evolving over time.
    """
    def __init__(self, input_dim, hidden_dim, k_hops):
        super(DiffGRUCell, self).__init__()
        self.hidden_dim = hidden_dim
        
        # We flatten the sequence of K hops into a single vector
        self.concat_dim = input_dim * k_hops
        
        # Standard GRU gates, but sized to accept the diffused graph data
        self.update_gate = nn.Linear(self.concat_dim + hidden_dim, hidden_dim)
        self.reset_gate = nn.Linear(self.concat_dim + hidden_dim, hidden_dim)
        self.candidate_layer = nn.Linear(self.concat_dim + hidden_dim, hidden_dim)

    def forward(self, diffused_x, h_prev):
        """
        Args:
            diffused_x: (Batch, N, k_hops, Feature_Dim)
            h_prev: Previous hidden state (Batch, N, Hidden_Dim)
        """
        batch_size, n_nodes, k_hops, feature_dim = diffused_x.shape
        
        # Flatten the K-hops into a wide feature vector for each intersection
        # Shape becomes: (Batch, N, k_hops * Feature_Dim)
        x_flat = diffused_x.view(batch_size, n_nodes, k_hops * feature_dim)
        
        # Combine the new graph data with the AI's previous memory
        combined = torch.cat([x_flat, h_prev], dim=-1)
        
        # Calculate update (z) and reset (r) gates
        z = torch.sigmoid(self.update_gate(combined))
        r = torch.sigmoid(self.reset_gate(combined))
        
        # Calculate the candidate for the new memory state
        combined_reset = torch.cat([x_flat, r * h_prev], dim=-1)
        h_candidate = torch.tanh(self.candidate_layer(combined_reset))
        
        # Final updated memory state
        h_new = (1 - z) * h_prev + z * h_candidate
        
        return h_new


class SAGNN_ActorCritic(nn.Module):
    """
    The complete Stochastic Aggregation Graph Neural Network Architecture.
    """
    def __init__(self, feature_dim=4, hidden_dim=64, num_actions=2, k_hops=3):
        super(SAGNN_ActorCritic, self).__init__()
        self.hidden_dim = hidden_dim
        
        self.aggregator = DiffusionAggregator(k_hops)
        self.gru_cell = DiffGRUCell(feature_dim, hidden_dim, k_hops)
        
        self.actor_head = nn.Sequential(
            nn.Linear(hidden_dim, 32),
            nn.ReLU(),
            nn.Linear(32, num_actions)
        )
        
        self.critic_head = nn.Sequential(
            nn.Linear(hidden_dim, 32),
            nn.ReLU(),
            nn.Linear(32, 1)
        )

    def forward(self, x, forward_trans, reverse_trans, h_prev):
        diffused_x = self.aggregator(x, forward_trans, reverse_trans)
        h_new = self.gru_cell(diffused_x, h_prev)
        
        action_logits = self.actor_head(h_new)
        action_probs = F.softmax(action_logits, dim=-1)
        
        state_value = self.critic_head(h_new)
        
        return action_probs, state_value, h_new

    def sample_action(self, action_probs):
        m = dist.Categorical(action_probs)
        action = m.sample()
        log_prob = m.log_prob(action)
        return action, log_prob

    # --- THE NEW PPO FUNCTION ---
    def evaluate(self, states, forward_trans, reverse_trans, h_prevs, actions):
        """
        Re-evaluates the entire memory buffer during the PPO Epoch loop.
        states shape: (Time, Nodes, Features)
        """
        # 1. Re-run the spatial diffusion and temporal memory
        diffused_x = self.aggregator(states, forward_trans, reverse_trans)
        h_new = self.gru_cell(diffused_x, h_prevs)
        
        # 2. Re-calculate Actor probabilities
        action_logits = self.actor_head(h_new)
        action_probs = F.softmax(action_logits, dim=-1)
        
        # 3. Re-calculate Critic values (and squeeze the last dimension so it's [Time, Nodes])
        state_values = self.critic_head(h_new).squeeze(-1)
        
        # 4. Find the log probabilities of the actions the AI *actually* took in the past
        m = dist.Categorical(action_probs)
        action_logprobs = m.log_prob(actions)
        dist_entropy = m.entropy()
        
        return action_logprobs, state_values, dist_entropy



# -----------------------Phase-3-------------------------------------
class GATLayer(nn.Module):
    """
    Multi-Head Graph Attention Layer (Optimized Broadcasting)
    Cuts memory usage from O(N^2) to O(N) using PyTorch broadcasting.
    """
    def __init__(self, in_features, out_features, num_heads=3, alpha=0.2):
        super(GATLayer, self).__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.num_heads = num_heads
        
        # Linear transformation (Output is expanded to accommodate all heads)
        self.W = nn.Linear(in_features, out_features * num_heads, bias=False)
        
        # Separate attention vectors for Source and Destination nodes
        self.a_src = nn.Parameter(torch.empty(1, 1, num_heads, out_features))
        self.a_dst = nn.Parameter(torch.empty(1, 1, num_heads, out_features))
        
        nn.init.xavier_uniform_(self.a_src)
        nn.init.xavier_uniform_(self.a_dst)
        
        self.leakyrelu = nn.LeakyReLU(alpha)

    def forward(self, h, adj):
        B, N, _ = h.size()
        
        # 1. Transform features and reshape into distinct heads
        # Shape becomes: (Batch, Nodes, Heads, Features)
        Wh = self.W(h).view(B, N, self.num_heads, self.out_features) 
        
        # 2. Calculate attention scores for source and destination separately
        attn_src = torch.sum(Wh * self.a_src, dim=-1) # Shape: (B, N, Heads)
        attn_dst = torch.sum(Wh * self.a_dst, dim=-1) # Shape: (B, N, Heads)
        
        # 3. Broadcasting addition to create the full N x N attention grid
        e = self.leakyrelu(attn_src.unsqueeze(2) + attn_dst.unsqueeze(1)) # (B, N, N, Heads)
        
        # 4. Mask with physical Adjacency Matrix
        zero_vec = -1e9 * torch.ones_like(e) 
        adj_batched = adj.unsqueeze(0).unsqueeze(-1).expand(B, N, N, self.num_heads)
        
        attention = torch.where(adj_batched > 0, e, zero_vec)
        attention = F.softmax(attention, dim=2) # Normalize across neighbors
        
        # 5. Apply attention weights using Einstein Summation (einsum)
        # Multiplies attention grid by neighbor features efficiently
        h_prime = torch.einsum('bnjh,bjhf->bnhf', attention, Wh) 
        
        # 6. Average the 3 heads together to keep hidden_dim constant for the GRU
        h_prime = h_prime.mean(dim=2) # Shape back to (B, N, out_features)
        
        return F.elu(h_prime)


class STGAT_ActorCritic(nn.Module):
    """
    Multi-Hop Spatial-Temporal Graph Attention Network + PPO Actor-Critic
    Upgraded with Multi-Head Attention & Residual Connections!
    """
    def __init__(self, feature_dim=4, hidden_dim=64, num_actions=2, k_hops=3, num_heads=3):
        super(STGAT_ActorCritic, self).__init__()
        self.k_hops = k_hops
        
        self.gat_layers = nn.ModuleList()
        self.gat_layers.append(GATLayer(feature_dim, hidden_dim, num_heads=num_heads))
        
        for _ in range(k_hops - 1):
            self.gat_layers.append(GATLayer(hidden_dim, hidden_dim, num_heads=num_heads))
        
        self.gru = nn.GRUCell(hidden_dim, hidden_dim)
        
        self.actor_head = nn.Sequential(
            nn.Linear(hidden_dim, 32),
            nn.ReLU(),
            nn.Linear(32, num_actions)
        )
        
        self.critic_head = nn.Sequential(
            nn.Linear(hidden_dim, 32),
            nn.ReLU(),
            nn.Linear(32, 1)
        )

        # OpenAI's standard initialization for PPO Actor-Critic networks
        # Only init actor and critic heads
        for m in [self.actor_head, self.critic_head]:
            for layer in m.modules():
                if isinstance(layer, nn.Linear):
                    nn.init.orthogonal_(layer.weight, gain=torch.nn.init.calculate_gain('relu'))

    def forward(self, x, adj, h_prev):
        spatial_features = self.gat_layers[0](x, adj)
        
        # Residual Connections
        for i in range(1, self.k_hops):
            new_features = self.gat_layers[i](spatial_features, adj)
            spatial_features = spatial_features + new_features 
            
        B, N, H = spatial_features.size()
        spatial_flat = spatial_features.view(B * N, H)
        h_prev_flat = h_prev.view(B * N, H)
        
        h_new_flat = self.gru(spatial_flat, h_prev_flat)
        h_new = h_new_flat.view(B, N, H)
        
        action_logits = self.actor_head(h_new)
        action_probs = F.softmax(action_logits, dim=-1)
        state_value = self.critic_head(h_new)
        
        return action_probs, state_value, h_new

    def sample_action(self, action_probs):
        m = dist.Categorical(action_probs)
        action = m.sample()
        log_prob = m.log_prob(action)
        return action, log_prob

    def evaluate(self, states, adj, h_prevs, actions):
        spatial_features = self.gat_layers[0](states, adj)
        
        for i in range(1, self.k_hops):
            new_features = self.gat_layers[i](spatial_features, adj)
            spatial_features = spatial_features + new_features 
            
        B, N, H = spatial_features.size()
        spatial_flat = spatial_features.view(B * N, H)
        h_prevs_flat = h_prevs.view(B * N, H)
        
        h_new_flat = self.gru(spatial_flat, h_prevs_flat)
        h_new = h_new_flat.view(B, N, H)
        
        action_logits = self.actor_head(h_new)
        action_probs = F.softmax(action_logits, dim=-1)
        state_values = self.critic_head(h_new).squeeze(-1)
        
        m = dist.Categorical(action_probs)
        action_logprobs = m.log_prob(actions)
        dist_entropy = m.entropy()
        
        return action_logprobs, state_values, dist_entropy