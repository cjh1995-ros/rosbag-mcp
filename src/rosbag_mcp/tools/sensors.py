"""Sensor analysis tools: LiDAR, Camera, PointCloud2, IMU, JointState, DiagnosticArray."""

from __future__ import annotations

import base64
import io
import logging
import math
from typing import Any

import numpy as np
from mcp.types import ImageContent, TextContent

from rosbag_mcp.bag_reader import get_message_at_time, read_messages
from rosbag_mcp.tools.utils import json_serialize

logger = logging.getLogger(__name__)

# PointCloud2 datatype mapping
POINTCLOUD_DTYPES = {
    1: ("int8", 1),
    2: ("uint8", 1),
    3: ("int16", 2),
    4: ("uint16", 2),
    5: ("int32", 4),
    6: ("uint32", 4),
    7: ("float32", 4),
    8: ("float64", 8),
}


async def analyze_pointcloud2(
    topic: str = "/points",
    timestamp: float | None = None,
    max_points: int = 10000,
    bag_path: str | None = None,
) -> list[TextContent]:
    """Analyze PointCloud2 data: bounds, centroid, intensity stats."""
    logger.info(f"Analyzing PointCloud2 from {topic}")

    # Get one message
    if timestamp is not None:
        msg = get_message_at_time(topic, timestamp, bag_path, tolerance=0.5)
        if not msg:
            return [TextContent(type="text", text=f"No PointCloud2 message found at {timestamp}")]
        messages = [msg]
    else:
        messages = list(read_messages(bag_path=bag_path, topics=[topic]))
        if not messages:
            return [TextContent(type="text", text=f"No messages found on topic {topic}")]
        messages = messages[:1]  # Just first message

    data = messages[0].data

    # Parse PointCloud2 fields
    fields = data.get("fields", [])
    if not fields:
        return [TextContent(type="text", text="No fields in PointCloud2 message")]

    # Build numpy dtype from fields
    dtype_list = []
    field_map = {}
    for field in fields:
        name = field.get("name", "")
        datatype = field.get("datatype", 0)
        offset = field.get("offset", 0)
        field.get("count", 1)

        if datatype in POINTCLOUD_DTYPES:
            np_type, size = POINTCLOUD_DTYPES[datatype]
            dtype_list.append((name, np_type))
            field_map[name] = offset

    if not dtype_list:
        return [TextContent(type="text", text="Could not parse PointCloud2 fields")]

    # Parse binary data
    point_data = data.get("data", [])
    if isinstance(point_data, list):
        point_data = bytes(point_data)

    data.get("point_step", 0)
    data.get("row_step", 0)
    width = data.get("width", 0)
    height = data.get("height", 0)
    is_dense = data.get("is_dense", False)

    try:
        # Parse points
        points = np.frombuffer(point_data, dtype=np.dtype(dtype_list))
        point_count = len(points)

        # Downsample if too many points
        if point_count > max_points:
            indices = np.linspace(0, point_count - 1, max_points, dtype=int)
            points = points[indices]
            logger.debug(f"Downsampled from {point_count} to {max_points} points")

        # Extract x, y, z if present
        result = {
            "point_count": point_count,
            "dimensions": {"width": width, "height": height},
            "is_dense": is_dense,
            "fields": [f.get("name") for f in fields],
        }

        if "x" in points.dtype.names and "y" in points.dtype.names and "z" in points.dtype.names:
            x = points["x"]
            y = points["y"]
            z = points["z"]

            # Filter out NaN/Inf
            valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
            x_valid = x[valid]
            y_valid = y[valid]
            z_valid = z[valid]

            if len(x_valid) > 0:
                result["bounds"] = {
                    "x": {"min": float(x_valid.min()), "max": float(x_valid.max())},
                    "y": {"min": float(y_valid.min()), "max": float(y_valid.max())},
                    "z": {"min": float(z_valid.min()), "max": float(z_valid.max())},
                }
                result["centroid"] = {
                    "x": float(x_valid.mean()),
                    "y": float(y_valid.mean()),
                    "z": float(z_valid.mean()),
                }

        # Extract intensity if present
        if "intensity" in points.dtype.names:
            intensity = points["intensity"]
            valid_intensity = intensity[np.isfinite(intensity)]
            if len(valid_intensity) > 0:
                result["intensity_stats"] = {
                    "mean": float(valid_intensity.mean()),
                    "std": float(valid_intensity.std()),
                    "min": float(valid_intensity.min()),
                    "max": float(valid_intensity.max()),
                }

        logger.debug(f"PointCloud2 analysis complete: {point_count} points")
        return [TextContent(type="text", text=json_serialize(result))]

    except Exception as e:
        logger.error(f"Failed to parse PointCloud2: {e}")
        return [TextContent(type="text", text=f"Failed to parse PointCloud2: {e}")]


async def analyze_joint_states(
    topic: str = "/joint_states",
    start_time: float | None = None,
    end_time: float | None = None,
    bag_path: str | None = None,
) -> list[TextContent]:
    """Analyze JointState data: per-joint statistics, potential issues."""
    logger.info(f"Analyzing JointState from {topic}")

    joint_data: dict[str, dict[str, list[float]]] = {}
    message_count = 0

    for msg in read_messages(
        bag_path=bag_path, topics=[topic], start_time=start_time, end_time=end_time
    ):
        data = msg.data
        names = data.get("name", [])
        positions = data.get("position", [])
        velocities = data.get("velocity", [])
        efforts = data.get("effort", [])

        for i, name in enumerate(names):
            if name not in joint_data:
                joint_data[name] = {"positions": [], "velocities": [], "efforts": []}

            if i < len(positions):
                joint_data[name]["positions"].append(positions[i])
            if i < len(velocities):
                joint_data[name]["velocities"].append(velocities[i])
            if i < len(efforts):
                joint_data[name]["efforts"].append(efforts[i])

        message_count += 1

    if not joint_data:
        logger.warning(f"No joint state data found on {topic}")
        return [TextContent(type="text", text="No joint state data found")]

    # Compute per-joint statistics
    joint_stats = {}
    alerts = []

    for joint_name, values in joint_data.items():
        positions = values["positions"]
        velocities = values["velocities"]
        efforts = values["efforts"]

        stats: dict[str, Any] = {"sample_count": len(positions)}

        if positions:
            pos_arr = np.array(positions)
            stats["position"] = {
                "min": float(pos_arr.min()),
                "max": float(pos_arr.max()),
                "mean": float(pos_arr.mean()),
                "std": float(pos_arr.std()),
                "range": float(pos_arr.max() - pos_arr.min()),
            }

            # Alert if range is very small (potentially stuck)
            if stats["position"]["range"] < 0.001:
                alerts.append(f"{joint_name}: Very small position range (potentially stuck)")

        if velocities:
            vel_arr = np.array(velocities)
            stats["velocity"] = {
                "mean": float(vel_arr.mean()),
                "std": float(vel_arr.std()),
                "max_abs": float(np.abs(vel_arr).max()),
            }

            # Alert if always zero velocity
            if np.all(np.abs(vel_arr) < 0.001):
                alerts.append(f"{joint_name}: Zero velocity throughout")

        if efforts:
            eff_arr = np.array(efforts)
            stats["effort"] = {
                "mean": float(eff_arr.mean()),
                "std": float(eff_arr.std()),
                "max_abs": float(np.abs(eff_arr).max()),
            }

            # Alert if high effort
            if np.abs(eff_arr).max() > 100:
                alerts.append(
                    f"{joint_name}: High effort detected (max={np.abs(eff_arr).max():.1f})"
                )

        joint_stats[joint_name] = stats

    result = {
        "joint_count": len(joint_data),
        "message_count": message_count,
        "joint_stats": joint_stats,
        "alerts": alerts,
    }

    logger.debug(
        f"JointState analysis complete: {len(joint_data)} joints, {message_count} messages"
    )
    return [TextContent(type="text", text=json_serialize(result))]


async def analyze_diagnostics(
    topic: str = "/diagnostics",
    start_time: float | None = None,
    end_time: float | None = None,
    bag_path: str | None = None,
) -> list[TextContent]:
    """Analyze DiagnosticArray: per-hardware status, error timeline."""
    logger.info(f"Analyzing diagnostics from {topic}")

    hardware_data: dict[str, dict[str, Any]] = {}
    error_timeline = []
    total_messages = 0

    for msg in read_messages(
        bag_path=bag_path, topics=[topic], start_time=start_time, end_time=end_time
    ):
        data = msg.data
        status_list = data.get("status", [])

        for status in status_list:
            name = status.get("name", "unknown")
            level = status.get("level", 0)  # 0=OK, 1=WARN, 2=ERROR, 3=STALE
            message = status.get("message", "")
            hardware_id = status.get("hardware_id", "")

            if name not in hardware_data:
                hardware_data[name] = {
                    "hardware_id": hardware_id,
                    "ok_count": 0,
                    "warn_count": 0,
                    "error_count": 0,
                    "stale_count": 0,
                    "first_seen": msg.timestamp,
                    "last_seen": msg.timestamp,
                    "messages": [],
                }

            hw = hardware_data[name]
            hw["last_seen"] = msg.timestamp

            if level == 0:
                hw["ok_count"] += 1
            elif level == 1:
                hw["warn_count"] += 1
                hw["messages"].append({"time": msg.timestamp, "level": "WARN", "message": message})
                error_timeline.append(
                    {"time": msg.timestamp, "hardware": name, "level": "WARN", "message": message}
                )
            elif level == 2:
                hw["error_count"] += 1
                hw["messages"].append({"time": msg.timestamp, "level": "ERROR", "message": message})
                error_timeline.append(
                    {"time": msg.timestamp, "hardware": name, "level": "ERROR", "message": message}
                )
            elif level == 3:
                hw["stale_count"] += 1

        total_messages += 1

    if not hardware_data:
        logger.warning(f"No diagnostic data found on {topic}")
        return [TextContent(type="text", text="No diagnostic data found")]

    # Summary counts
    summary = {
        "ok_count": sum(hw["ok_count"] for hw in hardware_data.values()),
        "warn_count": sum(hw["warn_count"] for hw in hardware_data.values()),
        "error_count": sum(hw["error_count"] for hw in hardware_data.values()),
        "stale_count": sum(hw["stale_count"] for hw in hardware_data.values()),
    }

    result = {
        "total_messages": total_messages,
        "unique_hardware": len(hardware_data),
        "summary": summary,
        "per_hardware": hardware_data,
        "error_timeline": error_timeline[:100],  # Limit to first 100 errors
    }

    logger.debug(
        f"Diagnostics analysis complete: {len(hardware_data)} hardware components, "
        f"{total_messages} messages"
    )
    return [TextContent(type="text", text=json_serialize(result))]


async def analyze_imu(
    imu_topic: str = "/imu",
    start_time: float | None = None,
    end_time: float | None = None,
    bag_path: str | None = None,
) -> list[TextContent]:
    """Compute IMU statistics: acceleration, angular velocity, orientation."""
    logger.info(f"Analyzing IMU data from topic {imu_topic}")
    orientations = []
    linear_accels = []
    angular_vels = []
    timestamps = []

    for msg in read_messages(
        bag_path=bag_path, topics=[imu_topic], start_time=start_time, end_time=end_time
    ):
        data = msg.data
        timestamps.append(msg.timestamp)

        if "orientation" in data:
            o = data["orientation"]
            orientations.append((o.get("x", 0), o.get("y", 0), o.get("z", 0), o.get("w", 1)))

        if "linear_acceleration" in data:
            la = data["linear_acceleration"]
            linear_accels.append((la.get("x", 0), la.get("y", 0), la.get("z", 0)))

        if "angular_velocity" in data:
            av = data["angular_velocity"]
            angular_vels.append((av.get("x", 0), av.get("y", 0), av.get("z", 0)))

    if not timestamps:
        return [TextContent(type="text", text="No IMU data found")]

    result = {
        "topic": imu_topic,
        "message_count": len(timestamps),
        "duration_s": round(timestamps[-1] - timestamps[0], 3) if len(timestamps) > 1 else 0,
        "sample_rate_hz": round(len(timestamps) / (timestamps[-1] - timestamps[0]), 2)
        if len(timestamps) > 1 and timestamps[-1] != timestamps[0]
        else 0,
    }

    if linear_accels:
        accel_magnitudes = [math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2) for a in linear_accels]
        result["linear_acceleration"] = {
            "x": {
                "mean": round(float(np.mean([a[0] for a in linear_accels])), 4),
                "std": round(float(np.std([a[0] for a in linear_accels])), 4),
                "min": round(min(a[0] for a in linear_accels), 4),
                "max": round(max(a[0] for a in linear_accels), 4),
            },
            "y": {
                "mean": round(float(np.mean([a[1] for a in linear_accels])), 4),
                "std": round(float(np.std([a[1] for a in linear_accels])), 4),
                "min": round(min(a[1] for a in linear_accels), 4),
                "max": round(max(a[1] for a in linear_accels), 4),
            },
            "z": {
                "mean": round(float(np.mean([a[2] for a in linear_accels])), 4),
                "std": round(float(np.std([a[2] for a in linear_accels])), 4),
                "min": round(min(a[2] for a in linear_accels), 4),
                "max": round(max(a[2] for a in linear_accels), 4),
            },
            "magnitude": {
                "mean": round(float(np.mean(accel_magnitudes)), 4),
                "max": round(max(accel_magnitudes), 4),
            },
        }

    if angular_vels:
        result["angular_velocity"] = {
            "x": {
                "mean": round(float(np.mean([a[0] for a in angular_vels])), 4),
                "std": round(float(np.std([a[0] for a in angular_vels])), 4),
                "max_abs": round(max(abs(a[0]) for a in angular_vels), 4),
            },
            "y": {
                "mean": round(float(np.mean([a[1] for a in angular_vels])), 4),
                "std": round(float(np.std([a[1] for a in angular_vels])), 4),
                "max_abs": round(max(abs(a[1]) for a in angular_vels), 4),
            },
            "z": {
                "mean": round(float(np.mean([a[2] for a in angular_vels])), 4),
                "std": round(float(np.std([a[2] for a in angular_vels])), 4),
                "max_abs": round(max(abs(a[2]) for a in angular_vels), 4),
            },
        }

    logger.debug(f"IMU analysis complete: {len(timestamps)} messages")
    return [TextContent(type="text", text=json_serialize(result))]


async def analyze_lidar_scan(
    scan_topic: str = "/scan",
    timestamp: float | None = None,
    obstacle_threshold: float = 1.0,
    bag_path: str | None = None,
) -> list[TextContent]:
    """Analyze a single LiDAR scan for obstacles and range statistics."""
    logger.info(f"Analyzing LiDAR scan from topic {scan_topic}")
    scan_msg = None

    if timestamp:
        logger.debug(f"Getting LiDAR scan at timestamp {timestamp}")
        scan_msg = get_message_at_time(scan_topic, timestamp, bag_path, tolerance=0.5)
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


async def get_image_at_time(
    image_topic: str,
    timestamp: float,
    bag_path: str | None = None,
    max_size: int = 1024,
    quality: int = 85,
) -> list[TextContent | ImageContent]:
    """Extract and encode a camera image at a specific timestamp."""
    from PIL import Image

    logger.info(f"Getting image from {image_topic} at {timestamp}")
    img_msg = get_message_at_time(image_topic, timestamp, bag_path, tolerance=0.5)

    if not img_msg:
        logger.warning(f"No image found at {timestamp} on {image_topic}")
        return [TextContent(type="text", text="No image found at specified time")]

    data = img_msg.data

    is_compressed = "format" in data and "width" not in data

    if is_compressed:
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
                img_arr = (img_arr >> 8).astype(np.uint8)
                img = Image.fromarray(img_arr)
            elif encoding == "32FC1":
                img_arr = np.frombuffer(img_data, dtype=np.float32).reshape((height, width))
                img_arr = (
                    (img_arr - img_arr.min()) / (img_arr.max() - img_arr.min()) * 255
                ).astype(np.uint8)
                img = Image.fromarray(img_arr)
            elif encoding == "rgba8":
                img_arr = np.frombuffer(img_data, dtype=np.uint8).reshape((height, width, 4))
                img_arr = img_arr[:, :, :3]
                img = Image.fromarray(img_arr)
            elif encoding == "bgra8":
                img_arr = np.frombuffer(img_data, dtype=np.uint8).reshape((height, width, 4))
                img_arr = img_arr[:, :, [2, 1, 0]]
                img = Image.fromarray(img_arr)
            else:
                return [TextContent(type="text", text=f"Unsupported image encoding: {encoding}")]
        except Exception as e:
            logger.error(f"Failed to decode raw image: {e}")
            return [TextContent(type="text", text=f"Failed to decode image: {e}")]

        original_size = (width, height)

    resized = False
    if max(img.size) > max_size:
        logger.debug(f"Resizing from {img.size} to fit {max_size}")
        img.thumbnail((max_size, max_size), Image.LANCZOS)
        resized = True

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

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


async def analyze_lidar_timeseries(
    scan_topic: str = "/scan",
    obstacle_threshold: float = 1.0,
    sample_interval: int = 1,
    start_time: float | None = None,
    end_time: float | None = None,
    bag_path: str | None = None,
) -> list[TextContent]:
    """Track LiDAR minimum distance and obstacle count over time."""
    timeline = []
    min_distances = []
    obstacle_counts = []
    valid_ray_ratios = []
    closest_approach = {"distance_m": float("inf"), "timestamp": 0.0}
    total_scans = 0

    for msg in read_messages(
        bag_path=bag_path, topics=[scan_topic], start_time=start_time, end_time=end_time
    ):
        total_scans += 1
        if total_scans % sample_interval != 0:
            continue

        data = msg.data
        ranges = data.get("ranges", [])
        if not ranges:
            continue

        ranges_arr = np.array(ranges)
        valid_mask = np.isfinite(ranges_arr) & (ranges_arr > 0)
        valid_ranges = ranges_arr[valid_mask]

        if len(valid_ranges) == 0:
            continue

        min_dist = float(np.min(valid_ranges))
        obstacle_count = int(np.sum(valid_ranges < obstacle_threshold))
        valid_ratio = len(valid_ranges) / len(ranges)

        min_distances.append(min_dist)
        obstacle_counts.append(obstacle_count)
        valid_ray_ratios.append(valid_ratio)

        timeline.append(
            {
                "timestamp": msg.timestamp,
                "min_distance": round(min_dist, 3),
                "obstacle_count": obstacle_count,
                "valid_rays": int(len(valid_ranges)),
            }
        )

        if min_dist < closest_approach["distance_m"]:
            closest_approach = {
                "distance_m": round(min_dist, 3),
                "timestamp": msg.timestamp,
            }

    if not min_distances:
        return [TextContent(type="text", text="No LiDAR data found")]

    duration_s = 0.0
    if len(timeline) > 1:
        duration_s = timeline[-1]["timestamp"] - timeline[0]["timestamp"]

    if len(timeline) > 50:
        step = len(timeline) // 50
        timeline = timeline[::step][:50]

    scans_with_obstacles = sum(1 for c in obstacle_counts if c > 0)

    result = {
        "scan_topic": scan_topic,
        "total_scans": total_scans,
        "sampled_scans": len(min_distances),
        "duration_s": round(duration_s, 3),
        "min_distance_over_time": {
            "mean": round(float(np.mean(min_distances)), 3),
            "min": round(float(np.min(min_distances)), 3),
            "max": round(float(np.max(min_distances)), 3),
            "std": round(float(np.std(min_distances)), 3),
        },
        "obstacle_count_over_time": {
            "mean": round(float(np.mean(obstacle_counts)), 1),
            "max": int(np.max(obstacle_counts)),
            "scans_with_obstacles": scans_with_obstacles,
        },
        "valid_ray_ratio": {
            "mean": round(float(np.mean(valid_ray_ratios)), 3),
            "min": round(float(np.min(valid_ray_ratios)), 3),
        },
        "closest_approach": closest_approach,
        "timeline": timeline,
    }

    return [TextContent(type="text", text=json_serialize(result))]
