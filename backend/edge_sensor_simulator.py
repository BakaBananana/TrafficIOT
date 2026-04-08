"""
edge_sensor_simulator.py
────────────────────────
Simulates IoT edge devices publishing sensor data via MQTT.
Run this locally to test the MQTT bridge without real hardware.

Usage:
    pip install paho-mqtt
    python edge_sensor_simulator.py

Publishes to:
    patna-stc/intersection/{id}/sensor/vehicle_count
    patna-stc/intersection/{id}/sensor/queue_length
    patna-stc/intersection/{id}/sensor/avg_speed
    patna-stc/system/health/heartbeat
"""

import json
import time
import random
import os

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Install paho-mqtt: pip install paho-mqtt")
    exit(1)

BROKER = os.getenv("MQTT_BROKER", "localhost")
PORT   = int(os.getenv("MQTT_PORT", "1883"))

# Simulated intersections (matching SUMO network)
INTERSECTIONS = [
    "9206957157", "2855586773", "316420820", "9193518702", "J4",
    "316058044", "389672175", "327585208", "2855586769", "9206957152",
]


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(BROKER, PORT)
    client.loop_start()

    print(f"Edge Sensor Simulator — publishing to {BROKER}:{PORT}")
    print(f"Simulating {len(INTERSECTIONS)} intersections")
    print("Press Ctrl+C to stop\n")

    step = 0
    try:
        while True:
            for ix_id in INTERSECTIONS:
                # Simulate realistic sensor readings
                vehicle_count = max(0, int(random.gauss(15, 8)))
                queue_length  = max(0, round(random.gauss(5, 3), 1))
                avg_speed     = max(0, round(random.gauss(25, 10), 1))

                # Publish sensor data
                client.publish(
                    f"patna-stc/intersection/{ix_id}/sensor/vehicle_count",
                    json.dumps({"count": vehicle_count, "step": step}),
                )
                client.publish(
                    f"patna-stc/intersection/{ix_id}/sensor/queue_length",
                    json.dumps({"pcu": queue_length, "step": step}),
                )
                client.publish(
                    f"patna-stc/intersection/{ix_id}/sensor/avg_speed",
                    json.dumps({"kmh": avg_speed, "step": step}),
                )

            # System heartbeat
            client.publish(
                "patna-stc/system/health/heartbeat",
                json.dumps({
                    "device": "simulator",
                    "step": step,
                    "intersections": len(INTERSECTIONS),
                    "timestamp": time.time(),
                }),
            )

            step += 1
            if step % 10 == 0:
                print(f"  Step {step} — published {len(INTERSECTIONS) * 3} sensor readings")

            time.sleep(1)  # 1 Hz update rate

    except KeyboardInterrupt:
        print(f"\nStopped after {step} steps")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
