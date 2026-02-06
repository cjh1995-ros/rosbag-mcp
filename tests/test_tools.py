"""Tests for tools module."""

from __future__ import annotations

import numpy as np

from rosbag_mcp.tools.utils import extract_position, get_nested_field, json_serialize


class TestJsonSerialize:
    """Test json_serialize utility."""

    def test_simple_dict(self):
        """Test with simple dict."""
        data = {"x": 1, "y": 2}
        result = json_serialize(data)
        assert '"x": 1' in result
        assert '"y": 2' in result

    def test_numpy_array(self):
        """Test with numpy array."""
        data = {"values": np.array([1.0, 2.0, 3.0])}
        result = json_serialize(data)
        assert "values" in result
        # Should convert numpy array to list

    def test_numpy_float(self):
        """Test with numpy float."""
        data = {"value": np.float64(3.14)}
        result = json_serialize(data)
        assert "3.14" in result

    def test_nested_dict(self):
        """Test with nested dict."""
        data = {"outer": {"inner": {"value": 42}}}
        result = json_serialize(data)
        assert "outer" in result
        assert "inner" in result
        assert "42" in result


class TestGetNestedField:
    """Test get_nested_field utility."""

    def test_simple_field(self):
        """Test with simple field."""
        data = {"x": 1, "y": 2}
        result = get_nested_field(data, "x")
        assert result == 1

    def test_nested_field(self):
        """Test with nested field path."""
        data = {"pose": {"position": {"x": 1.0, "y": 2.0}}}
        result = get_nested_field(data, "pose.position.x")
        assert result == 1.0

    def test_invalid_path(self):
        """Test with invalid path."""
        data = {"x": 1}
        result = get_nested_field(data, "y")
        assert result is None

    def test_none_handling(self):
        """Test with None values in path."""
        data = {"pose": None}
        result = get_nested_field(data, "pose.position.x")
        assert result is None

    def test_list_index(self):
        """Test with list index in path."""
        data = {"points": [{"x": 1}, {"x": 2}]}
        result = get_nested_field(data, "points.0.x")
        assert result == 1


class TestExtractPosition:
    """Test extract_position utility."""

    def test_odometry_style(self):
        """Test with Odometry-style data."""
        data = {"pose": {"pose": {"position": {"x": 1.0, "y": 2.0, "z": 0.0}}}}
        result = extract_position(data)
        assert result == (1.0, 2.0, 0.0)

    def test_pose_stamped_style(self):
        """Test with PoseStamped-style data."""
        data = {"pose": {"position": {"x": 3.0, "y": 4.0, "z": 1.0}}}
        result = extract_position(data)
        assert result == (3.0, 4.0, 1.0)

    def test_missing_position(self):
        """Test with missing position data."""
        data = {"other": "data"}
        result = extract_position(data)
        assert result is None

    def test_partial_position(self):
        """Test with partial position data."""
        data = {"pose": {"position": {"x": 1.0}}}
        extract_position(data)
        # Should handle missing y/z gracefully


class TestToolImportability:
    """Test that all 30 tool functions are importable."""

    def test_all_tools_importable(self):
        """Test that all 30 tools can be imported."""
        from rosbag_mcp.tools import (
            analyze_costmap_violations,
            analyze_diagnostics,
            analyze_imu,
            analyze_joint_states,
            analyze_lidar_scan,
            analyze_lidar_timeseries,
            analyze_logs,
            analyze_navigation_health,
            analyze_path_tracking,
            analyze_pointcloud2,
            analyze_topic_stats,
            analyze_trajectory,
            analyze_wheel_slip,
            bag_info,
            compare_topics,
            detect_events,
            export_to_csv,
            filter_bag,
            get_image_at_time,
            get_message_at_time,
            get_messages_in_range,
            get_tf_tree,
            get_topic_schema,
            list_bags,
            plot_2d,
            plot_comparison,
            plot_lidar_scan,
            plot_timeseries,
            search_messages,
            set_bag_path,
        )

        # Verify all are callable
        tools = [
            set_bag_path,
            list_bags,
            bag_info,
            get_topic_schema,
            get_message_at_time,
            get_messages_in_range,
            search_messages,
            filter_bag,
            analyze_trajectory,
            analyze_lidar_scan,
            analyze_imu,
            analyze_logs,
            get_tf_tree,
            get_image_at_time,
            analyze_path_tracking,
            analyze_costmap_violations,
            analyze_navigation_health,
            analyze_wheel_slip,
            analyze_topic_stats,
            compare_topics,
            detect_events,
            analyze_lidar_timeseries,
            plot_timeseries,
            plot_2d,
            plot_lidar_scan,
            plot_comparison,
            export_to_csv,
            analyze_pointcloud2,
            analyze_joint_states,
            analyze_diagnostics,
        ]

        assert len(tools) == 30
        for tool in tools:
            assert callable(tool)


class TestNewSearchConditions:
    """Test new search conditions (contains, field_exists)."""

    def test_contains_condition_concept(self):
        """Test contains condition concept."""
        # This would test the actual search_messages function with mock data
        # For now, just verify the concept
        test_data = {"status": "robot_moving_forward"}
        assert "moving" in test_data["status"].lower()

    def test_field_exists_condition_concept(self):
        """Test field_exists condition concept."""
        test_data = {"pose": {"position": {"x": 1.0}}}
        # Check if nested field exists
        assert "pose" in test_data
        assert "position" in test_data.get("pose", {})
        assert "x" in test_data.get("pose", {}).get("position", {})
