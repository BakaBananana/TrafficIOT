/**
 * ThroughputChart
 * ───────────────
 * Shows vehicle departure curve and cumulative phase switches over time.
 *
 * Props:
 *   history   Array<{ step, activeVehicles, switches }>
 */

import {
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { useMemo } from "react";

const C = {
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
          {p.name}: {typeof p.value === "number" ? p.value.toFixed(1) : p.value}
        </div>
      ))}
    </div>
  );
}

export default function ThroughputChart({ history = [] }) {
  // Compute cumulative switches
  const data = useMemo(() => {
    let cumSwitches = 0;
    return history.map(d => {
      cumSwitches += d.switches ?? 0;
      return { ...d, cumSwitches };
    });
  }, [history]);

  if (!data.length) {
    return (
      <div className="loading">
        <div className="spinner" />
        Awaiting throughput data…
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <ComposedChart data={data} margin={{ top: 8, right: 48, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="vehGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor={C.purple} stopOpacity={0.2} />
            <stop offset="95%" stopColor={C.purple} stopOpacity={0.02} />
          </linearGradient>
        </defs>

        <CartesianGrid stroke={C.border} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="step"
          tick={{ fill: C.text, fontSize: 10, fontFamily: "'Share Tech Mono', monospace" }}
          axisLine={{ stroke: C.border }} tickLine={false}
        />

        {/* Left Y — vehicles */}
        <YAxis
          yAxisId="left"
          tick={{ fill: C.text, fontSize: 10, fontFamily: "'Share Tech Mono', monospace" }}
          axisLine={false} tickLine={false} width={48}
        />

        {/* Right Y — cumulative switches */}
        <YAxis
          yAxisId="right"
          orientation="right"
          tick={{ fill: C.text, fontSize: 10, fontFamily: "'Share Tech Mono', monospace" }}
          axisLine={false} tickLine={false} width={48}
        />

        <Tooltip content={<CustomTooltip />} />
        <Legend wrapperStyle={{ fontSize: 11, fontFamily: "'Share Tech Mono', monospace", color: C.text }} />

        {/* Active Vehicles area */}
        <Area
          yAxisId="left"
          type="monotone"
          dataKey="activeVehicles"
          name="Active Vehicles"
          stroke={C.purple}
          strokeWidth={2}
          fill="url(#vehGrad)"
          dot={false}
          isAnimationActive={false}
        />

        {/* Cumulative switches line */}
        <Line
          yAxisId="right"
          type="monotone"
          dataKey="cumSwitches"
          name="Cum. Switches"
          stroke={C.green}
          strokeWidth={1.5}
          strokeDasharray="6 3"
          dot={false}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
