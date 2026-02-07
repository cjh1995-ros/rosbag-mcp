from __future__ import annotations

import logging
from pathlib import Path

from mcp.types import TextContent
from rosbags.highlevel import AnyReader
from rosbags.rosbag1 import Writer as Ros1Writer
from rosbags.rosbag2 import Writer as Ros2Writer

from rosbag_mcp.bag_reader import get_current_bag_path

logger = logging.getLogger(__name__)


def _write_filtered(
    writer: Ros1Writer | Ros2Writer,
    reader: AnyReader,
    topics: list[str],
    start_time: float | None,
    end_time: float | None,
) -> int:
    """Copy matching messages from reader to writer. Returns message count."""
    topic_set = set(topics)
    connections = {}
    for conn in reader.connections:
        if conn.topic in topic_set:
            connections[conn.topic] = writer.add_connection(conn.topic, conn.msgtype)

    count = 0
    for conn, timestamp, rawdata in reader.messages():
        if conn.topic not in topic_set:
            continue
        ts_sec = timestamp / 1e9
        if start_time and ts_sec < start_time:
            continue
        if end_time and ts_sec > end_time:
            continue
        writer.write(connections[conn.topic], timestamp, rawdata)
        count += 1
    return count


async def filter_bag(
    output_path: str,
    topics: list[str],
    start_time: float | None = None,
    end_time: float | None = None,
    bag_path: str | None = None,
) -> list[TextContent]:
    """Create a filtered copy of a bag file by topic and time range."""
    logger.info(f"Filtering bag to {output_path} with topics: {topics}")
    output_ext = Path(output_path).suffix
    source_path = bag_path or get_current_bag_path()
    logger.debug(f"Source bag: {source_path}, output format: {output_ext}")

    with AnyReader([Path(source_path)]) as reader:
        if output_ext == ".bag":
            with Ros1Writer(Path(output_path)) as writer:
                message_count = _write_filtered(writer, reader, topics, start_time, end_time)
        else:
            Path(output_path).mkdir(parents=True, exist_ok=True)
            with Ros2Writer(Path(output_path)) as writer:
                message_count = _write_filtered(writer, reader, topics, start_time, end_time)

    logger.info(f"Filtered bag created: {message_count} messages written to {output_path}")
    return [
        TextContent(
            type="text",
            text=f"Created filtered bag at {output_path} "
            f"with {message_count} messages from topics: {topics}",
        )
    ]
