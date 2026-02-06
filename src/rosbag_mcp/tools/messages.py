from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


async def get_message_at_time(
    topic: str,
    timestamp: float,
    bag_path: str | None = None,
    tolerance: float = 0.1,
) -> list[TextContent]:
    logger.info(f"Getting message from topic {topic} at timestamp {timestamp}")
    msg = _get_message_at_time(
        topic=topic,
        target_time=timestamp,
        bag_path=bag_path,
        tolerance=tolerance,
    )
    if msg:
        logger.debug(f"Message found at {msg.timestamp}")
        return [TextContent(type="text", text=json_serialize(asdict(msg)))]
    logger.debug(f"No message found for topic {topic} at timestamp {timestamp}")
    return [TextContent(type="text", text="No message found at specified time")]


async def get_messages_in_range(
    topic: str,
    start_time: float,
    end_time: float,
    bag_path: str | None = None,
    max_messages: int = 100,
) -> list[TextContent]:
    logger.info(f"Getting messages from topic {topic} in range [{start_time}, {end_time}]")
    msgs = _get_messages_in_range(
        topic=topic,
        start_time=start_time,
        end_time=end_time,
        bag_path=bag_path,
        max_messages=max_messages,
    )
    logger.debug(f"Retrieved {len(msgs)} messages from {topic}")
    return [TextContent(type="text", text=json_serialize([asdict(m) for m in msgs]))]


async def search_messages(
    topic: str,
    condition_type: str,
    value: str,
    field: str | None = None,
    limit: int = 10,
    bag_path: str | None = None,
    correlate_topic: str | None = None,
    correlation_tolerance: float = 0.1,
) -> list[TextContent]:
    logger.info(f"Searching messages in topic {topic} with condition {condition_type}")
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
                    result_entry = {
                        "timestamp": msg.timestamp,
                        "position": {"x": pos[0], "y": pos[1], "z": pos[2]},
                        "distance_to_target": round(dist, 4),
                    }

                    # Add correlated message if requested
                    if correlate_topic:
                        correlated_msg = _get_message_at_time(
                            correlate_topic,
                            msg.timestamp,
                            bag_path,
                            tolerance=correlation_tolerance,
                        )
                        result_entry["correlated"] = correlated_msg.data if correlated_msg else None

                    results.append(result_entry)
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
            elif condition_type == "contains":
                # Check if field value contains the substring (case-insensitive)
                if field_value and value.lower() in str(field_value).lower():
                    match = True
            elif condition_type == "field_exists":
                # Check if the field path exists and is not None
                if field_value is not None:
                    match = True

            if match and condition_type != "near_position":
                result_entry = {
                    "timestamp": msg.timestamp,
                    "value": field_value,
                    "data": msg.data,
                }

                # Add correlated message if requested
                if correlate_topic:
                    correlated_msg = _get_message_at_time(
                        correlate_topic, msg.timestamp, bag_path, tolerance=correlation_tolerance
                    )
                    result_entry["correlated"] = correlated_msg.data if correlated_msg else None

                results.append(result_entry)

    logger.debug(f"Search completed: found {len(results)} matching messages")
    return [TextContent(type="text", text=json_serialize(results))]
