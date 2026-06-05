import json
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests


ALLOWED_VORTEXAI_HOSTS = {
    "vortexai.vortexcloud.com",
    "vortexai.dev.vortexcloud.com",
    "vortexai.stage.vortexcloud.com",
}


def normalize_vortexai_base_url(base_url):
    """Return a safe VortexAI base URL with a trailing slash."""
    raw_url = str(base_url or "https://vortexai.vortexcloud.com/").strip()
    if not raw_url:
        raw_url = "https://vortexai.vortexcloud.com/"
    if "://" not in raw_url:
        raw_url = f"https://{raw_url}"
    parsed = urlparse(raw_url)
    host = parsed.netloc.lower()
    if host not in ALLOWED_VORTEXAI_HOSTS:
        raise ValueError("Base URL must be one of the supported VortexAI hosts.")
    return f"{parsed.scheme}://{host}/"


def iter_presigned_urls(obj):
    thumbnail_json = obj.get("thumbnail_json") or {}
    if not isinstance(thumbnail_json, dict):
        return
    for thumbnails in thumbnail_json.values():
        if not isinstance(thumbnails, list):
            continue
        for thumbnail in thumbnails:
            if not isinstance(thumbnail, dict):
                continue
            presigned_url = thumbnail.get("presigned_url")
            if presigned_url:
                yield presigned_url


def find_json_range(file_bytes):
    candidate_starts = [
        index for index, byte in enumerate(file_bytes)
        if byte in (ord("{"), ord("["))
    ]
    candidate_starts.sort(key=lambda index: (index != 0, index))

    for start in candidate_starts:
        for end in range(len(file_bytes), start, -1):
            if file_bytes[end - 1] not in (ord("}"), ord("]")):
                continue
            try:
                payload = json.loads(file_bytes[start:end].decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            return start, end, payload
    raise ValueError("No valid JSON payload found in downloaded file.")


def iter_feature_fields(payload, path="root"):
    if isinstance(payload, dict):
        for key, value in payload.items():
            next_path = f"{path}.{key}"
            if key == "feature":
                yield next_path, value
            yield from iter_feature_fields(value, next_path)
        return
    if isinstance(payload, list):
        for index, item in enumerate(payload):
            yield from iter_feature_fields(item, f"{path}[{index}]")


def summarize_downloaded_metadata(presigned_url, object_index, download_index):
    parsed_url = urlparse(presigned_url)
    safe_url = presigned_url if parsed_url.scheme else f"https://{presigned_url.lstrip('/')}"
    response = requests.get(safe_url, timeout=30)
    response.raise_for_status()
    file_bytes = response.content
    json_start, json_end, payload = find_json_range(file_bytes)
    features = []
    for feature_path, feature_values in iter_feature_fields(payload):
        preview = feature_values[:5] if isinstance(feature_values, list) else feature_values
        features.append({
            "path": feature_path,
            "length": len(feature_values) if isinstance(feature_values, list) else None,
            "preview": preview,
        })

    return {
        "object_index": object_index,
        "download_index": download_index,
        "file_size": len(file_bytes),
        "json_range": [json_start, json_end],
        "feature_count": len(features),
        "features": features[:5],
    }


def cumulative_points_from_base_diff(base, diffs):
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


def extract_trajectories(value, path="root"):
    trajectories = []
    if isinstance(value, dict):
        if isinstance(value.get("base"), list) and isinstance(value.get("diff"), list):
            points = cumulative_points_from_base_diff(value.get("base"), value.get("diff"))
            if len(points) >= 2:
                trajectories.append({"path": path, "points": points})

        for key in ("trajectoryPoints", "trajectory_points"):
            points_value = value.get(key)
            if isinstance(points_value, list):
                points = []
                for point in points_value:
                    if isinstance(point, dict) and "x" in point and "y" in point:
                        points.append({"x": point["x"], "y": point["y"]})
                if len(points) >= 2:
                    trajectories.append({"path": f"{path}.{key}", "points": points})

        for key, nested_value in value.items():
            trajectories.extend(extract_trajectories(nested_value, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            trajectories.extend(extract_trajectories(item, f"{path}[{index}]"))
    return trajectories


def build_getrecords_query(mac, utc_time, window_seconds):
    event_time = datetime.fromisoformat(str(utc_time).replace("Z", "+00:00"))
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    event_time = event_time.astimezone(timezone.utc)
    start_time = event_time.timestamp() - window_seconds
    end_time = event_time.timestamp() + window_seconds
    start_iso = datetime.fromtimestamp(start_time, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = datetime.fromtimestamp(end_time, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "columns": [
            {"field": "MacAddress", "type": "string", "aggregationFunction": None},
            {"field": "Device", "type": "string", "aggregationFunction": None},
            {"field": "StartTime", "type": "datetime", "aggregationFunction": None},
            {"field": "EndTime", "type": "datetime", "aggregationFunction": None},
            {"field": "Oid", "type": "string", "aggregationFunction": None},
            {"field": "Type", "type": "string", "aggregationFunction": None},
        ],
        "filters": {
            "type": "and",
            "filterClause": [
                {"type": "string", "field": "MacAddress", "condition": "equal", "value": mac},
                {"type": "datetime", "field": "StartTime", "condition": "gt", "value": start_iso},
                {"type": "datetime", "field": "StartTime", "condition": "lte", "value": end_iso},
            ],
        },
        "sorting": [
            {"columnName": "StartTime", "ascending": False, "sortOrder": 0}
        ],
        "paging": {"page": 1, "nrOfRecords": 20},
    }
