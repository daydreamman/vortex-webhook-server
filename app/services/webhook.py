"""Webhook token validation and Vortex alarm event mapping."""

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.state import KNOWN_VORTEX_TOKENS


def validate_webhook_token(client_token: str) -> bool:
    """Return whether a webhook token is currently registered by a dashboard."""
    return bool(client_token) and client_token in KNOWN_VORTEX_TOKENS


def parse_json_payload(
    raw_body: str,
    request_is_json: bool,
    request_json: Optional[dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    """Parse JSON payload from Flask's parsed JSON or raw body."""
    try:
        if request_is_json:
            return request_json or {}, True
        return json.loads(raw_body), True
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}, False


def resolve_event_utc_time(payload: dict[str, Any]) -> str:
    """Resolve Vortex timestamp variants into one UTC-ish ISO timestamp string."""
    for key in ("utcISOTime", "utc_iso_time"):
        if payload.get(key):
            return payload[key]

    utc_time = timestamp_to_utc_iso(payload.get("utcTime") or payload.get("utc_time_val"))
    if utc_time:
        return utc_time

    for key in ("localISOTime", "local_iso_time"):
        if payload.get(key):
            return payload[key]

    local_time = timestamp_to_utc_iso(payload.get("localTime") or payload.get("local_time"))
    return local_time or datetime.now(timezone.utc).isoformat()


def timestamp_to_utc_iso(value: Any) -> str:
    """Convert second or millisecond Unix timestamps to UTC ISO strings."""
    if value in (None, ""):
        return ""
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return ""
    if timestamp > 1e11:
        timestamp = timestamp / 1000.0
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def build_event_from_request(flask_request, client_token: str) -> dict[str, Any]:
    """Build a dashboard event record from a Flask webhook request."""
    raw_body = flask_request.get_data(as_text=True)
    payload, is_json = parse_json_payload(
        raw_body,
        flask_request.is_json,
        flask_request.get_json(force=True, silent=True),
    )
    local_time = payload.get("localTime") or payload.get("local_time")
    event_name = payload.get("eventName") or payload.get("event_name") or (
        "Raw HTTP Post" if not is_json else "Empty Event"
    )
    device_name = payload.get("deviceName") or payload.get("device_name") or "N/A"
    mac = payload.get("mac") or payload.get("macAddress") or "Unknown MAC"

    return {
        "internal_id": uuid.uuid4().hex,
        "event_id": payload.get("eventId") or payload.get("event_id") or f"debug_{int(time.time())}",
        "org_name": payload.get("organizationName") or payload.get("organization_name") or payload.get("org_name") or "N/A",
        "org_id": payload.get("organizationId") or payload.get("org_id") or "",
        "event_type": payload.get("eventType") or payload.get("event_type") or "",
        "event_name": event_name,
        "device_name": device_name,
        "device_id": payload.get("deviceId") or payload.get("device_id") or "",
        "mac": mac,
        "device_group_name": payload.get("deviceGroupName") or payload.get("device_group_name") or "",
        "device_group_id": payload.get("deviceGroupId") or payload.get("device_group_id") or payload.get("deviceGroupID") or "",
        "local_time": local_time,
        "local_iso_time": payload.get("localISOTime") or payload.get("local_iso_time") or "",
        "utc_time_val": payload.get("utcTime") or payload.get("utc_time_val") or "",
        "utc_iso_time": payload.get("utcISOTime") or payload.get("utc_iso_time") or "",
        "timezone": payload.get("timezone") or "",
        "alarm_id": payload.get("alarmId") or payload.get("alarm_id") or "",
        "profile_name": payload.get("profileName") or payload.get("profile_name") or "",
        "image_face": payload.get("imageFace") or payload.get("image_face") or "",
        "image_person": payload.get("imagePerson") or payload.get("image_person") or "",
        "thumbnail": payload.get("thumbnail") or payload.get("Thumbnail") or "",
        "utc_time": resolve_event_utc_time(payload),
        "debug_raw_headers": {k: v for k, v in flask_request.headers.items() if k.lower() != "authorization"},
        "debug_raw_body": raw_body,
        "debug_token_valid": True,
        "debug_is_json": is_json,
        "debug_received_token": client_token or "None",
    }
