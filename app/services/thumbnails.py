"""Thumbnail lookup, decoding, and normalization helpers."""

import base64
import io
import logging

from flask import Response

from app.state import EVENT_HISTORY_BY_TOKEN, get_event_history


def find_thumbnail_response(event_id: str, token: str) -> Response:
    """Find and return a thumbnail response for an event ID."""
    histories = [get_event_history(token)] if token else EVENT_HISTORY_BY_TOKEN.values()
    for history in histories:
        for event in history:
            if is_matching_thumbnail_event(event, event_id):
                return decode_thumbnail_response(event, event_id)
    return Response("Not found", status=404)


def is_matching_thumbnail_event(event: dict, event_id: str) -> bool:
    """Return whether an event has the requested thumbnail."""
    return bool(
        (event.get("internal_id") == event_id or event.get("event_id") == event_id)
        and event.get("thumbnail")
    )


def decode_thumbnail_response(event: dict, event_id: str) -> Response:
    """Decode a base64 thumbnail and normalize it when Pillow is available."""
    try:
        image_bytes = decode_thumbnail_bytes(event["thumbnail"])
        return normalized_jpeg_response(image_bytes, event_id)
    except Exception as err:
        logging.error("Thumbnail decode failed event_id=%s: %s", event_id, err)
        return Response("Decode error", status=500)


def decode_thumbnail_bytes(raw_thumbnail: str) -> bytes:
    """Decode a possibly data-URI-prefixed base64 thumbnail."""
    raw_b64 = str(raw_thumbnail).strip()
    if raw_b64.startswith("data:"):
        raw_b64 = raw_b64.split(",", 1)[1]
    raw_b64 = "".join(raw_b64.split())
    missing_padding = len(raw_b64) % 4
    if missing_padding:
        raw_b64 += "=" * (4 - missing_padding)
    return base64.b64decode(raw_b64, validate=False)


def normalized_jpeg_response(image_bytes: bytes, event_id: str) -> Response:
    """Return a browser-friendly JPEG response, falling back to raw bytes."""
    try:
        from PIL import Image, ImageOps

        image = Image.open(io.BytesIO(image_bytes))
        image = ImageOps.exif_transpose(image)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")

        output = io.BytesIO()
        image.save(output, format="JPEG", quality=90, optimize=True)
        return image_response(output.getvalue())
    except Exception as err:
        logging.warning(
            "Thumbnail normalization failed; returning raw image event_id=%s: %s",
            event_id,
            err,
        )
        return image_response(image_bytes)


def image_response(image_bytes: bytes) -> Response:
    """Build a non-cacheable JPEG response."""
    return Response(
        image_bytes,
        mimetype="image/jpeg",
        headers={"Cache-Control": "no-store, max-age=0"},
    )
