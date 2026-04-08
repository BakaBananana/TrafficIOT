import { useLocation } from "react-router-dom";

const TITLES = {
  "/training":  "Training Analytics",
  "/inference": "Live Inference Monitor",
};

export default function Header({ wsStatus }) {
  const { pathname } = useLocation();
  const now = new Date().toLocaleTimeString("en-IN", { hour12: false });

  return (
    <header className="header">
      <span className="header__title">{TITLES[pathname] ?? "Dashboard"}</span>
      <div className="header__right">
        <span className="header__badge header__badge--cyan">D3SR</span>
        {wsStatus === "running" && (
          <span className="header__badge header__badge--green">● LIVE</span>
        )}
      </div>
    </header>
  );
}
