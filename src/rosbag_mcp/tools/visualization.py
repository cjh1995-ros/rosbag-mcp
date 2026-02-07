from __future__ import annotations

import base64
import io
import logging

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from mcp.types import ImageContent, TextContent

from rosbag_mcp.bag_reader import (
    get_message_at_time as _get_message_at_time,
)
from rosbag_mcp.bag_reader import (
    read_messages,
)
from rosbag_mcp.tools.utils import extract_position, get_nested_field

logger = logging.getLogger(__name__)


async def plot_timeseries(
    fields: list[str],
    start_time: float | None = None,
    end_time: float | None = None,
    title: str = "Time Series Plot",
    bag_path: str | None = None,
) -> list[TextContent | ImageContent]:
    """Plot time series data for one or more topic fields."""
    logger.info(f"Plotting time series for fields: {fields}")
    topics_to_fields: dict[str, list[tuple[str, str | None]]] = {}
    for field in fields:
        parts = field.split(".")
        topic = "/" + parts[0]
        field_path = ".".join(parts[1:]) if len(parts) > 1 else None
        if topic not in topics_to_fields:
            topics_to_fields[topic] = []
        topics_to_fields[topic].append((field, field_path))

    series_data: dict[str, dict[str, list]] = {f: {"times": [], "values": []} for f in fields}

    for topic, field_list in topics_to_fields.items():
        base_time = None
        for msg in read_messages(
            bag_path=bag_path, topics=[topic], start_time=start_time, end_time=end_time
        ):
            if base_time is None:
                base_time = msg.timestamp

            rel_time = msg.timestamp - base_time

            for full_field, field_path in field_list:
                if field_path:
                    value = get_nested_field(msg.data, field_path)
                else:
                    value = msg.data

                if value is not None and isinstance(value, (int, float)):
                    series_data[full_field]["times"].append(rel_time)
                    series_data[full_field]["values"].append(value)

    fig, ax = plt.subplots(figsize=(10, 6))

    for field, data in series_data.items():
        if data["times"]:
            ax.plot(data["times"], data["values"], label=field)

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Value")
    ax.set_title(title)
    ax.legend()
    ax.grid(True, alpha=0.3)

    buffer = io.BytesIO()
    plt.savefig(buffer, format="png", dpi=100, bbox_inches="tight")
    plt.close()

    img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    logger.debug(f"Time series plot generated: {title}")

    return [
        ImageContent(type="image", data=img_base64, mimeType="image/png"),
        TextContent(type="text", text=f"Time series plot: {title}"),
    ]


async def plot_2d(
    pose_topic: str = "/odom",
    start_time: float | None = None,
    end_time: float | None = None,
    title: str = "2D Trajectory",
    bag_path: str | None = None,
) -> list[TextContent | ImageContent]:
    """Create a 2D XY trajectory plot from pose data."""
    logger.info(f"Plotting 2D trajectory from topic {pose_topic}")
    xs = []
    ys = []

    for msg in read_messages(
        bag_path=bag_path, topics=[pose_topic], start_time=start_time, end_time=end_time
    ):
        pos = extract_position(msg.data)
        if pos:
            xs.append(pos[0])
            ys.append(pos[1])

    if not xs:
        logger.warning(f"No position data found in topic {pose_topic}")
        return [TextContent(type="text", text="No position data found")]

    logger.debug(f"2D plot: {len(xs)} positions")
    fig, ax = plt.subplots(figsize=(8, 8))

    ax.plot(xs, ys, "b-", linewidth=1, alpha=0.7)
    ax.plot(xs[0], ys[0], "go", markersize=10, label="Start")
    ax.plot(xs[-1], ys[-1], "ro", markersize=10, label="End")

    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.set_title(title)
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_aspect("equal")

    buffer = io.BytesIO()
    plt.savefig(buffer, format="png", dpi=100, bbox_inches="tight")
    plt.close()

    img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    logger.debug(f"2D trajectory plot generated: {title}")

    return [
        ImageContent(type="image", data=img_base64, mimeType="image/png"),
        TextContent(type="text", text=f"2D trajectory plot with {len(xs)} points"),
    ]


async def plot_lidar_scan(
    timestamp: float,
    scan_topic: str = "/scan",
    title: str = "LiDAR Scan",
    bag_path: str | None = None,
) -> list[TextContent | ImageContent]:
    """Visualize a LiDAR scan as a polar plot."""
    logger.info(f"Plotting LiDAR scan from topic {scan_topic} at timestamp {timestamp}")
    scan_msg = _get_message_at_time(scan_topic, timestamp, bag_path, tolerance=0.5)

    if not scan_msg:
        logger.warning(f"No LiDAR scan found at timestamp {timestamp}")
        return [TextContent(type="text", text="No LiDAR scan found")]

    data = scan_msg.data
    ranges = np.array(data.get("ranges", []))
    angle_min = data.get("angle_min", 0)
    angle_increment = data.get("angle_increment", 0.01)

    angles = np.arange(len(ranges)) * angle_increment + angle_min

    valid_mask = np.isfinite(ranges) & (ranges > 0)
    valid_ranges = ranges[valid_mask]
    valid_angles = angles[valid_mask]

    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw={"projection": "polar"})

    ax.scatter(valid_angles, valid_ranges, c="blue", s=2, alpha=0.6)

    ax.set_title(title)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)

    buffer = io.BytesIO()
    plt.savefig(buffer, format="png", dpi=100, bbox_inches="tight")
    plt.close()

    img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    logger.debug(f"LiDAR scan plot generated: {title}")

    return [
        ImageContent(type="image", data=img_base64, mimeType="image/png"),
        TextContent(type="text", text=f"LiDAR scan plot: {title}"),
    ]


async def plot_comparison(
    topic1: str,
    topic2: str,
    field1: str,
    field2: str,
    start_time: float | None = None,
    end_time: float | None = None,
    title: str = "Topic Comparison",
    bag_path: str | None = None,
) -> list[TextContent | ImageContent]:
    """Overlay two topic fields with difference highlighting."""
    logger.info(f"Comparing topics {topic1} and {topic2}")
    data1 = {"times": [], "values": []}
    data2 = {"times": [], "values": []}

    for msg in read_messages(
        bag_path=bag_path, topics=[topic1], start_time=start_time, end_time=end_time
    ):
        value = get_nested_field(msg.data, field1)
        if value is not None and isinstance(value, (int, float)):
            data1["times"].append(msg.timestamp)
            data1["values"].append(float(value))

    for msg in read_messages(
        bag_path=bag_path, topics=[topic2], start_time=start_time, end_time=end_time
    ):
        value = get_nested_field(msg.data, field2)
        if value is not None and isinstance(value, (int, float)):
            data2["times"].append(msg.timestamp)
            data2["values"].append(float(value))

    if not data1["values"] or not data2["values"]:
        return [TextContent(type="text", text="Insufficient data for comparison plot")]

    # Use relative time from the earliest timestamp
    base_time = min(data1["times"][0], data2["times"][0])
    times1 = [t - base_time for t in data1["times"]]
    times2 = [t - base_time for t in data2["times"]]

    # Interpolate data2 onto data1 timestamps for difference computation
    interp_values2 = np.interp(times1, times2, data2["values"])
    differences = np.array(data1["values"]) - interp_values2

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), height_ratios=[2, 1], sharex=True)

    # Top subplot: both signals overlaid
    ax1.plot(times1, data1["values"], label=f"{topic1}.{field1}", alpha=0.8)
    ax1.plot(times2, data2["values"], label=f"{topic2}.{field2}", alpha=0.8)
    ax1.set_ylabel("Value")
    ax1.set_title(title)
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # Bottom subplot: difference
    ax2.fill_between(times1, differences, alpha=0.3, color="red")
    ax2.plot(times1, differences, color="red", linewidth=0.8, label="Difference")
    ax2.axhline(y=0, color="black", linewidth=0.5, linestyle="--")
    ax2.set_xlabel("Time (s)")
    ax2.set_ylabel("Difference")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()

    buffer = io.BytesIO()
    plt.savefig(buffer, format="png", dpi=100, bbox_inches="tight")
    plt.close()

    img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    return [
        ImageContent(type="image", data=img_base64, mimeType="image/png"),
        TextContent(type="text", text=f"Comparison plot: {title}"),
    ]
