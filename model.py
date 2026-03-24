"""
model.py — Decision model (pure MQTT subscriber/publisher)

Subscribes: traffic/+/state
Publishes:  traffic/{jid}/cmd   → {"junction_id": ..., "phase": N}

No SUMO dependency. Swap this file to plug in an ML model.
"""

import json
import time
import paho.mqtt.client as mqtt

BROKER_HOST = "localhost"
BROKER_PORT = 1883

MIN_GREEN  = 10   # seconds minimum green before switching
MAX_GREEN  = 60   # seconds maximum green before forced switch
THRESHOLD  = 5    # extra vehicles on another phase to trigger switch


def decide(state: dict) -> dict | None:
    """
    Returns {"junction_id", "phase", "reason"} or None (keep current phase).
    Replace this function body with an ML model call if needed.
    """
    jid      = state["junction_id"]
    phase    = state["current_phase"]
    duration = state["phase_duration"]
    queues   = state["queues"]
    waits    = state["waiting_times"]
    n        = len(queues)

    if n == 0:
        return None

    if duration < MIN_GREEN:
        return None  # too soon

    if duration >= MAX_GREEN:
        next_ph = (phase + 1) % n
        return {"junction_id": jid, "phase": next_ph, "reason": "max_green_exceeded"}

    cur_q   = queues[phase % n]
    others  = [(i, queues[i], waits[i]) for i in range(n) if i != phase % n]
    best    = max(others, key=lambda x: x[1], default=None)

    if best and best[1] > cur_q + THRESHOLD:
        return {"junction_id": jid, "phase": best[0], "reason": f"high_demand q={best[1]}"}

    if best and best[2] > 45 and cur_q < THRESHOLD:
        return {"junction_id": jid, "phase": best[0], "reason": f"long_wait {best[2]:.1f}s"}

    return None  # keep current


class DecisionModel:
    def __init__(self):
        self.client = mqtt.Client(client_id="decision-model")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_state

    def _on_connect(self, client, userdata, flags, rc):
        print(f"[Model] Connected (rc={rc})")
        client.subscribe("traffic/+/state")

    def _on_state(self, client, userdata, msg):
        try:
            state = json.loads(msg.payload)
            cmd   = decide(state)
            if cmd:
                cmd["ts"] = time.time()
                jid = cmd["junction_id"]
                client.publish(f"traffic/{jid}/cmd", json.dumps(cmd), qos=1)
                print(f"[Model] {jid} → phase {cmd['phase']} ({cmd['reason']})")
        except Exception as e:
            print(f"[Model] Error: {e}")

    def run(self):
        self.client.connect(BROKER_HOST, BROKER_PORT)
        print("[Model] Listening for state messages…")
        try:
            self.client.loop_forever()
        except KeyboardInterrupt:
            print("[Model] Stopped.")


if __name__ == "__main__":
    DecisionModel().run()