"""
sumo_gateway.py — Pure SUMO ↔ MQTT Gateway (no model code)

Message flow each simulation step:
  1. Extract PCU state from SUMO
  2. PUBLISH  traffic/network/state   → full (N, 3) tensor as JSON (all junctions at once)
  3. BLOCK    waiting for            ← traffic/network/actions  (model replies with all actions)
  4. Apply actions to SUMO
  5. PUBLISH  traffic/{jid}/state    → per-junction telemetry (for logger / dashboard / twin)
  6. simulationStep()

The synchronous request/reply keeps the simulation clock locked to the model.
The model process owns h_prev entirely — the gateway never touches it.

Topics:
  PUBLISH  traffic/network/state    {"step", "ts", "tls_ids": [...], "state": [[q,w,p], ...]}
  PUBLISH  traffic/{jid}/state      per-junction telemetry (legacy schema for logger/dashboard)
  SUBSCRIBE traffic/network/actions {"step", "actions": [0,1,0,...], "values": [...]}

Run:
  python sumo_gateway.py --cfg stc_simulation.sumocfg --net patna_stc.net.xml [--gui]
"""

import argparse
import json
import time
import threading

import sumolib
import libsumo as traci
import paho.mqtt.client as mqtt

# ── Config ─────────────────────────────────────────────────────────────────
BROKER_HOST    = "localhost"
BROKER_PORT    = 1883
STEP_LENGTH    = 1.0    # simulation seconds per step
ACTION_TIMEOUT = 5.0    # seconds to wait for model reply before skipping

# PCU weights — must match env_sumo.py and model.py
PCU_WEIGHTS = {
    "motorcycle_ind": 0.5,
    "car_ind":        1.0,
    "auto_ind":       1.0,
    "bus_ind":        3.0,
}


# ── State extraction ────────────────────────────────────────────────────────
def get_state(tls_ids: list[str]) -> list[list[float]]:
    """
    PCU-weighted state for all junctions.
    Returns list of [pcu_queue, max_wait, phase_index] per junction,
    in the same order as tls_ids.
    """
    rows = []
    for tls in tls_ids:
        pcu_queue = 0.0
        max_wait  = 0.0

        controlled_links = traci.trafficlight.getControlledLinks(tls)
        incoming_lanes   = set(link[0][0] for link in controlled_links if link)

        for lane in incoming_lanes:
            for veh in traci.lane.getLastStepVehicleIDs(lane):
                if traci.vehicle.getSpeed(veh) < 0.1:
                    v_type    = traci.vehicle.getTypeID(veh)
                    wait_time = traci.vehicle.getAccumulatedWaitingTime(veh)
                    pcu_queue += PCU_WEIGHTS.get(v_type, 1.0)
                    if wait_time > max_wait:
                        max_wait = wait_time

        phase = traci.trafficlight.getPhase(tls)
        rows.append([round(pcu_queue, 2), round(max_wait, 2), float(phase)])
    return rows


# ── Adjacency matrix ────────────────────────────────────────────────────────
def build_adjacency_matrix(net, tls_ids: list[str]) -> list[list[float]]:
    n = len(tls_ids)
    idx = {tls: i for i, tls in enumerate(tls_ids)}
    tls_set = set(tls_ids)
    W = [[0.0] * n for _ in range(n)]

    for start_tls in tls_ids:
        start_node = net.getNode(start_tls)
        stack = []
        for edge in start_node.getOutgoing():
            stack.append((edge.getToNode(), edge.getLength()))
        
        visited = set()
        
        while stack:
            curr_node, dist = stack.pop()
            if curr_node.getID() in visited:
                continue
            visited.add(curr_node.getID())

            if curr_node.getType() == "traffic_light":
                target_id = curr_node.getID()
                if target_id in idx and target_id != start_tls:
                    i, j = idx[start_tls], idx[target_id]
                    weight = 100.0 / (dist + 1.0)
                    W[i][j] = max(W[i][j], weight)
                continue

            for edge in curr_node.getOutgoing():
                stack.append((edge.getToNode(), dist + edge.getLength()))

    return W

# ── Gateway ─────────────────────────────────────────────────────────────────
class SumoGateway:
    def __init__(self, cfg: str, net_file: str, gui: bool):
        self.cfg  = cfg
        self.gui  = gui

        # Synchronisation: main loop blocks on this event until model replies
        self._action_event            = threading.Event()
        self._pending_actions: list[int] | None   = None
        self._pending_values:  list[float] | None = None

        # ── Read network topology ───────────────────────────────
        print("[Gateway] Reading network topology…")
        net = sumolib.net.readNet(net_file)

        # ── Start SUMO to discover junction ordering ────────────
        binary = "sumo-gui" if gui else "sumo"
        traci.start([binary, "-c", cfg, "--step-length", str(STEP_LENGTH)])
        self.tls_ids   = list(traci.trafficlight.getIDList())
        self.num_nodes = len(self.tls_ids)
        print(f"[Gateway] {self.num_nodes} TLS junctions: {self.tls_ids}")

        # Build adjacency matrix once — published as a retained MQTT message
        # so the model receives it immediately on connect, even if it starts late
        self.adj_matrix = build_adjacency_matrix(net, self.tls_ids)

        # ── MQTT ────────────────────────────────────────────────
        self.mqtt = mqtt.Client(client_id="sumo-gateway")
        self.mqtt.on_connect = self._on_connect
        self.mqtt.on_message = self._on_actions
        self.mqtt.connect(BROKER_HOST, BROKER_PORT)
        self.mqtt.loop_start()

    # ── MQTT callbacks ───────────────────────────────────────────
    def _on_connect(self, client, userdata, flags, rc):
        print(f"[Gateway] MQTT connected (rc={rc})")
        client.subscribe("traffic/network/actions")

        # Retained topology: model gets this the moment it subscribes,
        # regardless of startup order.
        client.publish(
            "traffic/network/topology",
            json.dumps({
                "tls_ids":    self.tls_ids,
                "adj_matrix": self.adj_matrix,
                "num_nodes":  self.num_nodes,
            }),
            qos=1,
            retain=True,
        )
        print("[Gateway] Topology published (retained).")

    def _on_actions(self, client, userdata, msg):
        """Model published its action vector — unblock the main loop."""
        try:
            payload               = json.loads(msg.payload)
            self._pending_actions = payload["actions"]        # list[int], length N
            self._pending_values  = payload.get("values", []) # list[float], length N
            self._action_event.set()
        except Exception as e:
            print(f"[Gateway] Bad actions message: {e}")

    def _publish(self, topic: str, payload: dict):
        self.mqtt.publish(topic, json.dumps(payload), qos=1)

    # ── Main simulation loop ─────────────────────────────────────
    def run(self):
        phase_starts: dict[str, int] = {jid: 0 for jid in self.tls_ids}
        step = 0

        print("[Gateway] Waiting for model to subscribe…")
        time.sleep(2.0)   # brief grace period for the model process to connect
        print("[Gateway] Simulation running.")

        try:
            while traci.simulation.getMinExpectedNumber() > 0:
                # if step % 5 != 0:
                #     traci.simulationStep()
                #     step += 1
                #     continue

                # ── 1. Extract PCU-weighted state ───────────────
                state_rows = get_state(self.tls_ids)   # list of [q, w, ph]

                # ── 2. Publish full network state ───────────────
                self._action_event.clear()
                self._pending_actions = None
                self._publish("traffic/network/state", {
                    "step":    step,
                    "ts":      time.time(),
                    "tls_ids": self.tls_ids,
                    "state":   state_rows,   # shape (N, 3) as nested list
                })

                # ── 3. Block until model replies (or timeout) ───
                got_reply = self._action_event.wait(timeout=ACTION_TIMEOUT)

                if not got_reply or self._pending_actions is None:
                    print(f"[Gateway] Step {step}: model timeout — holding all phases.")
                    actions = [0] * self.num_nodes
                    values  = [0.0] * self.num_nodes
                else:
                    actions = self._pending_actions
                    values  = self._pending_values or [0.0] * self.num_nodes

                # ── 4. Apply actions to SUMO ────────────────────
                for i, jid in enumerate(self.tls_ids):
                    if actions[i] == 1:
                        current = traci.trafficlight.getPhase(jid)
                        logic   = traci.trafficlight.getCompleteRedYellowGreenDefinition(jid)[0]
                        n_ph    = len(logic.phases)
                        traci.trafficlight.setPhase(jid, (current + 1) % n_ph)
                        phase_starts[jid] = step

                # ── 5. Publish per-junction telemetry ───────────
                # (legacy schema kept intact — logger/dashboard unchanged)
                for i, jid in enumerate(self.tls_ids):
                    q, w, ph = state_rows[i]
                    self._publish(f"traffic/{jid}/state", {
                        "junction_id":    jid,
                        "step":           step,
                        "ts":             time.time(),
                        "current_phase":  int(ph),
                        "phase_duration": round(
                            (step - phase_starts.get(jid, 0)) * STEP_LENGTH, 1
                        ),
                        "pcu_queue":      q,
                        "max_wait":       w,
                        "queues":         [q],       # legacy field
                        "waiting_times":  [w],       # legacy field
                    })
                    self._publish(f"traffic/{jid}/cmd", {
                        "junction_id": jid,
                        "step":        step,
                        "ts":          time.time(),
                        "phase":       int(ph),
                        "action":      actions[i],
                        "switched":    actions[i],
                        "reason":      "stgat",
                        "value":       values[i] if i < len(values) else 0.0,
                    })

                # ── 6. Advance simulation clock ──────────────────
                traci.simulationStep()
                step += 1

                if step % 100 == 0:
                    print(f"[Gateway] Step {step} | "
                          f"vehicles: {traci.simulation.getMinExpectedNumber()}")
                    
                time.sleep(STEP_LENGTH)

        except KeyboardInterrupt:
            print("\n[Gateway] Interrupted.")
        finally:
            self.mqtt.loop_stop()
            traci.close()
            print("[Gateway] Stopped.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="SUMO MQTT Gateway")
    p.add_argument("--cfg", required=True, help="Path to .sumocfg file")
    p.add_argument("--net", required=True, help="Path to .net.xml file")
    p.add_argument("--gui", action="store_true")
    args = p.parse_args()

    SumoGateway(args.cfg, args.net, args.gui).run()