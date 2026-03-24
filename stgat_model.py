import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.distributions as dist

class GATLayer(nn.Module):
    """
    Graph Attention Layer: Dynamically calculates attention scores between connected intersections.
    """
    def __init__(self, in_features, out_features, alpha=0.2):
        super(GATLayer, self).__init__()
        self.in_features = in_features
        self.out_features = out_features
        
        # Linear transformation for node features
        self.W = nn.Linear(in_features, out_features, bias=False)
        # Attention scoring mechanism
        self.a = nn.Linear(2 * out_features, 1, bias=False)
        self.leakyrelu = nn.LeakyReLU(alpha)

    def forward(self, h, adj):
        # h shape: (Batch, Nodes, Features)
        B, N, _ = h.size()
        
        # 1. Apply linear transformation to all nodes
        Wh = self.W(h) # Shape: (B, N, out_features)
        
        # 2. Create combinations of all nodes to calculate attention
        Wh_repeated_in_chunks = Wh.repeat_interleave(N, dim=1)
        Wh_repeated_alternating = Wh.repeat(1, N, 1)
        
        # Concatenate features of node i and node j
        a_input = torch.cat([Wh_repeated_in_chunks, Wh_repeated_alternating], dim=-1)
        a_input = a_input.view(B, N, N, 2 * self.out_features)
        
        # 3. Calculate raw attention scores
        e = self.leakyrelu(self.a(a_input).squeeze(-1)) # Shape: (B, N, N)
        
        # 4. Mask the attention scores using the physical Adjacency Matrix
        # If intersections are not physically connected (adj == 0), set attention to -1e9
        zero_vec = -9e15 * torch.ones_like(e)
        
        # Reshape adjacency matrix to match batch size
        adj_batched = adj.unsqueeze(0).expand(B, N, N)
        attention = torch.where(adj_batched > 0, e, zero_vec)
        
        # 5. Normalize attention scores using Softmax
        attention = F.softmax(attention, dim=-1)
        
        # 6. Apply attention weights to the neighbor features
        h_prime = torch.bmm(attention, Wh) # Shape: (B, N, out_features)
        
        return F.elu(h_prime)


class STGAT_ActorCritic(nn.Module):
    """
    Multi-Hop Spatial-Temporal Graph Attention Network + PPO Actor-Critic
    """
    def __init__(self, feature_dim=3, hidden_dim=64, num_actions=2, k_hops=3):
        super(STGAT_ActorCritic, self).__init__()
        self.k_hops = k_hops
        
        # SPATIAL: Stack multiple GAT layers to achieve K-Hop vision
        self.gat_layers = nn.ModuleList()
        
        # The first layer takes the raw features (e.g., queue lengths)
        self.gat_layers.append(GATLayer(feature_dim, hidden_dim))
        
        # The subsequent layers take the hidden features to expand the vision to 2-hop, 3-hop, etc.
        for _ in range(k_hops - 1):
            self.gat_layers.append(GATLayer(hidden_dim, hidden_dim))
        
        # TEMPORAL: Standard GRU for time-series memory
        self.gru = nn.GRUCell(hidden_dim, hidden_dim)
        
        # PPO HEADS
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

    def forward(self, x, adj, h_prev):
        # 1. Dynamic Spatial Attention (Pass through all K-Hop layers)
        spatial_features = x
        for gat in self.gat_layers:
            spatial_features = gat(spatial_features, adj) 
        # spatial_features Shape: (B, N, hidden_dim)
        
        # 2. Temporal Memory Update
        B, N, H = spatial_features.size()
        spatial_flat = spatial_features.view(B * N, H)
        h_prev_flat = h_prev.view(B * N, H)
        
        h_new_flat = self.gru(spatial_flat, h_prev_flat)
        h_new = h_new_flat.view(B, N, H)
        
        # 3. Action and Value generation
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
        """ Used during the PPO Epoch loop """
        # Pass through all K-Hop layers
        spatial_features = states
        for gat in self.gat_layers:
            spatial_features = gat(spatial_features, adj)
        
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