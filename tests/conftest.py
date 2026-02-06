"""Pytest fixtures for rosbag-mcp tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest


@dataclass
class MockMessage:
    """Mock ROS message for testing."""

    topic: str
    timestamp: int
    data: dict[str, Any]
    msgtype: str


@pytest.fixture
def mock_odometry_msg():
    """Mock Odometry message."""
    return {
        "header": {"stamp": {"sec": 100, "nanosec": 0}, "frame_id": "odom"},
        "pose": {
            "pose": {
                "position": {"x": 1.0, "y": 2.0, "z": 0.0},
                "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
            }
        },
        "twist": {
            "twist": {
                "linear": {"x": 0.5, "y": 0.0, "z": 0.0},
                "angular": {"x": 0.0, "y": 0.0, "z": 0.1},
            }
        },
    }


@pytest.fixture
def mock_laser_scan_msg():
    """Mock LaserScan message."""
    return {
        "header": {"stamp": {"sec": 100, "nanosec": 0}, "frame_id": "laser"},
        "angle_min": -3.14,
        "angle_max": 3.14,
        "angle_increment": 0.01,
        "range_min": 0.1,
        "range_max": 30.0,
        "ranges": [1.0, 2.0, 3.0, 4.0, 5.0],
        "intensities": [100, 200, 150, 180, 120],
    }


@pytest.fixture
def mock_joint_state_msg():
    """Mock JointState message."""
    return {
        "header": {"stamp": {"sec": 100, "nanosec": 0}, "frame_id": ""},
        "name": ["joint1", "joint2", "joint3"],
        "position": [0.1, 0.2, 0.3],
        "velocity": [0.01, 0.02, 0.03],
        "effort": [1.0, 2.0, 3.0],
    }


@pytest.fixture
def mock_bag_info():
    """Mock BagInfo object."""
    from rosbag_mcp.bag_reader import BagInfo

    return BagInfo(
        path="/mock/test.bag",
        duration=100.0,
        start_time=1000.0,
        end_time=1100.0,
        message_count=1000,
        topics=[
            {"name": "/odom", "type": "nav_msgs/msg/Odometry", "count": 500},
            {"name": "/scan", "type": "sensor_msgs/msg/LaserScan", "count": 500},
        ],
    )


@pytest.fixture
def mock_bag_message():
    """Mock BagMessage object."""
    from rosbag_mcp.bag_reader import BagMessage

    return BagMessage(
        topic="/odom",
        timestamp=1000.5,
        data={
            "pose": {
                "pose": {
                    "position": {"x": 1.0, "y": 2.0, "z": 0.0},
                }
            }
        },
        msg_type="nav_msgs/msg/Odometry",
    )
