from __future__ import annotations

import logging
from dataclasses import asdict

from mcp.types import TextContent

from rosbag_mcp.bag_reader import (
    get_bag_info as _get_bag_info,
)
from rosbag_mcp.bag_reader import (
    list_bags as _list_bags,
)
from rosbag_mcp.bag_reader import (
    set_bag_path as _set_bag_path,
)
from rosbag_mcp.tools.utils import json_serialize

logger = logging.getLogger(__name__)


async def set_bag_path(path: str) -> list[TextContent]:
    """Set the active rosbag file or directory path."""
    logger.info(f"Setting bag path to: {path}")
    result = _set_bag_path(path)
    logger.debug(f"Bag path set successfully: {result}")
    return [TextContent(type="text", text=result)]


async def list_bags(directory: str | None = None) -> list[TextContent]:
    """List all rosbag files in the given or current directory."""
    logger.info(f"Listing bags in directory: {directory or 'current'}")
    bags = _list_bags(directory)
    logger.debug(f"Found {len(bags)} bag files")
    return [TextContent(type="text", text=json_serialize(bags))]


async def bag_info(bag_path: str | None = None) -> list[TextContent]:
    """Retrieve bag metadata including topics, message counts, and duration."""
    logger.info(f"Getting bag info for: {bag_path or 'current bag'}")
    info = _get_bag_info(bag_path)
    logger.debug(
        f"Bag info retrieved: {info.path}, {len(info.topics)} topics, {info.message_count} messages"
    )
    return [TextContent(type="text", text=json_serialize(asdict(info)))]
