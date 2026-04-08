/**
 * VehicleProgressChart
 * ─────────────────────
 * Shows num_vehicles across training episodes.
 */

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

const C = {
  purple: "#b06cff",
  border: "#d6cfc4",
  panel:  "#faf7f2",
  text:   "#8fa4b4",
};

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: C.panel, border: `1px solid ${C.border}`,
      borderRadius: 6, padding: "8px 12px",
      fontFamily: "'Share Tech Mono', monospace", fontSize: 11,
    }}>
      <div style={{ color: C.text }}>Ep {label}</div>
      <div style={{ color: C.purple }}>{payload[0]?.value} vehicles</div>
    </div>
  );
}

export default function VehicleProgressChart({ data = [] }) {
  if (!data.length) return <div className="loading"><div className="spinner" /></div>;

  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="vehicleGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor="#b06cff" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#b06cff" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={C.border} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="episode"
          tick={{ fill: C.text, fontSize: 10, fontFamily: "'Share Tech Mono', monospace" }}
          axisLine={{ stroke: C.border }}
          tickLine={false}
        />
        <YAxis
          tick={{ fill: C.text, fontSize: 10, fontFamily: "'Share Tech Mono', monospace" }}
          axisLine={false} tickLine={false} width={50}
        />
        <Tooltip content={<CustomTooltip />} />
        <Area
          type="monotone"
          dataKey="num_vehicles"
          name="Vehicles"
          stroke={C.purple}
          strokeWidth={2}
          fill="url(#vehicleGrad)"
          dot={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
