from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from mcp.types import TextContent

from rosbag_mcp.bag_reader import (
    get_topic_schema as _get_topic_schema,
)
from rosbag_mcp.bag_reader import (
    get_topic_timestamps,
    read_messages,
)
from rosbag_mcp.tools.utils import get_nested_field, json_serialize


async def get_topic_schema(
    topic: str,
    bag_path: str | None = None,
) -> list[TextContent]:
    schema_info = _get_topic_schema(topic, bag_path)
    return [TextContent(type="text", text=json_serialize(schema_info))]


async def analyze_imu(
    imu_topic: str = "/imu",
    start_time: float | None = None,
    end_time: float | None = None,
    bag_path: str | None = None,
) -> list[TextContent]:
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

    return [TextContent(type="text", text=json_serialize(result))]


async def analyze_topic_stats(
    topic: str,
    bag_path: str | None = None,
) -> list[TextContent]:
    timestamps = get_topic_timestamps(topic, bag_path)

    if not timestamps:
        return [TextContent(type="text", text=f"No messages found for topic: {topic}")]

    if len(timestamps) < 2:
        return [
            TextContent(
                type="text",
                text=json_serialize(
                    {
                        "topic": topic,
                        "message_count": 1,
                        "note": "Only one message, cannot compute statistics",
                    }
                ),
            )
        ]

    intervals = np.diff(timestamps)
    gaps = intervals[intervals > np.mean(intervals) * 3]  # Gaps > 3x mean interval

    result = {
        "topic": topic,
        "message_count": len(timestamps),
        "duration_s": round(timestamps[-1] - timestamps[0], 3),
        "first_timestamp": timestamps[0],
        "last_timestamp": timestamps[-1],
        "frequency": {
            "mean_hz": round(1.0 / float(np.mean(intervals)), 2),
            "std_hz": round(float(np.std(1.0 / intervals)), 2) if np.all(intervals > 0) else 0,
            "min_hz": round(1.0 / float(np.max(intervals)), 2) if np.max(intervals) > 0 else 0,
            "max_hz": round(1.0 / float(np.min(intervals)), 2) if np.min(intervals) > 0 else 0,
        },
        "interval": {
            "mean_ms": round(float(np.mean(intervals)) * 1000, 3),
            "std_ms": round(float(np.std(intervals)) * 1000, 3),
            "min_ms": round(float(np.min(intervals)) * 1000, 3),
            "max_ms": round(float(np.max(intervals)) * 1000, 3),
        },
        "gaps": {
            "count": len(gaps),
            "threshold_ms": round(float(np.mean(intervals)) * 3 * 1000, 3),
            "largest_gap_ms": round(float(np.max(gaps)) * 1000, 3) if len(gaps) > 0 else 0,
        },
    }

    return [TextContent(type="text", text=json_serialize(result))]


async def compare_topics(
    topic1: str,
    topic2: str,
    field1: str,
    field2: str,
    start_time: float | None = None,
    end_time: float | None = None,
    bag_path: str | None = None,
) -> list[TextContent]:
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
        return [TextContent(type="text", text="Insufficient data for comparison")]

    interp_values2 = np.interp(data1["times"], data2["times"], data2["values"])
    differences = np.array(data1["values"]) - interp_values2

    correlation = float(np.corrcoef(data1["values"], interp_values2)[0, 1])

    result = {
        "topic1": {"topic": topic1, "field": field1, "count": len(data1["values"])},
        "topic2": {"topic": topic2, "field": field2, "count": len(data2["values"])},
        "comparison": {
            "correlation": round(correlation, 4) if not np.isnan(correlation) else None,
            "difference": {
                "mean": round(float(np.mean(differences)), 4),
                "std": round(float(np.std(differences)), 4),
                "min": round(float(np.min(differences)), 4),
                "max": round(float(np.max(differences)), 4),
                "rmse": round(float(np.sqrt(np.mean(differences**2))), 4),
            },
            "topic1_stats": {
                "mean": round(float(np.mean(data1["values"])), 4),
                "std": round(float(np.std(data1["values"])), 4),
                "min": round(float(np.min(data1["values"])), 4),
                "max": round(float(np.max(data1["values"])), 4),
            },
            "topic2_stats": {
                "mean": round(float(np.mean(data2["values"])), 4),
                "std": round(float(np.std(data2["values"])), 4),
                "min": round(float(np.min(data2["values"])), 4),
                "max": round(float(np.max(data2["values"])), 4),
            },
        },
    }

    return [TextContent(type="text", text=json_serialize(result))]


async def export_to_csv(
    topic: str,
    output_path: str,
    fields: list[str] | None = None,
    start_time: float | None = None,
    end_time: float | None = None,
    max_messages: int = 10000,
    bag_path: str | None = None,
) -> list[TextContent]:
    messages = []
    all_fields: set[str] = set()

    for msg in read_messages(
        bag_path=bag_path, topics=[topic], start_time=start_time, end_time=end_time
    ):
        if len(messages) >= max_messages:
            break

        row = {"timestamp": msg.timestamp}

        if fields:
            for field in fields:
                value = get_nested_field(msg.data, field)
                row[field] = value
                all_fields.add(field)
        else:
            _flatten_dict(msg.data, "", row, all_fields)

        messages.append(row)

    if not messages:
        return [TextContent(type="text", text="No messages found")]

    fieldnames = ["timestamp"] + sorted(all_fields)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(messages)

    return [
        TextContent(
            type="text",
            text=f"Exported {len(messages)} messages to {output_path}\nFields: {', '.join(fieldnames)}",
        )
    ]


def _flatten_dict(data: dict, prefix: str, row: dict, all_fields: set, max_depth: int = 4) -> None:
    if max_depth <= 0:
        return

    for key, value in data.items():
        field_name = f"{prefix}.{key}" if prefix else key

        if isinstance(value, dict):
            _flatten_dict(value, field_name, row, all_fields, max_depth - 1)
        elif isinstance(value, (int, float, str, bool)) or value is None:
            row[field_name] = value
            all_fields.add(field_name)
        elif isinstance(value, list) and len(value) <= 10:
            for i, item in enumerate(value):
                if isinstance(item, (int, float, str, bool)):
                    item_field = f"{field_name}.{i}"
                    row[item_field] = item
                    all_fields.add(item_field)


async def detect_events(
    topic: str,
    field: str,
    event_type: str = "threshold",
    threshold: float | None = None,
    window_size: int = 10,
    bag_path: str | None = None,
) -> list[TextContent]:
    values = []
    timestamps = []

    for msg in read_messages(bag_path=bag_path, topics=[topic]):
        value = get_nested_field(msg.data, field)
        if value is not None and isinstance(value, (int, float)):
            values.append(float(value))
            timestamps.append(msg.timestamp)

    if len(values) < window_size:
        return [TextContent(type="text", text="Insufficient data for event detection")]

    events = []
    values_arr = np.array(values)

    if event_type == "threshold" and threshold is not None:
        for i, (t, v) in enumerate(zip(timestamps, values)):
            if v > threshold:
                events.append(
                    {
                        "type": "threshold_exceeded",
                        "timestamp": t,
                        "value": round(v, 4),
                        "threshold": threshold,
                    }
                )

    elif event_type == "threshold_below" and threshold is not None:
        for i, (t, v) in enumerate(zip(timestamps, values)):
            if v < threshold:
                events.append(
                    {
                        "type": "threshold_below",
                        "timestamp": t,
                        "value": round(v, 4),
                        "threshold": threshold,
                    }
                )

    elif event_type == "sudden_change":
        if threshold is None:
            threshold = float(np.std(values_arr) * 2)

        for i in range(1, len(values)):
            change = abs(values[i] - values[i - 1])
            if change > threshold:
                events.append(
                    {
                        "type": "sudden_change",
                        "timestamp": timestamps[i],
                        "value": round(values[i], 4),
                        "previous_value": round(values[i - 1], 4),
                        "change": round(change, 4),
                    }
                )

    elif event_type == "anomaly":
        mean = float(np.mean(values_arr))
        std = float(np.std(values_arr))
        z_threshold = threshold if threshold else 3.0

        for i, (t, v) in enumerate(zip(timestamps, values)):
            z_score = abs(v - mean) / std if std > 0 else 0
            if z_score > z_threshold:
                events.append(
                    {
                        "type": "anomaly",
                        "timestamp": t,
                        "value": round(v, 4),
                        "z_score": round(z_score, 2),
                        "mean": round(mean, 4),
                        "std": round(std, 4),
                    }
                )

    elif event_type == "stoppage":
        stop_threshold = threshold if threshold else 0.01
        stop_duration = window_size

        in_stop = False
        stop_start = None
        stop_count = 0

        for i, (t, v) in enumerate(zip(timestamps, values)):
            if abs(v) < stop_threshold:
                if not in_stop:
                    stop_start = t
                    in_stop = True
                stop_count += 1
            else:
                if in_stop and stop_count >= stop_duration:
                    events.append(
                        {
                            "type": "stoppage",
                            "start_timestamp": stop_start,
                            "end_timestamp": timestamps[i - 1] if i > 0 else t,
                            "duration_s": round(timestamps[i - 1] - stop_start, 3) if i > 0 else 0,
                        }
                    )
                in_stop = False
                stop_count = 0

        if in_stop and stop_count >= stop_duration:
            events.append(
                {
                    "type": "stoppage",
                    "start_timestamp": stop_start,
                    "end_timestamp": timestamps[-1],
                    "duration_s": round(timestamps[-1] - stop_start, 3),
                }
            )

    result = {
        "topic": topic,
        "field": field,
        "event_type": event_type,
        "total_messages": len(values),
        "events_found": len(events),
        "events": events[:500],
    }

    return [TextContent(type="text", text=json_serialize(result))]


async def analyze_costmap_violations(
    costmap_topic: str = "/move_base/local_costmap/costmap",
    pose_topic: str = "/amcl_pose",
    cost_threshold: int = 253,
    bag_path: str | None = None,
) -> list[TextContent]:
    costmaps: list[tuple[float, dict]] = []
    poses: list[tuple[float, float, float]] = []

    for msg in read_messages(bag_path=bag_path, topics=[costmap_topic]):
        info = msg.data.get("info", {})
        costmap_data = {
            "resolution": info.get("resolution", 0.05),
            "width": info.get("width", 0),
            "height": info.get("height", 0),
            "origin_x": info.get("origin", {}).get("position", {}).get("x", 0),
            "origin_y": info.get("origin", {}).get("position", {}).get("y", 0),
            "data": msg.data.get("data", []),
        }
        costmaps.append((msg.timestamp, costmap_data))

    for msg in read_messages(bag_path=bag_path, topics=[pose_topic]):
        data = msg.data
        pose = data.get("pose", {})
        if "pose" in pose:
            pose = pose["pose"]
        pos = pose.get("position", {})
        poses.append((msg.timestamp, pos.get("x", 0), pos.get("y", 0)))

    if not costmaps:
        return [TextContent(type="text", text=f"No costmap data found on {costmap_topic}")]
    if not poses:
        return [TextContent(type="text", text=f"No pose data found on {pose_topic}")]

    violations = []
    high_cost_samples = []
    current_costmap_idx = 0

    for pose_ts, px, py in poses:
        while (
            current_costmap_idx < len(costmaps) - 1
            and costmaps[current_costmap_idx + 1][0] <= pose_ts
        ):
            current_costmap_idx += 1

        _, cm = costmaps[current_costmap_idx]
        res = cm["resolution"]
        ox, oy = cm["origin_x"], cm["origin_y"]
        width, height = cm["width"], cm["height"]
        data = cm["data"]

        cell_x = int((px - ox) / res)
        cell_y = int((py - oy) / res)

        if 0 <= cell_x < width and 0 <= cell_y < height:
            idx = cell_y * width + cell_x
            if idx < len(data):
                cost = data[idx]
                if cost >= cost_threshold:
                    violations.append(
                        {
                            "timestamp": pose_ts,
                            "pose_x": round(px, 3),
                            "pose_y": round(py, 3),
                            "cost": cost,
                            "cell": [cell_x, cell_y],
                        }
                    )
                elif cost > 0:
                    high_cost_samples.append({"timestamp": pose_ts, "cost": cost})

    cost_distribution = defaultdict(int)
    for sample in high_cost_samples:
        bucket = (sample["cost"] // 50) * 50
        cost_distribution[f"{bucket}-{bucket + 49}"] += 1

    result = {
        "costmap_topic": costmap_topic,
        "pose_topic": pose_topic,
        "costmap_messages": len(costmaps),
        "pose_messages": len(poses),
        "cost_threshold": cost_threshold,
        "violations": {
            "count": len(violations),
            "samples": violations[:20],
        },
        "cost_distribution": dict(cost_distribution),
        "summary": "COLLISION DETECTED - Robot entered lethal costmap cells!"
        if violations
        else "No costmap violations detected - Robot stayed in free space",
    }

    return [TextContent(type="text", text=json_serialize(result))]


async def analyze_path_tracking(
    path_topic: str = "/move_base/GlobalPlanner/plan",
    pose_topic: str = "/amcl_pose",
    start_time: float | None = None,
    end_time: float | None = None,
    bag_path: str | None = None,
) -> list[TextContent]:
    paths: list[tuple[float, list[tuple[float, float]]]] = []
    poses: list[tuple[float, float, float]] = []

    for msg in read_messages(
        bag_path=bag_path, topics=[path_topic], start_time=start_time, end_time=end_time
    ):
        path_poses = msg.data.get("poses", [])
        if path_poses:
            waypoints = []
            for p in path_poses:
                pose = p.get("pose", {})
                pos = pose.get("position", {})
                x, y = pos.get("x", 0), pos.get("y", 0)
                waypoints.append((x, y))
            if waypoints:
                paths.append((msg.timestamp, waypoints))

    for msg in read_messages(
        bag_path=bag_path, topics=[pose_topic], start_time=start_time, end_time=end_time
    ):
        data = msg.data
        pose = data.get("pose", {})
        if "pose" in pose:
            pose = pose["pose"]
        pos = pose.get("position", {})
        x, y = pos.get("x", 0), pos.get("y", 0)
        poses.append((msg.timestamp, x, y))

    if not paths:
        return [TextContent(type="text", text=f"No path data found on {path_topic}")]
    if not poses:
        return [TextContent(type="text", text=f"No pose data found on {pose_topic}")]

    def point_to_segment_distance(
        px: float, py: float, x1: float, y1: float, x2: float, y2: float
    ) -> tuple[float, float]:
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0:
            return math.sqrt((px - x1) ** 2 + (py - y1) ** 2), 0.0

        t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
        proj_x, proj_y = x1 + t * dx, y1 + t * dy
        dist = math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)
        return dist, t

    def find_closest_path_point(
        px: float, py: float, waypoints: list[tuple[float, float]]
    ) -> tuple[float, int, float]:
        min_dist = float("inf")
        best_idx = 0
        best_progress = 0.0

        cumulative_length = 0.0
        segment_lengths = []
        for i in range(len(waypoints) - 1):
            seg_len = math.sqrt(
                (waypoints[i + 1][0] - waypoints[i][0]) ** 2
                + (waypoints[i + 1][1] - waypoints[i][1]) ** 2
            )
            segment_lengths.append(seg_len)
            cumulative_length += seg_len

        total_length = cumulative_length
        cumulative_length = 0.0

        for i in range(len(waypoints) - 1):
            dist, t = point_to_segment_distance(
                px, py, waypoints[i][0], waypoints[i][1], waypoints[i + 1][0], waypoints[i + 1][1]
            )
            if dist < min_dist:
                min_dist = dist
                best_idx = i
                best_progress = (
                    (cumulative_length + t * segment_lengths[i]) / total_length
                    if total_length > 0
                    else 0
                )

            cumulative_length += segment_lengths[i]

        return min_dist, best_idx, best_progress

    cross_track_errors = []
    progress_values = []
    tracking_data = []

    current_path_idx = 0
    for pose_ts, px, py in poses:
        while current_path_idx < len(paths) - 1 and paths[current_path_idx + 1][0] <= pose_ts:
            current_path_idx += 1

        path_ts, waypoints = paths[current_path_idx]
        if len(waypoints) < 2:
            continue

        cross_track_error, segment_idx, progress = find_closest_path_point(px, py, waypoints)
        cross_track_errors.append(cross_track_error)
        progress_values.append(progress)

        tracking_data.append(
            {
                "timestamp": pose_ts,
                "pose_x": round(px, 3),
                "pose_y": round(py, 3),
                "cross_track_error_m": round(cross_track_error, 4),
                "path_progress": round(progress, 3),
            }
        )

    if not cross_track_errors:
        return [TextContent(type="text", text="Could not compute tracking errors")]

    cte_arr = np.array(cross_track_errors)
    high_error_threshold = float(np.mean(cte_arr) + 2 * np.std(cte_arr))
    high_error_events = [
        d for d in tracking_data if d["cross_track_error_m"] > high_error_threshold
    ]

    result = {
        "path_topic": path_topic,
        "pose_topic": pose_topic,
        "path_messages": len(paths),
        "pose_messages": len(poses),
        "tracking_samples": len(cross_track_errors),
        "cross_track_error": {
            "mean_m": round(float(np.mean(cte_arr)), 4),
            "std_m": round(float(np.std(cte_arr)), 4),
            "min_m": round(float(np.min(cte_arr)), 4),
            "max_m": round(float(np.max(cte_arr)), 4),
            "median_m": round(float(np.median(cte_arr)), 4),
            "p95_m": round(float(np.percentile(cte_arr, 95)), 4),
        },
        "path_completion": {
            "final_progress": round(progress_values[-1], 3) if progress_values else 0,
            "max_progress": round(max(progress_values), 3) if progress_values else 0,
        },
        "high_error_events": {
            "threshold_m": round(high_error_threshold, 4),
            "count": len(high_error_events),
            "samples": high_error_events[:10],
        },
    }

    return [TextContent(type="text", text=json_serialize(result))]


async def analyze_wheel_slip(
    cmd_vel_topic: str = "/cmd_vel",
    odom_topic: str = "/odom",
    cmd_vel_field: str = "twist.linear.x",
    odom_field: str = "twist.twist.linear.x",
    slip_threshold: float = 0.1,
    start_time: float | None = None,
    end_time: float | None = None,
    bag_path: str | None = None,
) -> list[TextContent]:
    cmd_data = {"times": [], "values": []}
    odom_data = {"times": [], "values": []}

    for msg in read_messages(
        bag_path=bag_path, topics=[cmd_vel_topic], start_time=start_time, end_time=end_time
    ):
        value = get_nested_field(msg.data, cmd_vel_field)
        if value is not None and isinstance(value, (int, float)):
            cmd_data["times"].append(msg.timestamp)
            cmd_data["values"].append(float(value))

    for msg in read_messages(
        bag_path=bag_path, topics=[odom_topic], start_time=start_time, end_time=end_time
    ):
        value = get_nested_field(msg.data, odom_field)
        if value is not None and isinstance(value, (int, float)):
            odom_data["times"].append(msg.timestamp)
            odom_data["values"].append(float(value))

    if not cmd_data["values"] or not odom_data["values"]:
        return [TextContent(type="text", text="Insufficient data for wheel slip analysis")]

    # Interpolate commanded values to odom timestamps
    interp_cmd = np.interp(odom_data["times"], cmd_data["times"], cmd_data["values"])
    odom_values = np.array(odom_data["values"])
    odom_times = np.array(odom_data["times"])

    slip = odom_values - interp_cmd
    abs_slip = np.abs(slip)

    # Compute correlation
    correlation = float(np.corrcoef(odom_values, interp_cmd)[0, 1])
    if np.isnan(correlation):
        correlation = 0.0

    rmse = float(np.sqrt(np.mean(slip**2)))

    # Detect slip events as contiguous windows where |actual - commanded| > threshold
    slip_events = []
    in_slip = False
    slip_start_idx = 0

    for i in range(len(abs_slip)):
        if abs_slip[i] > slip_threshold:
            if not in_slip:
                in_slip = True
                slip_start_idx = i
        else:
            if in_slip:
                event_slip = slip[slip_start_idx:i]
                event_abs_slip = abs_slip[slip_start_idx:i]
                mean_slip = float(np.mean(event_slip))
                if mean_slip < -slip_threshold:
                    slip_type = "backward_slip"
                elif (
                    np.mean(odom_values[slip_start_idx:i]) < -0.01
                    and np.mean(interp_cmd[slip_start_idx:i]) > 0.01
                ):
                    slip_type = "sliding"
                else:
                    slip_type = "forward_slip"
                slip_events.append(
                    {
                        "start_time": float(odom_times[slip_start_idx]),
                        "end_time": float(odom_times[i - 1]),
                        "duration_s": round(
                            float(odom_times[i - 1] - odom_times[slip_start_idx]), 3
                        ),
                        "max_slip": round(float(np.max(event_abs_slip)), 4),
                        "mean_slip": round(float(np.mean(event_abs_slip)), 4),
                        "type": slip_type,
                    }
                )
                in_slip = False

    # Handle trailing slip event
    if in_slip:
        event_slip = slip[slip_start_idx:]
        event_abs_slip = abs_slip[slip_start_idx:]
        mean_slip = float(np.mean(event_slip))
        if mean_slip < -slip_threshold:
            slip_type = "backward_slip"
        elif (
            np.mean(odom_values[slip_start_idx:]) < -0.01
            and np.mean(interp_cmd[slip_start_idx:]) > 0.01
        ):
            slip_type = "sliding"
        else:
            slip_type = "forward_slip"
        slip_events.append(
            {
                "start_time": float(odom_times[slip_start_idx]),
                "end_time": float(odom_times[-1]),
                "duration_s": round(float(odom_times[-1] - odom_times[slip_start_idx]), 3),
                "max_slip": round(float(np.max(event_abs_slip)), 4),
                "mean_slip": round(float(np.mean(event_abs_slip)), 4),
                "type": slip_type,
            }
        )

    total_slip_duration = sum(e["duration_s"] for e in slip_events)
    max_backward = float(np.min(odom_values))
    backward_detected = bool(max_backward < -0.01 and np.any(interp_cmd > 0.01))

    # Slip ratio: |actual - commanded| / |commanded| where commanded != 0
    nonzero_cmd = np.abs(interp_cmd) > 0.01
    if np.any(nonzero_cmd):
        slip_ratios = abs_slip[nonzero_cmd] / np.abs(interp_cmd[nonzero_cmd])
        slip_ratio_mean = round(float(np.mean(slip_ratios)), 4)
        slip_ratio_max = round(float(np.max(slip_ratios)), 4)
    else:
        slip_ratio_mean = 0.0
        slip_ratio_max = 0.0

    duration_s = float(odom_times[-1] - odom_times[0]) if len(odom_times) > 1 else 0.0

    result = {
        "cmd_vel_topic": cmd_vel_topic,
        "odom_topic": odom_topic,
        "duration_s": round(duration_s, 3),
        "correlation": round(correlation, 4),
        "rmse": round(rmse, 4),
        "slip_events": slip_events[:500],
        "slip_summary": {
            "total_slip_events": len(slip_events),
            "total_slip_duration_s": round(total_slip_duration, 3),
            "max_backward_velocity": round(max_backward, 4),
            "backward_sliding_detected": backward_detected,
            "slip_ratio": {"mean": slip_ratio_mean, "max": slip_ratio_max},
        },
        "velocity_stats": {
            "commanded": {
                "mean": round(float(np.mean(interp_cmd)), 4),
                "max": round(float(np.max(interp_cmd)), 4),
                "min": round(float(np.min(interp_cmd)), 4),
            },
            "actual": {
                "mean": round(float(np.mean(odom_values)), 4),
                "max": round(float(np.max(odom_values)), 4),
                "min": round(float(np.min(odom_values)), 4),
            },
        },
    }

    return [TextContent(type="text", text=json_serialize(result))]


async def analyze_navigation_health(
    log_topic: str = "/rosout",
    recovery_topic: str = "/move_base/debug/recovery_events",
    goal_topic: str = "/move_base/goal",
    nav_status_topic: str = "/move_base/navigation_status",
    bag_path: str | None = None,
) -> list[TextContent]:
    errors = []
    warnings = []
    all_timestamps = []

    error_categories = {
        "planning_failure": 0,
        "collision_in_costmap": 0,
        "goal_unreachable": 0,
        "other": 0,
    }
    warning_categories = {
        "rate_miss": 0,
        "costmap_timeout": 0,
        "other": 0,
    }

    for msg in read_messages(bag_path=bag_path, topics=[log_topic]):
        data = msg.data
        msg_level = data.get("level", data.get("severity", 0))
        if isinstance(msg_level, str):
            msg_level = {"DEBUG": 1, "INFO": 2, "WARN": 4, "ERROR": 8, "FATAL": 16}.get(
                msg_level, 0
            )

        all_timestamps.append(msg.timestamp)
        msg_text = data.get("msg", data.get("message", ""))

        if msg_level >= 8:  # ERROR or FATAL
            msg_lower = msg_text.lower()
            if "failed to find a plan" in msg_lower or (
                "planning" in msg_lower and "fail" in msg_lower
            ):
                error_categories["planning_failure"] += 1
            elif "collision" in msg_lower or "in collision" in msg_lower:
                error_categories["collision_in_costmap"] += 1
            elif "unreachable" in msg_lower or "aborted" in msg_lower:
                error_categories["goal_unreachable"] += 1
            else:
                error_categories["other"] += 1

            errors.append(
                {
                    "timestamp": msg.timestamp,
                    "message": msg_text[:200],
                }
            )

        elif msg_level == 4:  # WARN
            msg_lower = msg_text.lower()
            if "missed" in msg_lower and "rate" in msg_lower:
                warning_categories["rate_miss"] += 1
            elif "timeout" in msg_lower or "timed out" in msg_lower:
                warning_categories["costmap_timeout"] += 1
            else:
                warning_categories["other"] += 1

            warnings.append(
                {
                    "timestamp": msg.timestamp,
                    "message": msg_text[:200],
                }
            )

    # Collect recovery events
    recovery_events = []
    recovery_by_type: dict[int, int] = defaultdict(int)
    for msg in read_messages(bag_path=bag_path, topics=[recovery_topic]):
        data = msg.data
        recovery_type = data.get("type", data.get("recovery_type", 0))
        recovery_by_type[recovery_type] += 1
        recovery_events.append(msg.timestamp)
        all_timestamps.append(msg.timestamp)

    # Collect goals
    goal_timestamps = []
    for msg in read_messages(bag_path=bag_path, topics=[goal_topic]):
        goal_timestamps.append(msg.timestamp)
        all_timestamps.append(msg.timestamp)

    # Duration
    duration_s = 0.0
    if all_timestamps:
        duration_s = max(all_timestamps) - min(all_timestamps)

    # Health score (0-100)
    health_score = 100.0
    issues = []

    if errors:
        health_score -= min(40, len(errors) * 5)
        issues.append(f"{len(errors)} error(s) detected")

    if recovery_events:
        health_score -= min(30, len(recovery_events) * 10)
        issues.append(f"{len(recovery_events)} recovery event(s)")

    if error_categories["planning_failure"] > 0:
        issues.append(f"{error_categories['planning_failure']} planning failure(s)")

    if error_categories["collision_in_costmap"] > 0:
        issues.append(f"{error_categories['collision_in_costmap']} costmap collision(s)")

    if warning_categories["rate_miss"] > 5:
        health_score -= 10
        issues.append(f"{warning_categories['rate_miss']} rate miss warning(s)")

    if warning_categories["costmap_timeout"] > 0:
        health_score -= 5
        issues.append(f"{warning_categories['costmap_timeout']} costmap timeout(s)")

    health_score = max(0, health_score)

    if not issues:
        issues.append("No navigation issues detected")

    result = {
        "duration_s": round(duration_s, 3),
        "goals": {
            "total": len(goal_timestamps),
            "timestamps": goal_timestamps[:50],
        },
        "recovery_events": {
            "total": len(recovery_events),
            "by_type": dict(recovery_by_type),
            "timestamps": recovery_events[:50],
        },
        "errors": {
            "total": len(errors),
            "categories": error_categories,
            "samples": errors[:20],
        },
        "warnings": {
            "total": len(warnings),
            "categories": warning_categories,
        },
        "summary": {
            "health_score": round(health_score, 1),
            "issues": issues,
        },
    }

    return [TextContent(type="text", text=json_serialize(result))]


async def analyze_lidar_timeseries(
    scan_topic: str = "/scan",
    obstacle_threshold: float = 1.0,
    sample_interval: int = 1,
    start_time: float | None = None,
    end_time: float | None = None,
    bag_path: str | None = None,
) -> list[TextContent]:
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

    # Compute duration from first/last timeline entries (all sampled scans)
    duration_s = 0.0
    if len(timeline) > 1:
        duration_s = timeline[-1]["timestamp"] - timeline[0]["timestamp"]

    # Limit timeline to max 50 entries
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
