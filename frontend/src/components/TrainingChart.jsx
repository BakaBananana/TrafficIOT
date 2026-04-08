/**
 * TrainingChart
 * ─────────────
 * Renders training-log data with overlays:
 *   • Normalized reward (raw, faint cyan)
 *   • Rolling average (bold cyan) — window controlled by prop
 *   • Vehicle count (purple) — in non-compact mode
 *
 * Props:
 *   data      Array<{ episode, num_vehicles, cumulative_reward, normalized_reward }>
 *   compact   boolean  — reduced height for summary widgets
 *   maWindow  number   — rolling average window size (default 10)
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
} from "recharts";
import { useMemo } from "react";

const C = {
  cyan: "#00d4ff",
  amber: "#ffab00",
  purple: "#b06cff",
  green: "#00ff88",
  muted: "#8fa4b4",
  panel: "#faf7f2",
  border: "#d6cfc4",
  text: "#8fa4b4",
};

// ── Custom Tooltip ────────────────────────────────────────────────────────────
function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div
      style={{
        background: C.panel,
        border: `1px solid ${C.border}`,
        borderRadius: 6,
        padding: "10px 14px",
        fontFamily: "'Share Tech Mono', monospace",
        fontSize: 11,
      }}
    >
      <div style={{ color: C.text, marginBottom: 6 }}>Episode {label}</div>
      {payload.map(p => (
        <div key={p.dataKey} style={{ color: p.color, lineHeight: 1.8 }}>
          {p.name}: {typeof p.value === "number" ? p.value.toFixed(3) : p.value}
        </div>
      ))}
    </div>
  );
}

// ── Rolling average helper ────────────────────────────────────────────────────
function rollingAvg(data, key, window = 10) {
  return data.map((d, i) => {
    const slice = data.slice(Math.max(0, i - window + 1), i + 1);
    const avg = slice.reduce((s, r) => s + r[key], 0) / slice.length;
    
    return { ...d, [`${key}_avg`]: avg, num_vehicles:d.num_vehicles/100.0 };
  });
}

export default function TrainingChart({ data = [], compact = false, maWindow = 10 }) {
  if (!data.length) {
    return (
      <div className="loading">
        <div className="spinner" />
        Loading training data…
      </div>
    );
  }

  const enriched = useMemo(
    () => rollingAvg(data, "normalized_reward", maWindow),
    [data, maWindow]
  );

  return (
    <ResponsiveContainer width="100%" height={compact ? 180 : 300}>
      <LineChart data={enriched} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={C.border} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="episode"
          tick={{ fill: C.text, fontSize: 10, fontFamily: "'Share Tech Mono', monospace" }}
          axisLine={{ stroke: C.border }}
          tickLine={false}
          label={{ value: "Episode", fill: C.muted, fontSize: 10, position: "insideBottom", offset: -2 }}
        />
        <YAxis
          tick={{ fill: C.text, fontSize: 10, fontFamily: "'Share Tech Mono', monospace" }}
          axisLine={false}
          tickLine={false}
          width={52}
          // interval={0}
        />
        <Tooltip content={<CustomTooltip />} />
        <Legend
          wrapperStyle={{ fontSize: 11, fontFamily: "'Share Tech Mono', monospace", color: C.text }}
        />

        {/* Raw normalized reward — light, dotted */}
        <Line
          type="monotone"
          dataKey="normalized_reward"
          name="Norm. Reward (raw)"
          stroke={C.muted}
          strokeWidth={1}
          dot={false}
          opacity={0.5}
        />

        {/* Rolling average — bold */}
        <Line
          type="monotone"
          dataKey="normalized_reward_avg"
          name={`Norm. Reward (avg-${maWindow})`}
          stroke={C.cyan}
          strokeWidth={1.5}
          dot={false}
        />

        {/* {!compact && (
          <Line
            type="monotone"
            dataKey="num_vehicles"
            name="Vehicles (×.01)"
            stroke={C.purple}
            strokeWidth={1.5}
            dot={false}
            opacity={0.7}
            yAxisId={0}
          />
        )} */}
      </LineChart>
    </ResponsiveContainer>
  );
}

// ── Mini sparkline used inside summary cards ──────────────────────────────────
export function RewardSparkline({ data = [] }) {
  const recent = data.slice(-50);
  const enriched = rollingAvg(recent, "normalized_reward", 5);

  return (
    <ResponsiveContainer width="100%" height={60}>
      <LineChart data={enriched} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
        <Line
          type="monotone"
          dataKey="normalized_reward_avg"
          stroke={C.cyan}
          strokeWidth={1.5}
          dot={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
