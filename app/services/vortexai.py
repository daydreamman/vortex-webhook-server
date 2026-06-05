import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from app.state import VORTEXAI_SESSIONS, get_vortexai_auth_context
from app.services.vortexai_metadata import (
    find_json_range,
    iter_feature_fields,
    iter_presigned_urls,
    summarize_downloaded_metadata,
)
from app.services.vortexai_trajectory import cumulative_points_from_base_diff, extract_trajectories


ALLOWED_VORTEXAI_HOSTS = {
    "vortexai.vortexcloud.com",
    "vortexai.dev.vortexcloud.com",
    "vortexai.stage.vortexcloud.com",
}


def normalize_vortexai_base_url(base_url: Any) -> str:
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


def build_getrecords_query(mac: str, utc_time: str, window_seconds: int) -> dict[str, Any]:
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


def login(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Log in to VortexAI and keep a short-lived in-memory JWT session."""
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if not username or not password:
        return {
            "status": "error",
            "message": "Username and password are required.",
        }, 400

    try:
        base_url = normalize_vortexai_base_url(payload.get("base_url"))
    except ValueError as err:
        return {"status": "error", "message": str(err)}, 400

    try:
        login_data = request_vortexai_login(base_url, username, password)
        jwt = login_data.get("jwt") or login_data.get("access_token")
        if not jwt:
            return {
                "status": "error",
                "message": "Login succeeded but no JWT/access token was returned.",
                "login_keys": sorted(login_data.keys()),
            }, 502
        session_id = save_vortexai_session(jwt, base_url, username)
        return {
            "status": "success",
            "base_url": base_url,
            "login": "ok",
            "vortexai_session_id": session_id,
            "username": username,
        }, 200
    except requests.RequestException as err:
        logging.warning("VortexAI login failed: %s", err)
        return login_request_error_response(err), 502
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as err:
        logging.warning("VortexAI login response parsing failed: %s", err)
        return {
            "status": "error",
            "login": "failed",
            "message": "VortexAI login response could not be parsed.",
            "detail": str(err),
        }, 502


def request_vortexai_login(base_url: str, username: str, password: str) -> dict[str, Any]:
    """Call VortexAI login and return the decoded JSON response."""
    response = requests.post(
        f"{base_url}login",
        json={"username": username, "password": password},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def save_vortexai_session(jwt: str, base_url: str, username: str) -> str:
    """Persist one VortexAI login session in process memory."""
    session_id = uuid.uuid4().hex
    VORTEXAI_SESSIONS[session_id] = {
        "jwt": jwt,
        "base_url": base_url,
        "username": username,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return session_id


def login_request_error_response(err: requests.RequestException) -> dict[str, Any]:
    """Build a user-facing login error response from a requests exception."""
    status_code = getattr(err.response, "status_code", None)
    message = "The VortexAI username or password is incorrect."
    if status_code and status_code >= 500:
        message = "VortexAI login service is unavailable. Please try again later."
    return {
        "status": "error",
        "login": "failed",
        "message": message,
        "detail": str(err),
    }


def fetch_records(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Fetch object records around one event's UTC time and camera MAC."""
    auth_context = get_vortexai_auth_context(payload.get("vortexai_session_id"))
    if not auth_context:
        return {
            "status": "error",
            "message": "VortexAI login is required before fetching object records.",
        }, 401

    mac = str(payload.get("mac") or "").strip()
    utc_time = str(payload.get("utc_time") or "").strip()
    if not mac or not utc_time:
        return {
            "status": "error",
            "message": "Camera MAC and UTC event time are required.",
        }, 400

    try:
        window_seconds = bounded_window_seconds(payload.get("window_seconds"))
        query = build_getrecords_query(mac, utc_time, window_seconds)
    except (TypeError, ValueError) as err:
        return {
            "status": "error",
            "message": "UTC event time could not be parsed.",
            "detail": str(err),
        }, 400

    return request_records(auth_context, mac, utc_time, window_seconds, query)


def bounded_window_seconds(raw_value: Any) -> int:
    """Clamp requested getrecords window to a small safe range."""
    return max(1, min(int(raw_value or 30), 300))


def request_records(
    auth_context: dict[str, Any],
    mac: str,
    utc_time: str,
    window_seconds: int,
    query: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    """Call VortexAI getrecords and convert the response into dashboard data."""
    try:
        response = requests.post(
            f"{auth_context['base_url']}api/deepsearch/getrecords",
            json=query,
            headers=auth_context["headers"],
            timeout=60,
        )
        response.raise_for_status()
        body = response.json()
        records = flatten_records(body)
        return {
            "status": "success",
            "request_payload": request_payload(mac, utc_time, window_seconds),
            "query": query,
            "record_count": len(records),
            "records": records[:20],
            "trajectories": collect_record_trajectories(records)[:20],
            "raw": body,
        }, 200
    except requests.RequestException as err:
        logging.warning("VortexAI getrecords failed: %s", err)
        return records_request_error_response(err, mac, utc_time, window_seconds, query), 502
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as err:
        logging.warning("VortexAI getrecords parsing failed: %s", err)
        return {
            "status": "error",
            "message": "VortexAI getrecords response could not be parsed.",
            "detail": str(err),
        }, 502


def request_payload(mac: str, utc_time: str, window_seconds: int) -> dict[str, Any]:
    """Return the request payload echoed in debug responses."""
    return {
        "mac": mac,
        "utc_time": utc_time,
        "window_seconds": window_seconds,
    }


def flatten_records(body: Any) -> list[dict[str, Any]]:
    """Flatten VortexAI paged getrecords response bodies."""
    pages = body if isinstance(body, list) else [body]
    records = []
    for page in pages:
        if isinstance(page, dict) and isinstance(page.get("data"), list):
            records.extend(page["data"])
    return records


def collect_record_trajectories(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract trajectory data from records and annotate source indexes."""
    trajectories = []
    for record_index, record in enumerate(records):
        for trajectory in extract_trajectories(record):
            trajectories.append({
                "record_index": record_index,
                "path": trajectory["path"],
                "points": trajectory["points"],
            })
    return trajectories


def records_request_error_response(
    err: requests.RequestException,
    mac: str,
    utc_time: str,
    window_seconds: int,
    query: dict[str, Any],
) -> dict[str, Any]:
    """Build a debug-rich error response for failed getrecords calls."""
    response_text = ""
    if getattr(err, "response", None) is not None:
        response_text = getattr(err.response, "text", "")
    return {
        "status": "error",
        "message": "VortexAI getrecords request failed.",
        "detail": str(err),
        "response_body": response_text,
        "request_payload": request_payload(mac, utc_time, window_seconds),
        "query": query,
    }
