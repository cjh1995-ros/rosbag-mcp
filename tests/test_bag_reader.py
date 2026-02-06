"""Tests for bag_reader.py module."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from rosbag_mcp.bag_reader import BagInfo, BagMessage, _msg_to_dict


class TestBagReaderPublicAPI:
    """Test that all public functions exist and are callable."""

    def test_public_functions_exist(self):
        """Test that all public functions are importable."""
        from rosbag_mcp.bag_reader import (
            get_bag_info,
            get_message_at_time,
            get_topic_schema,
            get_topic_timestamps,
            list_bags,
            read_messages,
            set_bag_path,
        )

        assert callable(set_bag_path)
        assert callable(list_bags)
        assert callable(get_bag_info)
        assert callable(get_topic_schema)
        assert callable(read_messages)
        assert callable(get_message_at_time)
        assert callable(get_topic_timestamps)


class TestMsgToDict:
    """Test _msg_to_dict recursive converter."""

    def test_simple_dict(self):
        """Test with simple dict."""
        data = {"x": 1, "y": 2}
        result = _msg_to_dict(data)
        assert result == {"x": 1, "y": 2}

    def test_nested_dict(self):
        """Test with nested dict."""
        data = {"pose": {"position": {"x": 1.0, "y": 2.0}}}
        result = _msg_to_dict(data)
        assert result == {"pose": {"position": {"x": 1.0, "y": 2.0}}}

    def test_dataclass_like_object(self):
        """Test with dataclass-like object."""

        @dataclass
        class Position:
            x: float
            y: float

        @dataclass
        class Pose:
            position: Position

        pose = Pose(position=Position(x=1.0, y=2.0))
        result = _msg_to_dict(pose)
        assert result == {"position": {"x": 1.0, "y": 2.0}}

    def test_list_of_dicts(self):
        """Test with list of dicts."""
        data = {"points": [{"x": 1, "y": 2}, {"x": 3, "y": 4}]}
        result = _msg_to_dict(data)
        assert result == {"points": [{"x": 1, "y": 2}, {"x": 3, "y": 4}]}

    def test_none_values(self):
        """Test with None values."""
        data = {"x": 1, "y": None}
        result = _msg_to_dict(data)
        assert result == {"x": 1, "y": None}


class TestBagInfo:
    """Test BagInfo dataclass."""

    def test_bag_info_creation(self):
        """Test BagInfo can be created."""
        info = BagInfo(
            path="/test.bag",
            duration=100.0,
            start_time=1000.0,
            end_time=1100.0,
            message_count=500,
            topics=[{"name": "/odom", "type": "nav_msgs/msg/Odometry", "count": 500}],
        )
        assert info.path == "/test.bag"
        assert info.duration == 100.0
        assert info.message_count == 500


class TestBagMessage:
    """Test BagMessage dataclass."""

    def test_bag_message_creation(self):
        """Test BagMessage can be created."""
        msg = BagMessage(
            topic="/odom",
            timestamp=1000.5,
            data={"pose": {"position": {"x": 1.0}}},
            msg_type="nav_msgs/msg/Odometry",
        )
        assert msg.topic == "/odom"
        assert msg.timestamp == 1000.5
        assert isinstance(msg.data, dict)
        assert msg.msg_type == "nav_msgs/msg/Odometry"
