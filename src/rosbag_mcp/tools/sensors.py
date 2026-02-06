"""Sensor analysis tools for PointCloud2, JointState, and DiagnosticArray."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from mcp.types import TextContent

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
        f"Diagnostics analysis complete: {len(hardware_data)} hardware components, {total_messages} messages"
    )
    return [TextContent(type="text", text=json_serialize(result))]
