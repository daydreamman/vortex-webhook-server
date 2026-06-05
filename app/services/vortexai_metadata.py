"""VortexAI metadata download and feature parsing helpers."""

import json
from typing import Any
from urllib.parse import urlparse

import requests


def iter_presigned_urls(obj: dict[str, Any]):
    """Yield presigned thumbnail metadata URLs from a VortexAI object."""
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


def find_json_range(file_bytes: bytes) -> tuple[int, int, Any]:
    """Find the first valid JSON object or array inside arbitrary bytes."""
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


def iter_feature_fields(payload: Any, path: str = "root"):
    """Yield every nested `feature` field and its JSON path."""
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


def summarize_downloaded_metadata(
    presigned_url: str,
    object_index: int,
    download_index: int,
) -> dict[str, Any]:
    """Download and summarize metadata feature fields for debugging."""
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
