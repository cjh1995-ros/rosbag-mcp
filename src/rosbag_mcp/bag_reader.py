from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from rosbags.highlevel import AnyReader


@dataclass
class BagInfo:
    path: str
    duration: float
    start_time: float
    end_time: float
    message_count: int
    topics: list[dict[str, Any]]


@dataclass
class BagMessage:
    topic: str
    timestamp: float
    data: dict[str, Any]
    msg_type: str


class BagReaderState:
    current_bag_path: str | None = None
    current_bags_dir: str | None = None


_state = BagReaderState()


def set_bag_path(path: str) -> str:
    path = os.path.expanduser(path)
    if os.path.isfile(path):
        _state.current_bag_path = path
        _state.current_bags_dir = os.path.dirname(path)
        return f"Set bag path to: {path}"
    elif os.path.isdir(path):
        _state.current_bags_dir = path
        _state.current_bag_path = None
        return f"Set bags directory to: {path}"
    else:
        raise FileNotFoundError(f"Path not found: {path}")


def get_current_bag_path() -> str | None:
    return _state.current_bag_path


def get_current_bags_dir() -> str | None:
    return _state.current_bags_dir


def list_bags(directory: str | None = None) -> list[dict[str, Any]]:
    search_dir = directory or _state.current_bags_dir
    if not search_dir:
        raise ValueError("No directory set. Call set_bag_path first or provide a directory.")

    search_dir = os.path.expanduser(search_dir)
    bags = []

    for root, dirs, files in os.walk(search_dir):
        for f in files:
            if f.endswith((".bag", ".mcap", ".db3")):
                full_path = os.path.join(root, f)
                bags.append(
                    {
                        "path": full_path,
                        "name": f,
                        "format": Path(f).suffix[1:],
                        "size_mb": round(os.path.getsize(full_path) / (1024 * 1024), 2),
                    }
                )

        if "metadata.yaml" in files:
            bags.append(
                {
                    "path": root,
                    "name": os.path.basename(root),
                    "format": "ros2_directory",
                    "size_mb": sum(os.path.getsize(os.path.join(root, f)) for f in files)
                    / (1024 * 1024),
                }
            )
            dirs.clear()

    return bags


def get_bag_info(bag_path: str | None = None) -> BagInfo:
    path = bag_path or _state.current_bag_path
    if not path:
        raise ValueError("No bag path set. Call set_bag_path first or provide a bag_path.")

    path = os.path.expanduser(path)

    with AnyReader([Path(path)]) as reader:
        topics = []
        for conn in reader.connections:
            topics.append(
                {
                    "name": conn.topic,
                    "type": conn.msgtype,
                    "count": conn.msgcount,
                }
            )

        duration = (reader.end_time - reader.start_time) / 1e9
        start_time = reader.start_time / 1e9
        end_time = reader.end_time / 1e9
        message_count = sum(c.msgcount for c in reader.connections)

        return BagInfo(
            path=path,
            duration=duration,
            start_time=start_time,
            end_time=end_time,
            message_count=message_count,
            topics=topics,
        )


def _msg_to_dict(msg: Any) -> Any:
    if hasattr(msg, "__dataclass_fields__"):
        result = {}
        for field_name in msg.__dataclass_fields__:
            value = getattr(msg, field_name)
            result[field_name] = _msg_to_dict(value)
        return result
    elif isinstance(msg, (list, tuple)):
        return [_msg_to_dict(item) for item in msg]
    elif hasattr(msg, "tolist"):
        return msg.tolist()
    else:
        return msg


def read_messages(
    bag_path: str | None = None,
    topics: list[str] | None = None,
    start_time: float | None = None,
    end_time: float | None = None,
) -> Iterator[BagMessage]:
    path = bag_path or _state.current_bag_path
    if not path:
        raise ValueError("No bag path set. Call set_bag_path first or provide a bag_path.")

    path = os.path.expanduser(path)

    with AnyReader([Path(path)]) as reader:
        connections = reader.connections
        if topics:
            connections = [c for c in connections if c.topic in topics]

        start_ns = int(start_time * 1e9) if start_time else None
        end_ns = int(end_time * 1e9) if end_time else None

        for conn, timestamp, rawdata in reader.messages(connections=connections):
            ts_sec = timestamp / 1e9

            if start_ns and timestamp < start_ns:
                continue
            if end_ns and timestamp > end_ns:
                break

            msg = reader.deserialize(rawdata, conn.msgtype)
            yield BagMessage(
                topic=conn.topic, timestamp=ts_sec, data=_msg_to_dict(msg), msg_type=conn.msgtype
            )


def get_message_at_time(
    topic: str, target_time: float, bag_path: str | None = None, tolerance: float = 0.1
) -> BagMessage | None:
    path = bag_path or _state.current_bag_path
    if not path:
        raise ValueError("No bag path set. Call set_bag_path first or provide a bag_path.")

    path = os.path.expanduser(path)
    closest_msg = None
    min_diff = float("inf")

    with AnyReader([Path(path)]) as reader:
        connections = [c for c in reader.connections if c.topic == topic]
        if not connections:
            return None

        for conn, timestamp, rawdata in reader.messages(connections=connections):
            ts_sec = timestamp / 1e9
            diff = abs(ts_sec - target_time)

            if diff < min_diff:
                min_diff = diff
                msg = reader.deserialize(rawdata, conn.msgtype)
                closest_msg = BagMessage(
                    topic=conn.topic,
                    timestamp=ts_sec,
                    data=_msg_to_dict(msg),
                    msg_type=conn.msgtype,
                )

            if ts_sec > target_time + tolerance:
                break

    if closest_msg and min_diff <= tolerance:
        return closest_msg
    return closest_msg


def get_messages_in_range(
    topic: str,
    start_time: float,
    end_time: float,
    bag_path: str | None = None,
    max_messages: int = 100,
) -> list[BagMessage]:
    messages = []
    for msg in read_messages(
        bag_path=bag_path, topics=[topic], start_time=start_time, end_time=end_time
    ):
        messages.append(msg)
        if len(messages) >= max_messages:
            break
    return messages


def get_topic_schema(topic: str, bag_path: str | None = None) -> dict[str, Any]:
    """Get the message structure/schema for a topic by sampling a message."""
    path = bag_path or _state.current_bag_path
    if not path:
        raise ValueError("No bag path set. Call set_bag_path first or provide a bag_path.")

    path = os.path.expanduser(path)

    with AnyReader([Path(path)]) as reader:
        connections = [c for c in reader.connections if c.topic == topic]
        if not connections:
            raise ValueError(f"Topic '{topic}' not found in bag")

        conn = connections[0]
        msg_type = conn.msgtype

        sample_data = None
        for conn_iter, timestamp, rawdata in reader.messages(connections=connections):
            msg = reader.deserialize(rawdata, conn_iter.msgtype)
            sample_data = _msg_to_dict(msg)
            break

        def _extract_schema(data: Any, depth: int = 0) -> dict[str, Any]:
            if isinstance(data, dict):
                return {
                    "type": "object",
                    "fields": {k: _extract_schema(v, depth + 1) for k, v in data.items()},
                }
            elif isinstance(data, list):
                if len(data) > 0:
                    return {
                        "type": "array",
                        "length": len(data),
                        "element_type": _extract_schema(data[0], depth + 1),
                    }
                return {"type": "array", "length": 0, "element_type": "unknown"}
            elif isinstance(data, float):
                return {"type": "float64"}
            elif isinstance(data, int):
                return {"type": "int"}
            elif isinstance(data, bool):
                return {"type": "bool"}
            elif isinstance(data, str):
                return {"type": "string"}
            else:
                return {"type": str(type(data).__name__)}

        schema = _extract_schema(sample_data) if sample_data else {}

        return {
            "topic": topic,
            "msg_type": msg_type,
            "message_count": conn.msgcount,
            "schema": schema,
            "sample_data": sample_data,
        }


def get_topic_timestamps(topic: str, bag_path: str | None = None) -> list[float]:
    """Get all timestamps for a topic (for statistics)."""
    path = bag_path or _state.current_bag_path
    if not path:
        raise ValueError("No bag path set. Call set_bag_path first or provide a bag_path.")

    path = os.path.expanduser(path)
    timestamps = []

    with AnyReader([Path(path)]) as reader:
        connections = [c for c in reader.connections if c.topic == topic]
        if not connections:
            return []

        for conn, timestamp, rawdata in reader.messages(connections=connections):
            timestamps.append(timestamp / 1e9)

    return timestamps
