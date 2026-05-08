"""Pure helpers for normalizing ParaView picking event payloads."""

from __future__ import annotations

import json


def normalize_edit_selection_ids(event, view=None) -> list:
    """Extract picked cell IDs or screen coordinates from picking payloads."""
    if event is None:
        return []

    if isinstance(event, dict):
        coords = _resolve_event_view_coordinates(event, view)
        if coords is not None:
            return [("coords", coords[0], coords[1])]

        if isinstance(event.get("compositeID"), int):
            return [event["compositeID"]]
        if isinstance(event.get("selection"), list):
            result = []
            for item in event["selection"]:
                if isinstance(item, dict) and isinstance(item.get("compositeID"), int):
                    result.append(item["compositeID"])
            if result:
                return result

        return []

    if isinstance(event, list):
        result = []
        for item in event:
            if isinstance(item, dict) and isinstance(item.get("compositeID"), int):
                result.append(item["compositeID"])
        return result

    return []


def summarize_edit_event(event, view=None) -> str:
    """Return a compact, UI-friendly summary of a picking/selection event."""
    if event is None:
        return "No event payload"

    if isinstance(event, dict):
        summary = {}
        for key in (
            "mode",
            "remoteId",
            "representationId",
            "view",
            "x",
            "y",
            "z",
            "compositeID",
            "position",
            "pany",
            "panx",
        ):
            if key in event:
                summary[key] = event[key]

        normalized_ids = normalize_edit_selection_ids(event, view)
        if normalized_ids:
            if (
                isinstance(normalized_ids[0], tuple)
                and normalized_ids[0][0] == "coords"
            ):
                summary["resolved_coords"] = normalized_ids[0][1:]
            else:
                summary["selection_count"] = len(normalized_ids)
                summary["sample_ids"] = normalized_ids[:8]

        summary["all_keys"] = list(event.keys())
        return json.dumps(summary, indent=2, default=str)

    if isinstance(event, (list, tuple)):
        return json.dumps(event, indent=2, default=str)

    return str(event)


def _resolve_event_view_coordinates(event, view=None):
    """Map browser-side pointer coordinates into ParaView view coordinates."""
    if not isinstance(event, dict):
        return None

    x = y = None
    pos = event.get("position")
    if isinstance(pos, dict) and "x" in pos and "y" in pos:
        x = pos["x"]
        y = pos["y"]
    elif "x" in event and "y" in event:
        x = event["x"]
        y = event["y"]
    else:
        return None

    try:
        x = float(x)
        y = float(y)
    except (TypeError, ValueError):
        return None

    size_width, size_height = _extract_size_pair(event.get("size"))
    scale_x, scale_y = _extract_scale_pair(event.get("scale"))
    view_width, view_height = _view_size(view)

    if scale_x is not None and scale_y is not None:
        x *= scale_x
        y *= scale_y
    elif (
        size_width is not None
        and size_height is not None
        and view_width is not None
        and view_height is not None
        and size_width > 0
        and size_height > 0
    ):
        x *= view_width / size_width
        y *= view_height / size_height

    if view_width is not None:
        x = min(max(x, 0.0), max(view_width - 1.0, 0.0))
    if view_height is not None:
        y = min(max(y, 0.0), max(view_height - 1.0, 0.0))

    return int(round(x)), int(round(y))


def _view_size(view):
    """Return (width, height) from a ParaView view object, or (None, None)."""
    if view is None or not hasattr(view, "ViewSize"):
        return None, None
    try:
        width, height = view.ViewSize
        return float(width), float(height)
    except (TypeError, ValueError):
        return None, None


def _extract_size_pair(size):
    """Extract width/height from an event size payload."""
    if isinstance(size, dict):
        for width_key, height_key in (
            ("width", "height"),
            ("w", "h"),
            ("x", "y"),
        ):
            if width_key in size and height_key in size:
                try:
                    return float(size[width_key]), float(size[height_key])
                except (TypeError, ValueError):
                    return None, None
    if isinstance(size, (list, tuple)) and len(size) >= 2:
        try:
            return float(size[0]), float(size[1])
        except (TypeError, ValueError):
            return None, None
    return None, None


def _extract_scale_pair(scale):
    """Extract x/y scale factors from an event scale payload."""
    if isinstance(scale, dict):
        for x_key, y_key in (
            ("x", "y"),
            ("width", "height"),
            ("sx", "sy"),
        ):
            if x_key in scale and y_key in scale:
                try:
                    return float(scale[x_key]), float(scale[y_key])
                except (TypeError, ValueError):
                    return None, None
    try:
        uniform = float(scale)
    except (TypeError, ValueError):
        uniform = None
    if uniform is not None:
        return uniform, uniform
    return None, None
