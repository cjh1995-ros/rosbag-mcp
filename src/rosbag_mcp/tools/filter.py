from __future__ import annotations

from pathlib import Path

from mcp.types import TextContent
from rosbags.highlevel import AnyReader
from rosbags.rosbag1 import Writer as Ros1Writer
from rosbags.rosbag2 import Writer as Ros2Writer

from rosbag_mcp.bag_reader import get_current_bag_path


async def filter_bag(
    output_path: str,
    topics: list[str],
    start_time: float | None = None,
    end_time: float | None = None,
    bag_path: str | None = None,
) -> list[TextContent]:
    output_ext = Path(output_path).suffix
    message_count = 0
    source_path = bag_path or get_current_bag_path()

    with AnyReader([Path(source_path)]) as reader:
        if output_ext == ".bag":
            with Ros1Writer(Path(output_path)) as writer:
                connections = {}
                for conn in reader.connections:
                    if conn.topic in topics:
                        connections[conn.topic] = writer.add_connection(conn.topic, conn.msgtype)

                for conn, timestamp, rawdata in reader.messages():
                    if conn.topic not in topics:
                        continue
                    ts_sec = timestamp / 1e9
                    if start_time and ts_sec < start_time:
                        continue
                    if end_time and ts_sec > end_time:
                        continue

                    writer.write(connections[conn.topic], timestamp, rawdata)
                    message_count += 1
        else:
            Path(output_path).mkdir(parents=True, exist_ok=True)
            with Ros2Writer(Path(output_path)) as writer:
                connections = {}
                for conn in reader.connections:
                    if conn.topic in topics:
                        connections[conn.topic] = writer.add_connection(conn.topic, conn.msgtype)

                for conn, timestamp, rawdata in reader.messages():
                    if conn.topic not in topics:
                        continue
                    ts_sec = timestamp / 1e9
                    if start_time and ts_sec < start_time:
                        continue
                    if end_time and ts_sec > end_time:
                        continue

                    writer.write(connections[conn.topic], timestamp, rawdata)
                    message_count += 1

    return [
        TextContent(
            type="text",
            text=f"Created filtered bag at {output_path} with {message_count} messages from topics: {topics}",
        )
    ]
