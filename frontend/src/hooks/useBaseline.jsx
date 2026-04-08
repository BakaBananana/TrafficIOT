/**
 * useBaseline
 * ───────────
 * WebSocket hook for the fixed-timing baseline run.
 * Same protocol as useInference but connects to /ws/baseline.
 */

import { useRef, useState, useCallback, useEffect } from "react";

const WS_URL = "ws://localhost:8000/ws/baseline";

export function useBaseline() {
  const wsRef    = useRef(null);
  const statusRef = useRef("idle");

  const [status,       setStatus]       = useState("idle");
  const [stepHistory,  setStepHistory]  = useState([]);
  const [latestStep,   setLatestStep]   = useState(null);
  const [episodeSummary, setEpisodeSummary] = useState(null);

  const updateStatus = useCallback((s) => {
    statusRef.current = s;
    setStatus(s);
  }, []);

  // ── Connect ───────────────────────────────────────────────────────────
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === 1) return;
    updateStatus("connecting");

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => updateStatus("idle");

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);

      if (msg.type === "step") {
        const point = {
          step:           msg.step,
          totalQueue:     msg.total_queue_pcu,
          avgWait:        msg.avg_wait_s,
          reward:         msg.step_reward,
          activeVehicles: msg.active_vehicles,
          switches:       msg.switches ?? 0,
        };
        setLatestStep(msg);
        setStepHistory(prev => [...prev, point]);
      }

      if (msg.type === "episode_end") {
        setEpisodeSummary(msg);
        updateStatus("done");
      }

      if (msg.type === "error") {
        console.error("[Baseline WS]", msg.message);
        updateStatus("error");
      }
    };

    ws.onclose = () => {
      if (statusRef.current === "running") updateStatus("error");
      else if (statusRef.current !== "done") updateStatus("idle");
    };

    ws.onerror = () => updateStatus("error");
  }, [updateStatus]);

  // ── Auto-connect ──────────────────────────────────────────────────────
  useEffect(() => {
    connect();
    return () => wsRef.current?.close();
  }, [connect]);

  // ── Start baseline episode ────────────────────────────────────────────
  const startBaseline = useCallback(({ episode, numVehicles, maxSteps, spawnTime, seed, useGui }) => {
    if (!wsRef.current || wsRef.current.readyState !== 1) return;
    setStepHistory([]);
    setLatestStep(null);
    setEpisodeSummary(null);
    wsRef.current.send(JSON.stringify({
      action:       "start",
      episode,
      num_vehicles: numVehicles,
      max_steps:    maxSteps  ?? 4500,
      spawn:        spawnTime ?? 3540,
      seed:         seed ?? 42,
      use_gui:      useGui === true,
    }));
    updateStatus("running");
  }, [updateStatus]);

  // ── Stop ──────────────────────────────────────────────────────────────
  const stopBaseline = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ action: "stop" }));
    updateStatus("idle");
  }, [updateStatus]);

  return {
    status,
    stepHistory,
    latestStep,
    episodeSummary,
    startBaseline,
    stopBaseline,
  };
}
