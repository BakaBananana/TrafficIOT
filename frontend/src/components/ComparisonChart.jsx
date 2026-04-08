/**
 * ComparisonChart
 * ───────────────
 * Overlays RL Agent vs Baseline metrics on the same axes.
 *
 * Queue: Agent (ocean blue) vs Baseline (crimson)
 * Wait:  Agent (forest green) vs Baseline (burnt orange)
 *
 * Both with raw + MA smoothed lines. Adjustable MA window.
 *
 * Props:
 *   agentHistory    Array<{ step, totalQueue, avgWait }>
 *   baselineHistory Array<{ step, totalQueue, avgWait }>
 */

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Brush,
} from "recharts";
import { useState, useMemo } from "react";
import MASlider from "./MASlider.jsx";

const C = {
  agent:   "#0288d1",   // ocean blue — agent queue
  base:    "#c62828",   // crimson   — baseline queue
  agentW:  "#2e7d32",   // forest green — agent wait
  baseW:   "#e65100",   // burnt orange — baseline wait
  border:  "#d6cfc4",
  panel:   "#faf7f2",
  text:    "#8fa4b4",
};

function rollingAvg(arr, key, window) {
  return arr.map((d, i) => {
    const slice = arr.slice(Math.max(0, i - window + 1), i + 1);
    const avg = slice.reduce((s, r) => s + (r[key] ?? 0), 0) / slice.length;
    return { ...d, [`${key}_ma`]: avg };
  });
}

function mergeByStep(agent, baseline) {
  // Merge both histories into one array keyed by step
  const map = new Map();
  for (const d of agent) {
    map.set(d.step, {
      step:            d.step,
      agentQueue:      d.totalQueue,
      agentWait:       d.avgWait,
      baselineQueue:   null,
      baselineWait:    null,
    });
  }
  for (const d of baseline) {
    if (map.has(d.step)) {
      map.get(d.step).baselineQueue = d.totalQueue;
      map.get(d.step).baselineWait  = d.avgWait;
    } else {
      map.set(d.step, {
        step:          d.step,
        agentQueue:    null,
        agentWait:     null,
        baselineQueue: d.totalQueue,
        baselineWait:  d.avgWait,
      });
    }
  }
  return Array.from(map.values()).sort((a, b) => a.step - b.step);
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: C.panel, border: `1px solid ${C.border}`,
      borderRadius: 6, padding: "10px 14px",
      fontFamily: "'Share Tech Mono', monospace", fontSize: 11,
      boxShadow: "0 2px 12px rgba(0,0,0,0.08)",
    }}>
      <div style={{ color: C.text, marginBottom: 6, fontWeight: 600 }}>Step {label}</div>
      {payload.map(p => p.value != null && (
        <div key={p.dataKey} style={{ color: p.color, lineHeight: 1.9 }}>
          {p.name}: {p.value.toFixed(2)}
        </div>
      ))}
    </div>
  );
}

export default function ComparisonChart({ agentHistory = [], baselineHistory = [] }) {
  const [maWindow, setMaWindow] = useState(20);

  const data = useMemo(() => {
    if (!agentHistory.length && !baselineHistory.length) return [];
    let merged = mergeByStep(agentHistory, baselineHistory);
    merged = rollingAvg(merged, "agentQueue",    maWindow);
    merged = rollingAvg(merged, "baselineQueue", maWindow);
    merged = rollingAvg(merged, "agentWait",     maWindow);
    merged = rollingAvg(merged, "baselineWait",  maWindow);
    return merged;
  }, [agentHistory, baselineHistory, maWindow]);

  const hasAgent    = agentHistory.length > 0;
  const hasBaseline = baselineHistory.length > 0;

  if (!hasAgent && !hasBaseline) {
    return (
      <div className="loading">
        <div className="spinner" />
        Run an episode and a baseline to compare…
      </div>
    );
  }

  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        <MASlider value={maWindow} onChange={setMaWindow} min={1} max={200} label="MA Window" />
      </div>

      {/* Legend explanation */}
      <div style={{
        display: "flex", gap: 20, marginBottom: 12,
        fontFamily: "'Share Tech Mono', monospace", fontSize: 10,
        color: C.text, flexWrap: "wrap",
      }}>
        <span><span style={{ color: C.agent }}>■</span> Agent Queue</span>
        <span><span style={{ color: C.base }}>■</span> Baseline Queue</span>
        <span><span style={{ color: C.agentW }}>■</span> Agent Wait</span>
        <span><span style={{ color: C.baseW }}>■</span> Baseline Wait</span>
      </div>

      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid stroke={C.border} strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="step"
            tick={{ fill: C.text, fontSize: 10, fontFamily: "'Share Tech Mono', monospace" }}
            axisLine={{ stroke: C.border }} tickLine={false}
          />
          <YAxis
            tick={{ fill: C.text, fontSize: 10, fontFamily: "'Share Tech Mono', monospace" }}
            axisLine={false} tickLine={false} width={52}
          />
          <Tooltip content={<CustomTooltip />} />

          {/* Agent Queue — bold blue */}
          {hasAgent && <Line type="monotone" dataKey="agentQueue_ma"
            name={`Agent Queue (MA-${maWindow})`} stroke={C.agent}
            strokeWidth={2.5} dot={false} isAnimationActive={false} />}
          {hasAgent && <Line type="monotone" dataKey="agentQueue"
            name="Agent Queue (raw)" stroke={C.agent}
            strokeWidth={1} dot={false} opacity={0.18} isAnimationActive={false} />}

          {/* Baseline Queue — bold red */}
          {/* {hasBaseline && <Line type="monotone" dataKey="baselineQueue_ma"
            name={`Baseline Queue (MA-${maWindow})`} stroke={C.base}
            strokeWidth={2.5} dot={false} strokeDasharray="8 3" isAnimationActive={false} />} */}
          {/* {hasBaseline && <Line type="monotone" dataKey="baselineQueue"
            name="Baseline Queue (raw)" stroke={C.base}
            strokeWidth={1} dot={false} opacity={0.18} isAnimationActive={false} />} */}

          {/* Agent Wait — bold green */}
          {hasAgent && <Line type="monotone" dataKey="agentWait_ma"
            name={`Agent Wait (MA-${maWindow})`} stroke={C.agentW}
            strokeWidth={2} dot={false} isAnimationActive={false} />}

          {/* Baseline Wait — bold orange */}
          {hasBaseline && <Line type="monotone" dataKey="baselineWait_ma"
            name={`Baseline Wait (MA-${maWindow})`} stroke={C.baseW}
            strokeWidth={2} dot={false} strokeDasharray="8 3" isAnimationActive={false} />}

          {/* Scrollable brush overlay */}
          <Brush dataKey="step" height={20} stroke={C.text} fill="transparent"
             tickFormatter={() => ""} travellerWidth={8} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

