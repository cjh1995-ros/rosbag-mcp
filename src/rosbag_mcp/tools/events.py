from __future__ import annotations

import logging

import numpy as np
from mcp.types import TextContent

from rosbag_mcp.bag_reader import read_messages
from rosbag_mcp.tools.utils import get_nested_field, json_serialize

logger = logging.getLogger(__name__)


async def detect_events(
    topic: str,
    field: str,
    event_type: str = "threshold",
    threshold: float | None = None,
    window_size: int = 10,
    bag_path: str | None = None,
) -> list[TextContent]:
    """Detect threshold crossings, sudden changes, anomalies, and stoppages."""
    values = []
    timestamps = []

    for msg in read_messages(bag_path=bag_path, topics=[topic]):
        value = get_nested_field(msg.data, field)
        if value is not None and isinstance(value, (int, float)):
            values.append(float(value))
            timestamps.append(msg.timestamp)

    if len(values) < window_size:
        return [TextContent(type="text", text="Insufficient data for event detection")]

    events = []
    values_arr = np.array(values)

    if event_type == "threshold" and threshold is not None:
        for i, (t, v) in enumerate(zip(timestamps, values)):
            if v > threshold:
                events.append(
                    {
                        "type": "threshold_exceeded",
                        "timestamp": t,
                        "value": round(v, 4),
                        "threshold": threshold,
                    }
                )

    elif event_type == "threshold_below" and threshold is not None:
        for i, (t, v) in enumerate(zip(timestamps, values)):
            if v < threshold:
                events.append(
                    {
                        "type": "threshold_below",
                        "timestamp": t,
                        "value": round(v, 4),
                        "threshold": threshold,
                    }
                )

    elif event_type == "sudden_change":
        if threshold is None:
            threshold = float(np.std(values_arr) * 2)

        for i in range(1, len(values)):
            change = abs(values[i] - values[i - 1])
            if change > threshold:
                events.append(
                    {
                        "type": "sudden_change",
                        "timestamp": timestamps[i],
                        "value": round(values[i], 4),
                        "previous_value": round(values[i - 1], 4),
                        "change": round(change, 4),
                    }
                )

    elif event_type == "anomaly":
        mean = float(np.mean(values_arr))
        std = float(np.std(values_arr))
        z_threshold = threshold if threshold else 3.0

        for i, (t, v) in enumerate(zip(timestamps, values)):
            z_score = abs(v - mean) / std if std > 0 else 0
            if z_score > z_threshold:
                events.append(
                    {
                        "type": "anomaly",
                        "timestamp": t,
                        "value": round(v, 4),
                        "z_score": round(z_score, 2),
                        "mean": round(mean, 4),
                        "std": round(std, 4),
                    }
                )

    elif event_type == "stoppage":
        stop_threshold = threshold if threshold else 0.01
        stop_duration = window_size

        in_stop = False
        stop_start = None
        stop_count = 0

        for i, (t, v) in enumerate(zip(timestamps, values)):
            if abs(v) < stop_threshold:
                if not in_stop:
                    stop_start = t
                    in_stop = True
                stop_count += 1
            else:
                if in_stop and stop_count >= stop_duration:
                    events.append(
                        {
                            "type": "stoppage",
                            "start_timestamp": stop_start,
                            "end_timestamp": timestamps[i - 1] if i > 0 else t,
                            "duration_s": round(timestamps[i - 1] - stop_start, 3) if i > 0 else 0,
                        }
                    )
                in_stop = False
                stop_count = 0

        if in_stop and stop_count >= stop_duration:
            events.append(
                {
                    "type": "stoppage",
                    "start_timestamp": stop_start,
                    "end_timestamp": timestamps[-1],
                    "duration_s": round(timestamps[-1] - stop_start, 3),
                }
            )

    result = {
        "topic": topic,
        "field": field,
        "event_type": event_type,
        "total_messages": len(values),
        "events_found": len(events),
        "events": events[:500],
    }

    return [TextContent(type="text", text=json_serialize(result))]
