import { Routes, Route, Navigate } from "react-router-dom";
import Sidebar from "./components/Sidebar.jsx";
import Header  from "./components/Header.jsx";
import TrainingPage  from "./pages/TrainingPage.jsx";
import InferencePage from "./pages/InferencePage.jsx";
import { InferenceProvider, useInference } from "./hooks/useInference.jsx";

function AppShell() {
  const { status } = useInference();

  return (
    <div className="app-shell">
      <Sidebar wsStatus={status} />
      <Header  wsStatus={status} />
      <main className="main">
        <Routes>
          <Route path="/"          element={<Navigate to="/training" replace />} />
          <Route path="/training"  element={<TrainingPage />} />
          <Route path="/inference" element={<InferencePage />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <InferenceProvider>
      <AppShell />
    </InferenceProvider>
  );
}
