"""
api_server.py — REST + WebSocket bridge for the dashboard

REST endpoints (historical, from SQLite):
    GET /api/junctions
    GET /api/state/<jid>?since=<sim_step>&limit=200
    GET /api/cmds/<jid>?since=<sim_step>&limit=200
    GET /api/summary
    GET /api/sim_time        ← current max simulation time seen

WebSocket (live, re-broadcasts MQTT messages):
    ws://localhost:5050/ws → streams raw JSON state + cmd messages

NOTE: All time values (ts) are SUMO simulation seconds, not wall-clock time.
      Use the `since` query param to request records after a given simulation
      second (e.g. ?since=300 for everything after sim-second 300).
      Use `limit` to cap the number of rows returned (default 200).

Run:
    pip install flask flask-cors flask-sock paho-mqtt
    python api_server.py
"""

import json
import sqlite3
import threading

import paho.mqtt.client as mqtt
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_sock import Sock

BROKER_HOST = "localhost"
BROKER_PORT  = 1883
DB_FILE      = "traffic.db"
API_PORT     = 5050

app  = Flask(__name__)
CORS(app)
sock = Sock(app)

# ── Track the latest simulation time seen over MQTT ───────────────────────
_sim_time_lock = threading.Lock()
_latest_sim_ts: float = 0.0   # simulation seconds, updated by MQTT bridge


def _update_sim_ts(ts: float):
    global _latest_sim_ts
    with _sim_time_lock:
        if ts > _latest_sim_ts:
            _latest_sim_ts = ts


def _get_sim_ts() -> float:
    with _sim_time_lock:
        return _latest_sim_ts

# ── Live subscriber registry ──────────────────────────────────────────────
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

# ── MQTT → WebSocket bridge ───────────────────────────────────────────────
def start_mqtt_bridge():
    def on_connect(client, userdata, flags, rc):
        print(f"[API] MQTT bridge connected (rc={rc})")
        client.subscribe("traffic/#")

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
            # Keep track of the latest simulation timestamp
            if "ts" in payload:
                _update_sim_ts(float(payload["ts"]))
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

# ── WebSocket endpoint ────────────────────────────────────────────────────
@sock.route("/ws")
def ws_live(ws):
    with _ws_lock:
        _ws_clients.add(ws)
    try:
        while True:
            ws.receive(timeout=30)   # keep-alive
    except Exception:
        pass
    finally:
        with _ws_lock:
            _ws_clients.discard(ws)

# ── DB helper ─────────────────────────────────────────────────────────────
def db():
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    return con

# ── REST endpoints ────────────────────────────────────────────────────────

@app.route("/api/sim_time")
def sim_time():
    """Return the current maximum simulation timestamp seen (sim seconds)."""
    con = db()
    row = con.execute("SELECT MAX(ts) AS max_ts FROM junction_state").fetchone()
    con.close()
    db_max = row["max_ts"] if row and row["max_ts"] is not None else 0.0
    # Also consider what we've seen live over MQTT
    live_max = _get_sim_ts()
    return jsonify({"sim_ts": max(db_max, live_max)})


@app.route("/api/junctions")
def junctions():
    con = db()
    rows = con.execute(
        "SELECT DISTINCT junction_id FROM junction_state"
    ).fetchall()
    con.close()
    return jsonify([r["junction_id"] for r in rows])


@app.route("/api/state/<jid>")
def state(jid):
    """
    Return junction state rows for <jid>.

    Query params:
      since  – only rows with ts >= this simulation second (default 0)
      limit  – max rows to return, newest-last (default 200)
    """
    since = float(request.args.get("since", 0))
    limit = int(request.args.get("limit", 200))

    con = db()
    rows = con.execute(
        "SELECT ts, step, pcu_queue, max_wait, current_phase, phase_duration "
        "FROM junction_state "
        "WHERE junction_id=? AND ts>=? "
        "ORDER BY ts "
        "LIMIT ?",
        (jid, since, limit)
    ).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/cmds/<jid>")
def cmds(jid):
    """
    Return junction command rows for <jid>.

    Query params:
      since  – only rows with ts >= this simulation second (default 0)
      limit  – max rows to return (default 200)
    """
    since = float(request.args.get("since", 0))
    limit = int(request.args.get("limit", 200))

    con = db()
    rows = con.execute(
        "SELECT ts, step, action FROM junction_cmd "
        "WHERE junction_id=? AND ts>=? "
        "ORDER BY ts "
        "LIMIT ?",
        (jid, since, limit)
    ).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/summary")
def summary():
    con = db()
    rows = con.execute("""
        SELECT s.junction_id,
               s.ts,
               s.step,
               s.pcu_queue,
               s.max_wait,
               s.current_phase,
               COALESCE(c.total_switches, 0) AS total_switches
        FROM (
            SELECT junction_id, ts, step, pcu_queue, max_wait, current_phase
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
    print(f"[API] All timestamps are SUMO simulation seconds.")
    app.run(port=API_PORT, debug=False, threaded=True)