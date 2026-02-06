from __future__ import annotations

import base64
import io
import logging
import math
import re

import numpy as np
from mcp.types import ImageContent, TextContent

from rosbag_mcp.bag_reader import (
    get_message_at_time as _get_message_at_time,
)
from rosbag_mcp.bag_reader import (
    read_messages,
)
from rosbag_mcp.tools.utils import extract_position, extract_velocity, json_serialize

logger = logging.getLogger(__name__)


async def analyze_trajectory(
    pose_topic: str = "/odom",
    start_time: float | None = None,
    end_time: float | None = None,
    include_waypoints: bool = False,
    waypoint_angle_threshold: float = 15.0,
    bag_path: str | None = None,
) -> list[TextContent]:
    logger.info(f"Analyzing trajectory from topic {pose_topic}")
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
        logger.warning(f"No position data found in topic {pose_topic}")
        return [TextContent(type="text", text="No position data found")]

    logger.debug(f"Trajectory analysis: {len(positions)} positions, {len(velocities)} velocities")

    # Calculate total distance and displacement
    total_distance = 0.0
    for i in range(1, len(positions)):
        dx = positions[i][0] - positions[i - 1][0]
        dy = positions[i][1] - positions[i - 1][1]
        total_distance += math.sqrt(dx * dx + dy * dy)

    # Displacement: straight-line distance from start to end
    displacement = math.sqrt(
        (positions[-1][0] - positions[0][0]) ** 2 + (positions[-1][1] - positions[0][1]) ** 2
    )

    # Path efficiency: displacement / total_distance (1.0 = perfectly straight)
    path_efficiency = displacement / total_distance if total_distance > 0 else 0.0

    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]

    linear_speeds = [abs(v[0]) for v in velocities] if velocities else []
    angular_speeds = [abs(v[1]) for v in velocities] if velocities else []

    # Calculate moving vs stationary time
    moving_time_s = 0.0
    if linear_speeds and len(timestamps) > 1:
        for i in range(len(linear_speeds)):
            if linear_speeds[i] > 0.01:  # Moving threshold: 0.01 m/s
                if i < len(timestamps) - 1:
                    moving_time_s += timestamps[i + 1] - timestamps[i]

    duration_s = timestamps[-1] - timestamps[0] if len(timestamps) > 1 else 0
    stationary_time_s = duration_s - moving_time_s

    result = {
        "total_distance_m": round(total_distance, 3),
        "displacement_m": round(displacement, 3),
        "path_efficiency": round(path_efficiency, 3),
        "duration_s": round(duration_s, 3),
        "moving_time_s": round(moving_time_s, 3),
        "stationary_time_s": round(stationary_time_s, 3),
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
        # Angle-based waypoint detection
        waypoints = []
        angle_threshold_rad = math.radians(waypoint_angle_threshold)

        # Always include start point
        waypoints.append(
            {
                "x": round(positions[0][0], 3),
                "y": round(positions[0][1], 3),
                "z": round(positions[0][2], 3),
                "time": round(timestamps[0], 3),
                "reason": "start",
            }
        )

        # Detect waypoints based on heading changes
        for i in range(1, len(positions) - 1):
            # Calculate heading from previous to current
            dx1 = positions[i][0] - positions[i - 1][0]
            dy1 = positions[i][1] - positions[i - 1][1]
            heading1 = math.atan2(dy1, dx1)

            # Calculate heading from current to next
            dx2 = positions[i + 1][0] - positions[i][0]
            dy2 = positions[i + 1][1] - positions[i][1]
            heading2 = math.atan2(dy2, dx2)

            # Calculate heading change
            heading_change = abs(heading2 - heading1)
            # Normalize to [-pi, pi]
            if heading_change > math.pi:
                heading_change = 2 * math.pi - heading_change

            # Mark as waypoint if heading change exceeds threshold
            if heading_change > angle_threshold_rad:
                waypoints.append(
                    {
                        "x": round(positions[i][0], 3),
                        "y": round(positions[i][1], 3),
                        "z": round(positions[i][2], 3),
                        "time": round(timestamps[i], 3),
                        "reason": "heading_change",
                        "angle_deg": round(math.degrees(heading_change), 1),
                    }
                )

            # Detect stop points (speed drops below threshold)
            if i < len(linear_speeds) and linear_speeds[i] < 0.01:
                # Check if stopped for sustained period
                if i > 0 and i < len(linear_speeds) - 1:
                    if linear_speeds[i - 1] > 0.01 or linear_speeds[i + 1] > 0.01:
                        waypoints.append(
                            {
                                "x": round(positions[i][0], 3),
                                "y": round(positions[i][1], 3),
                                "z": round(positions[i][2], 3),
                                "time": round(timestamps[i], 3),
                                "reason": "stop",
                            }
                        )

        # Always include end point
        waypoints.append(
            {
                "x": round(positions[-1][0], 3),
                "y": round(positions[-1][1], 3),
                "z": round(positions[-1][2], 3),
                "time": round(timestamps[-1], 3),
                "reason": "end",
            }
        )

        result["waypoints"] = waypoints
        result["waypoint_count"] = len(waypoints)

    return [TextContent(type="text", text=json_serialize(result))]


async def analyze_lidar_scan(
    scan_topic: str = "/scan",
    timestamp: float | None = None,
    obstacle_threshold: float = 1.0,
    bag_path: str | None = None,
) -> list[TextContent]:
    logger.info(f"Analyzing LiDAR scan from topic {scan_topic}")
    scan_msg = None

    if timestamp:
        logger.debug(f"Getting LiDAR scan at timestamp {timestamp}")
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
    max_size: int = 1024,
    quality: int = 85,
) -> list[TextContent | ImageContent]:
    from PIL import Image

    logger.info(f"Getting image from {image_topic} at {timestamp}")
    img_msg = _get_message_at_time(image_topic, timestamp, bag_path, tolerance=0.5)

    if not img_msg:
        logger.warning(f"No image found at {timestamp} on {image_topic}")
        return [TextContent(type="text", text="No image found at specified time")]

    data = img_msg.data

    # Check if this is a CompressedImage (has 'format' field, no 'width' field)
    is_compressed = "format" in data and "width" not in data

    if is_compressed:
        # CompressedImage: decode JPEG/PNG directly with Pillow
        logger.debug(f"Detected CompressedImage format: {data.get('format', 'unknown')}")
        img_data = data.get("data", [])
        if not img_data:
            return [TextContent(type="text", text="Compressed image data is empty")]

        if isinstance(img_data, list):
            img_data = bytes(img_data)

        try:
            img = Image.open(io.BytesIO(img_data))
            original_size = img.size
            logger.debug(f"Decoded compressed image: {original_size}")
        except Exception as e:
            logger.error(f"Failed to decode compressed image: {e}")
            return [TextContent(type="text", text=f"Failed to decode compressed image: {e}")]
    else:
        # Raw Image: decode based on encoding
        width = data.get("width", 0)
        height = data.get("height", 0)
        encoding = data.get("encoding", "rgb8")
        img_data = data.get("data", [])

        if not img_data:
            return [TextContent(type="text", text="Image data is empty")]

        if isinstance(img_data, list):
            img_data = bytes(img_data)

        logger.debug(f"Raw image: {width}x{height}, encoding={encoding}")

        try:
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
            elif encoding in ["mono16", "16UC1"]:
                img_arr = np.frombuffer(img_data, dtype=np.uint16).reshape((height, width))
                # Scale to 8-bit
                img_arr = (img_arr >> 8).astype(np.uint8)
                img = Image.fromarray(img_arr)
            elif encoding == "32FC1":
                img_arr = np.frombuffer(img_data, dtype=np.float32).reshape((height, width))
                # Normalize to 0-255
                img_arr = (
                    (img_arr - img_arr.min()) / (img_arr.max() - img_arr.min()) * 255
                ).astype(np.uint8)
                img = Image.fromarray(img_arr)
            elif encoding == "rgba8":
                img_arr = np.frombuffer(img_data, dtype=np.uint8).reshape((height, width, 4))
                # Drop alpha channel
                img_arr = img_arr[:, :, :3]
                img = Image.fromarray(img_arr)
            elif encoding == "bgra8":
                img_arr = np.frombuffer(img_data, dtype=np.uint8).reshape((height, width, 4))
                # Swap BGR to RGB and drop alpha
                img_arr = img_arr[:, :, [2, 1, 0]]
                img = Image.fromarray(img_arr)
            else:
                return [TextContent(type="text", text=f"Unsupported image encoding: {encoding}")]
        except Exception as e:
            logger.error(f"Failed to decode raw image: {e}")
            return [TextContent(type="text", text=f"Failed to decode image: {e}")]

        original_size = (width, height)

    # Smart resize if image exceeds max_size
    resized = False
    if max(img.size) > max_size:
        logger.debug(f"Resizing from {img.size} to fit {max_size}")
        img.thumbnail((max_size, max_size), Image.LANCZOS)
        resized = True

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    # Build metadata
    metadata = {
        "timestamp": timestamp,
        "original_size": original_size,
        "final_size": img.size,
        "resized": resized,
        "quality": quality,
    }
    if is_compressed:
        metadata["format"] = data.get("format", "unknown")
    else:
        metadata["encoding"] = data.get("encoding", "unknown")

    return [
        ImageContent(type="image", data=img_base64, mimeType="image/jpeg"),
        TextContent(
            type="text",
            text=f"Image at timestamp {timestamp}: {metadata}",
        ),
    ]
