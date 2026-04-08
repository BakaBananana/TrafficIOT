/**
 * MetricCard
 * ──────────
 * Props:
 *   label   string   — short uppercase label
 *   value   number | string
 *   unit    string?  — e.g. "s", "PCU", "%"
 *   accent  string?  — CSS color var name, e.g. "--cyan", "--green"
 *   delta   string?  — e.g. "+3.2%" shown beneath value
 *   deltaUp boolean? — true = green, false = red
 */
export default function MetricCard({
  label,
  value,
  unit,
  accent = "--cyan",
  delta,
  deltaUp,
}) {
  const accentVal = `var(${accent})`;

  return (
    <div className="metric-card" style={{ "--accent": accentVal }}>
      <div className="metric-card__label">{label}</div>
      <div className="metric-card__value">
        {value ?? "—"}
        {unit && <span className="metric-card__unit">{unit}</span>}
      </div>
      {delta !== undefined && (
        <div
          className={
            "metric-card__delta " +
            (deltaUp === true  ? "delta-up"   :
             deltaUp === false ? "delta-down" : "")
          }
        >
          {delta}
        </div>
      )}
    </div>
  );
}
