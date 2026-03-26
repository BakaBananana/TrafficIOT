"""
api_server.py — REST API for traffic.db

Endpoints:
  GET /junctions                          — list all junction IDs
  GET /state/{junction_id}?limit=N        — last N state rows for a junction
  GET /cmd/{junction_id}?limit=N          — last N cmd rows for a junction
  GET /moving_average/{junction_id}       — moving avg for pcu_queue / max_wait
      ?window=30&field=pcu_queue
  GET /network_summary                    — combined analytics across all junctions
  GET /live                               — latest single row per junction (for dashboard polling)

Run:
  pip install fastapi uvicorn
  uvicorn api_server:app --reload --port 8000
"""

import sqlite3
from collections import defaultdict
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

DB_FILE = "traffic.db"
app = FastAPI(title="Traffic Analytics API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_con():
    con = sqlite3.connect(DB_FILE, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


# ── helpers ──────────────────────────────────────────────────────────────────

def moving_average(values: list[float], window: int) -> list[float]:
    result = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        chunk = values[start : i + 1]
        result.append(sum(chunk) / len(chunk))
    return result


# ── routes ───────────────────────────────────────────────────────────────────

@app.get("/junctions")
def list_junctions():
    con = get_con()
    rows = con.execute(
        "SELECT DISTINCT junction_id FROM junction_state ORDER BY junction_id"
    ).fetchall()
    con.close()
    return {"junctions": [r["junction_id"] for r in rows]}


@app.get("/state/{junction_id}")
def get_state(junction_id: str, limit: int = Query(300, ge=1, le=5000)):
    con = get_con()
    rows = con.execute(
        """SELECT ts, step, pcu_queue, max_wait, current_phase, phase_duration
           FROM junction_state
           WHERE junction_id = ?
           ORDER BY ts DESC LIMIT ?""",
        (junction_id, limit),
    ).fetchall()
    con.close()
    if not rows:
        raise HTTPException(404, f"No data for junction '{junction_id}'")
    return {"junction_id": junction_id, "rows": [dict(r) for r in reversed(rows)]}


@app.get("/cmd/{junction_id}")
def get_cmd(junction_id: str, limit: int = Query(300, ge=1, le=5000)):
    con = get_con()
    rows = con.execute(
        """SELECT ts, step, action
           FROM junction_cmd
           WHERE junction_id = ?
           ORDER BY ts DESC LIMIT ?""",
        (junction_id, limit),
    ).fetchall()
    con.close()
    return {"junction_id": junction_id, "rows": [dict(r) for r in reversed(rows)]}


@app.get("/moving_average/{junction_id}")
def get_moving_average(
    junction_id: str,
    window: int = Query(30, ge=2, le=500),
    field: str = Query("pcu_queue", pattern="^(pcu_queue|max_wait)$"),
    limit: int = Query(300, ge=10, le=5000),
):
    con = get_con()
    rows = con.execute(
        f"""SELECT ts, {field}
            FROM junction_state
            WHERE junction_id = ?
            ORDER BY ts DESC LIMIT ?""",
        (junction_id, limit),
    ).fetchall()
    con.close()
    if not rows:
        raise HTTPException(404, f"No data for junction '{junction_id}'")
    rows = list(reversed(rows))
    timestamps = [r["ts"] for r in rows]
    values = [r[field] for r in rows]
    ma = moving_average(values, window)
    return {
        "junction_id": junction_id,
        "field": field,
        "window": window,
        "data": [{"ts": t, "raw": v, "ma": m} for t, v, m in zip(timestamps, values, ma)],
    }


@app.get("/network_summary")
def network_summary():
    con = get_con()
    # Overall averages per junction
    per_junction = con.execute(
        """SELECT junction_id,
                  AVG(pcu_queue)  AS avg_pcu,
                  AVG(max_wait)   AS avg_wait,
                  MAX(pcu_queue)  AS peak_pcu,
                  MAX(max_wait)   AS peak_wait,
                  COUNT(*)        AS samples
           FROM junction_state
           GROUP BY junction_id
           ORDER BY junction_id"""
    ).fetchall()

    # Network-wide totals (sum across junctions per timestep → average of those sums)
    network_rows = con.execute(
        """SELECT ts,
                  SUM(pcu_queue) AS total_pcu,
                  SUM(max_wait)  AS total_wait,
                  MAX(max_wait)  AS worst_wait
           FROM junction_state
           GROUP BY ts
           ORDER BY ts"""
    ).fetchall()

    con.close()

    totals = [dict(r) for r in network_rows]
    avg_total_pcu  = sum(r["total_pcu"]  for r in totals) / len(totals) if totals else 0
    avg_total_wait = sum(r["total_wait"] for r in totals) / len(totals) if totals else 0
    peak_total_pcu = max((r["total_pcu"]  for r in totals), default=0)
    worst_wait_ever = max((r["worst_wait"] for r in totals), default=0)

    return {
        "per_junction": [dict(r) for r in per_junction],
        "network": {
            "avg_total_pcu_queue": round(avg_total_pcu, 3),
            "avg_total_max_wait":  round(avg_total_wait, 3),
            "peak_total_pcu_queue": round(peak_total_pcu, 3),
            "worst_single_junction_wait": round(worst_wait_ever, 3),
            "timesteps_recorded": len(totals),
        },
        "timeseries": totals[-300:],   # last 300 network-wide snapshots
    }


@app.get("/live")
def live():
    """Latest row per junction — poll this every second for the dashboard."""
    con = get_con()
    rows = con.execute(
        """SELECT js.*
           FROM junction_state js
           INNER JOIN (
               SELECT junction_id, MAX(ts) AS max_ts
               FROM junction_state
               GROUP BY junction_id
           ) latest ON js.junction_id = latest.junction_id AND js.ts = latest.max_ts
           ORDER BY js.junction_id"""
    ).fetchall()
    con.close()
    return {"junctions": [dict(r) for r in rows]}
