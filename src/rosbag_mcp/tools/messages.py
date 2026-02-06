from __future__ import annotations

import math
import re
from dataclasses import asdict

from mcp.types import TextContent

from rosbag_mcp.bag_reader import (
    get_message_at_time as _get_message_at_time,
)
from rosbag_mcp.bag_reader import (
    get_messages_in_range as _get_messages_in_range,
)
from rosbag_mcp.bag_reader import (
    read_messages,
)
from rosbag_mcp.tools.utils import extract_position, get_nested_field, json_serialize


async def get_message_at_time(
    topic: str,
    timestamp: float,
    bag_path: str | None = None,
    tolerance: float = 0.1,
) -> list[TextContent]:
    msg = _get_message_at_time(
        topic=topic,
        target_time=timestamp,
        bag_path=bag_path,
        tolerance=tolerance,
    )
    if msg:
        return [TextContent(type="text", text=json_serialize(asdict(msg)))]
    return [TextContent(type="text", text="No message found at specified time")]


async def get_messages_in_range(
    topic: str,
    start_time: float,
    end_time: float,
    bag_path: str | None = None,
    max_messages: int = 100,
) -> list[TextContent]:
    msgs = _get_messages_in_range(
        topic=topic,
        start_time=start_time,
        end_time=end_time,
        bag_path=bag_path,
        max_messages=max_messages,
    )
    return [TextContent(type="text", text=json_serialize([asdict(m) for m in msgs]))]


async def search_messages(
    topic: str,
    condition_type: str,
    value: str,
    field: str | None = None,
    limit: int = 10,
    bag_path: str | None = None,
) -> list[TextContent]:
    results = []

    for msg in read_messages(bag_path=bag_path, topics=[topic]):
        if len(results) >= limit:
            break

        match = False

        if condition_type == "near_position":
            parts = value.split(",")
            target_x, target_y, radius = float(parts[0]), float(parts[1]), float(parts[2])
            pos = extract_position(msg.data)
            if pos:
                dist = math.sqrt((pos[0] - target_x) ** 2 + (pos[1] - target_y) ** 2)
                if dist <= radius:
                    match = True
                    results.append(
                        {
                            "timestamp": msg.timestamp,
                            "position": {"x": pos[0], "y": pos[1], "z": pos[2]},
                            "distance_to_target": round(dist, 4),
                        }
                    )
        else:
            field_value = get_nested_field(msg.data, field) if field else msg.data

            if condition_type == "regex":
                if field_value and re.search(value, str(field_value)):
                    match = True
            elif condition_type == "equals":
                if str(field_value) == value:
                    match = True
            elif condition_type == "greater_than":
                if field_value is not None and float(field_value) > float(value):
                    match = True
            elif condition_type == "less_than":
                if field_value is not None and float(field_value) < float(value):
                    match = True

            if match and condition_type != "near_position":
                results.append(
                    {
                        "timestamp": msg.timestamp,
                        "value": field_value,
                        "data": msg.data,
                    }
                )

    return [TextContent(type="text", text=json_serialize(results))]
