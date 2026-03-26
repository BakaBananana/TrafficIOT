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
ACTION_TIMEOUT  = 5.0   # seconds to wait for model reply before skipping
YELLOW_STEPS    = 3     # simulation steps for yellow clearance (matches env_sumo.step)
MIN_GREEN_STEPS = 10    # minimum green time after a phase switch (matches env_sumo.step)

# PCU weights — must match env_sumo.py and model.py
PCU_WEIGHTS = {
    "motorcycle_ind": 0.5,
    "car_ind":        1.0,
    "auto_ind":       1.0,
    "bus_ind":        3.0,
}


# ── State extraction ────────────────────────────────────────────────────────
def get_state(tls_ids: list[str], normalized=False) -> list[list[float]]:
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
        logic = traci.trafficlight.getCompleteRedYellowGreenDefinition(tls)[0]
        num_phases = len(logic.phases)
        
        # Dynamic Normalization (Scales perfectly regardless of phase count)
        scaled_queue = pcu_queue / 50.0  
        scaled_wait = max_wait / 100.0    
        scaled_phase = phase / float(num_phases)     
        
        if normalized:
            rows.append([scaled_queue, scaled_wait, scaled_phase])
        else:
            rows.append([round(pcu_queue, 2), round(max_wait, 2), float(phase)])
    return rows


# ── Adjacency matrix ────────────────────────────────────────────────────────
def build_adjacency_matrix(net, tls_ids: list[str]) -> list[list[float]]:
    """Distance-weighted adjacency matrix as a nested list (JSON-serialisable)."""
    n   = len(tls_ids)
    idx = {tls: i for i, tls in enumerate(tls_ids)}
    W   = [[0.0] * n for _ in range(n)]
    
    for tls_i in tls_ids:
        idx_i = idx[tls_i]
        node = net.getNode(tls_i)
        outgoing_edges = [edge for edge in node.getOutgoing()]
        
        for edge in outgoing_edges:
            dest_node = edge.getToNode()
            if dest_node.getType() == "traffic_light":
                tls_j = dest_node.getID()
                if tls_j in idx:
                    idx_j = idx[tls_j]
                    distance = edge.getLength()
                    weight = 100.0 / (distance + 1.0) 
                    W[idx_i][idx_j] = weight
                    
    # GAT Self-Loops: Intersections must monitor their own queues!
    for i in range(n):
        W[i][i] = 100.0  
        
    return W


# ── Gateway ─────────────────────────────────────────────────────────────────
class SumoGateway:
    def __init__(self, cfg: str, net_file: str, gui: bool):
        self.cfg  = cfg
        self.gui  = gui

        # Synchronisation: main loop blocks on this event until model replies
        self._action_event            = threading.Event()
        self._pending_actions: list[int] | None   = None

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
        client.subscribe("network/actions")

        # Retained topology: model gets this the moment it subscribes,
        # regardless of startup order.
        client.publish(
            "network/topology",
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
            self._action_event.set()
        except Exception as e:
            print(f"[Gateway] Bad actions message: {e}")

    def _publish(self, topic: str, payload: dict):
        self.mqtt.publish(topic, json.dumps(payload), qos=1)

    # ── Simulation helpers ────────────────────────────────────────
    def _sim_step(self, step_counter: list[int], phase_starts: dict) -> bool:
        """
        Advance SUMO by one second, publish state for every junction, then increment counter.
        Returns False if the simulation has ended.
        """
        if traci.simulation.getMinExpectedNumber() == 0:
            return False
        traci.simulationStep()
        step_counter[0] += 1
        self._publish_states(get_state(self.tls_ids), phase_starts, step_counter[0])
        time.sleep(1)
        print(step_counter[0])
        return True

    def _publish_states(self, state_rows: list, phase_starts: dict, step: int):
        """Publish traffic/{jid}/state for every junction."""
        ts = traci.simulation.getTime()
        for i, jid in enumerate(self.tls_ids):
            q, w, ph = state_rows[i]
            self._publish(f"traffic/{jid}/state", {
                "junction_id":    jid,
                "step":           step,
                "ts":             ts,
                "current_phase":  int(ph),
                "phase_duration": round(
                    (step - phase_starts.get(jid, 0)) * STEP_LENGTH, 1
                ),
                "pcu_queue":      q,
                "max_wait":       w,
            })

    def _publish_cmds(self, actions: list[int], step: int):
        """Publish traffic/{jid}/cmd once per decision — action is the value (0 or 1)."""
        ts = traci.simulation.getTime()
        for i, jid in enumerate(self.tls_ids):
            self._publish(f"traffic/{jid}/cmd", {
                "junction_id": jid,
                "step":        step,
                "ts":          ts,
                "action":      actions[i],          # 0 = keep, 1 = switch
            })

    # ── Main simulation loop ─────────────────────────────────────
    def run(self):
        phase_starts: dict[str, int] = {jid: 0 for jid in self.tls_ids}
        step = [0]

        print("[Gateway] Waiting for model to subscribe…")
        time.sleep(2.0)
        print("[Gateway] Simulation running.")

        try:
            while traci.simulation.getMinExpectedNumber() > 0:

                # ── 1. Observe & publish current state ──────────
                state_rows = get_state(self.tls_ids)
                normalized_state_rows = get_state(self.tls_ids, normalized=True)
                self._publish_states(state_rows, phase_starts, step[0])

                # ── 2. Ask model for actions ────────────────────
                self._action_event.clear()
                self._pending_actions = None
                self._publish("network/state", {
                    "step":    step[0],
                    "ts":      traci.simulation.getTime(),
                    "tls_ids": self.tls_ids,
                    "state":   normalized_state_rows,
                })

                got_reply = self._action_event.wait(timeout=ACTION_TIMEOUT)
                if not got_reply or self._pending_actions is None:
                    print(f"[Gateway] Step {step[0]}: model timeout — holding phases.")
                    actions = [0] * self.num_nodes
                else:
                    actions = self._pending_actions

                # ── 3. Publish cmd now that actions are known ───
                self._publish_cmds(actions, step[0])

                # ── 4. Apply phase transitions ──────────────────
                any_switch  = False
                orig_phases: dict[str, int] = {}

                for i, jid in enumerate(self.tls_ids):
                    if actions[i] == 1:
                        any_switch = True
                        logic   = traci.trafficlight.getCompleteRedYellowGreenDefinition(jid)[0]
                        n_ph    = len(logic.phases)
                        current = traci.trafficlight.getPhase(jid)
                        orig_phases[jid] = current

                        yellow_phase = (current + 1) % n_ph
                        traci.trafficlight.setPhase(jid, yellow_phase)
                        traci.trafficlight.setPhaseDuration(jid, 100_000)

                # ── 5. Yellow clearance (3 steps, state each) ───
                if any_switch:
                    for _ in range(YELLOW_STEPS):
                        if not self._sim_step(step, phase_starts):
                            break

                    for jid, orig in orig_phases.items():
                        logic     = traci.trafficlight.getCompleteRedYellowGreenDefinition(jid)[0]
                        n_ph      = len(logic.phases)
                        new_green = (orig + 2) % n_ph
                        traci.trafficlight.setPhase(jid, new_green)
                        traci.trafficlight.setPhaseDuration(jid, 100_000)
                        phase_starts[jid] = step[0]

                # ── 6. Minimum green time (state each step) ─────
                green_steps = MIN_GREEN_STEPS if any_switch else 1
                for _ in range(green_steps):
                    if not self._sim_step(step, phase_starts):
                        break

                if step[0] % 100 == 0:
                    print(f"[Gateway] Step {step[0]} | "
                          f"vehicles: {traci.simulation.getMinExpectedNumber()}")

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