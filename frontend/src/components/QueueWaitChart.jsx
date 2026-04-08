/**
 * QueueWaitChart
 * ──────────────
 * Dual-line chart of Total Queue (PCU) and Average Wait Time (s)
 * with adjustable moving-average overlay.
 *
 * Props:
 *   history   Array<{ step, totalQueue, avgWait }>
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
    cyan: "#00d4ff",
    amber: "#ffab00",
    border: "#d6cfc4",
    panel: "#faf7f2",
    text: "#8fa4b4",
};

function rollingAvg(arr, key, window) {
    return arr.map((d, i) => {
        const slice = arr.slice(Math.max(0, i - window + 1), i + 1);
        const avg = slice.reduce((s, r) => s + (r[key] ?? 0), 0) / slice.length;
        return { ...d, [`${key}_ma`]: avg };
    });
}

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

export default function QueueWaitChart({ history = [] }) {
    const [maWindow, setMaWindow] = useState(20);

    const data = useMemo(() => {
        if (!history.length) return [];
        let enriched = rollingAvg(history, "totalQueue", maWindow);
        enriched = rollingAvg(enriched, "avgWait", maWindow);
        return enriched;
    }, [history, maWindow]);

    if (!data.length) {
        return (
            <div className="loading">
                <div className="spinner" />
                Awaiting queue/wait data…
            </div>
        );
    }

    return (
        <div>
            <div style={{ marginBottom: 8 }}>
                <MASlider value={maWindow} onChange={setMaWindow} min={1} max={200} label="MA Window" />
            </div>
            <ResponsiveContainer width="100%" height={220}>
                <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                    <CartesianGrid stroke={C.border} strokeDasharray="3 3" vertical={false} />
                    <XAxis
                        dataKey="step"
                        tick={{ fill: C.text, fontSize: 10, fontFamily: "'Share Tech Mono', monospace" }}
                        axisLine={{ stroke: C.border }}
                        tickLine={false}
                    />
                    <YAxis
                        tick={{ fill: C.text, fontSize: 10, fontFamily: "'Share Tech Mono', monospace" }}
                        axisLine={false} tickLine={false} width={52}
                    />
                    <Tooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: 11, fontFamily: "'Share Tech Mono', monospace", color: C.text }} />

                    {/* Raw Queue — faint */}
                    <Line type="monotone" dataKey="totalQueue" name="Queue (raw)" stroke={C.cyan}
                        strokeWidth={1} dot={false} opacity={0.3} isAnimationActive={false} />

                    {/* Smoothed Queue — bold */}
                    <Line type="monotone" dataKey="totalQueue_ma" name={`Queue (MA-${maWindow})`} stroke={C.cyan}
                        strokeWidth={2.5} dot={false} isAnimationActive={false} />

                    {/* Raw Wait — faint */}
                    <Line type="monotone" dataKey="avgWait" name="Wait (raw)" stroke={C.amber}
                        strokeWidth={1} dot={false} opacity={0.3} isAnimationActive={false} />

                    {/* Smoothed Wait — bold */}
                    <Line type="monotone" dataKey="avgWait_ma" name={`Wait (MA-${maWindow})`} stroke={C.amber}
                        strokeWidth={2.5} dot={false} isAnimationActive={false} />

                    <Brush dataKey="step" height={20} stroke={C.text} fill="transparent"
                        tickFormatter={() => ""} travellerWidth={8} />
                </LineChart>
            </ResponsiveContainer>
        </div>
    );
}
