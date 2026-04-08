# 🚦 Smart Traffic Control System (STC)

![License](https://img.shields.io/badge/license-MIT-green)

A production-ready Deep Reinforcement Learning infrastructure for adaptive, multi-intersection traffic signal control using **Spatial-Temporal Graph Attention Networks (STGAT)** and **Proximal Policy Optimization (PPO)**. 

Designed natively for a **Fog Computing** & IoT architecture, this project seamlessly bridges highly-scalable academic deep learning with a real-world edge telemetry stack (MQTT, InfluxDB, FastAPI) and multiple digital twin interfaces (Eclipse SUMO, Unity 3D, and React).

---

## 🌟 Core Features
- **$K=3$ Hop STGAT Architecture:** Replaces fixed-timing controllers with dynamic GNN logic, ensuring multi-agent intersections naturally cooperate rather than creating ripple-effect gridlocks.
- **Hardware-Locking Sim Engine:** An asynchronous 1 Hz hardware execution loop that completely decouples physical signal phases from the underlying traffic simulation. 
- **Fog Computing Design:** Centralized IoT inference architecture. Ingests YOLOv8-derived vehicle tensors from lightweight edge sensors via MQTT and dispatches phase logic.
- **Live Digital Twins:** Features a low-latency FastAPI WebSocket backend streaming live inference telemetry directly to a 2D **React Dashboard** and an immersive **Unity 3D** environment. 

## 🏗️ Architecture

The system operates across three distinct layers:
1. **Edge/Fog Layer:** Lightweight camera arrays and PLCs streaming tensor data (`Queue`, `Wait`, `Phase`) to a centralized Municipal AI Server over MQTT.
2. **Cloud/Server Layer:** The inference engine orchestrated via Docker Compose, running the PyTorch STGAT model, Eclipse Mosquitto broker, and InfluxDB time-series DB.
3. **Client/Visualization Layer:** A dedicated React frontend tracking real-time reward outputs, cumulative wait-time reductions, and queue pressure charts.

## 🛠️ Technology Stack

| Domain | Technologies |
| :--- | :--- |
| **Simulation** | ![SUMO](https://img.shields.io/badge/Eclipse_SUMO-006F8C?style=flat&logo=eclipse&logoColor=white) ![TraCI](https://img.shields.io/badge/TraCI_API-263A48?style=flat) |
| **AI / Model** | ![PyTorch](https://img.shields.io/badge/PyTorch-EE4C2C?style=flat&logo=pytorch&logoColor=white) ![Custom RL Environment](https://img.shields.io/badge/Custom_RL_Environment-000000?style=flat) |
| **Microservices & Data** | ![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white) ![Mosquitto MQTT](https://img.shields.io/badge/MQTT_Mosquitto-3C5280?style=flat&logo=eclipse-mosquitto&logoColor=white) ![InfluxDB](https://img.shields.io/badge/InfluxDB-22ADF6?style=flat&logo=influxdb&logoColor=white) ![Docker](https://img.shields.io/badge/Docker_Compose-2496ED?style=flat&logo=docker&logoColor=white) |
| **Frontend Dashboard** | ![NodeJS](https://img.shields.io/badge/Node.js-339933?style=flat&logo=nodedotjs&logoColor=white) ![React](https://img.shields.io/badge/React-61DAFB?style=flat&logo=react&logoColor=black) |
| **Spatial Rendering** | ![Unity](https://img.shields.io/badge/Unity_3D-000000?style=flat&logo=unity&logoColor=white) |


## 📂 Repository Structure
```text
traffic-dashboard/
├── backend/                  # FastApi WSS Server, IoT Agents & Model
│   ├── main.py               # Asynchronous WebSocket API orchestrator
│   ├── mqtt_bridge.py        # MQTT Pub/Sub consumer for Edge node telemetry
│   ├── tsdb.py               # InfluxDB time-series ingestion bindings
│   ├── sumo_inference.py     # TraCI RL loop synchronized via hardware locks
│   ├── baseline_runner.py    # Independent Q-Learning & Fixed-cycle agents
│   └── simulation/           # PyTorch and SUMO definitions
│       ├── models.py         # STGAT & PPO architecture logic
│       ├── env_sumo.py       # Graph embedding and BFS adjacency module
│       ├── train.py          # Centralized multi-agent training script
│       └── patna_stc.net.xml # Physical Patna Digital Twin road geometry
├── frontend/                 # React + Vite Client Dashboard
│   ├── src/
│   │   ├── pages/            # View layers integrating Unity 3D & Analytics
│   │   ├── components/       # Recharts streaming metrics and UI controls
│   │   └── hooks/            # Websocket decoupling and connection states
├── docs/                     # Project report
├── docker-compose.yml        # Orchestration for Eclipse Mosquitto and InfluxDB
└── start.sh                  # Bootstrap script for the full microservices stack
```

## 🚀 Getting Started

### Prerequisites
- **Python** 3.10+
- **Node.js** 18+
- **Docker Compose**
- **Eclipse SUMO** ($\geq$ 1.18.0)

### Setup

1. **Spin up the Data Backbone**
   Ensure Docker is running, then initialize the TSDB and MQTT brokers.
   ```bash
   docker-compose up -d
   ```

2. **Initialize the Backend Engine**
   Ensure Eclipse SUMO is installed and your `SUMO_HOME` environment variable is configured. 
   ```bash
   cd backend
   pip install -r requirements.txt
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

3. **Launch the Dashboard**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

4. Navigate to `http://localhost:5173` to access the live dashboard and trigger the RL inference.

---

## 👥 Team
Developed collaboratively by:
- **Divya Prakash Sinha**
- **Dyuti Ballav Paul**
- **Devansh Gupta**
- **Shreyas Kumar Patel**
- **Rishit Das**
