"""
stgat_model_client.py — STGAT decision model as a standalone MQTT client

MQTT flow:
  SUBSCRIBE  traffic/network/topology  → build adjacency matrix once at startup
  SUBSCRIBE  traffic/state/batch       → receive full network state each step
  PUBLISH    traffic/actions           → send batch actions back to gateway

The model owns h_prev (GRU hidden state) entirely.
It never shares it with the gateway — temporal continuity is maintained
inside this process across successive state messages.

Run:
    python stgat_model_client.py --model stgat_ppo_best.pth
    python stgat_model_client.py --model stgat_ppo_best.pth --hidden-dim 64 --k-hops 3
"""

import argparse
import json
import threading

import torch
import paho.mqtt.client as mqtt

from stgat_model import STGAT_ActorCritic

# ── Config ─────────────────────────────────────────────────────────────────
BROKER_HOST = "localhost"
BROKER_PORT = 1883
FEATURE_DIM = 3    # [pcu_queue, max_wait, phase_index]
NUM_ACTIONS = 2    # 0 = keep phase, 1 = advance phase


class STGATModelClient:
    def __init__(self, model_path: str | None, hidden_dim: int, k_hops: int):
        self.device     = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.hidden_dim = hidden_dim
        self.model_path = model_path

        # ── Model (loaded after topology is received) ────────────
        self.model:     STGAT_ActorCritic | None = None
        self.adj:       torch.Tensor | None      = None   # (N, N)
        self.tls_ids:   list[str]  | None        = None
        self.num_nodes: int        | None        = None
        self.h_prev:    torch.Tensor | None      = None   # (1, N, hidden_dim)

        self._topology_ready = threading.Event()

        # ── MQTT ────────────────────────────────────────────────
        self.mqtt = mqtt.Client(client_id="stgat-model")
        self.mqtt.on_connect = self._on_connect
        self.mqtt.on_message = self._on_message
        self.mqtt.connect(BROKER_HOST, BROKER_PORT)

        # Build model params for later use
        self._k_hops = k_hops

    # ── MQTT callbacks ────────────────────────────────────────────
    def _on_connect(self, client, userdata, flags, rc):
        print(f"[Model] MQTT connected (rc={rc})")
        # Topology is retained — we'll receive it immediately on subscribe
        client.subscribe("traffic/network/topology", qos=1)
        client.subscribe("traffic/network/state",      qos=1)

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = json.loads(msg.payload)
        except Exception as e:
            print(f"[Model] JSON parse error on {topic}: {e}")
            return

        if topic == "traffic/network/topology":
            self._handle_topology(payload)
        elif topic == "traffic/network/state":
            self._handle_state_batch(payload)

    # ── Topology handler ─────────────────────────────────────────
    def _handle_topology(self, payload: dict):
        """
        Reconstruct the adjacency matrix from the gateway's sparse edge list.
        Called once (or on reconnect if the retained message is re-delivered).
        """
        tls_ids   = payload["tls_ids"]
        self.num_nodes = payload["num_nodes"]
        self.adj = torch.tensor(payload["adj_matrix"], dtype=torch.float32).to(self.device)

        if self.tls_ids == tls_ids:
            return   # already initialised with this topology — nothing to do

        print(f"[Model] Topology received: {self.num_nodes} nodes")

        # Initialise GRU hidden state
        self.h_prev = torch.zeros(1, self.num_nodes, self.hidden_dim, device=self.device)

        # Build and load model
        self.model = STGAT_ActorCritic(
            feature_dim=FEATURE_DIM,
            hidden_dim=self.hidden_dim,
            num_actions=NUM_ACTIONS,
            k_hops=self._k_hops,
        ).to(self.device)

        if self.model_path:
            print(f"[Model] Loading weights from {self.model_path}…")
            ckpt = torch.load(self.model_path, map_location=self.device)
            self.model.load_state_dict(ckpt["model_state_dict"])
            print("[Model] Weights loaded.")
        else:
            print("[Model] No weights path — running with random weights (demo).")

        self.model.eval()
        self._topology_ready.set()
        print("[Model] Ready. Listening for state batches…")

    # ── State batch handler ───────────────────────────────────────
    def _handle_state_batch(self, payload: dict):
        """
        Receive full network state, run STGAT, publish actions.
        This is called from the MQTT network thread — model inference
        happens here, which is safe because loop_forever() is single-threaded.
        """
        if not self._topology_ready.is_set():
            print("[Model] State received before topology — dropping.")
            return
        step      = payload["step"]
        states_raw = payload["state"]   # list of dicts, ordered by node_index

        # ── Build state tensor (N, 3) in node_index order ────────
        state = torch.tensor(states_raw, dtype=torch.float32)   # (N, 3)
        state_dev = state.unsqueeze(0).to(self.device)           # (1, N, 3)

        # ── Run STGAT inference ───────────────────────────────────
        with torch.no_grad():
            action_probs, state_values, h_new = self.model(
                state_dev, self.adj, self.h_prev
            )
            # Deterministic: argmax over action dimension
            actions = torch.argmax(action_probs, dim=-1)   # (1, N)

        # Carry hidden state forward (the key reason the model must be stateful)
        self.h_prev = h_new

        actions_list = actions.squeeze(0).cpu().tolist()   # [0, 1, 0, ...]
        actions_list = [int(a) for a in actions_list]

        # ── Publish batch actions to gateway ─────────────────────
        self.mqtt.publish(
            "traffic/network/actions",
            json.dumps({
                "step":    step,
                "actions": actions_list,         # index matches tls_ids order
                "values":  [round(state_values[0, i, 0].item(), 4)
                            for i in range(self.num_nodes)],
            }),
            qos=1,
        )

        if step % 100 == 0:
            n_switches = sum(actions_list)
            print(f"[Model] Step {step} | switches: {n_switches}/{self.num_nodes}")

    # ── Entry point ───────────────────────────────────────────────
    def run(self):
        print("[Model] Connecting to broker…")
        try:
            self.mqtt.loop_forever()
        except KeyboardInterrupt:
            print("\n[Model] Stopped.")
        finally:
            self.mqtt.disconnect()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="STGAT decision model — standalone MQTT client")
    p.add_argument("--model",      default=None,  help="Path to stgat_ppo_best.pth")
    p.add_argument("--hidden-dim", type=int, default=64, help="GRU hidden size (default: 64)")
    p.add_argument("--k-hops",     type=int, default=3,  help="GAT hops (default: 3)")
    args = p.parse_args()

    STGATModelClient(
        model_path=args.model,
        hidden_dim=args.hidden_dim,
        k_hops=args.k_hops,
    ).run()