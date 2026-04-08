/**
 * InferencePage
 * ──────────────
 * Real-time inference dashboard with baseline comparison.
 */

import { useMemo, useState } from "react";
import { Play, Square, BarChart3 } from "lucide-react";
import { useInference }    from "../hooks/useInference.jsx";
import { useBaseline }     from "../hooks/useBaseline.jsx";
import MetricCard          from "../components/MetricCard.jsx";
import InferenceControls   from "../components/InferenceControls.jsx";
import LiveTimelineChart   from "../components/LiveTimelineChart.jsx";
import IntersectionGrid    from "../components/IntersectionGrid.jsx";
import ActionPieChart      from "../components/ActionPieChart.jsx";
import RewardTimeline      from "../components/RewardTimeline.jsx";
import QueueWaitChart      from "../components/QueueWaitChart.jsx";
import ComparisonChart     from "../components/ComparisonChart.jsx";
import EpisodeSummaryTable from "../components/EpisodeSummaryTable.jsx";

// ── Live ticker metrics ───────────────────────────────────────────────────────
function LiveMetrics({ latestStep, stepHistory, status }) {
  const cumReward = useMemo(
    () => stepHistory.reduce((s, h) => s + (h.reward ?? 0), 0),
    [stepHistory]
  );
  const isLive = status === "running";
  return (
    <div className="metrics-row">
      <MetricCard label="Active Vehicles"
        value={isLive && latestStep ? latestStep.active_vehicles : "—"}
        accent="--purple" delta={`Step ${latestStep?.step ?? 0}`} />
      <MetricCard label="Total Queue"
        value={isLive && latestStep ? latestStep.total_queue_pcu.toFixed(1) : "—"}
        unit=" PCU" accent="--cyan" />
      <MetricCard label="Avg Wait Time"
        value={isLive && latestStep ? latestStep.avg_wait_s.toFixed(1) : "—"}
        unit=" s" accent="--amber" />
      <MetricCard label="Step Reward"
        value={isLive && latestStep ? latestStep.step_reward.toFixed(1) : "—"}
        accent={latestStep?.step_reward > -200 ? "--green" : "--red"} />
      <MetricCard label="Cum. Reward"
        value={isLive ? cumReward.toFixed(0) : "—"}
        accent="--cyan" delta={`${stepHistory.length} steps recorded`} />
      <MetricCard label="Switches / Step"
        value={isLive && latestStep ? latestStep.switches : "—"}
        accent="--amber" delta="across all intersections" />
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function InferencePage() {
  const [config, setConfig] = useState({
    episodeNum: 1,
    numVehicles: 1500,
    maxSteps: 4500,
    spawnTime: 3540,
    seed: 42,
    useGui: false,
  });

  const {
    status, runId, latestStep, stepHistory, intersections,
    episodeSummaries, startEpisode, stopEpisode, reconnect,
  } = useInference();

  const {
    status: baselineStatus,
    stepHistory: baselineHistory,
    startBaseline,
    stopBaseline,
  } = useBaseline();

  const baselineRunning = baselineStatus === "running";
  const baselineDone    = baselineStatus === "done";

  return (
    <>
      {/* ── Controls + metrics ──────────────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "300px 1fr", gap: 20 }}>
        <div className="panel">
          <div className="panel__header">
            <span className="panel__title">Inference Controls</span>
          </div>
          <div className="panel__body">
            <InferenceControls
              status={status}
              config={config}
              setConfig={setConfig}
              startEpisode={startEpisode}
              stopEpisode={stopEpisode}
              reconnect={reconnect}
            />
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "center" }}>
          <LiveMetrics latestStep={latestStep} stepHistory={stepHistory} status={status} />
        </div>
      </div>

      {/* ── Live metrics timeline ────────────────────────────────────────── */}
      <div className="panel">
        <div className="panel__header">
          <span className="panel__title">Live Metrics Timeline</span>
          {status === "running" && (
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              {runId && (
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", letterSpacing: "0.06em" }}>
                  RUN: {runId}
                </span>
              )}
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--green)", letterSpacing: "0.08em" }}>
                ● STREAMING
              </span>
            </div>
          )}
        </div>
        <div className="panel__body">
          <LiveTimelineChart history={stepHistory} />
        </div>
      </div>

      {/* ── Intersection grid ────────────────────────────────────────────── */}
      <div className="panel">
        <div className="panel__header">
          <span className="panel__title">Intersection Status</span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", letterSpacing: "0.06em" }}>
            Sorted by queue length · ⇄ = switching
          </span>
        </div>
        <div className="panel__body">
          <IntersectionGrid intersections={intersections} />
        </div>
      </div>

      {/* ── Row 1: reward + queue/wait ───────────────────────────────────── */}
      <div className="grid-2">
        <div className="panel">
          <div className="panel__header">
            <span className="panel__title">Step Reward Timeline</span>
          </div>
          <div className="panel__body">
            <RewardTimeline history={stepHistory} />
          </div>
        </div>
        <div className="panel">
          <div className="panel__header">
            <span className="panel__title">Queue & Wait Analytics</span>
          </div>
          <div className="panel__body">
            <QueueWaitChart history={stepHistory} />
          </div>
        </div>
      </div>

      {/* ── Row 2: action pie + baseline comparison ──────────────────────── */}
      <div className="grid-2">
        {/* <div className="panel">
          <div className="panel__header">
            <span className="panel__title">Action Breakdown</span>
          </div>
          <div className="panel__body">
            <ActionPieChart history={stepHistory} />
          </div>
        </div> */}

        {/* ── Baseline control card */}
        <div className="panel">
          <div className="panel__header">
            <span className="panel__title">Baseline Run (No Agent)</span>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              {baselineDone && (
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--green)" }}>
                  ✓ COMPLETE
                </span>
              )}
              {baselineRunning && (
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--amber)" }}>
                  ● RUNNING
                </span>
              )}
            </div>
          </div>
          <div className="panel__body" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-muted)", lineHeight: 1.7 }}>
              Run SUMO with <strong style={{ color: "var(--text-secondary)" }}>fixed-timing</strong> (no RL agent) to compare against the STGAT-PPO agent. Uses the same vehicle count and spawn settings as your last inference run.
            </div>
            <div style={{ display: "flex", gap: 10 }}>
              {!baselineRunning ? (
                <button
                  className="btn btn--primary"
                  style={{ flex: 1 }}
                  onClick={() => startBaseline({
                    episode: config.episodeNum,
                    numVehicles: config.numVehicles,
                    maxSteps: config.maxSteps,
                    spawnTime: config.spawnTime,
                    seed: config.seed,
                    useGui: config.useGui,
                  })}
                  disabled={baselineRunning}
                >
                  <BarChart3 size={14} />
                  Run Baseline
                </button>
              ) : (
                <button className="btn btn--danger" style={{ flex: 1 }} onClick={stopBaseline}>
                  <Square size={14} />
                  Stop Baseline
                </button>
              )}
            </div>
            {baselineHistory.length > 0 && (
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)" }}>
                {baselineHistory.length} steps collected
                {baselineDone && ` · Avg Queue: ${(baselineHistory.reduce((s,h)=>s+h.totalQueue,0)/baselineHistory.length).toFixed(1)} PCU`}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Comparison chart — full width ────────────────────────────────── */}
      {(stepHistory.length > 0 || baselineHistory.length > 0) && (
        <div className="panel">
          <div className="panel__header">
            <span className="panel__title">RL Agent vs Baseline Comparison</span>
            <div style={{ display: "flex", gap: 16, fontFamily: "var(--font-mono)", fontSize: 10 }}>
              <span style={{ color: "var(--cyan)" }}>── Agent</span>
              <span style={{ color: "var(--red)" }}>- - Baseline</span>
            </div>
          </div>
          <div className="panel__body">
            <ComparisonChart agentHistory={stepHistory} baselineHistory={baselineHistory} />
          </div>
        </div>
      )}

      {/* ── Episode summaries ────────────────────────────────────────────── */}
      <div className="panel">
        <div className="panel__header">
          <span className="panel__title">Episode Summaries</span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", letterSpacing: "0.06em" }}>
            {episodeSummaries.length} episode{episodeSummaries.length !== 1 ? "s" : ""} completed
          </span>
        </div>
        <div className="panel__body">
          <EpisodeSummaryTable summaries={episodeSummaries} />
        </div>
      </div>
    </>
  );
}
