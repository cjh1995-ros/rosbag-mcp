from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from rosbag_mcp.cache import BagCacheManager, TopicTimeIndex

logger = logging.getLogger(__name__)


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
_cache = BagCacheManager()


def _resolve_path(bag_path: str | None) -> str:
    """Resolve bag path from argument or state."""
    path = bag_path or _state.current_bag_path
    if not path:
        raise ValueError("No bag path set. Call set_bag_path first or provide a bag_path.")
    return os.path.expanduser(path)


def set_bag_path(path: str) -> str:
    path = os.path.expanduser(path)
    if os.path.isfile(path):
        _state.current_bag_path = path
        _state.current_bags_dir = os.path.dirname(path)
        logger.info(f"Set bag path to: {path}")
        return f"Set bag path to: {path}"
    elif os.path.isdir(path):
        _state.current_bags_dir = path
        _state.current_bag_path = None
        logger.info(f"Set bags directory to: {path}")
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
    path = _resolve_path(bag_path)
    handle = _cache.get_handle(path)

    # Check cache first
    cached_info = handle.meta.get("bag_info")
    if cached_info is not None:
        logger.debug(f"Cache hit: bag_info for {path}")
        return cached_info

    # Cache miss - compute and store
    logger.debug(f"Cache miss: bag_info for {path}")
    with handle.reader_ctx() as reader:
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

        bag_info = BagInfo(
            path=path,
            duration=duration,
            start_time=start_time,
            end_time=end_time,
            message_count=message_count,
            topics=topics,
        )

        # Cache the result
        handle.meta["bag_info"] = bag_info
        return bag_info


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
    path = _resolve_path(bag_path)
    handle = _cache.get_handle(path)

    single_topic = topics is not None and len(topics) == 1
    start_ns = int(start_time * 1e9) if start_time else None
    end_ns = int(end_time * 1e9) if end_time else None

    # --- Fast path: serve from message cache ---
    if single_topic and handle.message_cache.has(topics[0]):
        cached = handle.message_cache.get_range(topics[0], start_ns, end_ns)
        if cached is not None:
            logger.debug("Message cache hit: %s (%d messages)", topics[0], len(cached))
            yield from cached
            return

    # --- Slow path: read from disk ---
    no_time_filter = start_time is None and end_time is None
    build_index = single_topic and no_time_filter
    topic_for_index = topics[0] if build_index else None
    timestamps_ns: list[int] | None = [] if build_index else None

    should_collect = single_topic and no_time_filter and not handle.message_cache.has(topics[0])
    collected: list[BagMessage] | None = [] if should_collect else None
    collected_bytes = 0
    completed = False

    with handle.reader_ctx() as reader:
        connections = reader.connections
        if topics:
            connections = [c for c in connections if c.topic in topics]

        try:
            for conn, timestamp, rawdata in reader.messages(connections=connections):
                ts_sec = timestamp / 1e9

                if start_ns and timestamp < start_ns:
                    continue
                if end_ns and timestamp > end_ns:
                    break

                if build_index and timestamps_ns is not None:
                    timestamps_ns.append(timestamp)

                # Size gate: check first message raw payload
                if collected is not None and collected_bytes == 0:
                    msg_count = conn.msgcount or 0
                    if not handle.message_cache.can_cache(len(rawdata), msg_count):
                        logger.debug(
                            "Skipping message cache for %s (raw=%d bytes, count=%d)",
                            conn.topic,
                            len(rawdata),
                            msg_count,
                        )
                        collected = None

                msg = reader.deserialize(rawdata, conn.msgtype)
                bag_msg = BagMessage(
                    topic=conn.topic,
                    timestamp=ts_sec,
                    data=_msg_to_dict(msg),
                    msg_type=conn.msgtype,
                )

                if collected is not None:
                    collected.append(bag_msg)
                    collected_bytes += len(rawdata) + 200
                    if not handle.message_cache.budget_ok(collected_bytes):
                        logger.debug(
                            "Aborting message cache for %s (budget exceeded at %d bytes)",
                            conn.topic,
                            collected_bytes,
                        )
                        collected = None
                        collected_bytes = 0

                yield bag_msg
            completed = True
        finally:
            if build_index and topic_for_index and timestamps_ns:
                index = TopicTimeIndex(timestamps_ns=timestamps_ns)
                handle.store_index(topic_for_index, index)

            if completed and collected is not None and collected:
                handle.message_cache.commit(topics[0], collected, collected_bytes)


def get_message_at_time(
    topic: str, target_time: float, bag_path: str | None = None, tolerance: float = 0.1
) -> BagMessage | None:
    path = _resolve_path(bag_path)
    handle = _cache.get_handle(path)

    # Try to use cached index for fast lookup
    index = handle.get_or_build_index(topic)
    target_ns = int(target_time * 1e9)
    tolerance_ns = int(tolerance * 1e9)

    if index is not None:
        # Fast path: use index to find nearest timestamp
        nearest_ts = index.find_nearest(target_ns, tolerance_ns)
        if nearest_ts is None:
            logger.debug(f"Index lookup: no message within tolerance for {topic} at {target_time}")
            return None

        # Scan near the indexed timestamp
        logger.debug(f"Index hit: {topic} at {target_time} -> {nearest_ts / 1e9}")
        with handle.reader_ctx() as reader:
            connections = [c for c in reader.connections if c.topic == topic]
            if not connections:
                return None

            # Scan a small window around the indexed timestamp
            window_start = nearest_ts - tolerance_ns
            window_end = nearest_ts + tolerance_ns

            closest_msg = None
            min_diff = float("inf")

            for conn, timestamp, rawdata in reader.messages(connections=connections):
                if timestamp < window_start:
                    continue
                if timestamp > window_end:
                    break

                diff = abs(timestamp - target_ns)
                if diff < min_diff:
                    min_diff = diff
                    msg = reader.deserialize(rawdata, conn.msgtype)
                    closest_msg = BagMessage(
                        topic=conn.topic,
                        timestamp=timestamp / 1e9,
                        data=_msg_to_dict(msg),
                        msg_type=conn.msgtype,
                    )

            return closest_msg if closest_msg and min_diff <= tolerance_ns else None

    # Slow path: full scan (no index available)
    logger.debug(f"Index miss: full scan for {topic} at {target_time}")
    with handle.reader_ctx() as reader:
        connections = [c for c in reader.connections if c.topic == topic]
        if not connections:
            return None

        closest_msg = None
        min_diff = float("inf")

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
    path = _resolve_path(bag_path)
    handle = _cache.get_handle(path)

    # Check cache first
    cache_key = f"schema:{topic}"
    cached_schema = handle.meta.get(cache_key)
    if cached_schema is not None:
        logger.debug(f"Cache hit: schema for {topic}")
        return cached_schema

    # Cache miss - compute and store
    logger.debug(f"Cache miss: schema for {topic}")
    with handle.reader_ctx() as reader:
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

        result = {
            "topic": topic,
            "msg_type": msg_type,
            "message_count": conn.msgcount,
            "schema": schema,
            "sample_data": sample_data,
        }

        # Cache the result
        handle.meta[cache_key] = result
        return result


def get_topic_timestamps(topic: str, bag_path: str | None = None) -> list[float]:
    """Get all timestamps for a topic (for statistics)."""
    path = _resolve_path(bag_path)
    handle = _cache.get_handle(path)

    # Check if we have a cached index
    index = handle.get_or_build_index(topic)
    if index is not None:
        logger.debug(f"Index hit: returning {len(index.timestamps_ns)} timestamps for {topic}")
        return [t / 1e9 for t in index.timestamps_ns]

    # No index - build one during scan
    logger.debug(f"Index miss: building timestamps for {topic}")
    timestamps = []
    timestamps_ns = []

    with handle.reader_ctx() as reader:
        connections = [c for c in reader.connections if c.topic == topic]
        if not connections:
            return []

        for conn, timestamp, rawdata in reader.messages(connections=connections):
            timestamps.append(timestamp / 1e9)
            timestamps_ns.append(timestamp)

        # Store index for future use
        if timestamps_ns:
            index = TopicTimeIndex(timestamps_ns=timestamps_ns)
            handle.store_index(topic, index)
            logger.debug(f"Built and cached index for {topic}: {len(timestamps_ns)} timestamps")

        return timestamps
