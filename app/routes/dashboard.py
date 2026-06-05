"""Dashboard, webhook, SSE, thumbnail, and monitor API routes."""

import json
import logging
import queue

from flask import (
    Blueprint,
    current_app,
    jsonify,
    make_response,
    render_template,
    request,
    stream_with_context,
)

from app.services.events import broadcast_clear, broadcast_event, open_subscription
from app.services.thumbnails import find_thumbnail_response
from app.services.vortexai import fetch_records, login
from app.services.webhook import build_event_from_request, validate_webhook_token
from app.state import get_event_history, normalize_token, register_token


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/settings/token", methods=["GET", "POST"])
def webhook_token_setting():
    """Read the default token or register a dashboard-scoped X-Vortex-Token."""
    if request.method == "GET":
        return jsonify({"x_vortex_token": "", "configured": False}), 200

    payload = request.get_json(force=True, silent=True) or {}
    next_token = normalize_token(payload.get("x_vortex_token"))
    if not next_token:
        return jsonify({
            "status": "error",
            "message": "X-Vortex-Token cannot be empty.",
        }), 400

    register_token(next_token)
    logging.info("X-Vortex-Token registered from dashboard.")
    return jsonify({"status": "success", "x_vortex_token": next_token}), 200


@dashboard_bp.route("/monitor/vortexai/login", methods=["POST"])
def login_vortexai():
    """Log in to VortexAI and keep the JWT for future monitor API calls."""
    result, status_code = login(request.get_json(force=True, silent=True) or {})
    return jsonify(result), status_code


@dashboard_bp.route("/monitor/vortexai/getrecords", methods=["POST"])
def get_vortexai_records():
    """Fetch VortexAI object records around one event's UTC time and MAC."""
    result, status_code = fetch_records(request.get_json(force=True, silent=True) or {})
    return jsonify(result), status_code


@dashboard_bp.route("/webhook", methods=["POST"])
def handle_vortex_webhook():
    """Receive Vortex webhook events and publish accepted events to dashboards."""
    client_token = normalize_token(request.headers.get("X-Vortex-Token"))
    if not validate_webhook_token(client_token):
        logging.warning(
            "Rejected webhook due to X-Vortex-Token mismatch. source=%s received=%s",
            request.remote_addr,
            client_token or "None",
        )
        return jsonify({
            "status": "error",
            "message": "X-Vortex-Token mismatch. Event rejected.",
            "received_token": client_token or "None",
        }), 401

    event_data = build_event_from_request(request, client_token)
    logging.info(
        "Webhook received source=%s device=%s mac=%s event=%s",
        request.remote_addr,
        event_data["device_name"],
        event_data["mac"],
        event_data["event_name"],
    )
    broadcast_event(client_token, event_data)
    return jsonify({"status": "success", "message": "Vortex Webhook processed"}), 200


@dashboard_bp.route("/events/clear", methods=["POST"])
def clear_events():
    """Clear all stored events and notify connected dashboard clients."""
    payload = request.get_json(force=True, silent=True) or {}
    token = normalize_token(payload.get("x_vortex_token") or request.args.get("token"))
    if not token:
        return jsonify({
            "status": "error",
            "message": "X-Vortex-Token must be configured before clearing events.",
        }), 400

    get_event_history(token).clear()
    broadcast_clear(token)
    logging.info("Dashboard events cleared for token scope.")
    return jsonify({"status": "success", "message": "All events cleared."}), 200


@dashboard_bp.route("/events")
def stream_events():
    """Server-Sent Events endpoint for real-time dashboard updates."""
    requested_token = normalize_token(request.args.get("token"))
    if not requested_token:
        return jsonify({
            "status": "error",
            "message": "X-Vortex-Token must be configured before streaming events.",
        }), 400

    response = current_app.response_class(
        stream_with_context(event_generator(requested_token)),
        mimetype="text/event-stream",
    )
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["X-Accel-Buffering"] = "no"
    return response


def event_generator(requested_token):
    """Yield SSE history, messages, and keep-alives for one token."""
    token = register_token(requested_token)
    subscriber, client_queue = open_subscription(token)

    yield ": connected\n\n"
    yield f"event: history\ndata: {json.dumps(get_event_history(token), ensure_ascii=False)}\n\n"

    try:
        while True:
            try:
                queue_item = client_queue.get(timeout=15)
                event_type = queue_item.get("type", "message")
                event_data = queue_item.get("data", {})
                yield f"event: {event_type}\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
            except queue.Empty:
                yield ": keep-alive\n\n"
    except GeneratorExit:
        pass
    finally:
        subscriber.close()


@dashboard_bp.route("/thumbnail/<event_id>")
def serve_thumbnail(event_id):
    """Decode an event thumbnail and normalize it as a browser-friendly JPEG."""
    token = normalize_token(request.args.get("token"))
    return find_thumbnail_response(event_id, token)


def render_dashboard_template(template_name):
    """Render a dashboard page with no HTML caching."""
    response = make_response(render_template(template_name))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@dashboard_bp.route("/", methods=["GET"])
def index():
    """Render the primary dashboard page."""
    return render_dashboard_template("index.html")


@dashboard_bp.route("/monitor", methods=["GET"])
def monitor():
    """Render the alternate monitor page for independent UI iteration."""
    return render_dashboard_template("monitor.html")
