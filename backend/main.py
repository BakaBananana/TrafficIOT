"""
Traffic Control Dashboard — FastAPI Backend
Serves training data, manages inference sessions, and streams live metrics via WebSocket.

Supports two modes:
  • REAL SUMO — runs actual SUMO simulation with STGAT-PPO model (requires SUMO installed)
  • MOCK       — built-in simulation for demo/development (no external deps)

Auto-detects SUMO availability; falls back to mock if unavailable.
"""

import asyncio
import sys

# Fix for aiomqtt on Windows (ProactorEventLoop doesn't support add_reader)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import csv
import json
import os
import random
import math
import traceback
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ── Time-Series DB (optional — graceful fallback) ────────────────────────────
from tsdb import tsdb

# ── MQTT Bridge (optional — graceful fallback) ───────────────────────────────
from mqtt_bridge import mqtt_bridge

# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="Patna STC Dashboard API", version="2.0.0")

# Start MQTT listener as a background task
@app.on_event("startup")
async def start_mqtt():
    asyncio.create_task(mqtt_bridge.start())

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent.parent  # project root
LOG_CSV    = BASE_DIR / "training_log_real_good.csv"

# ── SUMO Mode Detection ──────────────────────────────────────────────────────
USE_REAL_SUMO = False
_sumo_unavail_reason = ""

try:
    import torch
    import numpy as np
    import traci  # subprocess mode
    from sumo_inference import SumoInferenceRunner

    # Quick sanity check — can we actually find the simulation files?
    sim_dir = Path(__file__).parent / "simulation"
    _model_ok = (sim_dir / "stgat_ppo_best_real_actual_consistent.pth").exists()
    _net_ok   = (sim_dir / "patna_stc.net.xml").exists()
    _cfg_ok   = (sim_dir / "stc_simulation.sumocfg").exists()

    if _model_ok and _net_ok and _cfg_ok:
        USE_REAL_SUMO = True
    else:
        missing = []
        if not _model_ok: missing.append("model .pth")
        if not _net_ok:   missing.append("net .xml")
        if not _cfg_ok:   missing.append("sumocfg")
        _sumo_unavail_reason = f"Missing files: {', '.join(missing)}"
except ImportError as e:
    _sumo_unavail_reason = f"Import error: {e}"
except Exception as e:
    _sumo_unavail_reason = f"Unexpected error: {e}"

# ── Concurrency lock (only one SUMO session at a time) ────────────────────────
_sumo_lock = asyncio.Lock()
_active_runner: Optional["SumoInferenceRunner"] = None


@app.on_event("startup")
async def startup():
    mode = "REAL SUMO" if USE_REAL_SUMO else f"MOCK (fallback: {_sumo_unavail_reason})"
    print(f"\n{'='*60}")
    print(f"  Patna STC Dashboard API")
    print(f"  Inference mode: {mode}")
    print(f"{'='*60}\n")


# ── Training Data ─────────────────────────────────────────────────────────────
@app.get("/api/training")
def get_training_data():
    """Return full training log as JSON."""
    if not LOG_CSV.exists():
        for candidate in Path(__file__).parents:
            found = list(candidate.glob("training_log_real_good.csv"))
            if found:
                csv_path = found[0]
                break
        else:
            raise HTTPException(404, "training_log_real_good.csv not found")
    else:
        csv_path = LOG_CSV

    rows = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "episode":           int(row["episode"]),
                "num_vehicles":      int(row["num_vehicles"]),
                "cumulative_reward": float(row["cumulative_reward"]),
                "normalized_reward": float(row["normalized_reward"]),
            })
    return JSONResponse(content={"data": rows})


# ── Status endpoint ───────────────────────────────────────────────────────────
@app.get("/api/status")
def get_status():
    """Return current mode and availability info."""
    return {
        "mode": "sumo" if USE_REAL_SUMO else "mock",
        "sumo_available": USE_REAL_SUMO,
        "sumo_unavail_reason": _sumo_unavail_reason if not USE_REAL_SUMO else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# MOCK SIMULATION (fallback when SUMO is unavailable)
# ══════════════════════════════════════════════════════════════════════════════

NUM_INTERSECTIONS_MOCK = 10
TLS_IDS_MOCK = [f"J{i}" for i in range(NUM_INTERSECTIONS_MOCK)]


def _make_snapshot(step: int, episode: int, rng: random.Random) -> dict:
    """Produce one step's worth of simulated metrics (mock mode)."""
    t = step / 3600.0

    global_load = math.sin(t * math.pi) ** 1.2

    intersections = []
    for idx, tls_id in enumerate(TLS_IDS_MOCK):
        phase_offset  = idx * 0.3
        local_load    = global_load * (0.6 + 0.4 * math.sin(t * 5 + phase_offset))
        queue         = max(0.0, local_load * 45 + rng.gauss(0, 3))
        wait          = max(0.0, queue * 2.1 + rng.gauss(0, 5))
        phase         = int((step // 30 + idx * 2) % 4)
        action        = 1 if (step % (25 + idx * 3) == 0) else 0

        intersections.append({
            "id":           tls_id,
            "index":        idx,
            "queue_pcu":    round(queue, 2),
            "wait_time_s":  round(wait, 2),
            "phase":        phase,
            "action":       action,
        })

    total_queue   = sum(i["queue_pcu"]   for i in intersections)
    avg_wait      = sum(i["wait_time_s"] for i in intersections) / NUM_INTERSECTIONS_MOCK
    switches      = sum(i["action"]      for i in intersections)
    reward        = -(total_queue + 0.5 * avg_wait * NUM_INTERSECTIONS_MOCK) - switches * 15
    active_vehs   = max(0, int(1500 * (1 - t ** 0.7) + rng.gauss(0, 20)))

    return {
        "type":            "step",
        "episode":         episode,
        "step":            step,
        "timestamp_s":     step,
        "active_vehicles": active_vehs,
        "total_queue_pcu": round(total_queue, 2),
        "avg_wait_s":      round(avg_wait, 2),
        "step_reward":     round(reward, 2),
        "switches":        switches,
        "intersections":   intersections,
    }


# ══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET HANDLER (shared protocol for both modes)
# ══════════════════════════════════════════════════════════════════════════════

@app.websocket("/ws/inference")
async def inference_websocket(ws: WebSocket):
    """
    Stream live inference metrics to the dashboard.

    Message protocol
    ────────────────
    Client → Server:
        { "action": "start", "episode": N, "num_vehicles": K }
        { "action": "stop" }

    Server → Client:
        { "type": "ready", "mode": "sumo"|"mock" }
        { "type": "episode_start", "episode": N, "num_vehicles": K }
        { "type": "step", ...metrics... }
        { "type": "episode_end", ...summary... }
        { "type": "error", "message": "..." }
    """
    await ws.accept()
    await ws.send_json({
        "type": "ready",
        "mode": "sumo" if USE_REAL_SUMO else "mock",
    })

    stop_flag = asyncio.Event()

    # ── MOCK inference loop ───────────────────────────────────────────
    async def mock_inference_loop(episode: int, num_vehicles: int, max_steps: int = 3600, run_id: str = "default"):
        rng = random.Random(episode * 1000 + num_vehicles)
        max_steps_mock = max_steps
        cumulative_reward = 0.0
        total_switches = 0

        await ws.send_json({
            "type":         "episode_start",
            "episode":      episode,
            "num_vehicles": num_vehicles,
            "run_id":       run_id,
        })

        for step in range(max_steps_mock):
            if stop_flag.is_set():
                break

            snapshot = _make_snapshot(step, episode, rng)
            cumulative_reward += snapshot["step_reward"]
            total_switches    += snapshot["switches"]

            await ws.send_json(snapshot)
            tsdb.write_step(snapshot, mode="agent", episode=episode, run_id=run_id)
            await mqtt_bridge.publish_sensor_snapshot(snapshot)
            await asyncio.sleep(0.03)

            if snapshot["active_vehicles"] == 0:
                break

        norm_reward = cumulative_reward / num_vehicles

        summary_msg = {
            "type":               "episode_end",
            "episode":            episode,
            "num_vehicles":       num_vehicles,
            "cumulative_reward":  round(cumulative_reward, 2),
            "normalized_reward":  round(norm_reward, 4),
            "total_switches":     total_switches,
            "steps_completed":    step + 1,
        }
        await ws.send_json(summary_msg)
        tsdb.write_episode_summary(summary_msg, mode="agent", run_id=run_id)

    # ── REAL SUMO inference loop ──────────────────────────────────────
    async def sumo_inference_loop(episode: int, num_vehicles: int, max_steps: int = 4500, spawn: int = 3540, run_id: str = "default", seed: int = 42, use_gui: bool = False):
        global _active_runner

        runner = None
        try:
            # Acquire lock — only one SUMO session at a time
            async with _sumo_lock:
                runner = SumoInferenceRunner()

                # Initialize model + env in a thread (blocking I/O)
                print(f"[SUMO] Initializing runner (gui={use_gui})...")
                await asyncio.to_thread(runner.initialize, use_gui)
                _active_runner = runner

                # Start episode (blocking — resets SUMO, generates demand)
                print(f"[SUMO] Starting episode {episode} with {num_vehicles} vehicles, max_steps={max_steps}, spawn={spawn}...")
                episode_start_msg = await asyncio.to_thread(
                    runner.start_episode, episode, num_vehicles, max_steps, spawn, seed
                )
                episode_start_msg["run_id"] = run_id
                print("[SUMO] Episode started, sending to frontend...")
                await ws.send_json(episode_start_msg)

                # Step loop
                step_count = 0
                while not stop_flag.is_set():
                    # Run one SUMO step in a thread to avoid blocking the event loop
                    snapshot = await asyncio.to_thread(runner.step)

                    if snapshot is None:
                        print(f"[SUMO] Episode finished at step {step_count}")
                        break

                    await ws.send_json(snapshot)
                    tsdb.write_step(snapshot, mode="agent", episode=episode, run_id=run_id)
                    await mqtt_bridge.publish_sensor_snapshot(snapshot)
                    step_count += 1

                    if step_count % 100 == 0:
                        print(f"[SUMO] Step {step_count} | vehicles={snapshot['active_vehicles']} | reward={snapshot['step_reward']}")

                    # Check if episode is done
                    done = await asyncio.to_thread(runner.is_done)
                    if done:
                        print(f"[SUMO] Simulation done at step {step_count}")
                        break

                    # Small yield to let other coroutines run
                    await asyncio.sleep(0.01)

                # Send episode summary
                summary = await asyncio.to_thread(runner.end_episode)
                if summary["type"] == "episode_end":
                    await ws.send_json(summary)
                    tsdb.write_episode_summary(summary, mode="agent", run_id=run_id)
                    print(f"[SUMO] Episode complete: {summary['steps_completed']} steps, reward={summary['cumulative_reward']}")

        except Exception as e:
            print(f"[SUMO] ❌ ERROR in inference loop: {e}")
            traceback.print_exc()
            try:
                await ws.send_json({"type": "error", "message": f"SUMO error: {e}"})
            except Exception:
                pass
        finally:
            if runner:
                try:
                    await asyncio.to_thread(runner.cleanup)
                    print("[SUMO] Cleanup complete")
                except Exception as cleanup_err:
                    print(f"[SUMO] Cleanup error: {cleanup_err}")
            _active_runner = None

    # ── Message dispatch ──────────────────────────────────────────────
    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)

            if msg.get("action") == "start":
                stop_flag.clear()
                import uuid
                run_id       = uuid.uuid4().hex[:8]
                episode      = msg.get("episode",      1)
                num_vehicles = msg.get("num_vehicles", 1500)
                max_steps    = msg.get("max_steps",    4500)
                spawn        = msg.get("spawn",        3540)
                seed         = msg.get("seed",         42)
                use_gui      = msg.get("use_gui",      False)

                if USE_REAL_SUMO:
                    asyncio.create_task(
                        sumo_inference_loop(episode, num_vehicles, max_steps, spawn, run_id, seed, use_gui)
                    )
                else:
                    asyncio.create_task(
                        mock_inference_loop(episode, num_vehicles, max_steps, run_id)
                    )

            elif msg.get("action") == "stop":
                stop_flag.set()
                # If SUMO is running, cleanup will happen via the finally block

    except WebSocketDisconnect:
        stop_flag.set()
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "Patna STC Dashboard",
        "inference_mode": "sumo" if USE_REAL_SUMO else "mock",
    }


# ── Baseline WebSocket ────────────────────────────────────────────────────────
@app.websocket("/ws/baseline")
async def baseline_websocket(ws: WebSocket):
    """
    Stream fixed-timing (no-agent) baseline metrics.
    Same protocol as /ws/inference — connects to BaselineRunner.
    Only works when USE_REAL_SUMO is True.
    """
    from baseline_runner import BaselineRunner

    await ws.accept()
    await ws.send_json({
        "type": "ready",
        "mode": "baseline",
        "sumo_available": USE_REAL_SUMO,
    })

    if not USE_REAL_SUMO:
        await ws.send_json({
            "type": "error",
            "message": "Baseline mode requires SUMO to be installed and configured.",
        })
        return

    stop_flag = asyncio.Event()

    async def baseline_loop(episode: int, num_vehicles: int,
                            max_steps: int = 4500, spawn: int = 3540, run_id: str = "default", seed: int = 42, use_gui: bool = False):
        runner = None
        try:
            async with _sumo_lock:
                runner = BaselineRunner()
                print(f"[BASE] Initializing runner (gui={use_gui})...")
                await asyncio.to_thread(runner.initialize, use_gui)

                print(f"[BASE] Starting episode {episode} — {num_vehicles} vehicles, no agent")
                start_msg = await asyncio.to_thread(
                    runner.start_episode, episode, num_vehicles, max_steps, spawn, seed
                )
                start_msg["run_id"] = run_id
                await ws.send_json(start_msg)

                step_count = 0
                while not stop_flag.is_set():
                    snapshot = await asyncio.to_thread(runner.step)
                    if snapshot is None:
                        break
                    await ws.send_json(snapshot)
                    tsdb.write_step(snapshot, mode="baseline", episode=episode, run_id=run_id)
                    await mqtt_bridge.publish_sensor_snapshot(snapshot)
                    step_count += 1

                    if step_count % 100 == 0:
                        print(f"[BASE] Step {step_count} | vehicles={snapshot['active_vehicles']}")

                    done = await asyncio.to_thread(runner.is_done)
                    if done:
                        break

                    await asyncio.sleep(0.01)

                summary = await asyncio.to_thread(runner.end_episode)
                await ws.send_json(summary)
                tsdb.write_episode_summary(summary, mode="baseline", run_id=run_id)
                print(f"[BASE] Episode complete — {summary['steps_completed']} steps")

        except Exception as e:
            print(f"[BASE] ❌ ERROR: {e}")
            traceback.print_exc()
            try:
                await ws.send_json({"type": "error", "message": f"Baseline error: {e}"})
            except Exception:
                pass
        finally:
            if runner:
                try:
                    await asyncio.to_thread(runner.cleanup)
                    print("[BASE] Cleanup complete")
                except Exception as ce:
                    print(f"[BASE] Cleanup error: {ce}")

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)

            if msg.get("action") == "start":
                stop_flag.clear()
                import uuid
                run_id       = uuid.uuid4().hex[:8]
                episode      = msg.get("episode",      1)
                num_vehicles = msg.get("num_vehicles", 1500)
                max_steps    = msg.get("max_steps",    4500)
                spawn        = msg.get("spawn",        3540)
                seed         = msg.get("seed",         42)
                use_gui      = msg.get("use_gui",      False)
                asyncio.create_task(
                    baseline_loop(episode, num_vehicles, max_steps, spawn, run_id, seed, use_gui)
                )

            elif msg.get("action") == "stop":
                stop_flag.set()

    except WebSocketDisconnect:
        stop_flag.set()
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


# ── History API (reads from InfluxDB) ─────────────────────────────────────────
@app.get("/api/history/steps")
def get_step_history(
    mode: str = Query("agent", description="agent or baseline"),
    episode: str = Query(None, description="Episode number filter"),
    minutes: int = Query(60, description="Look-back window in minutes"),
):
    """Return stored step metrics from InfluxDB."""
    if not tsdb.available:
        return JSONResponse(
            {"error": "InfluxDB not available", "data": []},
            status_code=503,
        )
    data = tsdb.query_step_history(mode=mode, episode=episode, minutes=minutes)
    return {"count": len(data), "data": data}


@app.get("/api/history/episodes")
def get_episode_summaries(
    mode: str = Query(None, description="Filter by mode (agent/baseline)"),
    minutes: int = Query(1440, description="Look-back window in minutes"),
):
    """Return stored episode summaries from InfluxDB."""
    if not tsdb.available:
        return JSONResponse(
            {"error": "InfluxDB not available", "data": []},
            status_code=503,
        )
    data = tsdb.query_episode_summaries(mode=mode, minutes=minutes)
    return {"count": len(data), "data": data}


@app.get("/api/history/status")
def tsdb_status():
    """Check if InfluxDB persistence is available."""
    return {
        "influxdb_available": tsdb.available,
        "influx_url": os.getenv("INFLUX_URL", "http://localhost:8086"),
    }


# ── IoT Sensor Data (from MQTT) ──────────────────────────────────────────────
@app.get("/api/sensors")
def get_sensor_data():
    """Return latest cached sensor readings from MQTT edge devices."""
    return {
        "mqtt_connected": mqtt_bridge.available,
        "intersections": mqtt_bridge.get_sensor_snapshot(),
    }


@app.get("/api/iot/status")
def iot_status():
    """Full IoT stack status check."""
    return {
        "influxdb": {
            "available": tsdb.available,
            "url": os.getenv("INFLUX_URL", "http://localhost:8086"),
        },
        "mqtt": {
            "available": mqtt_bridge.available,
            "broker": os.getenv("MQTT_BROKER", "localhost"),
            "port": int(os.getenv("MQTT_PORT", "1883")),
        },
        "inference_mode": "sumo" if USE_REAL_SUMO else "mock",
    }


# ── Shutdown ─────────────────────────────────────────────────────────────────
@app.on_event("shutdown")
def shutdown_tsdb():
    tsdb.close()


if __name__ == "__main__":
    import uvicorn
    # When running directly on Windows, the selector event loop policy set at
    # the top of this file takes effect BEFORE uvicorn starts its event loop.
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
