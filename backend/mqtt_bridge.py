"""
mqtt_bridge.py — MQTT Sensor Data Bridge
─────────────────────────────────────────
Bridges IoT sensor data from MQTT topics into the FastAPI backend.
Publishes phase commands back to edge controllers.

Topic structure:
    patna-stc/intersection/{id}/sensor/{type}   ← from edge
    patna-stc/intersection/{id}/control/phase    → to edge
    patna-stc/system/health/heartbeat           ← from edge

Environment variables:
    MQTT_BROKER   default localhost
    MQTT_PORT     default 1883
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT   = int(os.getenv("MQTT_PORT", "1883"))

# Optional import — don't crash if aiomqtt isn't installed
try:
    import aiomqtt
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False
    logger.info("aiomqtt not installed — MQTT bridge disabled")


class MQTTBridge:
    """
    Subscribes to sensor topics, caches latest readings,
    and provides methods to publish control commands.
    """

    def __init__(self):
        self.latest_sensor: dict[str, dict] = {}
        # { intersection_id: { sensor_type: { value, timestamp } } }
        self._connected = False
        self._client = None

    @property
    def available(self) -> bool:
        return HAS_MQTT and self._connected

    async def start(self):
        """Start the MQTT listener loop (runs forever).
        Skips silently if aiomqtt is not installed or broker is unreachable."""
        if not HAS_MQTT:
            logger.info("MQTT bridge not starting (aiomqtt not installed)")
            return

        # Quick TCP probe — don't attempt MQTT if broker isn't reachable
        reachable = await self._probe_broker()
        if not reachable:
            logger.warning(
                "MQTT broker not reachable at %s:%s — bridge disabled. "
                "Start Mosquitto (or run: docker compose up mosquitto -d) to enable.",
                MQTT_BROKER, MQTT_PORT,
            )
            return

        while True:
            try:
                async with aiomqtt.Client(MQTT_BROKER, MQTT_PORT) as client:
                    self._client = client
                    self._connected = True
                    logger.info("✓ MQTT connected to %s:%s", MQTT_BROKER, MQTT_PORT)

                    # Subscribe to all sensor topics
                    await client.subscribe("patna-stc/intersection/+/sensor/#")
                    await client.subscribe("patna-stc/system/#")

                    async for message in client.messages:
                        self._handle_message(message)

            except Exception as e:
                self._connected = False
                logger.warning("MQTT connection lost (%s), reconnecting in 5s...", e)
                await asyncio.sleep(5)

    async def _probe_broker(self) -> bool:
        """Returns True if the MQTT broker TCP port is open."""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(MQTT_BROKER, MQTT_PORT),
                timeout=2.0,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False

    def _handle_message(self, message):
        """Parse incoming MQTT message and update cache."""
        topic = str(message.topic)
        parts = topic.split("/")

        try:
            payload = json.loads(message.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = message.payload.decode()

        # patna-stc/intersection/{id}/sensor/{type}
        if len(parts) >= 5 and parts[1] == "intersection" and parts[3] == "sensor":
            ix_id = parts[2]
            sensor_type = parts[4]
            self.latest_sensor.setdefault(ix_id, {})[sensor_type] = {
                "value": payload,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            logger.debug("Sensor %s/%s = %s", ix_id, sensor_type, payload)

        # patna-stc/system/health/heartbeat
        elif "heartbeat" in topic:
            logger.debug("Heartbeat: %s", payload)

    async def publish_phase(self, intersection_id: str, phase_index: int):
        """Send phase command to an edge controller."""
        if not self.available or not self._client:
            return
        try:
            await self._client.publish(
                f"patna-stc/intersection/{intersection_id}/control/phase",
                json.dumps({"phase": phase_index, "source": "cloud-rl"}),
            )
        except Exception as e:
            logger.warning("MQTT publish error: %s", e)

    async def publish_sensor_snapshot(self, snapshot: dict):
        """Publish real simulation state back out to MQTT (acting as the edge device)."""
        if not self.available or not self._client:
            return
        step = snapshot.get("step", 0)
        try:
            for ix in snapshot.get("intersections", []):
                ix_id = ix["id"]
                await self._client.publish(
                    f"patna-stc/intersection/{ix_id}/sensor/queue_length",
                    json.dumps({"pcu": ix.get("queue_pcu", 0), "step": step}),
                )
                await self._client.publish(
                    f"patna-stc/intersection/{ix_id}/sensor/wait_time",
                    json.dumps({"s": ix.get("wait_time_s", 0), "step": step}),
                )

            # System heartbeat
            await self._client.publish(
                "patna-stc/system/health/heartbeat",
                json.dumps({
                    "device": "sumo_simulation",
                    "step": step,
                    "active_vehicles": snapshot.get("active_vehicles", 0),
                }),
            )
        except Exception as e:
            logger.warning("MQTT bridge sensor publish error: %s", e)

    def get_sensor_snapshot(self) -> dict:
        """Return the latest cached sensor readings for all intersections."""
        return dict(self.latest_sensor)


# Singleton
mqtt_bridge = MQTTBridge()
