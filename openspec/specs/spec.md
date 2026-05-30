# System Specification (Source of Truth)

## Purpose
The VIVOTEK Vortex Webhook Server & Dashboard receives alarm webhooks from VORTEX Portal, stores the latest events in memory, and streams them to a real-time web dashboard. The backend is a Flask app deployed on Google Cloud Run. The frontend is a single-page dashboard rendered from `templates/index.html`.

---

## Current Deployment

* **Platform**: Google Cloud Run
* **GCP Project**: `webhook-479112`
* **Region**: `asia-east1`
* **Service**: `vortex-webhook-server`
* **Latest deployed revision**: `vortex-webhook-server-00034-lbq`
* **Traffic**: 100% to latest revision
* **Service URL**: `https://vortex-webhook-server-flraxb4fsq-de.a.run.app`
* **Alternate run.app URL used during testing**: `https://vortex-webhook-server-933678246560.asia-east1.run.app`
* **Container image**: built by Cloud Run source deploy into Artifact Registry
* **Runtime command**: Gunicorn with one worker and eight threads

```bash
gunicorn --bind 0.0.0.0:8080 --workers 1 --threads 8 --timeout 0 main:app
```

The threaded Gunicorn configuration is required because `/events` is a long-lived SSE connection. A single sync worker can be occupied by one stream and block other requests.

---

## Backend Specifications

### `POST /webhook`

Receives VORTEX webhook events.

* Reads `X-Vortex-Token`.
* Validates the token against `VORTEX_TOKEN`.
* Optionally accepts `FALLBACK_VORTEX_TOKEN` when configured.
* Invalid tokens do not block ingestion. The event is still broadcast with `debug_token_valid = false` so the dashboard can display a warning.
* Parses JSON payloads from normal JSON requests, with raw-body JSON fallback.
* Generates a unique `internal_id` for each received webhook event using `uuid.uuid4().hex`.

Mapped payload fields:

* `organizationName` / `organization_name` / `org_name` -> `org_name`
* `organizationId` / `org_id` -> `org_id`
* `eventType` / `event_type` -> `event_type`
* `eventName` / `event_name` -> `event_name`
* `eventId` / `event_id` -> `event_id`
* `deviceName` / `device_name` -> `device_name`
* `deviceId` / `device_id` -> `device_id`
* `mac` / `macAddress` -> `mac`
* `deviceGroupName` / `device_group_name` -> `device_group_name`
* `deviceGroupId` / `device_group_id` / `deviceGroupID` -> `device_group_id`
* `localTime` / `local_time` -> `local_time`
* `localISOTime` / `local_iso_time` -> `local_iso_time`
* `utcTime` / `utc_time_val` -> `utc_time_val`
* `utcISOTime` / `utc_iso_time` -> `utc_iso_time`
* `timezone` -> `timezone`
* `alarmId` / `alarm_id` -> `alarm_id`
* `profileName` / `profile_name` -> `profile_name`
* `imageFace` / `image_face` -> `image_face`
* `imagePerson` / `image_person` -> `image_person`
* `thumbnail` / `Thumbnail` -> `thumbnail`

Timestamp display priority:

1. `utcISOTime`
2. `utcTime`
3. `localISOTime`
4. `localTime`
5. server current UTC time

### `GET /events`

Streams real-time events to the dashboard via Server-Sent Events.

Required behavior:

* Immediately sends `: connected` to flush the stream.
* Sends a `history` event with the current in-memory event history.
* Sends a `message` event for each new webhook.
* Sends `: keep-alive` every 15 seconds of silence.
* Uses `json.dumps(..., ensure_ascii=False)`.
* Uses `stream_with_context`.
* Sets:
  * `Content-Type: text/event-stream`
  * `Cache-Control: no-cache, no-transform`
  * `X-Accel-Buffering: no`

The event history is in memory and keeps up to 50 events. Deploying a new Cloud Run revision resets this history.

### `GET /thumbnail/<event_id>`

Serves normalized event thumbnails as real JPEG images.

Lookup rules:

* Match `event_id` against either `internal_id` or the original VORTEX `event_id`.
* Read the event `thumbnail` base64 string.
* Strip `data:` prefix if present.
* Remove whitespace and fix missing base64 padding.
* Decode the base64 image.
* Re-encode through Pillow as JPEG when possible:
  * `ImageOps.exif_transpose`
  * convert to RGB when needed
  * `quality=90`
  * `optimize=True`
* Fallback to raw decoded bytes if Pillow normalization fails.
* Return `404` if the event or thumbnail is not found.
* Return `Cache-Control: no-store, max-age=0`.

This endpoint exists because browser rendering of large inline base64 thumbnails in the right-side detail panel was unstable and made debugging harder. The left list can still use data URLs directly.

### `GET /`

Serves the dashboard and disables HTML caching:

* `Cache-Control: no-store, no-cache, must-revalidate, max-age=0`
* `Pragma: no-cache`
* `Expires: 0`

---

## Frontend Specifications

### Real-Time Connection

* Uses native `EventSource('/events')`.
* Shows `即時連線中` when connected.
* Shows disconnected state and retries after 5 seconds when SSE fails.
* Loads `history` into the dashboard.
* Prepends each live `message` event.
* Keeps at most 50 client-side events.
* Automatically selects the newest real event.

### Event Identity

Frontend selection must use:

```js
evt.internal_id || evt.event_id || ''
```

This prevents duplicate VORTEX `eventId` values from causing the wrong list item or detail panel to be selected.

### Image Rendering

Left alarm stream thumbnails:

* Use inline data URLs from the webhook `thumbnail`.
* Render with `.event-card-thumb`.
* Fixed dimensions: `50px x 50px`.
* `object-fit: cover`.

Right alarm detail thumbnail:

* Prefer `/thumbnail/<internal_id>?v=<timestamp>`.
* Use the embedded base64 data URL only as fallback.
* Render as a simple `<a><img></a>` pair through `renderDetailImage`.
* Clicking opens an in-page overlay preview instead of `window.open(data:image...)`, avoiding `about:blank`.
* Image CSS must constrain width and height:
  * `width: 100%`
  * `max-width: 100%`
  * `height: auto`
  * `max-height: 520px`
  * `object-fit: contain`

### Layout Stability

The right detail panel must never be expanded by raw base64 JSON or natural image dimensions.

Required CSS patterns:

* Main dashboard grid uses `minmax(360px, 450px) minmax(0, 1fr)`.
* Grid/flex children that contain long content must have `min-width: 0`.
* Detail rows use `100px minmax(0, 1fr)`.
* Image grid uses `repeat(2, minmax(0, 1fr))`.
* Raw JSON uses:
  * `white-space: pre-wrap`
  * `overflow-wrap: anywhere`
  * `word-break: break-all`
  * `max-width: 100%`
  * `min-width: 0`

### Alarm Stream Card Height

The left alarm list is a scroll container. Individual cards must not shrink when many events exist.

Required CSS:

* `.event-list { min-height: 0; overflow-y: auto; }`
* `.event-item { flex: 0 0 auto; min-height: 82px; }`
* `.event-card-inner { min-height: 50px; min-width: 0; }`
* Long labels, timestamps, device names, and MAC fields must not collapse the card height.

This fixes the issue where 50 events caused cards to compress vertically and clip thumbnails/text.

### Token Warning Display

If `debug_token_valid === false`, the selected event detail panel shows:

* Token mismatch warning.
* Received token value.
* Explanation that it differs from the currently configured Cloud Run `VORTEX_TOKEN`.
* Reminder that VORTEX Portal must send the custom header name `X-Vortex-Token`.

---

## Dependencies

Python dependencies:

* `Flask==3.0.0`
* `gunicorn==21.2.0`
* `Pillow==10.4.0`

Pillow is required for thumbnail normalization.

---

## Validation Performed

* `python3 -m py_compile main.py`
* `git diff --check`
* Cloud Run deployed and verified at the live service URL.
* Live SSE confirmed to return `: connected` and history/message events.
* Live dashboard verified:
  * status shows `即時連線中`
  * right-side thumbnail loads with nonzero natural dimensions
  * right-side panel no longer expands to abnormal width
  * left-side event cards remain full height and scroll normally

---

## GitHub State

Changes were merged through:

* PR: `https://github.com/daydreamman/vortex-webhook-server/pull/1`
* Base branch: `main`
* Feature branch: `codex/fix-live-thumbnail-rendering`
* Merge commit: `a4e325c`

The repository default branch is `main`, not `master`.
