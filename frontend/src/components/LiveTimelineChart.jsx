/**
 * LiveTimelineChart
 * ──────────────────
 * Renders the rolling window of inference step metrics:
 *   • Total queue (PCU)  — cyan
 *   • Average wait (s)   — amber
 *   • Active vehicles    — purple (right axis)
 *
 * Props:
 *   history   Array<{ step, totalQueue, avgWait, reward, activeVehicles, switches }>
 */

import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Brush,
} from "recharts";

const C = {
  cyan:   "#00d4ff",
  amber:  "#ffab00",
  purple: "#b06cff",
  green:  "#00ff88",
  border: "#d6cfc4",
  panel:  "#faf7f2",
  text:   "#8fa4b4",
};

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: C.panel, border: `1px solid ${C.border}`,
      borderRadius: 6, padding: "10px 14px",
      fontFamily: "'Share Tech Mono', monospace", fontSize: 11,
    }}>
      <div style={{ color: C.text, marginBottom: 6 }}>Step {label}</div>
      {payload.map(p => (
        <div key={p.dataKey} style={{ color: p.color, lineHeight: 1.8 }}>
          {p.name}: {typeof p.value === "number" ? p.value.toFixed(2) : p.value}
        </div>
      ))}
    </div>
  );
}

export default function LiveTimelineChart({ history = [] }) {
  if (!history.length) {
    return (
      <div className="loading">
        <div className="spinner" />
        Awaiting live data stream…
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={history} margin={{ top: 8, right: 48, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="queueGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor={C.cyan}   stopOpacity={0.25} />
            <stop offset="95%" stopColor={C.cyan}   stopOpacity={0.02} />
          </linearGradient>
          <linearGradient id="waitGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor={C.amber}  stopOpacity={0.2} />
            <stop offset="95%" stopColor={C.amber}  stopOpacity={0.02} />
          </linearGradient>
        </defs>

        <CartesianGrid stroke={C.border} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="step"
          tick={{ fill: C.text, fontSize: 10, fontFamily: "'Share Tech Mono', monospace" }}
          axisLine={{ stroke: C.border }}
          tickLine={false}
          label={{ value: "Simulation Step (s)", fill: C.text, fontSize: 10, position: "insideBottom", offset: -2 }}
        />

        {/* Left Y — queue & wait */}
        <YAxis
          yAxisId="left"
          tick={{ fill: C.text, fontSize: 10, fontFamily: "'Share Tech Mono', monospace" }}
          axisLine={false} tickLine={false} width={48}
        />

        {/* Right Y — vehicle count */}
        <YAxis
          yAxisId="right"
          orientation="right"
          tick={{ fill: C.text, fontSize: 10, fontFamily: "'Share Tech Mono', monospace" }}
          axisLine={false} tickLine={false} width={48}
        />

        <Tooltip content={<CustomTooltip />} />
        <Legend
          wrapperStyle={{ fontSize: 11, fontFamily: "'Share Tech Mono', monospace", color: C.text }}
        />

        <Area
          yAxisId="left"
          type="monotone"
          dataKey="totalQueue"
          name="Total Queue (PCU)"
          stroke={C.cyan}
          strokeWidth={2}
          fill="url(#queueGrad)"
          dot={false}
          isAnimationActive={false}
        />

        <Area
          yAxisId="left"
          type="monotone"
          dataKey="avgWait"
          name="Avg Wait (s)"
          stroke={C.amber}
          strokeWidth={1.5}
          fill="url(#waitGrad)"
          dot={false}
          isAnimationActive={false}
        />

        <Line
          yAxisId="right"
          type="monotone"
          dataKey="activeVehicles"
          name="Active Vehicles"
          stroke={C.purple}
          strokeWidth={1.5}
          dot={false}
          opacity={0.75}
          isAnimationActive={false}
        />

        <Brush dataKey="step" height={20} stroke={C.text} fill="transparent"
             tickFormatter={() => ""} travellerWidth={8} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

