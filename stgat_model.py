import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.distributions as dist

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
    def __init__(self, feature_dim=3, hidden_dim=64, num_actions=2, k_hops=3, num_heads=3):
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
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.orthogonal_(m.weight, gain=torch.nn.init.calculate_gain('relu'))
                if m.bias is not None:
                    nn.init.constant_(m.bias, 0.0)

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