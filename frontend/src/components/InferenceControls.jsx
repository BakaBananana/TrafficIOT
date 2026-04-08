/**
 * InferenceControls
 * ──────────────────
 * Panel for configuring and launching an inference episode.
 *
 * Props (all from useInference):
 *   status        "idle" | "connecting" | "running" | "done" | "error"
 *   startEpisode  (config) => void
 *   stopEpisode   () => void
 *   reconnect     () => void
 */

import { useState } from "react";
import { Play, Square, RefreshCw, AlertTriangle } from "lucide-react";

export default function InferenceControls({
  status,
  config,
  setConfig,
  startEpisode,
  stopEpisode,
  reconnect,
}) {
  const { episodeNum, numVehicles, maxSteps, spawnTime, seed, useGui } = config || {
    episodeNum: 1, numVehicles: 1500, maxSteps: 4500, spawnTime: 3540, seed: 42, useGui: false
  };

  const isRunning     = status === "running";
  const isConnecting  = status === "connecting";
  const isError       = status === "error";
  const canStart      = status === "idle" || status === "done";

  function handleStart() {
    startEpisode({
      episode:     episodeNum,
      numVehicles,
      maxSteps,
      spawnTime, // already pulled from config state in InferencePage
      seed,
      useGui,
    });
    // Increment episode number automatically
    setConfig(c => ({ ...c, episodeNum: c.episodeNum + 1 }));
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

      {/* Config grid — 2 columns */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div className="ctrl-group">
          <label className="ctrl-label">Vehicles</label>
          <input
            type="number"
            className="ctrl-input"
            value={numVehicles}
            min={100}
            max={4000}
            step={100}
            disabled={isRunning}
            onChange={e => setConfig(c => ({ ...c, numVehicles: Number(e.target.value) }))}
          />
        </div>
        <div className="ctrl-group">
          <label className="ctrl-label">Episode #</label>
          <input
            type="number"
            className="ctrl-input"
            value={episodeNum}
            min={1}
            disabled={isRunning}
            onChange={e => setConfig(c => ({ ...c, episodeNum: Number(e.target.value) }))}
          />
        </div>
        <div className="ctrl-group">
          <label className="ctrl-label">Max Steps</label>
          <input
            type="number"
            className="ctrl-input"
            value={maxSteps}
            min={100}
            max={10000}
            step={100}
            disabled={isRunning}
            onChange={e => setConfig(c => ({ ...c, maxSteps: Number(e.target.value) }))}
          />
        </div>
        <div className="ctrl-group">
          <label className="ctrl-label">Spawn Time (s)</label>
          <input
            type="number"
            className="ctrl-input"
            value={spawnTime}
            min={60}
            max={7200}
            step={60}
            disabled={isRunning}
            onChange={e => setConfig(c => ({ ...c, spawnTime: Number(e.target.value) }))}
          />
        </div>
        <div className="ctrl-group">
          <label className="ctrl-label">Random Seed</label>
          <input
            type="number"
            className="ctrl-input"
            value={seed}
            min={1}
            disabled={isRunning}
            onChange={e => setConfig(c => ({ ...c, seed: Number(e.target.value) }))}
          />
        </div>
        <div className="ctrl-group" style={{ display: "flex", alignItems: "flex-start", justifyContent: "center", gap: 8, flexDirection: "column" }}>
          <label className="ctrl-label" style={{ marginBottom: 0 }}>Digital Twin</label>
          <div style={{ display: "flex", alignItems: "center", gap: 8, height: "100%" }}>
            <input
              type="checkbox"
              id="useGuiToggle"
              style={{ width: 14, height: 14, accentColor: "var(--primary-light)", cursor: isRunning ? "not-allowed" : "pointer" }}
              checked={useGui || false}
              disabled={isRunning}
              onChange={e => setConfig(c => ({ ...c, useGui: e.target.checked }))}
            />
            <label htmlFor="useGuiToggle" style={{ fontSize: 13, color: "var(--text-main)", cursor: isRunning ? "not-allowed" : "pointer" }}>Show GUI output</label>
          </div>
        </div>
      </div>

      {/* Action buttons */}
      <div style={{ display: "flex", gap: 10 }}>
        {!isRunning ? (
          <button
            className="btn btn--success"
            onClick={handleStart}
            disabled={!canStart || isConnecting}
            style={{ flex: 1 }}
          >
            <Play size={14} />
            {isConnecting ? "Connecting…" : "Run Episode"}
          </button>
        ) : (
          <button
            className="btn btn--danger"
            onClick={stopEpisode}
            style={{ flex: 1 }}
          >
            <Square size={14} />
            Stop
          </button>
        )}

        {isError && (
          <button className="btn btn--ghost" onClick={reconnect}>
            <RefreshCw size={14} />
            Reconnect
          </button>
        )}
      </div>

      {/* Status indicator */}
      {isError && (
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "10px 14px",
          background: "rgba(255,68,102,0.08)",
          border: "1px solid rgba(255,68,102,0.3)",
          borderRadius: "var(--radius)",
          color: "var(--red)",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          letterSpacing: "0.04em",
        }}>
          <AlertTriangle size={13} />
          WebSocket disconnected — check that the backend is running on port 8000.
        </div>
      )}

      {/* Info block */}
      <div style={{
        padding: "12px 14px",
        background: "var(--bg-void)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius)",
        fontFamily: "var(--font-mono)",
        fontSize: 10,
        color: "var(--text-muted)",
        lineHeight: 1.8,
        letterSpacing: "0.04em",
      }}>
        <div style={{ color: "var(--text-secondary)", marginBottom: 4 }}>MODEL INFO</div>
        <div>Architecture: STGAT-PPO</div>
        <div>K-Hops: 3 · Heads: 3 · Hidden: 128</div>
        <div>Actions: Hold (0) / Switch (1)</div>
        <div>Simulation: SUMO — Patna STC</div>
      </div>
    </div>
  );
}
