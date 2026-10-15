"""Validation for the versioned local inverter settings protocol."""
from __future__ import annotations

import math
from typing import Any


def valid_value(spec: dict[str, Any], value: Any) -> bool:
    """Use displayed units and strict types; firmware validates again before enqueue."""
    if spec["platform"] == "switch":
        return isinstance(value, bool)
    if spec["platform"] == "select":
        return isinstance(value, str) and value in spec["options"]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    if not math.isfinite(value) or not spec["min"] <= value <= spec["max"]:
        return False
    steps = (value - spec["min"]) / spec["step"]
    return abs(steps - round(steps)) <= 0.0001


def parse_catalog(items: Any) -> dict[str, dict[str, Any]] | None:
    """Reject a malformed catalog without disrupting legacy monitoring."""
    if not isinstance(items, list) or len(items) > 64:
        return None
    result = {}
    for item in items:
        if not isinstance(item, dict):
            return None
        key = item.get("key")
        if not isinstance(key, str) or not key.startswith("ctl_") or len(key) > 64 or key in result:
            return None
        if not isinstance(item.get("name"), str) or not isinstance(item.get("icon", ""), str):
            return None
        platform = item.get("platform")
        if platform == "number":
            if any(isinstance(item.get(k), bool) or not isinstance(item.get(k), (int, float))
                   or not math.isfinite(item[k]) for k in ("min", "max", "step")):
                return None
            if item["min"] > item["max"] or item["step"] <= 0 or not isinstance(item.get("unit", ""), str):
                return None
        elif platform == "select":
            options = item.get("options")
            if not isinstance(options, list) or not options or any(not isinstance(o, str) for o in options):
                return None
        elif platform != "switch":
            return None
        result[key] = dict(item)
    return result


