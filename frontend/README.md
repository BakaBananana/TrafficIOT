# Patna STC — Traffic Control Dashboard

Real-time analytics dashboard for the STGAT-PPO smart traffic control system.
Built with **FastAPI** (backend) + **React + Vite** (frontend).

---

## Project Structure

```
traffic-dashboard/
├── backend/
│   ├── main.py              # FastAPI app — REST + WebSocket (dual-mode)
│   ├── sumo_inference.py    # Real SUMO inference runner (step-by-step)
│   ├── requirements.txt
│   └── simulation/          # SUMO environment, model, training scripts
│       ├── env_sumo.py
│       ├── models.py
│       ├── inference.py
│       ├── train.py
│       ├── generate_demand.py
│       ├── stc_simulation.sumocfg
│       ├── patna_stc.net.xml
│       ├── patna_stc.rou.xml
│       └── stgat_ppo_best_real_actual_consistent.pth
└── frontend/
    ├── src/
    │   ├── components/
    │   │   ├── MetricCard.jsx
    │   │   ├── TrainingChart.jsx
    │   │   ├── VehicleProgressChart.jsx
    │   │   ├── IntersectionGrid.jsx
    │   │   ├── LiveTimelineChart.jsx
    │   │   ├── ActionPieChart.jsx
    │   │   ├── RewardTimeline.jsx
    │   │   ├── EpisodeSummaryTable.jsx
    │   │   ├── InferenceControls.jsx
    │   │   ├── Sidebar.jsx
    │   │   └── Header.jsx
    │   ├── hooks/
    │   │   └── useInference.jsx
    │   ├── pages/
    │   │   ├── TrainingPage.jsx
    │   │   └── InferencePage.jsx
    │   ├── App.jsx
    │   ├── main.jsx
    │   └── index.css
    ├── index.html
    ├── package.json
    └── vite.config.js
```

---

## Quick Start

### 1 — Place the training log

Copy `training_log_real_good.csv` into the **project root**:

```
traffic-dashboard/
├── training_log_real_good.csv   ← here
├── backend/
└── frontend/
```

### 2 — Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The server auto-detects whether SUMO is available:
- **SUMO installed** → real inference with the STGAT-PPO model
- **No SUMO** → falls back to built-in mock simulation (no setup needed)

Check the startup log for: `Inference mode: REAL SUMO` or `Inference mode: MOCK`.

### 3 — Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

---

## Inference Modes

### Mock Mode (default fallback)

The built-in simulation produces realistic-looking metrics without requiring SUMO. Runs at 33fps for rapid prototyping and UI development.

### Real SUMO Mode

When SUMO is installed and all simulation files are present, the backend uses the actual STGAT-PPO model to control traffic lights in a real SUMO simulation. Requirements:

1. **SUMO installed** with `SUMO_HOME` environment variable set
2. **Simulation files** in `backend/simulation/`:
   - `stc_simulation.sumocfg`
   - `patna_stc.net.xml`
   - `stgat_ppo_best_real_actual_consistent.pth` (trained model checkpoint)
3. **Python packages**: `torch`, `numpy`, `sumolib`, `traci` (SUMO packages come with SUMO installation)

The system uses `traci` (subprocess mode) to spawn SUMO as a separate process — clean isolation and easy termination.

> **Note:** Only one inference session can run at a time. The backend enforces this with a concurrency lock.

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/training` | GET | Training log data as JSON |
| `/api/health` | GET | Health check + current inference mode |
| `/api/status` | GET | Detailed SUMO availability status |
| `/ws/inference` | WebSocket | Live inference metrics stream |

### WebSocket Protocol (`/ws/inference`)

**Client → Server:**
```json
{ "action": "start", "episode": 1, "num_vehicles": 1500 }
{ "action": "stop" }
```

**Server → Client:**
```json
{ "type": "ready", "mode": "sumo" }
{ "type": "episode_start", "episode": 1, "num_vehicles": 1500 }
{ "type": "step", "episode": 1, "step": 42, "active_vehicles": 1200, "total_queue_pcu": 183.4, "avg_wait_s": 28.1, "step_reward": -312.5, "switches": 3, "intersections": [...] }
{ "type": "episode_end", "episode": 1, "cumulative_reward": -5230.0, "normalized_reward": -3.49, "total_switches": 120, "steps_completed": 3600 }
{ "type": "error", "message": "..." }
```

---

## Pages

| Page | Route | Description |
|------|-------|-------------|
| Training Analytics | `/training` | Learning curves, vehicle curriculum, episode stats |
| Live Inference | `/inference` | Real-time intersection grid, metrics stream, action breakdown |

---

## Design

- **Theme**: Mission-control dark UI — `#060c14` void background, cyan/amber/green accents
- **Fonts**: Share Tech Mono (data values) + Exo 2 (UI labels)
- **Charts**: Recharts — all animations disabled during streaming for performance
- **State**: Single `InferenceProvider` context wraps the app; WebSocket auto-connects
