# Monitor Dashboard Specification

## Purpose

The `/monitor` dashboard is an alternate frontend entry point for the VIVOTEK Vortex Webhook Server. It is intended to evolve into a new web UI without changing the primary dashboard at `/`.

This specification is the source of truth for the `/monitor` route and `templates/monitor.html`.

---

## Route

### `GET /monitor`

Serves the monitor dashboard from `templates/monitor.html`.

Required behavior:

* Returns HTTP `200`.
* Renders with the same no-cache dashboard headers used by `/`:
  * `Cache-Control: no-store, no-cache, must-revalidate, max-age=0`
  * `Pragma: no-cache`
  * `Expires: 0`
* Uses the shared Flask dashboard render helper.
* Must not redirect to `/`.
* Must not reuse `templates/index.html` directly.

---

## Template Ownership

The monitor UI owns its own template file:

```text
templates/monitor.html
```

Required behavior:

* `templates/monitor.html` must exist as an independent file.
* Changes intended only for the new monitor UI should be made in `templates/monitor.html`.
* Changes intended only for the primary dashboard should be made in `templates/index.html`.
* Shared backend behavior must stay in `main.py` and shared API endpoints, not be duplicated in the monitor template.
* The monitor template may initially match `templates/index.html`, but future monitor-specific UI changes should not require editing `templates/index.html`.

---

## Shared Backend APIs

The monitor dashboard uses the same backend APIs as the primary dashboard.

Required APIs:

* `POST /webhook`
* `GET /settings/token`
* `POST /settings/token`
* `GET /events`
* `POST /events/clear`
* `GET /thumbnail/<event_id>`

Required behavior:

* Relative frontend API calls must continue to work from `/monitor`.
* The monitor dashboard must subscribe to events with `EventSource('/events?token=<X-Vortex-Token>')`.
* The monitor dashboard must not subscribe to `/events` until the user has a saved `X-Vortex-Token`.
* Token-scoped event isolation is shared with the primary dashboard.
* Clearing events from `/monitor` clears only the current token partition, matching primary dashboard behavior.
* Thumbnail rendering from `/monitor` must continue to use `/thumbnail/<event_id>?token=<X-Vortex-Token>` when a normalized thumbnail is available.

---

## Initial UI Behavior

Until intentionally redesigned, `/monitor` must preserve the current dashboard behavior.

Required behavior:

* Shows the VORTEX logo and `Webhook Live Monitor` title.
* Shows the customer webhook URL: `https://webhook.vivotek.tools/webhook`.
* Provides editable `X-Vortex-Token` settings with a `?` setup guide and `Save` button.
* Shows live connection state.
* Shows the alarm stream as a date-grouped gallery of visual event cards.
* Does not show the primary dashboard's right-side alarm detail, raw payload, or debug panel.
* Supports Clear for the current token-scoped event partition.
* Uses the same mobile responsive behavior as the primary dashboard until replaced by a monitor-specific design.

---

## Selection Behavior

Required behavior:

* Event cards must not open or update a side debug/detail panel.
* New live events must continue to appear in the gallery and update statistics.
* Clicking an event card may open an in-page image preview for the card image.
* Clearing events or changing the saved token resets the gallery to an empty state for the active token partition.

---

## Event Gallery Layout

Required behavior:

* Events must render as one continuous gallery without date headings.
* Event cards must be sorted by trigger time from oldest to newest, so the newest card appears last.
* Live updates must preserve existing event card DOM nodes when possible instead of replacing the full gallery, so incoming events do not cause the whole page or all images to flash.
* History reloads and live events must merge by stable event key; an already-known event must update in place rather than create a duplicate card or replace the whole event array.
* The stable event key must prefer the VORTEX `event_id` and only fall back to backend `internal_id` when the event has no external ID.
* When an existing event changes, text fields and metadata must update in place without replacing the entire gallery; media nodes should be preserved unless the event's media structure changes.
* Event card icons must not require running a full-page icon replacement pass during each live update.
* Event cards must not use entry animations during live updates.
* Event display times and sort order must be based on a browser-local client time derived from the event `local_iso_time` or `local_time` plus its `timezone`, falling back to `utc_time` only when local fields are unavailable.
* Each event card must use a VORTEX search-result style layout:
  * A light blue header row with camera/profile name, a chevron, and event type/name.
  * A large image area using the event thumbnail as the main image.
  * When face/person crop imagery is available, show it as a narrow crop panel beside the main image.
  * A footer row with large trigger time, camera name, and event date.
* Event card images, including vertical or narrow face/person crops, must display the complete image inside the card media area instead of cropping to only the upper or lower portion.
* Long camera/profile/event labels must be truncated or wrapped within their own regions and must not overlap.
* The gallery must use a dense responsive grid that can fit more cards on wide screens.
* Event cards should use compact spacing, compact header text, and smaller metadata typography to increase visible card density.
* The gallery must collapse to one column on narrow phone-sized screens.
* The right-side debug/detail panel from the primary dashboard must stay hidden on `/monitor`.

---

## Relationship To `openspec/specs/spec.md`

`openspec/specs/spec.md` remains the source of truth for:

* Cloud Run deployment settings.
* Shared backend APIs.
* Token validation and token-scoped event history.
* Shared thumbnail normalization.
* Primary dashboard behavior for `/`.

This file remains the source of truth for:

* `/monitor`.
* `templates/monitor.html`.
* Monitor-specific UI behavior and future monitor redesign requirements.

When a future change affects both dashboards, update both relevant specs. When a change affects only `/monitor`, update this file only.

---

## Imported VortexAI OpenAPI

The user provided a VortexAI OpenAPI 3.0.3 specification for future monitor work.

Stored files:

```text
openspec/external/vortexai-openapi.yaml
openspec/external/vortexai-openapi-summary.md
```

Required behavior:

* Treat `openspec/external/vortexai-openapi.yaml` as the canonical imported API specification.
* Use `openspec/external/vortexai-openapi-summary.md` as a quick navigation summary only.
* The imported VortexAI API uses JWT bearer auth, separate from the dashboard's `X-Vortex-Token` webhook isolation.
* `/monitor` includes a VortexAI login dialog based on the OpenAPI `POST /login` endpoint.
* Login must only call VortexAI `POST /login` to obtain a JWT token; it must not call Deepsearch or any other VortexAI API as part of login.
* When login succeeds, the dialog closes, the backend keeps the JWT in memory, and the browser stores only an opaque `vortexai_session_id` for future monitor API calls.
* When login succeeds, `/monitor` must show an obvious logged-in action/state indicator in the header.
* The backend must not return the password or JWT to the browser.
* When login fails, the UI must present a clear username/password error message.
* The backend VortexAI proxy must restrict `base_url` to supported VortexAI hosts.
* After VortexAI login, each event card must provide an object-record action that converts the card's trigger time to UTC, sends the UTC time and camera MAC to the backend, and calls VortexAI `POST /api/deepsearch/getrecords` with the stored JWT.
* Object-record responses containing trajectory data with `base` and `diff` must be converted to cumulative points by adding each diff to the previous coordinate.
* Trajectory coordinates use the Vortex `0..9999` coordinate system and must be rendered onto the card image using `x * width / 10000` and `y * height / 10000` equivalent scaling.

---

## Validation Performed

* Local `GET /monitor` returned HTTP `200`.
* Local `/monitor` returned no-cache headers.
* Local `/monitor` loaded the dashboard UI and showed `Live`.
* Live `GET /monitor` returned HTTP `200`.
* Live `/monitor` returned no-cache headers.
* Live `/monitor` loaded the dashboard UI and showed `Live`.
* Cloud Run revision `vortex-webhook-server-00059-br2` deployed the continuous no-date monitor gallery with DOM-preserving live updates.
* Live `/monitor` verified the right-side debug/detail panel is hidden.
* Local interleaved-date event test verified each date heading appears once, no duplicate headings remain, and no orphan headings are rendered.
* Local live-update test verified no date headings render, event cards sort oldest-to-newest, and `Latest activity` reflects the newest event timestamp.
* Local browser test verified `localISOTime` plus `timezone` converts to browser-local display time: `2026-06-04T10:30:00` in `Asia/Tokyo` displayed as `09:30:00` for the Taipei browser.
* Local duplicate-event test verified repeated VORTEX `event_id` updates an existing card in place instead of adding a duplicate card.
* Local DOM test verified event cards have no entry animation and no per-card `data-lucide="video"` replacement targets during live updates.
* Live `GET /monitor` for revision `vortex-webhook-server-00059-br2` returned HTTP `200` with no-cache headers.
* Live browser DOM check for revision `vortex-webhook-server-00059-br2` verified `Live`, 20 rendered cards, zero date headings, zero animated event cards, and zero per-card Lucide video placeholders.
* Local browser check verified the VortexAI login dialog opens, defaults to `https://vortexai.vortexcloud.com/`, and event card images use `object-fit: contain`.
* Local API check verified `POST /monitor/vortexai/login` rejects missing credentials and rejects unsupported base URL hosts.
* Local credential test verified `POST /monitor/vortexai/login` succeeds with a valid VortexAI account, returns an opaque `vortexai_session_id`, and does not call Deepsearch.
* Local invalid-password test verified `POST /monitor/vortexai/login` returns a clear username/password error message.
* Local getrecords test verified the stored VortexAI session can call `POST /api/deepsearch/getrecords` with card-style UTC time and MAC payload; the sample MAC `0002D1BC2DEE` returns `No permission to access mac 0002D1BC2DEE` for the tested account.
* Cloud Run revision `vortex-webhook-server-00060-djq` deployed the VortexAI login/session state, event object-record action, and trajectory overlay changes.
* Live `GET /monitor` for revision `vortex-webhook-server-00060-djq` returned HTTP `200` with no-cache headers.
* Live browser DOM check for revision `vortex-webhook-server-00060-djq` verified `Live`, 19 rendered cards, 19 object-record action buttons, zero date headings, and the VortexAI login/session indicator UI.
* Cloud Run revision `vortex-webhook-server-00064-s2z` deployed the no-default-token runtime behavior shared by `/` and `/monitor`.
* Live `/settings/token` on revision `vortex-webhook-server-00064-s2z` returned an empty token with `configured: false`.
* Live `/events` on revision `vortex-webhook-server-00064-s2z` returned HTTP `400` when no `X-Vortex-Token` was supplied.
