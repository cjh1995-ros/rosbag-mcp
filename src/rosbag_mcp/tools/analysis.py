from __future__ import annotations

import base64
import io
import math
import re

import numpy as np
from mcp.types import TextContent, ImageContent

from rosbag_mcp.bag_reader import (
    get_message_at_time as _get_message_at_time,
    read_messages,
)
from rosbag_mcp.tools.utils import json_serialize, extract_position, extract_velocity


async def analyze_trajectory(
    pose_topic: str = "/odom",
    start_time: float | None = None,
    end_time: float | None = None,
    include_waypoints: bool = False,
    bag_path: str | None = None,
) -> list[TextContent]:
    positions = []
    velocities = []
    timestamps = []

    for msg in read_messages(
        bag_path=bag_path, topics=[pose_topic], start_time=start_time, end_time=end_time
    ):
        pos = extract_position(msg.data)
        vel = extract_velocity(msg.data)

        if pos:
            positions.append(pos)
            timestamps.append(msg.timestamp)
        if vel:
            velocities.append(vel)

    if not positions:
        return [TextContent(type="text", text="No position data found")]

    total_distance = 0.0
    for i in range(1, len(positions)):
        dx = positions[i][0] - positions[i - 1][0]
        dy = positions[i][1] - positions[i - 1][1]
        total_distance += math.sqrt(dx * dx + dy * dy)

    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]

    linear_speeds = [abs(v[0]) for v in velocities] if velocities else []
    angular_speeds = [abs(v[1]) for v in velocities] if velocities else []

    result = {
        "total_distance_m": round(total_distance, 3),
        "duration_s": round(timestamps[-1] - timestamps[0], 3) if len(timestamps) > 1 else 0,
        "x_range": {"min": round(min(xs), 3), "max": round(max(xs), 3)},
        "y_range": {"min": round(min(ys), 3), "max": round(max(ys), 3)},
        "position_count": len(positions),
    }

    if linear_speeds:
        result["linear_speed"] = {
            "mean": round(float(np.mean(linear_speeds)), 3),
            "max": round(max(linear_speeds), 3),
            "min": round(min(linear_speeds), 3),
        }

    if angular_speeds:
        result["angular_speed"] = {
            "mean": round(float(np.mean(angular_speeds)), 3),
            "max": round(max(angular_speeds), 3),
            "min": round(min(angular_speeds), 3),
        }

    if include_waypoints:
        step = max(1, len(positions) // 10)
        result["waypoints"] = [
            {
                "x": round(p[0], 3),
                "y": round(p[1], 3),
                "z": round(p[2], 3),
                "time": round(timestamps[i * step], 3),
            }
            for i, p in enumerate(positions[::step])
        ]

    return [TextContent(type="text", text=json_serialize(result))]


async def analyze_lidar_scan(
    scan_topic: str = "/scan",
    timestamp: float | None = None,
    obstacle_threshold: float = 1.0,
    bag_path: str | None = None,
) -> list[TextContent]:
    scan_msg = None

    if timestamp:
        scan_msg = _get_message_at_time(scan_topic, timestamp, bag_path, tolerance=0.5)
    else:
        for msg in read_messages(bag_path=bag_path, topics=[scan_topic]):
            scan_msg = msg
            break

    if not scan_msg:
        return [TextContent(type="text", text="No LiDAR scan found")]

    data = scan_msg.data
    ranges = data.get("ranges", [])

    if not ranges:
        return [TextContent(type="text", text="No range data in scan")]

    ranges_arr = np.array(ranges)
    valid_ranges = ranges_arr[np.isfinite(ranges_arr) & (ranges_arr > 0)]
    obstacles = valid_ranges[valid_ranges < obstacle_threshold]

    result = {
        "timestamp": scan_msg.timestamp,
        "angle_min": data.get("angle_min"),
        "angle_max": data.get("angle_max"),
        "angle_increment": data.get("angle_increment"),
        "range_min": data.get("range_min"),
        "range_max": data.get("range_max"),
        "total_rays": len(ranges),
        "valid_rays": len(valid_ranges),
        "statistics": {
            "min_distance": round(float(np.min(valid_ranges)), 3)
            if len(valid_ranges) > 0
            else None,
            "max_distance": round(float(np.max(valid_ranges)), 3)
            if len(valid_ranges) > 0
            else None,
            "mean_distance": round(float(np.mean(valid_ranges)), 3)
            if len(valid_ranges) > 0
            else None,
        },
        "obstacles": {
            "threshold_m": obstacle_threshold,
            "count": len(obstacles),
            "closest_distance": round(float(np.min(obstacles)), 3) if len(obstacles) > 0 else None,
        },
    }

    return [TextContent(type="text", text=json_serialize(result))]


async def analyze_logs(
    log_topic: str = "/rosout",
    level: str | None = None,
    node_filter: str | None = None,
    limit: int = 50,
    bag_path: str | None = None,
) -> list[TextContent]:
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


async def get_image_at_time(
    image_topic: str,
    timestamp: float,
    bag_path: str | None = None,
) -> list[TextContent | ImageContent]:
    from PIL import Image

    img_msg = _get_message_at_time(image_topic, timestamp, bag_path, tolerance=0.5)

    if not img_msg:
        return [TextContent(type="text", text="No image found at specified time")]

    data = img_msg.data
    width = data.get("width", 0)
    height = data.get("height", 0)
    encoding = data.get("encoding", "rgb8")
    img_data = data.get("data", [])

    if not img_data:
        return [TextContent(type="text", text="Image data is empty")]

    if isinstance(img_data, list):
        img_data = bytes(img_data)

    if encoding in ["rgb8", "bgr8"]:
        if encoding == "bgr8":
            img_arr = np.frombuffer(img_data, dtype=np.uint8).reshape((height, width, 3))
            img_arr = img_arr[:, :, ::-1]
        else:
            img_arr = np.frombuffer(img_data, dtype=np.uint8).reshape((height, width, 3))
        img = Image.fromarray(img_arr)
    elif encoding == "mono8":
        img_arr = np.frombuffer(img_data, dtype=np.uint8).reshape((height, width))
        img = Image.fromarray(img_arr)
    else:
        return [TextContent(type="text", text=f"Unsupported image encoding: {encoding}")]

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    return [
        ImageContent(type="image", data=img_base64, mimeType="image/jpeg"),
        TextContent(
            type="text",
            text=f"Image at timestamp {timestamp}: {width}x{height}, encoding: {encoding}",
        ),
    ]
