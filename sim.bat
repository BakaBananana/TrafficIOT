@echo on
title SUMO Traffic IoT — Launcher

:: ── Config ────────────────────────────────────────────────────
set SUMO_CFG=stc_simulation.sumocfg
set SUMO_NET=patna_stc.net.xml
set MODEL_PTH=stgat_ppo_best.pth
set "MOSQUITTO=.\Mosquitto\mosquitto.exe"
set PYTHON=python

echo.
echo  Starting SUMO Traffic IoT System
echo  ----------------------------------
echo.

:: T1 — MQTT Broker
start "MQTT Broker" cmd /k "%MOSQUITTO%"
timeout /t 2 /nobreak >nul

:: T2 — DB Logger (must start before gateway so no messages are missed)
start "DB Logger" cmd /k "%PYTHON% logger.py"
timeout /t 1 /nobreak >nul

:: T3 — Decision Model
start "Decision Model" cmd /k "%PYTHON% stgat_model_client.py --model %MODEL_PTH%"
timeout /t 1 /nobreak >nul

:: T4 — API Server
start "API Server" cmd /k "uvicorn api_server:app --reload --port 8000"
timeout /t 2 /nobreak >nul

:: T5 — SUMO Gateway (last — simulation drives everything)
start "SUMO Gateway" cmd /k "%PYTHON% sumo_gateway.py --cfg %SUMO_CFG% --net %SUMO_NET%"
timeout /t 5 /nobreak >nul

:: Open dashboard in default browser
::start "Dashboard" cmd /k "cd /d traffic-dashboard && npm run dev"
::timeout /t 3 /nobreak >nul
::start "" http://localhost:3000
start "Dashboard" dashboard.html

echo  All services started.
echo  Dashboard opened in browser.
echo  Close this window to keep services running.
echo.
pause