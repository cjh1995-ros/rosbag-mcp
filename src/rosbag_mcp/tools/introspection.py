"""ROS system inspection tools: logs and TF tree."""

from __future__ import annotations

import logging
import re

from mcp.types import TextContent

from rosbag_mcp.bag_reader import read_messages
from rosbag_mcp.tools.utils import json_serialize

logger = logging.getLogger(__name__)


async def analyze_logs(
    log_topic: str = "/rosout",
    level: str | None = None,
    node_filter: str | None = None,
    limit: int = 50,
    bag_path: str | None = None,
) -> list[TextContent]:
    """Parse and filter ROS log messages by level or node."""
    level_map = {"DEBUG": 1, "INFO": 2, "WARN": 4, "ERROR": 8, "FATAL": 16}
    level_names = {1: "DEBUG", 2: "INFO", 4: "WARN", 8: "ERROR", 16: "FATAL"}

    logs = []
    msg_count = 0

    for msg in read_messages(bag_path=bag_path, topics=[log_topic]):
        if len(logs) >= limit:
            break

        msg_count += 1
        data = msg.data

        # Handle level: try multiple field names, handle both int and string types
        msg_level = data.get("level", data.get("severity", 0))
        if isinstance(msg_level, str):
            msg_level = level_map.get(msg_level.upper(), 0)

        # Handle node name: try multiple field names
        msg_name = data.get("name", data.get("node_name", ""))

        if level and level_map.get(level, 0) != msg_level:
            continue

        if node_filter and not re.search(node_filter, msg_name):
            continue

        # Handle message text: try multiple field names
        msg_text = data.get("msg", data.get("message", ""))

        # Handle file/line: try multiple field names
        msg_file = data.get("file", data.get("filename", ""))
        msg_line = data.get("line", data.get("lineno", 0))

        # If all key fields are empty, dump available fields as fallback
        if not msg_text and not msg_name:
            available_keys = list(data.keys())
            msg_text = f"[raw fields: {', '.join(available_keys)}]"

        logs.append(
            {
                "timestamp": msg.timestamp,
                "level": level_names.get(msg_level, str(msg_level)),
                "node": msg_name,
                "message": msg_text,
                "file": msg_file,
                "line": msg_line,
            }
        )

    if not logs and msg_count == 0:
        from rosbag_mcp.bag_reader import get_bag_info

        try:
            info = get_bag_info(bag_path)
            available = [t["name"] for t in info.topics]
            log_topics = [t for t in available if "rosout" in t.lower() or "log" in t.lower()]
            hint = f"No messages found on '{log_topic}'."
            if log_topics:
                hint += f" Available log-like topics: {', '.join(log_topics)}"
            else:
                hint += f" Available topics: {', '.join(available[:20])}"
            return [TextContent(type="text", text=hint)]
        except Exception:
            pass

    return [TextContent(type="text", text=json_serialize(logs))]


async def get_tf_tree(bag_path: str | None = None) -> list[TextContent]:
    """Build the TF coordinate frame tree from transform messages."""
    transforms: dict[str, set] = {}

    for msg in read_messages(bag_path=bag_path, topics=["/tf", "/tf_static"]):
        data = msg.data
        tf_list = data.get("transforms", [])

        for tf in tf_list:
            header = tf.get("header", {})
            parent = header.get("frame_id", "")
            child = tf.get("child_frame_id", "")

            if parent and child:
                if parent not in transforms:
                    transforms[parent] = set()
                transforms[parent].add(child)

    def build_tree(frame: str, visited: set) -> dict:
        if frame in visited:
            return {"frame": frame, "note": "circular reference"}
        visited.add(frame)
        children = []
        for child in transforms.get(frame, []):
            children.append(build_tree(child, visited.copy()))
        result = {"frame": frame}
        if children:
            result["children"] = children
        return result

    all_children: set = set()
    for children in transforms.values():
        all_children.update(children)

    roots = set(transforms.keys()) - all_children
    if not roots:
        roots = set(transforms.keys())

    tree = [build_tree(root, set()) for root in roots]
    frames_list = list(set(transforms.keys()) | all_children)

    result = {
        "frames": frames_list,
        "frame_count": len(frames_list),
        "tree": tree,
        "relationships": {k: list(v) for k, v in transforms.items()},
    }

    return [TextContent(type="text", text=json_serialize(result))]
