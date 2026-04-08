/**
 * MASlider
 * ────────
 * Reusable moving-average window slider.
 * Dark-themed range input with live value display.
 *
 * Props:
 *   value     number       current window size
 *   onChange  (n) => void  callback when slider changes
 *   min       number       minimum window (default 1)
 *   max       number       maximum window (default 100)
 *   label     string       label text (default "MA Window")
 */

export default function MASlider({
  value,
  onChange,
  min = 1,
  max = 100,
  label = "MA Window",
}) {
  return (
    <div className="ma-slider">
      <label className="ma-slider__label">{label}</label>
      <input
        type="range"
        className="ma-slider__range"
        min={min}
        max={max}
        value={value}
        onChange={e => onChange(Number(e.target.value))}
      />
      <span className="ma-slider__value">{value}</span>
    </div>
  );
}
