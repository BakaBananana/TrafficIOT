/**
 * EpisodeSummaryTable
 * ────────────────────
 * Shows a scrollable table of completed inference episode summaries.
 *
 * Props:
 *   summaries   Array<{
 *     episode, numVehicles, cumulativeReward,
 *     normalizedReward, totalSwitches, stepsCompleted
 *   }>
 */

export default function EpisodeSummaryTable({ summaries = [] }) {
  if (!summaries.length) {
    return (
      <div style={{
        textAlign: "center",
        padding: "32px",
        color: "var(--text-muted)",
        fontFamily: "var(--font-mono)",
        fontSize: 12,
        letterSpacing: "0.06em",
      }}>
        No episodes completed yet. Run an inference session to see results.
      </div>
    );
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table className="ep-table">
        <thead>
          <tr>
            <th>Episode</th>
            <th>Vehicles</th>
            <th>Norm. Reward</th>
            <th>Cum. Reward</th>
            <th>Switches</th>
            <th>Steps</th>
          </tr>
        </thead>
        <tbody>
          {summaries.map(s => {
            const normColor =
              s.normalizedReward > -20 ? "val--green" :
              s.normalizedReward > -30 ? "val--cyan"  :
              s.normalizedReward > -40 ? "val--amber" : "val--red";

            return (
              <tr key={s.episode}>
                <td className="val--muted">#{s.episode}</td>
                <td className="val--cyan">{s.numVehicles.toLocaleString()}</td>
                <td className={normColor}>{s.normalizedReward.toFixed(4)}</td>
                <td className="val--muted">{s.cumulativeReward.toFixed(0)}</td>
                <td className="val--amber">{s.totalSwitches.toLocaleString()}</td>
                <td className="val--muted">{s.stepsCompleted.toLocaleString()}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
