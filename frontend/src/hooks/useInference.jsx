/**
 * useInference.jsx
 * ─────────────────
 * React context + hook that manages the WebSocket connection to the backend,
 * buffers incoming step metrics, and exposes controls (start / stop).
 *
 * Status values: "idle" | "connecting" | "running" | "done" | "error"
 */

import {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useRef,
    useState,
} from "react";

const MAX_HISTORY_STEPS = 600; // Keep last N steps in the live timeline buffer

// ── Context ───────────────────────────────────────────────────────────────────
const InferenceCtx = createContext(null);

export function InferenceProvider({ children }) {
    const wsRef = useRef(null);
    const statusRef = useRef("idle");

    // Connection / session state
    const [status, setStatus] = useState("idle");   // "idle"|"connecting"|"running"|"done"|"error"
    const [episode, setEpisode] = useState(1);
    const [runId, setRunId] = useState(null);
    const runIdRef = useRef(null);

    // Keep statusRef in sync with state
    const updateStatus = useCallback((newStatus) => {
        statusRef.current = newStatus;
        setStatus(newStatus);
    }, []);

    // Live step data
    const [latestStep, setLatestStep] = useState(null);   // most-recent step snapshot
    const [stepHistory, setStepHistory] = useState([]);     // rolling buffer for timeline charts
    const [intersections, setIntersections] = useState([]);   // per-intersection breakdown

    // Episode summaries
    const [episodeSummaries, setEpisodeSummaries] = useState([]);

    // ── Connect ─────────────────────────────────────────────────────────────────
    const connect = useCallback(() => {
        if (wsRef.current && wsRef.current.readyState < 2) return; // already open/connecting

        const protocol = window.location.protocol === "https:" ? "wss" : "ws";
        const ws = new WebSocket(`${protocol}://${window.location.host}/ws/inference`);
        wsRef.current = ws;
        updateStatus("connecting");

        ws.onopen = () => {
            console.log("[WS] connected");
        };

        ws.onmessage = (evt) => {
            const msg = JSON.parse(evt.data);

            switch (msg.type) {
                case "ready":
                    updateStatus("idle");
                    break;

                case "episode_start":
                    setEpisode(msg.episode);
                    setRunId(msg.run_id);
                    runIdRef.current = msg.run_id;
                    setStepHistory([]);
                    setIntersections([]);
                    setLatestStep(null);
                    updateStatus("running");
                    break;

                case "step": {
                    const point = {
                        step: msg.step,
                        totalQueue: msg.total_queue_pcu,
                        avgWait: msg.avg_wait_s,
                        reward: msg.step_reward,
                        activeVehicles: msg.active_vehicles,
                        switches: msg.switches,
                    };

                    setLatestStep(msg);
                    setIntersections(msg.intersections ?? []);
                    setStepHistory(prev => [...prev, point]);
                    break;
                }

                case "episode_end":
                    updateStatus("done");
                    setEpisodeSummaries(prev => [
                        {
                            episode: msg.episode,
                            runId: msg.run_id || runIdRef.current,
                            numVehicles: msg.num_vehicles,
                            cumulativeReward: msg.cumulative_reward,
                            normalizedReward: msg.normalized_reward,
                            totalSwitches: msg.total_switches,
                            stepsCompleted: msg.steps_completed,
                        },
                        ...prev,
                    ]);
                    break;

                case "error":
                    console.error("[WS] server error:", msg.message);
                    updateStatus("error");
                    break;

                default:
                    break;
            }
        };

        ws.onerror = () => updateStatus("error");
        ws.onclose = () => {
            if (statusRef.current !== "done") updateStatus("idle");
        };
    }, [updateStatus]);

    // ── Start inference episode ─────────────────────────────────────────────────
    const startEpisode = useCallback(({ episode, numVehicles, maxSteps, spawnTime, seed, useGui }) => {
        if (!wsRef.current || wsRef.current.readyState !== 1) {
            console.warn("[WS] not connected — call connect() first");
            return;
        }
        wsRef.current.send(JSON.stringify({
            action: "start",
            episode,
            num_vehicles: numVehicles,
            max_steps: maxSteps ?? 4500,
            spawn: spawnTime ?? 3540,
            seed: seed ?? 42,
            use_gui: useGui === true,
        }));
        updateStatus("running");
    }, []);

    // ── Stop ────────────────────────────────────────────────────────────────────
    const stopEpisode = useCallback(() => {
        wsRef.current?.send(JSON.stringify({ action: "stop" }));
        updateStatus("idle");
    }, []);

    // ── Auto-connect on mount ───────────────────────────────────────────────────
    useEffect(() => {
        connect();
        return () => wsRef.current?.close();
    }, [connect]);

    return (
        <InferenceCtx.Provider value={{
            status,
            episode,
            runId,
            latestStep,
            stepHistory,
            intersections,
            episodeSummaries,
            startEpisode,
            stopEpisode,
            reconnect: connect,
        }}>
            {children}
        </InferenceCtx.Provider>
    );
}

export function useInference() {
    const ctx = useContext(InferenceCtx);
    if (!ctx) throw new Error("useInference must be used inside <InferenceProvider>");
    return ctx;
}
