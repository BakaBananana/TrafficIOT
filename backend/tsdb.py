"""
tsdb.py — Time-Series Database Writer (InfluxDB)
─────────────────────────────────────────────────
Async-compatible InfluxDB writer for step-level and episode-level metrics.
Falls back gracefully if InfluxDB is unavailable (dashboard works without it).

Environment variables:
    INFLUX_URL     default http://localhost:8086
    INFLUX_TOKEN   default my-super-secret-token
    INFLUX_ORG     default patna-stc
    INFLUX_BUCKET  default traffic_metrics
"""

import os
import logging
from datetime import datetime, timezone
import zoneinfo

logger = logging.getLogger(__name__)

# ── Optional import — don't crash if influxdb-client isn't installed ─────────
try:
    from influxdb_client import InfluxDBClient, Point, WritePrecision
    from influxdb_client.client.write_api import ASYNCHRONOUS
    HAS_INFLUX = True
except ImportError:
    HAS_INFLUX = False
    logger.info("influxdb-client not installed — running without persistence")

INFLUX_URL    = os.getenv("INFLUX_URL",    "http://localhost:8086")
INFLUX_TOKEN  = os.getenv("INFLUX_TOKEN",  "my-super-secret-token")
INFLUX_ORG    = os.getenv("INFLUX_ORG",    "patna-stc")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "traffic_metrics")


class TSDBWriter:
    """Write traffic metrics to InfluxDB. No-ops silently if unavailable."""

    def __init__(self):
        self._client = None
        self._write_api = None
        self._query_api = None

        if not HAS_INFLUX:
            return

        try:
            self._client = InfluxDBClient(
                url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG
            )
            self._write_api = self._client.write_api(write_options=ASYNCHRONOUS)
            self._query_api = self._client.query_api()
        except Exception as e:
            logger.warning("InfluxDB unavailable (continuing without): %s", e)

    @property
    def available(self) -> bool:
        return self._write_api is not None

    # ── Write step metrics ───────────────────────────────────────────────
    def write_step(self, step_data: dict, mode: str = "agent",
                   episode: int = 0, run_id: str = "default"):
        """Persist a single simulation step snapshot."""
        if not self.available:
            return
        try:
            now = datetime.now(timezone.utc)
            p = (
                Point("step_metrics")
                .tag("mode", mode)
                .tag("episode", str(episode))
                .tag("run_id", run_id)
                .field("step", int(step_data.get("step", 0)))
                .field("total_queue_pcu",
                       float(step_data.get("total_queue_pcu", 0)))
                .field("avg_wait_s",
                       float(step_data.get("avg_wait_s", 0)))
                .field("step_reward",
                       float(step_data.get("step_reward", 0)))
                .field("active_vehicles",
                       int(step_data.get("active_vehicles", 0)))
                .field("switches",
                       int(step_data.get("switches", 0)))
                .time(now, WritePrecision.MS)
            )
            self._write_api.write(bucket=INFLUX_BUCKET, record=p)

            # Per-intersection data
            for ix in step_data.get("intersections", []):
                ix_p = (
                    Point("intersection_metrics")
                    .tag("mode", mode)
                    .tag("episode", str(episode))
                    .tag("run_id", run_id)
                    .tag("intersection_id", str(ix.get("id", "")))
                    .field("queue_pcu",
                           float(ix.get("queue_pcu", 0)))
                    .field("avg_wait_s",
                           float(ix.get("avg_wait_s", 0)))
                    .field("phase_index",
                           int(ix.get("phase_index", 0)))
                    .time(now, WritePrecision.MS)
                )
                self._write_api.write(bucket=INFLUX_BUCKET, record=ix_p)
        except Exception as e:
            logger.warning("TSDB write_step error: %s", e)

    # ── Write episode summary ────────────────────────────────────────────
    def write_episode_summary(self, summary: dict, mode: str = "agent", run_id: str = "default"):
        """Persist episode summary."""
        if not self.available:
            return
        try:
            p = (
                Point("episode_summary")
                .tag("mode", mode)
                .tag("episode", str(summary.get("episode", 0)))
                .tag("run_id", run_id)
                .field("cumulative_reward",
                       float(summary.get("cumulative_reward", 0)))
                .field("normalized_reward",
                       float(summary.get("normalized_reward", 0)))
                .field("total_switches",
                       int(summary.get("total_switches", 0)))
                .field("steps_completed",
                       int(summary.get("steps_completed", 0)))
                .field("num_vehicles",
                       int(summary.get("num_vehicles", 0)))
                .time(datetime.now(timezone.utc), WritePrecision.MS)
            )
            self._write_api.write(bucket=INFLUX_BUCKET, record=p)
        except Exception as e:
            logger.warning("TSDB write_episode error: %s", e)

    # ── Query helpers ────────────────────────────────────────────────────
    def query_step_history(self, mode: str = "agent",
                           episode: str = None,
                           minutes: int = 60) -> list:
        """
        Query step_metrics for the given mode/episode
        within the last `minutes` minutes.
        Returns list of dicts.
        """
        if not self.available or not self._query_api:
            return []
        try:
            episode_filter = ""
            if episode:
                episode_filter = (
                    f'  |> filter(fn: (r) => r.episode == "{episode}")\n'
                )
            flux = f'''
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -{minutes}m)
  |> filter(fn: (r) => r._measurement == "step_metrics")
  |> filter(fn: (r) => r.mode == "{mode}")
{episode_filter}  |> pivot(rowKey:["_time"], columnKey:["_field"], valueColumn:"_value")
  |> sort(columns: ["_time"])
  |> limit(n: 10000)
'''
            tables = self._query_api.query(flux, org=INFLUX_ORG)
            result = []
            for table in tables:
                for record in table.records:
                    result.append({
                        "time":             str(record.get_time()),
                        "step":             record.values.get("step", 0),
                        "total_queue_pcu":  record.values.get("total_queue_pcu", 0),
                        "avg_wait_s":       record.values.get("avg_wait_s", 0),
                        "step_reward":      record.values.get("step_reward", 0),
                        "active_vehicles":  record.values.get("active_vehicles", 0),
                        "switches":         record.values.get("switches", 0),
                        "mode":             mode,
                        "episode":          record.values.get("episode", "0"),
                        "run_id":           record.values.get("run_id", "default"),
                    })
            return result
        except Exception as e:
            logger.warning("TSDB query error: %s", e)
            return []

    def query_episode_summaries(self, mode: str = None,
                                minutes: int = 1440) -> list:
        """Query episode summaries within the last `minutes` minutes."""
        if not self.available or not self._query_api:
            return []
        try:
            mode_filter = ""
            if mode:
                mode_filter = (
                    f'  |> filter(fn: (r) => r.mode == "{mode}")\n'
                )
            flux = f'''
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -{minutes}m)
  |> filter(fn: (r) => r._measurement == "episode_summary")
{mode_filter}  |> pivot(rowKey:["_time"], columnKey:["_field"], valueColumn:"_value")
  |> sort(columns: ["_time"], desc: true)
  |> limit(n: 100)
'''
            tables = self._query_api.query(flux, org=INFLUX_ORG)
            result = []
            for table in tables:
                for record in table.records:
                    result.append({
                        "time":               str(record.get_time()),
                        "episode":            record.values.get("episode", "0"),
                        "mode":               record.values.get("mode", "agent"),
                        "run_id":             record.values.get("run_id", "default"),
                        "cumulative_reward":   record.values.get("cumulative_reward", 0),
                        "normalized_reward":   record.values.get("normalized_reward", 0),
                        "total_switches":      record.values.get("total_switches", 0),
                        "steps_completed":     record.values.get("steps_completed", 0),
                        "num_vehicles":        record.values.get("num_vehicles", 0),
                    })
            return result
        except Exception as e:
            logger.warning("TSDB query error: %s", e)
            return []

    def close(self):
        if self._client:
            self._client.close()


# ── Singleton ────────────────────────────────────────────────────────────────
tsdb = TSDBWriter()
