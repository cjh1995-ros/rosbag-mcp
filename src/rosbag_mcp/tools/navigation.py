from __future__ import annotations

import logging
import math
from collections import defaultdict

import numpy as np
from mcp.types import TextContent

from rosbag_mcp.bag_reader import read_messages
from rosbag_mcp.tools.utils import get_nested_field, json_serialize

logger = logging.getLogger(__name__)


async def analyze_costmap_violations(
    costmap_topic: str = "/move_base/local_costmap/costmap",
    pose_topic: str = "/amcl_pose",
    cost_threshold: int = 253,
    bag_path: str | None = None,
) -> list[TextContent]:
    """Check if the robot entered lethal costmap cells."""
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
    """Compute cross-track error between planned path and actual pose."""
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
    """Compare commanded vs actual velocity to detect wheel slip."""
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

    interp_cmd = np.interp(odom_data["times"], cmd_data["times"], cmd_data["values"])
    odom_values = np.array(odom_data["values"])
    odom_times = np.array(odom_data["times"])

    slip = odom_values - interp_cmd
    abs_slip = np.abs(slip)

    correlation = float(np.corrcoef(odom_values, interp_cmd)[0, 1])
    if np.isnan(correlation):
        correlation = 0.0

    rmse = float(np.sqrt(np.mean(slip**2)))

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
    """Aggregate navigation errors, recoveries, and compute health score."""
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

        if msg_level >= 8:
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

        elif msg_level == 4:
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

    recovery_events = []
    recovery_by_type: dict[int, int] = defaultdict(int)
    for msg in read_messages(bag_path=bag_path, topics=[recovery_topic]):
        data = msg.data
        recovery_type = data.get("type", data.get("recovery_type", 0))
        recovery_by_type[recovery_type] += 1
        recovery_events.append(msg.timestamp)
        all_timestamps.append(msg.timestamp)

    goal_timestamps = []
    for msg in read_messages(bag_path=bag_path, topics=[goal_topic]):
        goal_timestamps.append(msg.timestamp)
        all_timestamps.append(msg.timestamp)

    duration_s = 0.0
    if all_timestamps:
        duration_s = max(all_timestamps) - min(all_timestamps)

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
