"""Trajectory extraction helpers for VortexAI object records."""

from typing import Any


def cumulative_points_from_base_diff(base: Any, diffs: Any) -> list[dict[str, float]]:
    """Convert Vortex base/diff trajectory encoding into cumulative points."""
    if not isinstance(base, list) or len(base) < 2 or not isinstance(diffs, list):
        return []
    x = float(base[0])
    y = float(base[1])
    points = [{"x": x, "y": y}]
    for diff in diffs:
        if not isinstance(diff, list) or len(diff) < 2:
            continue
        x += float(diff[0])
        y += float(diff[1])
        points.append({"x": x, "y": y})
    return points


def extract_trajectories(value: Any, path: str = "root") -> list[dict[str, Any]]:
    """Extract supported trajectory shapes from an arbitrary JSON value."""
    trajectories = []
    if isinstance(value, dict):
        trajectories.extend(extract_base_diff_trajectory(value, path))
        trajectories.extend(extract_point_list_trajectories(value, path))
        for key, nested_value in value.items():
            trajectories.extend(extract_trajectories(nested_value, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            trajectories.extend(extract_trajectories(item, f"{path}[{index}]"))
    return trajectories


def extract_base_diff_trajectory(value: dict[str, Any], path: str) -> list[dict[str, Any]]:
    """Extract Vortex `{base, diff}` trajectory shape."""
    if not (isinstance(value.get("base"), list) and isinstance(value.get("diff"), list)):
        return []
    points = cumulative_points_from_base_diff(value.get("base"), value.get("diff"))
    if len(points) < 2:
        return []
    return [{"path": path, "points": points}]


def extract_point_list_trajectories(value: dict[str, Any], path: str) -> list[dict[str, Any]]:
    """Extract explicit point-list trajectory shapes."""
    trajectories = []
    for key in ("trajectoryPoints", "trajectory_points"):
        points_value = value.get(key)
        if not isinstance(points_value, list):
            continue
        points = [
            {"x": point["x"], "y": point["y"]}
            for point in points_value
            if isinstance(point, dict) and "x" in point and "y" in point
        ]
        if len(points) >= 2:
            trajectories.append({"path": f"{path}.{key}", "points": points})
    return trajectories
