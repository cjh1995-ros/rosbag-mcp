from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any

logger = logging.getLogger(__name__)


def json_serialize(obj: Any) -> str:
    def default(o):
        if hasattr(o, "__dataclass_fields__"):
            return asdict(o)
        if hasattr(o, "tolist"):
            return o.tolist()
        if isinstance(o, (set, frozenset)):
            return list(o)
        return str(o)

    return json.dumps(obj, indent=2, default=default)


def get_nested_field(data: dict, field_path: str) -> Any:
    parts = field_path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            return None
        if current is None:
            return None
    return current


def extract_position(data: dict) -> tuple[float, float, float] | None:
    if "pose" in data:
        pose = data["pose"]
        if "pose" in pose:
            pose = pose["pose"]
        if "position" in pose:
            pos = pose["position"]
            return (pos.get("x", 0), pos.get("y", 0), pos.get("z", 0))
    if "position" in data:
        pos = data["position"]
        return (pos.get("x", 0), pos.get("y", 0), pos.get("z", 0))
    if "x" in data and "y" in data:
        return (data["x"], data["y"], data.get("z", 0))
    return None


def extract_velocity(data: dict) -> tuple[float, float] | None:
    if "twist" in data:
        twist = data["twist"]
        if "twist" in twist:
            twist = twist["twist"]
        linear = twist.get("linear", {})
        angular = twist.get("angular", {})
        return (linear.get("x", 0), angular.get("z", 0))
    if "linear" in data and "angular" in data:
        return (data["linear"].get("x", 0), data["angular"].get("z", 0))
    return None
