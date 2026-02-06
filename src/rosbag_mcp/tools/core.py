from __future__ import annotations

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


async def set_bag_path(path: str) -> list[TextContent]:
    result = _set_bag_path(path)
    return [TextContent(type="text", text=result)]


async def list_bags(directory: str | None = None) -> list[TextContent]:
    bags = _list_bags(directory)
    return [TextContent(type="text", text=json_serialize(bags))]


async def bag_info(bag_path: str | None = None) -> list[TextContent]:
    info = _get_bag_info(bag_path)
    return [TextContent(type="text", text=json_serialize(asdict(info)))]
