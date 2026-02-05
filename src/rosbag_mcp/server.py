from __future__ import annotations

import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, ImageContent, Tool

from rosbag_mcp.tools import (
    set_bag_path,
    list_bags,
    bag_info,
    get_message_at_time,
    get_messages_in_range,
    search_messages,
    filter_bag,
    analyze_trajectory,
    analyze_lidar_scan,
    analyze_logs,
    get_tf_tree,
    get_image_at_time,
    plot_timeseries,
    plot_2d,
    plot_lidar_scan,
    plot_comparison,
    get_topic_schema,
    analyze_imu,
    analyze_topic_stats,
    compare_topics,
    export_to_csv,
    detect_events,
    analyze_costmap_violations,
    analyze_path_tracking,
    analyze_wheel_slip,
    analyze_navigation_health,
    analyze_lidar_timeseries,
)

server = Server("rosbag-mcp")

TOOL_DEFINITIONS = [
    Tool(
        name="set_bag_path",
        description="Set the path to a rosbag file or directory containing rosbags",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to a rosbag file (.bag, .mcap, .db3) or directory",
                }
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="list_bags",
        description="List all available rosbag files in the directory",
        inputSchema={
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Optional: directory to search (uses current if not specified)",
                }
            },
            "required": [],
        },
    ),
    Tool(
        name="bag_info",
        description="Retrieve bag metadata: topics, message counts, duration, time range",
        inputSchema={
            "type": "object",
            "properties": {
                "bag_path": {
                    "type": "string",
                    "description": "Optional: specific bag file (uses current if not specified)",
                }
            },
            "required": [],
        },
    ),
    Tool(
        name="get_message_at_time",
        description="Get message from a topic at a specific timestamp",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "ROS topic name"},
                "timestamp": {"type": "number", "description": "Unix timestamp in seconds"},
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
                "tolerance": {
                    "type": "number",
                    "description": "Time tolerance in seconds (default: 0.1)",
                },
            },
            "required": ["topic", "timestamp"],
        },
    ),
    Tool(
        name="get_messages_in_range",
        description="Get all messages from a topic within a time range",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "ROS topic name"},
                "start_time": {
                    "type": "number",
                    "description": "Start unix timestamp in seconds",
                },
                "end_time": {"type": "number", "description": "End unix timestamp in seconds"},
                "max_messages": {
                    "type": "integer",
                    "description": "Maximum messages to return (default: 100)",
                },
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": ["topic", "start_time", "end_time"],
        },
    ),
    Tool(
        name="search_messages",
        description="Search messages using conditions (regex, equals, near_position, threshold)",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "ROS topic name"},
                "condition_type": {
                    "type": "string",
                    "enum": ["regex", "equals", "greater_than", "less_than", "near_position"],
                    "description": "Type of search condition",
                },
                "field": {
                    "type": "string",
                    "description": "Field path to search (e.g., 'linear.x' for velocity)",
                },
                "value": {
                    "type": "string",
                    "description": "Value to search for. For near_position: 'x,y,radius'",
                },
                "limit": {"type": "integer", "description": "Maximum results (default: 10)"},
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": ["topic", "condition_type", "value"],
        },
    ),
    Tool(
        name="filter_bag",
        description="Create a filtered copy of a bag file by topic, time, or sample rate",
        inputSchema={
            "type": "object",
            "properties": {
                "output_path": {
                    "type": "string",
                    "description": "Output path for filtered bag",
                },
                "topics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Topics to include",
                },
                "start_time": {"type": "number", "description": "Optional: start time filter"},
                "end_time": {"type": "number", "description": "Optional: end time filter"},
                "bag_path": {"type": "string", "description": "Optional: source bag file"},
            },
            "required": ["output_path", "topics"],
        },
    ),
    Tool(
        name="analyze_trajectory",
        description="Compute trajectory metrics: total distance, mean/max speeds, position bounds, waypoints",
        inputSchema={
            "type": "object",
            "properties": {
                "pose_topic": {
                    "type": "string",
                    "description": "Topic with pose/odometry data (default: /odom)",
                },
                "start_time": {"type": "number", "description": "Optional: start time"},
                "end_time": {"type": "number", "description": "Optional: end time"},
                "include_waypoints": {
                    "type": "boolean",
                    "description": "Include sampled waypoints (default: false)",
                },
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": [],
        },
    ),
    Tool(
        name="analyze_lidar_scan",
        description="Analyze LiDAR scans for obstacles, gaps, and statistics",
        inputSchema={
            "type": "object",
            "properties": {
                "scan_topic": {
                    "type": "string",
                    "description": "LiDAR scan topic (default: /scan)",
                },
                "timestamp": {
                    "type": "number",
                    "description": "Optional: specific timestamp to analyze",
                },
                "obstacle_threshold": {
                    "type": "number",
                    "description": "Distance threshold for obstacles in meters (default: 1.0)",
                },
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": [],
        },
    ),
    Tool(
        name="analyze_logs",
        description="Parse and analyze ROS logs; filter by level or node",
        inputSchema={
            "type": "object",
            "properties": {
                "log_topic": {"type": "string", "description": "Log topic (default: /rosout)"},
                "level": {
                    "type": "string",
                    "enum": ["DEBUG", "INFO", "WARN", "ERROR", "FATAL"],
                    "description": "Filter by log level",
                },
                "node_filter": {"type": "string", "description": "Filter by node name (regex)"},
                "limit": {
                    "type": "integer",
                    "description": "Maximum logs to return (default: 50)",
                },
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": [],
        },
    ),
    Tool(
        name="get_tf_tree",
        description="Get TF tree of coordinate frame relationships",
        inputSchema={
            "type": "object",
            "properties": {
                "bag_path": {"type": "string", "description": "Optional: specific bag file"}
            },
            "required": [],
        },
    ),
    Tool(
        name="get_image_at_time",
        description="Extract camera image at specific time (returns base64 JPEG)",
        inputSchema={
            "type": "object",
            "properties": {
                "image_topic": {"type": "string", "description": "Image topic name"},
                "timestamp": {"type": "number", "description": "Unix timestamp in seconds"},
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": ["image_topic", "timestamp"],
        },
    ),
    Tool(
        name="plot_timeseries",
        description="Plot time series data with multiple fields/styles",
        inputSchema={
            "type": "object",
            "properties": {
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Fields to plot (e.g., ['odom.twist.twist.linear.x', 'cmd_vel.linear.x'])",
                },
                "start_time": {"type": "number", "description": "Optional: start time"},
                "end_time": {"type": "number", "description": "Optional: end time"},
                "title": {"type": "string", "description": "Plot title"},
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": ["fields"],
        },
    ),
    Tool(
        name="plot_2d",
        description="Create 2D trajectory plot (XY positions)",
        inputSchema={
            "type": "object",
            "properties": {
                "pose_topic": {
                    "type": "string",
                    "description": "Topic with pose/odometry data (default: /odom)",
                },
                "start_time": {"type": "number", "description": "Optional: start time"},
                "end_time": {"type": "number", "description": "Optional: end time"},
                "title": {"type": "string", "description": "Plot title"},
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": [],
        },
    ),
    Tool(
        name="plot_lidar_scan",
        description="Visualize LiDAR scans as polar plots",
        inputSchema={
            "type": "object",
            "properties": {
                "scan_topic": {
                    "type": "string",
                    "description": "LiDAR scan topic (default: /scan)",
                },
                "timestamp": {"type": "number", "description": "Timestamp to visualize"},
                "title": {"type": "string", "description": "Plot title"},
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": ["timestamp"],
        },
    ),
    Tool(
        name="get_topic_schema",
        description="Get message structure/schema for a topic with sample data",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "ROS topic name"},
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": ["topic"],
        },
    ),
    Tool(
        name="analyze_imu",
        description="Analyze IMU data: orientation, linear acceleration, angular velocity statistics",
        inputSchema={
            "type": "object",
            "properties": {
                "imu_topic": {
                    "type": "string",
                    "description": "IMU topic (default: /imu)",
                },
                "start_time": {"type": "number", "description": "Optional: start time"},
                "end_time": {"type": "number", "description": "Optional: end time"},
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": [],
        },
    ),
    Tool(
        name="analyze_topic_stats",
        description="Analyze topic statistics: frequency, latency, message intervals, gaps",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "ROS topic name"},
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": ["topic"],
        },
    ),
    Tool(
        name="compare_topics",
        description="Compare two topic fields: correlation, difference, RMSE",
        inputSchema={
            "type": "object",
            "properties": {
                "topic1": {"type": "string", "description": "First topic name"},
                "topic2": {"type": "string", "description": "Second topic name"},
                "field1": {
                    "type": "string",
                    "description": "Field path in first topic (e.g., 'twist.twist.linear.x')",
                },
                "field2": {
                    "type": "string",
                    "description": "Field path in second topic",
                },
                "start_time": {"type": "number", "description": "Optional: start time"},
                "end_time": {"type": "number", "description": "Optional: end time"},
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": ["topic1", "topic2", "field1", "field2"],
        },
    ),
    Tool(
        name="export_to_csv",
        description="Export topic data to CSV file for external analysis",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "ROS topic name"},
                "output_path": {"type": "string", "description": "Output CSV file path"},
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: specific fields to export (exports all if not specified)",
                },
                "start_time": {"type": "number", "description": "Optional: start time"},
                "end_time": {"type": "number", "description": "Optional: end time"},
                "max_messages": {
                    "type": "integer",
                    "description": "Maximum messages to export (default: 10000)",
                },
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": ["topic", "output_path"],
        },
    ),
    Tool(
        name="detect_events",
        description="Detect events in topic data: threshold crossings, sudden changes, anomalies, stoppages",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "ROS topic name"},
                "field": {"type": "string", "description": "Field path to analyze"},
                "event_type": {
                    "type": "string",
                    "enum": ["threshold", "threshold_below", "sudden_change", "anomaly", "stoppage"],
                    "description": "Type of event to detect",
                },
                "threshold": {
                    "type": "number",
                    "description": "Threshold value (meaning depends on event_type)",
                },
                "window_size": {
                    "type": "integer",
                    "description": "Window size for detection (default: 10)",
                },
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": ["topic", "field"],
        },
    ),
    Tool(
        name="analyze_costmap_violations",
        description="Check if robot entered obstacle/lethal cells in costmap (collision detection)",
        inputSchema={
            "type": "object",
            "properties": {
                "costmap_topic": {
                    "type": "string",
                    "description": "Costmap topic (default: /move_base/local_costmap/costmap)",
                },
                "pose_topic": {
                    "type": "string",
                    "description": "Pose topic (default: /amcl_pose)",
                },
                "cost_threshold": {
                    "type": "integer",
                    "description": "Cost threshold for violation (default: 253, lethal=254-255)",
                },
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": [],
        },
    ),
    Tool(
        name="analyze_path_tracking",
        description="Analyze path tracking: cross-track error between planned path and actual pose (MCL/odom)",
        inputSchema={
            "type": "object",
            "properties": {
                "path_topic": {
                    "type": "string",
                    "description": "Path topic (default: /move_base/GlobalPlanner/plan)",
                },
                "pose_topic": {
                    "type": "string",
                    "description": "Pose topic (default: /amcl_pose). Supports Odometry or PoseWithCovarianceStamped",
                },
                "start_time": {"type": "number", "description": "Optional: start time"},
                "end_time": {"type": "number", "description": "Optional: end time"},
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": [],
        },
    ),
    Tool(
        name="analyze_wheel_slip",
        description="Compare commanded velocity vs actual odometry velocity to detect traction loss and wheel slip",
        inputSchema={
            "type": "object",
            "properties": {
                "cmd_vel_topic": {
                    "type": "string",
                    "description": "Commanded velocity topic (default: /cmd_vel)",
                },
                "odom_topic": {
                    "type": "string",
                    "description": "Odometry topic (default: /odom)",
                },
                "cmd_vel_field": {
                    "type": "string",
                    "description": "Field path for commanded velocity (default: twist.linear.x)",
                },
                "odom_field": {
                    "type": "string",
                    "description": "Field path for actual velocity (default: twist.twist.linear.x)",
                },
                "slip_threshold": {
                    "type": "number",
                    "description": "Minimum difference to consider as slip in m/s (default: 0.1)",
                },
                "start_time": {"type": "number", "description": "Optional: start time"},
                "end_time": {"type": "number", "description": "Optional: end time"},
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": [],
        },
    ),
    Tool(
        name="analyze_navigation_health",
        description="Aggregate navigation errors, recovery events, and goal outcomes for health assessment",
        inputSchema={
            "type": "object",
            "properties": {
                "log_topic": {
                    "type": "string",
                    "description": "Log topic (default: /rosout)",
                },
                "recovery_topic": {
                    "type": "string",
                    "description": "Recovery events topic (default: /move_base/debug/recovery_events)",
                },
                "goal_topic": {
                    "type": "string",
                    "description": "Navigation goal topic (default: /move_base/goal)",
                },
                "nav_status_topic": {
                    "type": "string",
                    "description": "Navigation status topic (default: /move_base/navigation_status)",
                },
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": [],
        },
    ),
    Tool(
        name="analyze_lidar_timeseries",
        description="Track LiDAR statistics over time: min distance, obstacle count, closest approach",
        inputSchema={
            "type": "object",
            "properties": {
                "scan_topic": {
                    "type": "string",
                    "description": "LiDAR scan topic (default: /scan)",
                },
                "obstacle_threshold": {
                    "type": "number",
                    "description": "Distance threshold for obstacles in meters (default: 1.0)",
                },
                "sample_interval": {
                    "type": "integer",
                    "description": "Sample every Nth scan to reduce data (default: 1)",
                },
                "start_time": {"type": "number", "description": "Optional: start time"},
                "end_time": {"type": "number", "description": "Optional: end time"},
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": [],
        },
    ),
    Tool(
        name="plot_comparison",
        description="Overlay plot of two topic fields with difference highlighting",
        inputSchema={
            "type": "object",
            "properties": {
                "topic1": {"type": "string", "description": "First topic name"},
                "topic2": {"type": "string", "description": "Second topic name"},
                "field1": {
                    "type": "string",
                    "description": "Field path in first topic",
                },
                "field2": {
                    "type": "string",
                    "description": "Field path in second topic",
                },
                "start_time": {"type": "number", "description": "Optional: start time"},
                "end_time": {"type": "number", "description": "Optional: end time"},
                "title": {"type": "string", "description": "Plot title (default: Topic Comparison)"},
                "bag_path": {"type": "string", "description": "Optional: specific bag file"},
            },
            "required": ["topic1", "topic2", "field1", "field2"],
        },
    ),
]

TOOL_HANDLERS = {
    "set_bag_path": lambda args: set_bag_path(args["path"]),
    "list_bags": lambda args: list_bags(args.get("directory")),
    "bag_info": lambda args: bag_info(args.get("bag_path")),
    "get_message_at_time": lambda args: get_message_at_time(
        topic=args["topic"],
        timestamp=args["timestamp"],
        bag_path=args.get("bag_path"),
        tolerance=args.get("tolerance", 0.1),
    ),
    "get_messages_in_range": lambda args: get_messages_in_range(
        topic=args["topic"],
        start_time=args["start_time"],
        end_time=args["end_time"],
        bag_path=args.get("bag_path"),
        max_messages=args.get("max_messages", 100),
    ),
    "search_messages": lambda args: search_messages(
        topic=args["topic"],
        condition_type=args["condition_type"],
        value=args["value"],
        field=args.get("field"),
        limit=args.get("limit", 10),
        bag_path=args.get("bag_path"),
    ),
    "filter_bag": lambda args: filter_bag(
        output_path=args["output_path"],
        topics=args["topics"],
        start_time=args.get("start_time"),
        end_time=args.get("end_time"),
        bag_path=args.get("bag_path"),
    ),
    "analyze_trajectory": lambda args: analyze_trajectory(
        pose_topic=args.get("pose_topic", "/odom"),
        start_time=args.get("start_time"),
        end_time=args.get("end_time"),
        include_waypoints=args.get("include_waypoints", False),
        bag_path=args.get("bag_path"),
    ),
    "analyze_lidar_scan": lambda args: analyze_lidar_scan(
        scan_topic=args.get("scan_topic", "/scan"),
        timestamp=args.get("timestamp"),
        obstacle_threshold=args.get("obstacle_threshold", 1.0),
        bag_path=args.get("bag_path"),
    ),
    "analyze_logs": lambda args: analyze_logs(
        log_topic=args.get("log_topic", "/rosout"),
        level=args.get("level"),
        node_filter=args.get("node_filter"),
        limit=args.get("limit", 50),
        bag_path=args.get("bag_path"),
    ),
    "get_tf_tree": lambda args: get_tf_tree(bag_path=args.get("bag_path")),
    "get_image_at_time": lambda args: get_image_at_time(
        image_topic=args["image_topic"],
        timestamp=args["timestamp"],
        bag_path=args.get("bag_path"),
    ),
    "plot_timeseries": lambda args: plot_timeseries(
        fields=args["fields"],
        start_time=args.get("start_time"),
        end_time=args.get("end_time"),
        title=args.get("title", "Time Series Plot"),
        bag_path=args.get("bag_path"),
    ),
    "plot_2d": lambda args: plot_2d(
        pose_topic=args.get("pose_topic", "/odom"),
        start_time=args.get("start_time"),
        end_time=args.get("end_time"),
        title=args.get("title", "2D Trajectory"),
        bag_path=args.get("bag_path"),
    ),
    "plot_lidar_scan": lambda args: plot_lidar_scan(
        timestamp=args["timestamp"],
        scan_topic=args.get("scan_topic", "/scan"),
        title=args.get("title", "LiDAR Scan"),
        bag_path=args.get("bag_path"),
    ),
    "get_topic_schema": lambda args: get_topic_schema(
        topic=args["topic"],
        bag_path=args.get("bag_path"),
    ),
    "analyze_imu": lambda args: analyze_imu(
        imu_topic=args.get("imu_topic", "/imu"),
        start_time=args.get("start_time"),
        end_time=args.get("end_time"),
        bag_path=args.get("bag_path"),
    ),
    "analyze_topic_stats": lambda args: analyze_topic_stats(
        topic=args["topic"],
        bag_path=args.get("bag_path"),
    ),
    "compare_topics": lambda args: compare_topics(
        topic1=args["topic1"],
        topic2=args["topic2"],
        field1=args["field1"],
        field2=args["field2"],
        start_time=args.get("start_time"),
        end_time=args.get("end_time"),
        bag_path=args.get("bag_path"),
    ),
    "export_to_csv": lambda args: export_to_csv(
        topic=args["topic"],
        output_path=args["output_path"],
        fields=args.get("fields"),
        start_time=args.get("start_time"),
        end_time=args.get("end_time"),
        max_messages=args.get("max_messages", 10000),
        bag_path=args.get("bag_path"),
    ),
    "detect_events": lambda args: detect_events(
        topic=args["topic"],
        field=args["field"],
        event_type=args.get("event_type", "threshold"),
        threshold=args.get("threshold"),
        window_size=args.get("window_size", 10),
        bag_path=args.get("bag_path"),
    ),
    "analyze_costmap_violations": lambda args: analyze_costmap_violations(
        costmap_topic=args.get("costmap_topic", "/move_base/local_costmap/costmap"),
        pose_topic=args.get("pose_topic", "/amcl_pose"),
        cost_threshold=args.get("cost_threshold", 253),
        bag_path=args.get("bag_path"),
    ),
    "analyze_path_tracking": lambda args: analyze_path_tracking(
        path_topic=args.get("path_topic", "/move_base/GlobalPlanner/plan"),
        pose_topic=args.get("pose_topic", "/amcl_pose"),
        start_time=args.get("start_time"),
        end_time=args.get("end_time"),
        bag_path=args.get("bag_path"),
    ),
    "analyze_wheel_slip": lambda args: analyze_wheel_slip(
        cmd_vel_topic=args.get("cmd_vel_topic", "/cmd_vel"),
        odom_topic=args.get("odom_topic", "/odom"),
        cmd_vel_field=args.get("cmd_vel_field", "twist.linear.x"),
        odom_field=args.get("odom_field", "twist.twist.linear.x"),
        slip_threshold=args.get("slip_threshold", 0.1),
        start_time=args.get("start_time"),
        end_time=args.get("end_time"),
        bag_path=args.get("bag_path"),
    ),
    "analyze_navigation_health": lambda args: analyze_navigation_health(
        log_topic=args.get("log_topic", "/rosout"),
        recovery_topic=args.get("recovery_topic", "/move_base/debug/recovery_events"),
        goal_topic=args.get("goal_topic", "/move_base/goal"),
        nav_status_topic=args.get("nav_status_topic", "/move_base/navigation_status"),
        bag_path=args.get("bag_path"),
    ),
    "analyze_lidar_timeseries": lambda args: analyze_lidar_timeseries(
        scan_topic=args.get("scan_topic", "/scan"),
        obstacle_threshold=args.get("obstacle_threshold", 1.0),
        sample_interval=args.get("sample_interval", 1),
        start_time=args.get("start_time"),
        end_time=args.get("end_time"),
        bag_path=args.get("bag_path"),
    ),
    "plot_comparison": lambda args: plot_comparison(
        topic1=args["topic1"],
        topic2=args["topic2"],
        field1=args["field1"],
        field2=args["field2"],
        start_time=args.get("start_time"),
        end_time=args.get("end_time"),
        title=args.get("title", "Topic Comparison"),
        bag_path=args.get("bag_path"),
    ),
}


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return TOOL_DEFINITIONS


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent | ImageContent]:
    try:
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
        return await handler(arguments)
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def run_server():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
