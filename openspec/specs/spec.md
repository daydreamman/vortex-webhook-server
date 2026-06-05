# System Specification (Source of Truth)

## Purpose
The VIVOTEK Vortex Webhook Server & Dashboard receives alarm webhooks from VORTEX Portal, stores the latest events in memory, and streams them to a real-time web dashboard. The backend is a Flask app deployed on Google Cloud Run. The primary frontend dashboard is rendered from `templates/index.html`. The alternate `/monitor` frontend has its own independent specification in `openspec/specs/monitor.md`.

---

## Current Deployment

* **Platform**: Google Cloud Run
* **GCP Project**: `webhook-479112`
* **Region**: `asia-east1`
* **Service**: `vortex-webhook-server`
* **Latest deployed revision**: `vortex-webhook-server-00068-sgf`
* **Traffic**: 100% to latest revision
* **Service URL**: `https://vortex-webhook-server-flraxb4fsq-de.a.run.app`
* **Alternate run.app URL used during testing**: `https://vortex-webhook-server-933678246560.asia-east1.run.app`
* **Custom domain**: `https://webhook.vivotek.tools`
* **Customer webhook URL**: `https://webhook.vivotek.tools/webhook`
* **Container image**: built by Cloud Run source deploy into Artifact Registry
* **Runtime command**: Gunicorn with one worker and eight threads
* **Cost-control settings**:
  * Minimum instances: `0`
  * Maximum instances: `1`
  * Memory limit: `256Mi`
  * CPU limit: `1`
  * CPU throttling: enabled
  * Startup CPU boost: disabled
  * Container concurrency: `80`

```bash
gunicorn --bind 0.0.0.0:8080 --workers 1 --threads 8 --timeout 0 main:app
```

The threaded Gunicorn configuration is required because `/events` is a long-lived SSE connection. A single sync worker can be occupied by one stream and block other requests.

The cost-control settings keep the service able to scale to zero when idle, prevent multiple instances from being created during bursts, and reduce memory allocation cost. Any future Cloud Run deploy must preserve these settings unless the operating requirement changes.

Source deployments must use `.gcloudignore` to exclude local tooling, virtual environments, Git metadata, and Python bytecode caches from the uploaded source bundle.

---

## Backend Specifications

### Flask Application Structure

The backend uses a Flask application factory and Blueprint-based route organization.

Required behavior:

* `main.py` remains the WSGI entry point and exposes `app = create_app()`.
* The application factory lives in `app/__init__.py`.
* Dashboard and API routes are registered through `app/routes/dashboard.py`.
* Token-scoped event history and subscriber coordination stay in process memory.
* Shared route logic must be delegated to service modules:
  * `app/services/events.py` for in-memory event history broadcasting and SSE subscriptions.
  * `app/services/webhook.py` for webhook token validation and Vortex payload mapping.
  * `app/services/thumbnails.py` for thumbnail lookup, decoding, and JPEG normalization.
  * `app/services/vortexai.py` for VortexAI login and getrecords proxy orchestration.
  * `app/services/vortexai_metadata.py` for VortexAI metadata download/debug helpers.
  * `app/services/vortexai_trajectory.py` for VortexAI trajectory extraction.
* Template and static folders continue to resolve to the repository-level `templates/` and `static/` directories.
* This structure must preserve the public routes and response behavior documented below.

### `POST /webhook`

Receives VORTEX webhook events.

* Reads `X-Vortex-Token`.
* Validates the token against the set of registered `X-Vortex-Token` values.
* There is no built-in or environment-provided default accepted token.
* A token is accepted only after a dashboard user saves it through `POST /settings/token`.
* Invalid tokens are rejected with HTTP `401`.
* Rejected events are not parsed into dashboard events, not stored in event history, and not broadcast over SSE.
* Accepted events are stored in an in-memory history partition keyed by the received `X-Vortex-Token`.
* Accepted events are broadcast only to dashboard clients subscribed with the same token.
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

### `GET /settings/token`

Returns an empty `X-Vortex-Token` value when a browser has no saved local token.

Response shape:

```json
{
  "x_vortex_token": "",
  "configured": false
}
```

Required behavior:

* Does not expose or register any default token.
* Does not mutate the runtime token registry.

### `POST /settings/token`

Registers a dashboard-scoped `X-Vortex-Token` value.

Required request shape:

```json
{
  "x_vortex_token": "..."
}
```

Required behavior:

* Rejects an empty token with HTTP `400`.
* Registers the token in process memory so `POST /webhook` can accept events with that token.
* Does not make the token global for other dashboard clients.
* Does not persist across Cloud Run instance restart or new revision deployment.

### `GET /events`

Streams real-time events to the dashboard via Server-Sent Events.

Required behavior:

* Immediately sends `: connected` to flush the stream.
* Reads the subscriber token from `/events?token=<X-Vortex-Token>`.
* Sends a `history` event with the current in-memory event history for that token.
* Sends a `message` event only for new webhooks received with the same token.
* Sends a `clear` event only when the server-side event history for the same token is cleared from the dashboard.
* Sends `: keep-alive` every 15 seconds of silence.
* Uses `json.dumps(..., ensure_ascii=False)`.
* Uses `stream_with_context`.
* Sets:
  * `Content-Type: text/event-stream`
  * `Cache-Control: no-cache, no-transform`
  * `X-Accel-Buffering: no`

The event history is partitioned by `X-Vortex-Token`, kept in memory, and has no application-level event count limit. Deploying a new Cloud Run revision or restarting the instance resets this history. Because events are kept in memory, high-volume deployments should be monitored for memory growth.

### `POST /events/clear`

Clears all stored dashboard events.

Required behavior:

* Reads `x_vortex_token` from the JSON request body.
* Clears only the event history for that token.
* Broadcasts an SSE `clear` event only to connected dashboard clients subscribed to that token.
* Returns HTTP `200` with a success JSON response.
* Does not clear other token partitions.

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

### Dashboard Page Rendering

Dashboard HTML pages must be rendered with caching disabled:

* `Cache-Control: no-store, no-cache, must-revalidate, max-age=0`
* `Pragma: no-cache`
* `Expires: 0`

The Flask app uses a shared helper for dashboard template rendering so all dashboard pages receive the same no-cache headers.

### `GET /`

Serves the primary dashboard from `templates/index.html`.

### `GET /monitor`

Serves the alternate monitor dashboard. The monitor route, template, frontend behavior, and future monitor-specific requirements are specified independently in `openspec/specs/monitor.md`.

---

## Frontend Specifications

### Branding

The dashboard header uses the VORTEX logo from the official VORTEX website.

Required behavior:

* The logo asset is stored locally at `static/images/vortex-logo.svg`.
* The header renders it through Flask static routing:

```html
<img class="brand-logo" src="{{ url_for('static', filename='images/vortex-logo.svg') }}" alt="VORTEX">
```

* The logo links to `https://www.vortexcloud.com/tc`.
* Because the official SVG contains dark lettering, it must sit on a light rounded background in the dark dashboard header.
* The adjacent page title is `Webhook Live Monitor` to avoid duplicating the VORTEX wordmark.

### Visual Style

The dashboard uses a light, clean visual style inspired by VORTEX/AI search review pages.

Required behavior:

* Overall background is light neutral (`#fafafa`) rather than a dark gradient.
* Header is a white sticky bar with a subtle bottom border.
* Panels are white cards with thin neutral borders, soft shadow, and rounded corners.
* Event cards use light borders, small shadows, rounded image thumbnails, and a restrained active state.
* Summary metric cards use equal heights, fixed title space, and aligned value baselines.
* Latest activity uses a compact numeric `HH:MM:SS` style instead of locale-specific AM/PM text.
* Status badges and event tags use pill styling with neutral colors unless communicating connection or warning state.
* JSON/debug blocks use light gray surfaces and dark readable text.
* The existing left alarm stream and right alarm detail two-column structure remains intact.
* This style is deployed in revision `vortex-webhook-server-00064-s2z`.

### Mobile Header Layout

At phone-sized widths, the dashboard header must avoid overlapping the brand area, connection badge, webhook URL control, and token setting control.

Required behavior:

* At `max-width: 720px`, the header stacks vertically.
* The logo/title area occupies its own row.
* The Live/connection badge, webhook URL control, and `X-Vortex-Token` control are laid out as separate rows.
* The webhook URL and token inputs are the only elements that shrink horizontally.
* The copy, `?`, and `Save` buttons remain visible and keep fixed touch-friendly dimensions.
* Copy/save status text may be hidden on phone-sized widths to preserve the control layout.

### Responsive Alarm Details

When the viewport is narrow enough that the dashboard can only comfortably show the alarm stream column, the right-side alarm detail panel is hidden.

Required behavior:

* At `max-width: 1100px`, the dashboard becomes a single-column alarm stream view.
* The standalone right-side `Alarm Details` card is hidden in this single-column mode.
* Clicking an alarm event card in single-column mode expands the selected event details directly below that event card.
* Clicking the same event card again collapses the inline details and returns the card to its compact state.
* Clicking a different event card moves the same detail/debug DOM content under the newly selected card.
* The inline detail section includes the same image, parsed field, raw payload, and debug information shown in the desktop right-side panel.
* Live/history events are not automatically expanded in single-column mode; details appear only after the user clicks an event card.
* Desktop mode keeps the two-column layout and automatically selects the newest real event.

### Language

All dashboard UI text, user-facing messages, help content, empty states, debug labels, and backend response/log messages must be in English.

### Customer Webhook URL Display

The dashboard header shows the customer webhook URL so visitors know what to configure in VORTEX Portal.

Required behavior:

* Display `https://webhook.vivotek.tools/webhook` as the customer webhook URL.
* Provide a copy button beside the URL.
* If clipboard writing is blocked by the browser, select the URL text and show `URL selected`.
* The token setup help dialog must also instruct users to set the VORTEX webhook URL to `https://webhook.vivotek.tools/webhook`.
* The empty state must mention the same URL and the required `X-Vortex-Token` header.

### Real-Time Connection

* Uses native `EventSource('/events?token=<X-Vortex-Token>')`.
* Shows `Live` when connected.
* Shows disconnected state and retries after 5 seconds when SSE fails.
* Loads token-scoped `history` into the dashboard.
* Prepends each live token-scoped `message` event.
* Handles token-scoped `clear` events by clearing the client event list and resetting the detail panel.
* Does not apply a client-side event count limit.
* Automatically selects the newest real event until the user manually selects an event card.
* After the user manually selects an event card, new live events continue to appear in the alarm stream and update statistics, but must not replace the selected detail image, parsed fields, or raw payload.
* Clearing events or changing the saved token resets the manual selection lock.
* When the saved token changes, reconnects SSE with the new token and reloads only that token's event history.

### Alarm Stream Controls

The Alarm Stream title bar includes a `Clear` button with a trash icon and visible `Clear` text.

Required behavior:

* Calls `POST /events/clear` with the current browser token.
* Clears the local event list and resets statistics/detail state after success.
* Connected dashboard clients with the same token also clear when they receive the SSE `clear` event.
* Connected dashboard clients using other tokens must not clear.

### X-Vortex-Token Setting UI

The dashboard header includes runtime webhook token controls.

Required behavior:

* Displays an editable `X-Vortex-Token` input.
* Loads the saved browser token from `localStorage`; when no browser token exists, the token input stays empty and prompts the user to set a token.
* Has no default `X-Vortex-Token`.
* Saves changes to `localStorage` and registers the token through `POST /settings/token`.
* Shows save status next to the setting.
* Provides a `?` help button.
* The help dialog explains that VORTEX webhook settings must add a custom header named `X-Vortex-Token` with the saved token value.
* After saving, this browser sees only webhook events whose `X-Vortex-Token` header equals the saved value.
* The dashboard must not open `/events` or accept webhook events for a visitor until that visitor saves an `X-Vortex-Token`.
* The token setting row must keep the `?` and `Save` buttons visible without text wrapping; the token input is the element that shrinks when horizontal space is tight.
* Two dashboard clients using different tokens must not see each other's events.

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
* `.event-card-inner { min-height: 50px; min-width: 0; align-items: flex-start; }`
* Event name/type tags must occupy their own row above the timestamp.
* Event name/type tags must allow wrapping with `white-space: normal` and `overflow-wrap: anywhere`.
* The timestamp must occupy its own row below the event name/type tag.
* Long labels, timestamps, device names, and MAC fields must not collapse the card height or visually cover each other.

This keeps cards from compressing vertically and clipping thumbnails/text when many events are present.

### Rejected Token Behavior

Events with an `X-Vortex-Token` header that is not registered are rejected by the backend and do not appear in the dashboard. There is no built-in default accepted token. Events with a registered token appear only in dashboard clients subscribed to that same token.

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
* Local Flask run with `.venv/bin/python main.py`
* Local browser verification of `http://127.0.0.1:8080/`
* `git diff --check`
* Cloud Run deployed revision `vortex-webhook-server-00064-s2z` and verified it at the live service URL.
* Live asset check for `/static/images/vortex-logo.svg` returned HTTP `200` and `Content-Type: image/svg+xml`.
* Live browser verification confirmed the header logo loads with nonzero natural dimensions.
* Live token settings API confirmed `X-Vortex-Token` is empty with `configured: false` for a first-time visitor.
* Live webhook token filtering confirmed:
  * unregistered `X-Vortex-Token` returns HTTP `401`
  * the same `X-Vortex-Token` returns HTTP `200` only after being registered through `POST /settings/token`
* Live `/events` verification confirmed missing `X-Vortex-Token` returns HTTP `400`.
* Cloud Run service settings verified `VORTEX_TOKEN` was removed from the deployed environment.
* Live browser verification confirmed the token input, save button, and `?` help button are present.
* Local `/settings/token` verification confirmed it returns an empty token with `configured: false`.
* Local `/events` verification confirmed missing `X-Vortex-Token` returns HTTP `400`.
* Local webhook verification confirmed an unregistered token returns HTTP `401`, and the same token is accepted only after `POST /settings/token` registers it.
* Cloud Run revision `vortex-webhook-server-00067-m4x` attempted to deploy the Flask application factory, Blueprint route organization, service layer refactor, and `.gcloudignore` source packaging rules, but failed to boot because Cloud Run uses Python 3.9 and one type annotation used Python 3.10 union syntax.
* Cloud Run revision `vortex-webhook-server-00068-sgf` deployed the Python 3.9-compatible Flask application factory, Blueprint route organization, service layer refactor, and `.gcloudignore` source packaging rules.
* Live `/` and `/monitor` for revision `vortex-webhook-server-00068-sgf` returned HTTP `200`.
* Live `/settings/token` for revision `vortex-webhook-server-00068-sgf` returned an empty token with `configured: false`.
* Live `/events` for revision `vortex-webhook-server-00068-sgf` returned HTTP `400` when no `X-Vortex-Token` was supplied.
* Local `/` browser verification confirmed a first-time visitor sees an empty token input, `Disconnected` status, and `Set token to start`.
* Live SSE confirmed to return `: connected` and history/message events.
* Live dashboard verified:
  * status shows `Live`
  * right-side thumbnail loads with nonzero natural dimensions
  * right-side panel no longer expands to abnormal width
  * left-side event cards remain full height and scroll normally

---

## GitHub State

Changes were merged through:

* PR: `https://github.com/daydreamman/vortex-webhook-server/pull/1`
* PR: `https://github.com/daydreamman/vortex-webhook-server/pull/2`
* PR: `https://github.com/daydreamman/vortex-webhook-server/pull/3`
* Base branch: `main`
* Earlier feature branch: `codex/fix-live-thumbnail-rendering`
* Earlier merge commit: `a4e325c`

Current unmerged local changes after PR #3:

* Runtime `X-Vortex-Token` setting UI and help dialog.
* `/settings/token` API for reading/updating the webhook token.
* Hard rejection of webhook events whose `X-Vortex-Token` does not equal the runtime setting.
* Token setting row layout fix so `?` and `Save` buttons remain visible in narrow headers.
* English-only UI and user-facing messages.
* Customer webhook URL display and copy action.
* Clipboard fallback for the webhook URL copy action.
* Clear events button and `/events/clear` endpoint.
* Token-scoped event history, SSE delivery, and clear behavior for multi-user isolation.
* Visible `Clear` text on the Alarm Stream clear button.
* Summary metric card alignment refinement.
* Cloud Run deployment with token setting/filtering, layout, language, webhook URL, clear-event, token isolation, and summary card updates: revision `vortex-webhook-server-00047-wp5`.

The repository default branch is `main`, not `master`.
