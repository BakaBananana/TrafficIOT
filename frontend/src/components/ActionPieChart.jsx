/**
 * ActionPieChart
 * ───────────────
 * Shows the ratio of "Hold" vs "Switch" actions across all intersections
 * in the current inference session.
 *
 * Props:
 *   history   Array<{ switches, step }>   — from useInference stepHistory
 */

import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { useMemo } from "react";

const C = {
  green:  "#00ff88",
  amber:  "#ffab00",
  border: "#d6cfc4",
  panel:  "#faf7f2",
  text:   "#8fa4b4",
};

const NUM_INTERSECTIONS = 10; // keep in sync with backend (main.py NUM_INTERSECTIONS)

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const { name, value } = payload[0];
  return (
    <div style={{
      background: C.panel, border: `1px solid ${C.border}`,
      borderRadius: 6, padding: "8px 12px",
      fontFamily: "'Share Tech Mono', monospace", fontSize: 11,
    }}>
      <div style={{ color: payload[0].fill }}>{name}: {value.toLocaleString()}</div>
    </div>
  );
}

function CustomLabel({ cx, cy, midAngle, innerRadius, outerRadius, percent }) {
  if (percent < 0.05) return null;
  const RADIAN = Math.PI / 180;
  const r  = innerRadius + (outerRadius - innerRadius) * 0.5;
  const x  = cx + r * Math.cos(-midAngle * RADIAN);
  const y  = cy + r * Math.sin(-midAngle * RADIAN);

  return (
    <text
      x={x} y={y}
      fill="#fff"
      textAnchor="middle"
      dominantBaseline="central"
      style={{ fontFamily: "'Share Tech Mono', monospace", fontSize: 12 }}
    >
      {(percent * 100).toFixed(1)}%
    </text>
  );
}

export default function ActionPieChart({ history = [] }) {
  const { holds, switches } = useMemo(() => {
    const totalSteps   = history.length;
    const totalActions = totalSteps * NUM_INTERSECTIONS;
    const totalSwitches = history.reduce((s, h) => s + (h.switches ?? 0), 0);
    return {
      holds:    Math.max(0, totalActions - totalSwitches),
      switches: totalSwitches,
    };
  }, [history]);

  const pieData = [
    { name: "Hold",   value: holds    },
    { name: "Switch", value: switches },
  ];

  if (!history.length) {
    return (
      <div className="loading">
        <div className="spinner" />
        Awaiting action data…
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <PieChart>
        <Pie
          data={pieData}
          cx="50%"
          cy="50%"
          innerRadius={55}
          outerRadius={85}
          paddingAngle={3}
          dataKey="value"
          labelLine={false}
          label={<CustomLabel />}
          isAnimationActive={false}
        >
          <Cell fill={C.green} />
          <Cell fill={C.amber} />
        </Pie>
        <Tooltip content={<CustomTooltip />} />
        <Legend
          wrapperStyle={{
            fontSize: 11,
            fontFamily: "'Share Tech Mono', monospace",
            color: C.text,
          }}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}
