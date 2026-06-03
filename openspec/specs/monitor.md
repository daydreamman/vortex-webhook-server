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
* Shows the alarm stream list.
* Shows alarm details, raw payload, and debug information for the selected event.
* Supports Clear for the current token-scoped event partition.
* Uses the same mobile responsive behavior as the primary dashboard until replaced by a monitor-specific design.

---

## Selection Behavior

Required behavior:

* Before a user manually selects an event card, the newest real event may be selected automatically on desktop-width layouts.
* After a user manually selects an event card, new live events must continue to appear in the alarm stream and update statistics, but must not replace the selected detail image, parsed fields, or raw payload.
* Clearing events or changing the saved token resets the manual selection lock.
* On narrow layouts, event details are displayed inline beneath the selected event card and can be collapsed by clicking the same card again.

---

## Event Card Layout

Required behavior:

* Event name/type tags must occupy their own row above the timestamp.
* Event name/type tags must wrap instead of being clipped or covered.
* The timestamp must occupy its own row below the event name/type tag.
* Long event names, timestamps, camera names, and MAC values must not visually overlap.
* The event card may grow vertically to preserve important information.

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

## Validation Performed

* Local `GET /monitor` returned HTTP `200`.
* Local `/monitor` returned no-cache headers.
* Local `/monitor` loaded the dashboard UI and showed `Live`.
* Live `GET /monitor` returned HTTP `200`.
* Live `/monitor` returned no-cache headers.
* Live `/monitor` loaded the dashboard UI and showed `Live`.
