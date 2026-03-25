"""
logger.py — Database logger (pure MQTT subscriber)

Subscribes: traffic/+/state
            traffic/+/cmd
Writes to:  traffic.db (SQLite)

No SUMO dependency. Runs independently alongside any other subscribers.
"""

import json
import sqlite3
import time
import paho.mqtt.client as mqtt

BROKER_HOST = "localhost"
BROKER_PORT = 1883
DB_FILE     = "traffic.db"


def init_db():
    con = sqlite3.connect(DB_FILE)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS junction_state (
            ts             REAL    NOT NULL,
            junction_id    TEXT    NOT NULL,
            step           INTEGER,
            pcu_queue      REAL    NOT NULL,
            max_wait       REAL    NOT NULL,
            current_phase  INTEGER NOT NULL,
            phase_duration REAL    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_state ON junction_state(junction_id, ts);

        CREATE TABLE IF NOT EXISTS junction_cmd (
            ts             REAL    NOT NULL,
            junction_id    TEXT    NOT NULL,
            step           INTEGER,
            action         INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cmd ON junction_cmd(junction_id, ts);
    """)
    con.commit()
    con.close()
    print(f"[Logger] Database ready: {DB_FILE}")


class DBLogger:
    def __init__(self):
        self.client = mqtt.Client(client_id="db-logger")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        print(f"[Logger] Connected (rc={rc})")
        client.subscribe("traffic/+/state")
        client.subscribe("traffic/+/cmd")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
            parts   = msg.topic.split("/")
            jid, kind = parts[1], parts[2]
            ts = payload.get("ts")

            con = sqlite3.connect(DB_FILE)
            if kind == "state":
                con.execute(
                    "INSERT INTO junction_state VALUES (?,?,?,?,?,?,?)",
                    (ts, jid,
                     payload.get("step"),
                     payload.get("pcu_queue", 0.0),
                     payload.get("max_wait",  0.0),
                     payload.get("current_phase",  0),
                     payload.get("phase_duration", 0.0))
                )
            elif kind == "cmd":
                con.execute(
                    "INSERT INTO junction_cmd VALUES (?,?,?,?)",
                    (ts, jid,
                     payload.get("step"),
                     payload.get("action", 0))
                )
            con.commit()
            con.close()
        except Exception as e:
            print(f"[Logger] Error: {e}")

    def run(self):
        self.client.connect(BROKER_HOST, BROKER_PORT)
        print("[Logger] Writing all traffic messages to SQLite…")
        try:
            self.client.loop_forever()
        except KeyboardInterrupt:
            print("[Logger] Stopped.")


if __name__ == "__main__":
    init_db()
    DBLogger().run()