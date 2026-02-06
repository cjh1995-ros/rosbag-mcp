from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ServerConfig — loads server settings from YAML or dict defaults
# ---------------------------------------------------------------------------


class ServerConfig:
    """Server configuration with YAML loading and dict fallback."""

    # Default configuration values
    _DEFAULTS = {
        "time_tolerance": 0.1,
        "cache_max_open": 3,
        "cache_idle_ttl": 300,
        "image_max_size": 1024,
        "image_quality": 85,
        "log_level": "INFO",
    }

    def __init__(self, config_path: str | Path | None = None) -> None:
        """Load configuration from YAML file or use defaults.

        Args:
            config_path: Optional path to YAML config file. If None, uses defaults.
        """
        self._config: dict[str, Any] = self._DEFAULTS.copy()

        if config_path is not None:
            self._load_yaml(config_path)

    def _load_yaml(self, config_path: str | Path) -> None:
        """Load configuration from YAML file."""
        if yaml is None:
            logger.warning(
                "PyYAML not installed, using default configuration. "
                "Install with: pip install pyyaml"
            )
            return

        try:
            path = Path(config_path)
            if not path.exists():
                logger.warning("Config file not found: %s, using defaults", config_path)
                return

            with path.open("r") as f:
                loaded = yaml.safe_load(f)
                if loaded and isinstance(loaded, dict):
                    self._config.update(loaded)
                    logger.info("Loaded configuration from %s", config_path)
        except Exception as e:
            logger.error("Failed to load config from %s: %s", config_path, e)

    @property
    def time_tolerance(self) -> float:
        """Time tolerance in seconds for message matching."""
        return float(self._config["time_tolerance"])

    @property
    def cache_max_open(self) -> int:
        """Maximum number of open bag handles in cache."""
        return int(self._config["cache_max_open"])

    @property
    def cache_idle_ttl(self) -> int:
        """Idle TTL in seconds for cached bag handles."""
        return int(self._config["cache_idle_ttl"])

    @property
    def image_max_size(self) -> int:
        """Maximum image dimension (width/height) in pixels."""
        return int(self._config["image_max_size"])

    @property
    def image_quality(self) -> int:
        """JPEG quality (0-100) for image extraction."""
        return int(self._config["image_quality"])

    @property
    def log_level(self) -> str:
        """Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)."""
        return str(self._config["log_level"])


# ---------------------------------------------------------------------------
# SchemaManager — loads message field schemas from YAML
# ---------------------------------------------------------------------------


class SchemaManager:
    """Manages ROS message field schemas for dynamic field extraction."""

    # Default schemas (hardcoded fallback if YAML not available)
    _DEFAULT_SCHEMAS = {
        "nav_msgs/Odometry": {
            "position_fields": [
                "pose.pose.position.x",
                "pose.pose.position.y",
                "pose.pose.position.z",
            ],
            "velocity_fields": ["twist.twist.linear.x", "twist.twist.angular.z"],
            "timestamp_field": "header.stamp",
        },
        "nav_msgs/msg/Odometry": {
            "position_fields": [
                "pose.pose.position.x",
                "pose.pose.position.y",
                "pose.pose.position.z",
            ],
            "velocity_fields": ["twist.twist.linear.x", "twist.twist.angular.z"],
            "timestamp_field": "header.stamp",
        },
        "geometry_msgs/PoseStamped": {
            "position_fields": ["pose.position.x", "pose.position.y", "pose.position.z"],
            "orientation_fields": [
                "pose.orientation.x",
                "pose.orientation.y",
                "pose.orientation.z",
                "pose.orientation.w",
            ],
            "timestamp_field": "header.stamp",
        },
        "geometry_msgs/msg/PoseStamped": {
            "position_fields": ["pose.position.x", "pose.position.y", "pose.position.z"],
            "orientation_fields": [
                "pose.orientation.x",
                "pose.orientation.y",
                "pose.orientation.z",
                "pose.orientation.w",
            ],
            "timestamp_field": "header.stamp",
        },
        "sensor_msgs/LaserScan": {
            "range_fields": ["ranges"],
            "angle_fields": ["angle_min", "angle_max", "angle_increment"],
            "timestamp_field": "header.stamp",
        },
        "sensor_msgs/msg/LaserScan": {
            "range_fields": ["ranges"],
            "angle_fields": ["angle_min", "angle_max", "angle_increment"],
            "timestamp_field": "header.stamp",
        },
        "sensor_msgs/Imu": {
            "linear_acceleration_fields": [
                "linear_acceleration.x",
                "linear_acceleration.y",
                "linear_acceleration.z",
            ],
            "angular_velocity_fields": [
                "angular_velocity.x",
                "angular_velocity.y",
                "angular_velocity.z",
            ],
            "orientation_fields": [
                "orientation.x",
                "orientation.y",
                "orientation.z",
                "orientation.w",
            ],
            "timestamp_field": "header.stamp",
        },
        "sensor_msgs/msg/Imu": {
            "linear_acceleration_fields": [
                "linear_acceleration.x",
                "linear_acceleration.y",
                "linear_acceleration.z",
            ],
            "angular_velocity_fields": [
                "angular_velocity.x",
                "angular_velocity.y",
                "angular_velocity.z",
            ],
            "orientation_fields": [
                "orientation.x",
                "orientation.y",
                "orientation.z",
                "orientation.w",
            ],
            "timestamp_field": "header.stamp",
        },
        "sensor_msgs/JointState": {
            "position_fields": ["position"],
            "velocity_fields": ["velocity"],
            "effort_fields": ["effort"],
            "timestamp_field": "header.stamp",
        },
        "sensor_msgs/msg/JointState": {
            "position_fields": ["position"],
            "velocity_fields": ["velocity"],
            "effort_fields": ["effort"],
            "timestamp_field": "header.stamp",
        },
        "sensor_msgs/PointCloud2": {
            "data_fields": ["data"],
            "timestamp_field": "header.stamp",
        },
        "sensor_msgs/msg/PointCloud2": {
            "data_fields": ["data"],
            "timestamp_field": "header.stamp",
        },
        "diagnostic_msgs/DiagnosticArray": {
            "status_fields": ["status"],
            "timestamp_field": "header.stamp",
        },
        "diagnostic_msgs/msg/DiagnosticArray": {
            "status_fields": ["status"],
            "timestamp_field": "header.stamp",
        },
        "rosgraph_msgs/Log": {
            "level_field": "level",
            "message_field": "msg",
            "timestamp_field": "header.stamp",
        },
        "rcl_interfaces/msg/Log": {
            "level_field": "level",
            "message_field": "msg",
            "timestamp_field": "stamp",
        },
    }

    def __init__(self, schema_path: str | Path | None = None) -> None:
        """Load message schemas from YAML file or use defaults.

        Args:
            schema_path: Optional path to YAML schema file. If None, uses defaults.
        """
        self._schemas: dict[str, dict[str, Any]] = self._DEFAULT_SCHEMAS.copy()

        if schema_path is not None:
            self._load_yaml(schema_path)

    def _load_yaml(self, schema_path: str | Path) -> None:
        """Load schemas from YAML file."""
        if yaml is None:
            logger.warning(
                "PyYAML not installed, using default schemas. Install with: pip install pyyaml"
            )
            return

        try:
            path = Path(schema_path)
            if not path.exists():
                logger.warning("Schema file not found: %s, using defaults", schema_path)
                return

            with path.open("r") as f:
                loaded = yaml.safe_load(f)
                if loaded and isinstance(loaded, dict):
                    self._schemas.update(loaded)
                    logger.info("Loaded message schemas from %s", schema_path)
        except Exception as e:
            logger.error("Failed to load schemas from %s: %s", schema_path, e)

    def get_position_fields(self, msg_type: str) -> list[str]:
        """Get position field paths for a message type.

        Args:
            msg_type: ROS message type (e.g., "nav_msgs/Odometry")

        Returns:
            List of field paths (e.g., ["pose.pose.position.x", ...])
        """
        schema = self._schemas.get(msg_type, {})
        return schema.get("position_fields", [])

    def get_velocity_fields(self, msg_type: str) -> list[str]:
        """Get velocity field paths for a message type.

        Args:
            msg_type: ROS message type

        Returns:
            List of field paths (e.g., ["twist.twist.linear.x", ...])
        """
        schema = self._schemas.get(msg_type, {})
        return schema.get("velocity_fields", [])

    def get_timestamp_field(self, msg_type: str) -> str | None:
        """Get timestamp field path for a message type.

        Args:
            msg_type: ROS message type

        Returns:
            Field path (e.g., "header.stamp") or None if not defined
        """
        schema = self._schemas.get(msg_type, {})
        return schema.get("timestamp_field")

    def quaternion_to_euler(self, quat_dict: dict[str, float]) -> tuple[float, float, float]:
        """Convert quaternion to Euler angles (roll, pitch, yaw).

        Args:
            quat_dict: Dictionary with keys 'x', 'y', 'z', 'w'

        Returns:
            Tuple of (roll, pitch, yaw) in radians
        """
        x = quat_dict.get("x", 0.0)
        y = quat_dict.get("y", 0.0)
        z = quat_dict.get("z", 0.0)
        w = quat_dict.get("w", 1.0)

        # Roll (x-axis rotation)
        sinr_cosp = 2.0 * (w * x + y * z)
        cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
        roll = math.atan2(sinr_cosp, cosr_cosp)

        # Pitch (y-axis rotation)
        sinp = 2.0 * (w * y - z * x)
        if abs(sinp) >= 1:
            pitch = math.copysign(math.pi / 2, sinp)  # Use 90 degrees if out of range
        else:
            pitch = math.asin(sinp)

        # Yaw (z-axis rotation)
        siny_cosp = 2.0 * (w * z + x * y)
        cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
        yaw = math.atan2(siny_cosp, cosy_cosp)

        return roll, pitch, yaw

    def downsample_array(self, arr: list[Any], max_len: int) -> list[Any]:
        """Downsample array to maximum length by uniform sampling.

        Args:
            arr: Input array
            max_len: Maximum output length

        Returns:
            Downsampled array
        """
        if len(arr) <= max_len:
            return arr

        # Uniform sampling with step
        step = len(arr) / max_len
        indices = [int(i * step) for i in range(max_len)]
        return [arr[i] for i in indices]
