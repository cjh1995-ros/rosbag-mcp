"""SLAM / odometry analysis tools."""

from __future__ import annotations

import logging
import math

import numpy as np
from mcp.types import TextContent

from rosbag_mcp.bag_reader import read_messages
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
    """Compute trajectory metrics: distance, displacement, speed, and waypoints."""
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


def _extract_covariance_diagonal(data: dict) -> tuple[float, float, float] | None:
    """Extract (xx, yy, yaw_yaw) from PoseWithCovarianceStamped covariance[36]."""
    pose_cov = data.get("pose", {})
    cov = pose_cov.get("covariance")
    if not cov or len(cov) < 36:
        return None
    return (float(cov[0]), float(cov[7]), float(cov[35]))


async def analyze_mcl_divergence(
    amcl_topic: str = "/amcl_pose",
    jump_threshold: float = 0.5,
    covariance_warn: float = 0.25,
    start_time: float | None = None,
    end_time: float | None = None,
    bag_path: str | None = None,
) -> list[TextContent]:
    """Detect AMCL relocalization jumps and covariance growth from PoseWithCovarianceStamped."""
    logger.info(f"Analyzing MCL divergence from {amcl_topic}")

    positions: list[tuple[float, float, float]] = []
    covariances: list[tuple[float, float, float]] = []
    timestamps: list[float] = []

    for msg in read_messages(
        bag_path=bag_path, topics=[amcl_topic], start_time=start_time, end_time=end_time
    ):
        pos = extract_position(msg.data)
        if not pos:
            continue

        positions.append(pos)
        timestamps.append(msg.timestamp)

        cov = _extract_covariance_diagonal(msg.data)
        covariances.append(cov if cov else (0.0, 0.0, 0.0))

    if len(positions) < 2:
        return [TextContent(type="text", text="Insufficient AMCL data (need >= 2 poses)")]

    has_covariance = any(c != (0.0, 0.0, 0.0) for c in covariances)

    jump_events = []
    consecutive_distances = []
    for i in range(1, len(positions)):
        dx = positions[i][0] - positions[i - 1][0]
        dy = positions[i][1] - positions[i - 1][1]
        dist = math.sqrt(dx * dx + dy * dy)
        dt = timestamps[i] - timestamps[i - 1]
        consecutive_distances.append(dist)

        if dist > jump_threshold:
            jump_events.append(
                {
                    "timestamp": timestamps[i],
                    "from": {
                        "x": round(positions[i - 1][0], 3),
                        "y": round(positions[i - 1][1], 3),
                    },
                    "to": {"x": round(positions[i][0], 3), "y": round(positions[i][1], 3)},
                    "distance_m": round(dist, 4),
                    "dt_s": round(dt, 4),
                }
            )

    dist_arr = np.array(consecutive_distances)

    result: dict = {
        "topic": amcl_topic,
        "message_count": len(positions),
        "duration_s": round(timestamps[-1] - timestamps[0], 3),
        "jump_detection": {
            "threshold_m": jump_threshold,
            "count": len(jump_events),
            "events": jump_events[:50],
        },
        "pose_step_distance": {
            "mean_m": round(float(np.mean(dist_arr)), 4),
            "std_m": round(float(np.std(dist_arr)), 4),
            "max_m": round(float(np.max(dist_arr)), 4),
            "median_m": round(float(np.median(dist_arr)), 4),
            "p95_m": round(float(np.percentile(dist_arr, 95)), 4),
        },
    }

    if has_covariance:
        cov_xx = np.array([c[0] for c in covariances])
        cov_yy = np.array([c[1] for c in covariances])
        cov_yaw = np.array([c[2] for c in covariances])
        position_uncertainty = np.sqrt(cov_xx + cov_yy)

        high_uncertainty_periods = []
        in_high = False
        high_start_idx = 0
        for i in range(len(position_uncertainty)):
            if position_uncertainty[i] > covariance_warn:
                if not in_high:
                    in_high = True
                    high_start_idx = i
            else:
                if in_high:
                    high_uncertainty_periods.append(
                        {
                            "start_time": timestamps[high_start_idx],
                            "end_time": timestamps[i - 1],
                            "duration_s": round(timestamps[i - 1] - timestamps[high_start_idx], 3),
                            "max_uncertainty_m": round(
                                float(np.max(position_uncertainty[high_start_idx:i])), 4
                            ),
                        }
                    )
                    in_high = False
        if in_high:
            high_uncertainty_periods.append(
                {
                    "start_time": timestamps[high_start_idx],
                    "end_time": timestamps[-1],
                    "duration_s": round(timestamps[-1] - timestamps[high_start_idx], 3),
                    "max_uncertainty_m": round(
                        float(np.max(position_uncertainty[high_start_idx:])), 4
                    ),
                }
            )

        cov_timeline = []
        step = max(1, len(timestamps) // 50)
        for i in range(0, len(timestamps), step):
            cov_timeline.append(
                {
                    "timestamp": timestamps[i],
                    "position_uncertainty_m": round(float(position_uncertainty[i]), 4),
                    "yaw_uncertainty_rad": round(float(math.sqrt(max(0.0, cov_yaw[i]))), 4),
                }
            )

        first_quarter = position_uncertainty[: len(position_uncertainty) // 4]
        last_quarter = position_uncertainty[3 * len(position_uncertainty) // 4 :]
        growing = bool(
            len(first_quarter) > 0
            and len(last_quarter) > 0
            and float(np.mean(last_quarter)) > float(np.mean(first_quarter)) * 1.5
        )

        result["covariance_analysis"] = {
            "position_uncertainty_m": {
                "mean": round(float(np.mean(position_uncertainty)), 4),
                "std": round(float(np.std(position_uncertainty)), 4),
                "min": round(float(np.min(position_uncertainty)), 4),
                "max": round(float(np.max(position_uncertainty)), 4),
            },
            "yaw_uncertainty_rad": {
                "mean": round(float(np.mean(np.sqrt(np.maximum(0.0, cov_yaw)))), 4),
                "max": round(float(np.max(np.sqrt(np.maximum(0.0, cov_yaw)))), 4),
            },
            "warn_threshold_m": covariance_warn,
            "high_uncertainty_periods": high_uncertainty_periods[:20],
            "uncertainty_growing": growing,
            "timeline": cov_timeline,
        }
    else:
        result["covariance_analysis"] = None

    health_score = 100.0
    issues = []

    if jump_events:
        health_score -= min(40, len(jump_events) * 10)
        issues.append(f"{len(jump_events)} relocalization jump(s) detected")

    if has_covariance:
        if high_uncertainty_periods:
            health_score -= min(30, len(high_uncertainty_periods) * 5)
            issues.append(f"{len(high_uncertainty_periods)} high-uncertainty period(s)")
        if growing:
            health_score -= 20
            issues.append("Covariance growing over time — particle filter may be diverging")

    health_score = max(0.0, health_score)
    if not issues:
        issues.append("No divergence detected")

    result["summary"] = {
        "health_score": round(health_score, 1),
        "issues": issues,
    }

    return [TextContent(type="text", text=json_serialize(result))]
