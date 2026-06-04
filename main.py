from flask import Flask, request, jsonify, render_template, make_response, stream_with_context
import os
import logging
import queue
import json
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

app = Flask(__name__)

# Configure logging.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

DEFAULT_RUNTIME_TOKEN = ""
KNOWN_VORTEX_TOKENS = set()

# Event history is partitioned by X-Vortex-Token. New events are stored first.
EVENT_HISTORY_BY_TOKEN = {}
# Message queues for connected dashboard clients.
SUBSCRIBERS = []
VORTEXAI_SESSIONS = {}
ALLOWED_VORTEXAI_HOSTS = {
    "vortexai.vortexcloud.com",
    "vortexai.dev.vortexcloud.com",
    "vortexai.stage.vortexcloud.com",
}

def normalize_token(token):
    return str(token or "").strip()

def register_token(token):
    clean_token = normalize_token(token)
    if clean_token:
        KNOWN_VORTEX_TOKENS.add(clean_token)
    return clean_token

def get_event_history(token):
    clean_token = register_token(token)
    return EVENT_HISTORY_BY_TOKEN.setdefault(clean_token, [])

def get_vortexai_session(session_id):
    return VORTEXAI_SESSIONS.get(str(session_id or "").strip())

def get_vortexai_auth_context(session_id):
    session = get_vortexai_session(session_id)
    if not session:
        return None
    return {
        "base_url": session["base_url"],
        "headers": {
            "Authorization": f"Bearer {session['jwt']}",
            "Content-Type": "application/json",
        },
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

@app.route('/settings/token', methods=['GET', 'POST'])
def webhook_token_setting():
    """Read the default token or register a dashboard-scoped X-Vortex-Token."""

    if request.method == 'GET':
        return jsonify({"x_vortex_token": "", "configured": False}), 200

    payload = request.get_json(force=True, silent=True) or {}
    next_token = str(payload.get("x_vortex_token") or "").strip()
    if not next_token:
        return jsonify({
            "status": "error",
            "message": "X-Vortex-Token cannot be empty."
        }), 400

    register_token(next_token)
    logging.info("X-Vortex-Token registered from dashboard.")
    return jsonify({
        "status": "success",
        "x_vortex_token": next_token
    }), 200

@app.route('/monitor/vortexai/login', methods=['POST'])
def login_vortexai():
    """Log in to VortexAI and keep the JWT for future monitor API calls."""
    payload = request.get_json(force=True, silent=True) or {}
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")

    if not username or not password:
        return jsonify({
            "status": "error",
            "message": "Username and password are required."
        }), 400

    try:
        base_url = normalize_vortexai_base_url(payload.get("base_url"))
    except ValueError as err:
        return jsonify({"status": "error", "message": str(err)}), 400

    try:
        login_res = requests.post(
            f"{base_url}login",
            json={"username": username, "password": password},
            timeout=30,
        )
        login_res.raise_for_status()
        login_data = login_res.json()
        jwt = login_data.get("jwt") or login_data.get("access_token")
        if not jwt:
            return jsonify({
                "status": "error",
                "message": "Login succeeded but no JWT/access token was returned.",
                "login_keys": sorted(login_data.keys()),
            }), 502
        session_id = uuid.uuid4().hex
        VORTEXAI_SESSIONS[session_id] = {
            "jwt": jwt,
            "base_url": base_url,
            "username": username,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        return jsonify({
            "status": "success",
            "base_url": base_url,
            "login": "ok",
            "vortexai_session_id": session_id,
            "username": username,
        }), 200
    except requests.RequestException as err:
        logging.warning("VortexAI login failed: %s", err)
        status_code = getattr(err.response, "status_code", None)
        message = "The VortexAI username or password is incorrect."
        if status_code and status_code >= 500:
            message = "VortexAI login service is unavailable. Please try again later."
        return jsonify({
            "status": "error",
            "login": "failed",
            "message": message,
            "detail": str(err),
        }), 502
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as err:
        logging.warning("VortexAI login response parsing failed: %s", err)
        return jsonify({
            "status": "error",
            "login": "failed",
            "message": "VortexAI login response could not be parsed.",
            "detail": str(err),
        }), 502

@app.route('/monitor/vortexai/getrecords', methods=['POST'])
def get_vortexai_records():
    """Fetch VortexAI object records around one event's UTC time and MAC."""
    payload = request.get_json(force=True, silent=True) or {}
    session_id = payload.get("vortexai_session_id")
    auth_context = get_vortexai_auth_context(session_id)
    if not auth_context:
        return jsonify({
            "status": "error",
            "message": "VortexAI login is required before fetching object records."
        }), 401

    mac = str(payload.get("mac") or "").strip()
    utc_time = str(payload.get("utc_time") or "").strip()
    if not mac or not utc_time:
        return jsonify({
            "status": "error",
            "message": "Camera MAC and UTC event time are required."
        }), 400

    try:
        window_seconds = max(1, min(int(payload.get("window_seconds") or 30), 300))
        query = build_getrecords_query(mac, utc_time, window_seconds)
    except (TypeError, ValueError) as err:
        return jsonify({
            "status": "error",
            "message": "UTC event time could not be parsed.",
            "detail": str(err),
        }), 400

    try:
        records_res = requests.post(
            f"{auth_context['base_url']}api/deepsearch/getrecords",
            json=query,
            headers=auth_context["headers"],
            timeout=60,
        )
        records_res.raise_for_status()
        body = records_res.json()
        pages = body if isinstance(body, list) else [body]
        records = []
        for page in pages:
            if isinstance(page, dict) and isinstance(page.get("data"), list):
                records.extend(page.get("data"))
        trajectories = []
        for record_index, record in enumerate(records):
            for trajectory in extract_trajectories(record):
                trajectories.append({
                    "record_index": record_index,
                    "path": trajectory["path"],
                    "points": trajectory["points"],
                })

        return jsonify({
            "status": "success",
            "query": query,
            "record_count": len(records),
            "records": records[:20],
            "trajectories": trajectories[:20],
            "raw": body,
        }), 200
    except requests.RequestException as err:
        logging.warning("VortexAI getrecords failed: %s", err)
        response_text = getattr(err.response, "text", "") if getattr(err, "response", None) is not None else ""
        return jsonify({
            "status": "error",
            "message": "VortexAI getrecords request failed.",
            "detail": str(err),
            "response_body": response_text,
            "query": query,
        }), 502
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as err:
        logging.warning("VortexAI getrecords parsing failed: %s", err)
        return jsonify({
            "status": "error",
            "message": "VortexAI getrecords response could not be parsed.",
            "detail": str(err),
        }), 502

def broadcast_event(token, event_data):
    """Store a new event and broadcast it to connected dashboard clients."""
    clean_token = register_token(token)
    history = get_event_history(clean_token)
    history.insert(0, event_data)
        
    # Broadcast only to active SSE connections subscribed to the same token.
    for subscriber in list(SUBSCRIBERS):
        try:
            if subscriber["token"] == clean_token:
                subscriber["queue"].put({"type": "message", "data": event_data})
        except Exception as e:
            logging.error(f"Failed to send event to subscriber: {e}")
            if subscriber in SUBSCRIBERS:
                SUBSCRIBERS.remove(subscriber)

def broadcast_clear(token):
    """Broadcast a clear command to connected dashboard clients."""
    clean_token = normalize_token(token)
    for subscriber in list(SUBSCRIBERS):
        try:
            if subscriber["token"] == clean_token:
                subscriber["queue"].put({"type": "clear", "data": {}})
        except Exception as e:
            logging.error(f"Failed to send clear command to subscriber: {e}")
            if subscriber in SUBSCRIBERS:
                SUBSCRIBERS.remove(subscriber)

@app.route('/webhook', methods=['POST'])
def handle_vortex_webhook():
    import time
    from datetime import datetime, timezone

    # 1. Capture raw request data for debugging.
    raw_body_str = request.get_data(as_text=True)
    client_token = normalize_token(request.headers.get('X-Vortex-Token'))
    
    # Reject mismatched tokens before parsing or broadcasting the event.
    token_valid = bool(client_token) and client_token in KNOWN_VORTEX_TOKENS
    if not token_valid:
        logging.warning(
            "Rejected webhook due to X-Vortex-Token mismatch. source=%s received=%s",
            request.remote_addr,
            client_token or "None"
        )
        return jsonify({
            "status": "error",
            "message": "X-Vortex-Token mismatch. Event rejected.",
            "received_token": client_token or "None"
        }), 401
    
    # 2. Parse JSON when possible.
    is_json = True
    payload = {}
    try:
        if request.is_json:
            payload = request.get_json(force=True, silent=True) or {}
        else:
            # Try parsing the raw body as JSON.
            payload = json.loads(raw_body_str)
    except Exception:
        is_json = False
        payload = {}

    # 3. Map VIVOTEK Vortex alarm event fields and timestamp variants.
    utc_time_str = ""
    
    # Priority 1: UtcISOTime (e.g. "2026-05-29T09:50:00Z")
    utc_iso_val = payload.get("utcISOTime") or payload.get("utc_iso_time")
    if utc_iso_val:
        utc_time_str = utc_iso_val
        
    # Priority 2: UtcTime (Unix timestamp in seconds/milliseconds)
    if not utc_time_str:
        utc_time_val = payload.get("utcTime") or payload.get("utc_time_val")
        if utc_time_val:
            try:
                ts = float(utc_time_val)
                if ts > 1e11:
                    ts = ts / 1000.0
                utc_time_str = datetime.fromtimestamp(ts, timezone.utc).isoformat()
            except Exception:
                pass
                
    # Priority 3: LocalISOTime
    if not utc_time_str:
        local_iso_val = payload.get("localISOTime") or payload.get("local_iso_time")
        if local_iso_val:
            utc_time_str = local_iso_val

    # Priority 4: LocalTime (Unix timestamp)
    local_time_val = payload.get("localTime") or payload.get("local_time")
    if not utc_time_str and local_time_val:
        try:
            ts = float(local_time_val)
            if ts > 1e11:
                ts = ts / 1000.0
            utc_time_str = datetime.fromtimestamp(ts, timezone.utc).isoformat()
        except Exception:
            pass

    # Priority 5: current server time fallback.
    if not utc_time_str:
        utc_time_str = datetime.now(timezone.utc).isoformat()

    event_id = payload.get("eventId") or payload.get("event_id") or f"debug_{int(time.time())}"
    event_name = payload.get("eventName") or payload.get("event_name") or ("Raw HTTP Post" if not is_json else "Empty Event")
    device_name = payload.get("deviceName") or payload.get("device_name") or "N/A"
    mac = payload.get("mac") or payload.get("macAddress") or "Unknown MAC"

    event_data = {
        "internal_id": uuid.uuid4().hex,
        "event_id": event_id,
        "org_name": payload.get("organizationName") or payload.get("organization_name") or payload.get("org_name") or "N/A",
        "org_id": payload.get("organizationId") or payload.get("org_id") or "",
        "event_type": payload.get("eventType") or payload.get("event_type") or "",
        "event_name": event_name,
        "device_name": device_name,
        "device_id": payload.get("deviceId") or payload.get("device_id") or "",
        "mac": mac,
        "device_group_name": payload.get("deviceGroupName") or payload.get("device_group_name") or "",
        "device_group_id": payload.get("deviceGroupId") or payload.get("device_group_id") or payload.get("deviceGroupID") or "",
        "local_time": local_time_val,
        "local_iso_time": payload.get("localISOTime") or payload.get("local_iso_time") or "",
        "utc_time_val": payload.get("utcTime") or payload.get("utc_time_val") or "",
        "utc_iso_time": payload.get("utcISOTime") or payload.get("utc_iso_time") or "",
        "timezone": payload.get("timezone") or "",
        "alarm_id": payload.get("alarmId") or payload.get("alarm_id") or "",
        "profile_name": payload.get("profileName") or payload.get("profile_name") or "",
        "image_face": payload.get("imageFace") or payload.get("image_face") or "",
        "image_person": payload.get("imagePerson") or payload.get("image_person") or "",
        "thumbnail": payload.get("thumbnail") or payload.get("Thumbnail") or "",
        "utc_time": utc_time_str,
        # Debug fields.
        "debug_raw_headers": {k: v for k, v in request.headers.items() if k.lower() != "authorization"},
        "debug_raw_body": raw_body_str,
        "debug_token_valid": token_valid,
        "debug_is_json": is_json,
        "debug_received_token": client_token or "None"
    }

    # 4. Log accepted event details.
    logging.info("=" * 50)
    logging.info(f"Webhook received (token_valid={token_valid}, is_json={is_json})")
    logging.info(f"Source IP: {request.remote_addr}")
    logging.info(f"Device: {device_name} (MAC: {mac})")
    logging.info(f"Event: {event_name}")
    logging.info("=" * 50)

    # 5. Broadcast accepted events to connected dashboard clients.
    broadcast_event(client_token, event_data)

    return jsonify({"status": "success", "message": "Vortex Webhook processed"}), 200

@app.route('/events/clear', methods=['POST'])
def clear_events():
    """Clear all stored events and notify connected dashboard clients."""
    payload = request.get_json(force=True, silent=True) or {}
    token = normalize_token(payload.get("x_vortex_token") or request.args.get("token"))
    if not token:
        return jsonify({
            "status": "error",
            "message": "X-Vortex-Token must be configured before clearing events."
        }), 400
    history = get_event_history(token)
    history.clear()
    broadcast_clear(token)
    logging.info("Dashboard events cleared for token scope.")
    return jsonify({"status": "success", "message": "All events cleared."}), 200

@app.route('/events')
def stream_events():
    """Server-Sent Events (SSE) endpoint for real-time dashboard updates."""
    requested_token = normalize_token(request.args.get("token"))
    if not requested_token:
        return jsonify({
            "status": "error",
            "message": "X-Vortex-Token must be configured before streaming events."
        }), 400

    def event_generator():
        token = register_token(requested_token)
        # Create a dedicated queue for this dashboard connection.
        client_queue = queue.Queue()
        subscriber = {"queue": client_queue, "token": token}
        SUBSCRIBERS.append(subscriber)

        # Flush the stream immediately instead of waiting for the first alarm.
        yield ": connected\n\n"
        
        # Send current history when the connection is established.
        yield f"event: history\ndata: {json.dumps(get_event_history(token), ensure_ascii=False)}\n\n"
        
        try:
            while True:
                try:
                    # Wait up to 15 seconds for the next event.
                    queue_item = client_queue.get(timeout=15)
                    event_type = queue_item.get("type", "message")
                    event_data = queue_item.get("data", {})
                    yield f"event: {event_type}\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    # Keep the connection alive through proxies.
                    yield ": keep-alive\n\n"
        except GeneratorExit:
            # Browser tab closed or connection disconnected.
            pass
        finally:
            if subscriber in SUBSCRIBERS:
                SUBSCRIBERS.remove(subscriber)
                
    response = app.response_class(
        stream_with_context(event_generator()),
        mimetype='text/event-stream'
    )
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["X-Accel-Buffering"] = "no"
    return response

@app.route('/thumbnail/<event_id>')
def serve_thumbnail(event_id):
    """Decode an event thumbnail and normalize it as a browser-friendly JPEG."""
    import base64
    import io
    from flask import Response

    token = normalize_token(request.args.get("token"))
    histories = [get_event_history(token)] if token else EVENT_HISTORY_BY_TOKEN.values()

    for history in histories:
        for evt in history:
            if not (
                (evt.get("internal_id") == event_id or evt.get("event_id") == event_id)
                and evt.get("thumbnail")
            ):
                continue

            try:
                raw_b64 = str(evt["thumbnail"]).strip()
                # Remove data:image prefix when present.
                if raw_b64.startswith("data:"):
                    raw_b64 = raw_b64.split(",", 1)[1]
                raw_b64 = "".join(raw_b64.split())
                missing_padding = len(raw_b64) % 4
                if missing_padding:
                    raw_b64 += "=" * (4 - missing_padding)

                img_bytes = base64.b64decode(raw_b64, validate=False)

                try:
                    from PIL import Image, ImageOps

                    image = Image.open(io.BytesIO(img_bytes))
                    image = ImageOps.exif_transpose(image)
                    if image.mode not in ("RGB", "L"):
                        image = image.convert("RGB")

                    output = io.BytesIO()
                    image.save(output, format="JPEG", quality=90, optimize=True)
                    return Response(
                        output.getvalue(),
                        mimetype='image/jpeg',
                        headers={'Cache-Control': 'no-store, max-age=0'}
                    )
                except Exception as normalize_error:
                    logging.warning(
                        f"Thumbnail normalization failed; returning raw image event_id={event_id}: {normalize_error}"
                    )
                    return Response(
                        img_bytes,
                        mimetype='image/jpeg',
                        headers={'Cache-Control': 'no-store, max-age=0'}
                    )
            except Exception as e:
                logging.error(f"Thumbnail decode failed event_id={event_id}: {e}")
                return Response("Decode error", status=500)

    return Response("Not found", status=404)

def render_dashboard_template(template_name):
    """Render a dashboard page with no HTML caching."""
    response = make_response(render_template(template_name))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route('/', methods=['GET'])
def index():
    # Render the primary dashboard page.
    return render_dashboard_template('index.html')

@app.route('/monitor', methods=['GET'])
def monitor():
    # Render the alternate monitor page for independent UI iteration.
    return render_dashboard_template('monitor.html')

if __name__ == '__main__':
    # Local development entrypoint.
    app.run(host='0.0.0.0', port=8080, debug=True)
