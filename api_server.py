"""
api_server.py — REST + WebSocket bridge for the dashboard

REST endpoints (historical, from SQLite):
  GET /api/junctions
  GET /api/state/<jid>?minutes=15
  GET /api/cmds/<jid>?minutes=15
  GET /api/summary

WebSocket (live, re-broadcasts MQTT messages):
  ws://localhost:5050/ws   → streams raw JSON state + cmd messages

Run:
  pip install flask flask-cors flask-sock paho-mqtt
  python api_server.py
"""

import json
import sqlite3
import time
import threading
import paho.mqtt.client as mqtt
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_sock import Sock

BROKER_HOST = "localhost"
BROKER_PORT = 1883
DB_FILE     = "traffic.db"
API_PORT    = 5050

app  = Flask(__name__)
CORS(app)
sock = Sock(app)

# ── Live subscriber registry ──────────────────────────────────
_ws_clients: set = set()
_ws_lock = threading.Lock()

def broadcast(payload: str):
    with _ws_lock:
        dead = set()
        for ws in _ws_clients:
            try:
                ws.send(payload)
            except Exception:
                dead.add(ws)
        _ws_clients -= dead

# ── MQTT → WebSocket bridge ───────────────────────────────────
def start_mqtt_bridge():
    def on_connect(client, userdata, flags, rc):
        print(f"[API] MQTT bridge connected (rc={rc})")
        client.subscribe("traffic/#")

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
            payload["_topic"] = msg.topic
            broadcast(json.dumps(payload))
        except Exception:
            pass

    client = mqtt.Client(client_id="api-bridge")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER_HOST, BROKER_PORT)
    client.loop_forever()

threading.Thread(target=start_mqtt_bridge, daemon=True).start()

# ── WebSocket endpoint ────────────────────────────────────────
@sock.route("/ws")
def ws_live(ws):
    with _ws_lock:
        _ws_clients.add(ws)
    try:
        while True:
            ws.receive(timeout=30)   # keep-alive ping
    except Exception:
        pass
    finally:
        with _ws_lock:
            _ws_clients.discard(ws)

# ── DB helper ─────────────────────────────────────────────────
def db():
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    return con

# ── REST endpoints ────────────────────────────────────────────
@app.route("/api/junctions")
def junctions():
    con = db()
    rows = con.execute("SELECT DISTINCT junction_id FROM junction_state").fetchall()
    con.close()
    return jsonify([r["junction_id"] for r in rows])

@app.route("/api/state/<jid>")
def state(jid):
    minutes = float(request.args.get("minutes", 15))
    since   = time.time() - minutes * 60
    con = db()
    rows = con.execute(
        "SELECT ts, pcu_queue, max_wait, current_phase, phase_duration "
        "FROM junction_state WHERE junction_id=? AND ts>=? ORDER BY ts",
        (jid, since)
    ).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/cmds/<jid>")
def cmds(jid):
    minutes = float(request.args.get("minutes", 15))
    since   = time.time() - minutes * 60
    con = db()
    rows = con.execute(
        "SELECT ts, step, action FROM junction_cmd "
        "WHERE junction_id=? AND ts>=? ORDER BY ts",
        (jid, since)
    ).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/summary")
def summary():
    con = db()
    rows = con.execute("""
        SELECT s.junction_id,
               s.pcu_queue, s.max_wait, s.current_phase,
               COALESCE(c.total_switches, 0) AS total_switches
        FROM (
            SELECT junction_id, pcu_queue, max_wait, current_phase
            FROM junction_state
            WHERE (junction_id, ts) IN (
                SELECT junction_id, MAX(ts) FROM junction_state GROUP BY junction_id
            )
        ) s
        LEFT JOIN (
            SELECT junction_id, SUM(action) AS total_switches
            FROM junction_cmd GROUP BY junction_id
        ) c ON s.junction_id = c.junction_id
    """).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

if __name__ == "__main__":
    print(f"[API] Starting on http://localhost:{API_PORT}")
    print(f"[API] WebSocket live feed at ws://localhost:{API_PORT}/ws")
    app.run(port=API_PORT, debug=False, threaded=True)