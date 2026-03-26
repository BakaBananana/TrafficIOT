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

:: T3 — Decision Model
start "Decision Model" cmd /k "%PYTHON% stgat_model_client.py --model %MODEL_PTH%"
timeout /t 1 /nobreak >nul

:: T5 — SUMO Gateway (last — simulation drives everything)
start "SUMO Gateway" cmd /k "%PYTHON% sumo_gateway.py --cfg %SUMO_CFG% --net %SUMO_NET%"
timeout /t 2 /nobreak >nul

echo  All services started.
echo  Close this window to keep services running.
echo.
pause