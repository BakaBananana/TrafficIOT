import { NavLink } from "react-router-dom";
import { BarChart2, Radio, Activity } from "lucide-react";

const NAV = [
  { to: "/training",  label: "Training Log",    Icon: BarChart2 },
  { to: "/inference", label: "Live Inference",   Icon: Radio },
];

const STATUS_LABEL = {
  idle:       "Standby",
  connecting: "Connecting…",
  running:    "Inference Running",
  done:       "Episode Complete",
  error:      "Connection Error",
};

export default function Sidebar({ wsStatus = "idle" }) {
  return (
    <aside className="sidebar">
      {/* Logo */}
      <div className="sidebar__logo">
        <div className="sidebar__logo-title">PATNA&nbsp;STC</div>
        <div className="sidebar__logo-sub">STGAT-PPO&nbsp;·&nbsp;v1.0</div>
      </div>

      {/* Nav */}
      <nav className="sidebar__nav">
        <div className="sidebar__section-label">Modules</div>
        {NAV.map(({ to, label, Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              "sidebar__link" + (isActive ? " active" : "")
            }
          >
            <Icon size={15} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Status footer */}
      <div className="sidebar__status">
        <span className={`status-dot ${wsStatus}`} />
        <span>{STATUS_LABEL[wsStatus] ?? wsStatus}</span>
      </div>
    </aside>
  );
}
