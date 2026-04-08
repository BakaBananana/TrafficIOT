/**
 * IntersectionGrid
 * ─────────────────
 * Renders one card per intersection showing queue, wait time, phase, and last action.
 *
 * Props:
 *   intersections   Array<{
 *     id, index, queue_pcu, wait_time_s, phase, action
 *   }>
 */

import { useMemo } from "react";

const NUM_PHASES = 4; // assumed from your env (adjust if different)

function QueueBar({ value, max = 50 }) {
  const pct = Math.min(100, (value / max) * 100);
  const color =
    pct > 70 ? "var(--red)" :
    pct > 40 ? "var(--amber)" :
               "var(--green)";

  return (
    <div style={{ marginTop: 6 }}>
      <div style={{
        height: 3, background: "var(--border)", borderRadius: 2, overflow: "hidden"
      }}>
        <div style={{
          height: "100%", width: `${pct}%`,
          background: color, borderRadius: 2,
          transition: "width 0.4s ease, background 0.4s ease",
          boxShadow: `0 0 6px ${color}`,
        }} />
      </div>
    </div>
  );
}

function IntersectionCard({ node }) {
  const queueColor =
    node.queue_pcu > 35 ? "var(--red)" :
    node.queue_pcu > 18 ? "var(--amber)" :
                          "var(--cyan)";

  return (
    <div className={`intersection-card${node.action === 1 ? " switching" : ""}`}>
      <div className="intersection-card__id">
        {node.id}
        {node.action === 1 && (
          <span style={{
            marginLeft: 6, color: "var(--amber)",
            fontSize: 9, letterSpacing: "0.06em"
          }}>⇄ SW</span>
        )}
      </div>

      {/* Queue */}
      <div className="intersection-card__queue" style={{ color: queueColor }}>
        {node.queue_pcu.toFixed(1)}
        <span style={{ fontSize: 11, color: "var(--text-muted)", marginLeft: 3 }}>PCU</span>
      </div>

      {/* Wait */}
      <div className="intersection-card__wait">
        ⏱ {node.wait_time_s.toFixed(1)}s avg wait
      </div>

      {/* Queue bar */}
      <QueueBar value={node.queue_pcu} />

      {/* Phase indicator */}
      <div className="phase-indicator">
        {Array.from({ length: NUM_PHASES }).map((_, i) => (
          <div
            key={i}
            className={`phase-dot ${i === node.phase ? "active" : ""}`}
          />
        ))}
      </div>
    </div>
  );
}

export default function IntersectionGrid({ intersections = [] }) {
  const sorted = useMemo(
    () => [...intersections].sort((a, b) => b.queue_pcu - a.queue_pcu),
    [intersections]
  );

  if (!sorted.length) {
    return (
      <div className="loading">
        <div className="spinner" />
        Waiting for simulation data…
      </div>
    );
  }

  return (
    <div className="intersection-grid">
      {intersections.map(node => (
        <IntersectionCard key={node.id} node={node} />
      ))}
    </div>
  );
}
