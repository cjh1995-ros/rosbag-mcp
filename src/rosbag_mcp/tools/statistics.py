from __future__ import annotations

import csv
import logging
from pathlib import Path

import numpy as np
from mcp.types import TextContent

from rosbag_mcp.bag_reader import (
    get_topic_schema as _get_topic_schema,
)
from rosbag_mcp.bag_reader import (
    get_topic_timestamps,
    read_messages,
)
from rosbag_mcp.tools.utils import get_nested_field, json_serialize

logger = logging.getLogger(__name__)


async def get_topic_schema(
    topic: str,
    bag_path: str | None = None,
) -> list[TextContent]:
    """Inspect the message structure and schema for a topic."""
    logger.info(f"Getting schema for topic {topic}")
    schema_info = _get_topic_schema(topic, bag_path)
    logger.debug(f"Schema retrieved for {topic}")
    return [TextContent(type="text", text=json_serialize(schema_info))]


async def analyze_topic_stats(
    topic: str,
    bag_path: str | None = None,
) -> list[TextContent]:
    """Analyze topic publishing frequency, intervals, and gaps."""
    logger.info(f"Analyzing topic statistics for {topic}")
    timestamps = get_topic_timestamps(topic, bag_path)

    if not timestamps:
        return [TextContent(type="text", text=f"No messages found for topic: {topic}")]

    if len(timestamps) < 2:
        return [
            TextContent(
                type="text",
                text=json_serialize(
                    {
                        "topic": topic,
                        "message_count": 1,
                        "note": "Only one message, cannot compute statistics",
                    }
                ),
            )
        ]

    intervals = np.diff(timestamps)
    gaps = intervals[intervals > np.mean(intervals) * 3]  # Gaps > 3x mean interval

    result = {
        "topic": topic,
        "message_count": len(timestamps),
        "duration_s": round(timestamps[-1] - timestamps[0], 3),
        "first_timestamp": timestamps[0],
        "last_timestamp": timestamps[-1],
        "frequency": {
            "mean_hz": round(1.0 / float(np.mean(intervals)), 2),
            "std_hz": round(float(np.std(1.0 / intervals)), 2) if np.all(intervals > 0) else 0,
            "min_hz": round(1.0 / float(np.max(intervals)), 2) if np.max(intervals) > 0 else 0,
            "max_hz": round(1.0 / float(np.min(intervals)), 2) if np.min(intervals) > 0 else 0,
        },
        "interval": {
            "mean_ms": round(float(np.mean(intervals)) * 1000, 3),
            "std_ms": round(float(np.std(intervals)) * 1000, 3),
            "min_ms": round(float(np.min(intervals)) * 1000, 3),
            "max_ms": round(float(np.max(intervals)) * 1000, 3),
        },
        "gaps": {
            "count": len(gaps),
            "threshold_ms": round(float(np.mean(intervals)) * 3 * 1000, 3),
            "largest_gap_ms": round(float(np.max(gaps)) * 1000, 3) if len(gaps) > 0 else 0,
        },
    }

    logger.debug(f"Topic stats: {len(timestamps)} messages, {len(gaps)} gaps detected")
    return [TextContent(type="text", text=json_serialize(result))]


async def compare_topics(
    topic1: str,
    topic2: str,
    field1: str,
    field2: str,
    start_time: float | None = None,
    end_time: float | None = None,
    bag_path: str | None = None,
) -> list[TextContent]:
    """Compare two topic fields with correlation and RMSE metrics."""
    logger.info(f"Comparing topics {topic1} and {topic2}")
    data1 = {"times": [], "values": []}
    data2 = {"times": [], "values": []}

    for msg in read_messages(
        bag_path=bag_path, topics=[topic1], start_time=start_time, end_time=end_time
    ):
        value = get_nested_field(msg.data, field1)
        if value is not None and isinstance(value, (int, float)):
            data1["times"].append(msg.timestamp)
            data1["values"].append(float(value))

    for msg in read_messages(
        bag_path=bag_path, topics=[topic2], start_time=start_time, end_time=end_time
    ):
        value = get_nested_field(msg.data, field2)
        if value is not None and isinstance(value, (int, float)):
            data2["times"].append(msg.timestamp)
            data2["values"].append(float(value))

    if not data1["values"] or not data2["values"]:
        logger.warning(
            f"Insufficient data for comparison: "
            f"topic1={len(data1['values'])}, topic2={len(data2['values'])}"
        )
        return [TextContent(type="text", text="Insufficient data for comparison")]

    logger.debug(f"Comparing {len(data1['values'])} vs {len(data2['values'])} values")
    interp_values2 = np.interp(data1["times"], data2["times"], data2["values"])
    differences = np.array(data1["values"]) - interp_values2

    correlation = float(np.corrcoef(data1["values"], interp_values2)[0, 1])

    result = {
        "topic1": {"topic": topic1, "field": field1, "count": len(data1["values"])},
        "topic2": {"topic": topic2, "field": field2, "count": len(data2["values"])},
        "comparison": {
            "correlation": round(correlation, 4) if not np.isnan(correlation) else None,
            "difference": {
                "mean": round(float(np.mean(differences)), 4),
                "std": round(float(np.std(differences)), 4),
                "min": round(float(np.min(differences)), 4),
                "max": round(float(np.max(differences)), 4),
                "rmse": round(float(np.sqrt(np.mean(differences**2))), 4),
            },
            "topic1_stats": {
                "mean": round(float(np.mean(data1["values"])), 4),
                "std": round(float(np.std(data1["values"])), 4),
                "min": round(float(np.min(data1["values"])), 4),
                "max": round(float(np.max(data1["values"])), 4),
            },
            "topic2_stats": {
                "mean": round(float(np.mean(data2["values"])), 4),
                "std": round(float(np.std(data2["values"])), 4),
                "min": round(float(np.min(data2["values"])), 4),
                "max": round(float(np.max(data2["values"])), 4),
            },
        },
    }

    logger.debug("Topic comparison complete")
    return [TextContent(type="text", text=json_serialize(result))]


async def export_to_csv(
    topic: str,
    output_path: str,
    fields: list[str] | None = None,
    start_time: float | None = None,
    end_time: float | None = None,
    max_messages: int = 10000,
    bag_path: str | None = None,
) -> list[TextContent]:
    """Export topic message data to a CSV file."""
    logger.info(f"Exporting topic {topic} to CSV: {output_path}")
    messages = []
    all_fields: set[str] = set()

    for msg in read_messages(
        bag_path=bag_path, topics=[topic], start_time=start_time, end_time=end_time
    ):
        if len(messages) >= max_messages:
            break

        row = {"timestamp": msg.timestamp}

        if fields:
            for field in fields:
                value = get_nested_field(msg.data, field)
                row[field] = value
                all_fields.add(field)
        else:
            _flatten_dict(msg.data, "", row, all_fields)

        messages.append(row)

    if not messages:
        logger.warning(f"No messages found in topic {topic}")
        return [TextContent(type="text", text="No messages found")]

    fieldnames = ["timestamp"] + sorted(all_fields)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(messages)

    logger.info(f"CSV export complete: {len(messages)} messages, {len(fieldnames)} fields")
    return [
        TextContent(
            type="text",
            text=f"Exported {len(messages)} messages to {output_path}\n"
            f"Fields: {', '.join(fieldnames)}",
        )
    ]


def _flatten_dict(data: dict, prefix: str, row: dict, all_fields: set, max_depth: int = 4) -> None:
    if max_depth <= 0:
        return

    for key, value in data.items():
        field_name = f"{prefix}.{key}" if prefix else key

        if isinstance(value, dict):
            _flatten_dict(value, field_name, row, all_fields, max_depth - 1)
        elif isinstance(value, (int, float, str, bool)) or value is None:
            row[field_name] = value
            all_fields.add(field_name)
        elif isinstance(value, list) and len(value) <= 10:
            for i, item in enumerate(value):
                if isinstance(item, (int, float, str, bool)):
                    item_field = f"{field_name}.{i}"
                    row[item_field] = item
                    all_fields.add(item_field)
