/**
 * TrainingPage
 * ─────────────
 * Fetches training_log_real_good.csv via the API and renders:
 *   • Summary metric cards (best reward, final reward, episodes, total vehicles)
 *   • Normalized reward learning curve (with adjustable rolling average)
 *   • Vehicle count progression
 *   • Episode statistics table (first / last 10)
 */

import { useEffect, useState, useMemo } from "react";
import MetricCard from "../components/MetricCard.jsx";
import TrainingChart from "../components/TrainingChart.jsx";
import VehicleProgressChart from "../components/VehicleProgressChart.jsx";
import MASlider from "../components/MASlider.jsx";

function StatTable({ rows, title }) {
  return (
    <div>
      <div style={{
        fontFamily: "var(--font-ui)", fontSize: 10,
        color: "var(--text-muted)", letterSpacing: "0.1em",
        textTransform: "uppercase", marginBottom: 10,
      }}>
        {title}
      </div>
      <table className="ep-table">
        <thead>
          <tr>
            <th>Ep</th>
            <th>Vehicles</th>
            <th>Norm. Reward</th>
            <th>Cum. Reward</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.episode}>
              <td className="val--muted">#{r.episode}</td>
              <td className="val--purple" style={{ color: "var(--purple)" }}>
                {r.num_vehicles.toLocaleString()}
              </td>
              <td className={
                r.normalized_reward > -25 ? "val--green" :
                  r.normalized_reward > -35 ? "val--cyan" :
                    r.normalized_reward > -40 ? "val--amber" : "val--red"
              }>
                {r.normalized_reward.toFixed(3)}
              </td>
              <td className="val--muted">{r.cumulative_reward.toFixed(0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function TrainingPage() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [maWindow, setMaWindow] = useState(10);

  useEffect(() => {
    fetch("/api/training")
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(json => { setData(json.data); setLoading(false); })
      .catch(err => { setError(err.message); setLoading(false); });
  }, []);

  // ── Summary metrics ─────────────────────────────────────────────────────────
  const stats = useMemo(() => {
    if (!data.length) return null;
    const rewards = data.map(d => d.normalized_reward);
    const bestEp = data.reduce((b, d) => d.normalized_reward > b.normalized_reward ? d : b, data[0]);
    const first10 = rewards.slice(0, 10).reduce((s, v) => s + v, 0) / 10;
    const last10 = rewards.slice(-10).reduce((s, v) => s + v, 0) / 10;
    const improvement = ((last10 - first10) / Math.abs(first10)) * 100;

    return {
      totalEpisodes: data.length,
      bestReward: bestEp.normalized_reward,
      bestEpisode: bestEp.episode,
      lastReward: rewards[rewards.length - 1],
      avgLast10: last10,
      improvement: improvement,
      maxVehicles: Math.max(...data.map(d => d.num_vehicles)),
    };
  }, [data]);

  if (loading) {
    return (
      <div className="loading" style={{ height: "60vh" }}>
        <div className="spinner" />
        Loading training data…
      </div>
    );
  }

  if (error) {
    return (
      <div className="loading" style={{ height: "60vh", color: "var(--red)" }}>
        ⚠ {error} — Is the backend running on port 8000?
      </div>
    );
  }

  return (
    <>
      {/* ── Metric Cards ─────────────────────────────────────────────────── */}
      <div className="metrics-row">
        <MetricCard
          label="Total Episodes"
          value={stats.totalEpisodes}
          accent="--cyan"
        />
        <MetricCard
          label="Best Norm. Reward"
          value={stats.bestReward.toFixed(3)}
          accent="--green"
          delta={`Episode #${stats.bestEpisode}`}
        />
        <MetricCard
          label="Latest Norm. Reward"
          value={stats.lastReward.toFixed(3)}
          accent="--amber"
          delta={`Avg last 10: ${stats.avgLast10.toFixed(3)}`}
        />
        <MetricCard
          label="Improvement"
          value={`${stats.improvement > 0 ? "+" : ""}${stats.improvement.toFixed(1)}`}
          unit="%"
          accent={stats.improvement > 0 ? "--green" : "--red"}
          delta="First-10 vs Last-10 avg"
          deltaUp={stats.improvement > 0}
        />
        <MetricCard
          label="Peak Traffic"
          value={stats.maxVehicles.toLocaleString()}
          unit=" veh"
          accent="--purple"
        />
      </div>

      {/* ── Learning Curve ───────────────────────────────────────────────── */}
      {/* <div className="panel">
        <div className="panel__header">
          <span className="panel__title">Normalized Reward — Learning Curve</span>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <MASlider
              value={maWindow}
              onChange={setMaWindow}
              min={1}
              max={50}
              label="Rolling Avg"
            />
            <span style={{
              fontFamily: "var(--font-mono)", fontSize: 10,
              color: "var(--text-muted)", letterSpacing: "0.06em",
              whiteSpace: "nowrap",
            }}>
              {data.length} episodes
            </span>
          </div>
        </div>
        <div className="panel__body">
          <TrainingChart data={data.slice(0,300)} maWindow={maWindow} />
        </div>
      </div> */}

      {/* ── Two-column ───────────────────────────────────────────────────── */}
      <div className="grid-2">
        {/* ── Learning Curve ───────────────────────────────────────────────── */}
        <div className="panel">
          <div className="panel__header">
            <span className="panel__title">Normalized Reward — Learning Curve</span>
            <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
              <MASlider
                value={maWindow}
                onChange={setMaWindow}
                min={1}
                max={50}
                label="Rolling Avg"
              />
              <span style={{
                fontFamily: "var(--font-mono)", fontSize: 10,
                color: "var(--text-muted)", letterSpacing: "0.06em",
                whiteSpace: "nowrap",
              }}>
                {data.length} episodes
              </span>
            </div>
          </div>
          <div className="panel__body">
            <TrainingChart data={data.slice(0, 292)} maWindow={maWindow} />
          </div>
        </div>

        {/* Vehicle curriculum */}
        <div className="panel">
          <div className="panel__header">
            <span className="panel__title">Vehicle Curriculum</span>
          </div>
          <div className="panel__body">
            <VehicleProgressChart data={data} />
          </div>
        </div>

        {/* Episode stats */}
        {/* <div className="panel">
          <div className="panel__header">
            <span className="panel__title">Episode Statistics</span>
          </div>
          <div className="panel__body" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
            <StatTable rows={data.slice(0, 8)}  title="First 8 Episodes" />
            <StatTable rows={data.slice(-8)}     title="Last 8 Episodes"  />
          </div>
        </div> */}
      </div>
    </>
  );
}
