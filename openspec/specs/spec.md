# System Specification (Source of Truth)

## Purpose
The VIVOTEK Vortex Webhook Server & Dashboard is a serverless application designed to receive, process, and visually stream real-time alarm webhooks from the VORTEX Portal. It comprises a lightweight Flask backend (webhook receiver & SSE broadcaster) and a premium, responsive glassmorphism dark-mode frontend dashboard.

---

## 1. Backend Specifications

### 1.1 Webhook Endpoint (`POST /webhook`)
*   **Path**: `/webhook`
*   **HTTP Method**: `POST`
*   **Content-Type**: Configured as `application/json` (falls back to raw body parsing on alternative types).
*   **Authentication**:
    *   MUST read the custom header `X-Vortex-Token`.
    *   MUST validate the token against the `VORTEX_TOKEN` environment variable (defaults to `vortex_default_secure_token`).
    *   MUST NOT block requests with invalid/missing tokens; instead, mark `debug_token_valid = false` and broadcast it to the dashboard with a warning highlight.
*   **Payload Properties & Parsing**:
    *   MUST support both VORTEX PascalCase schema and snake_case formats.
    *   Mapped Parameters:
        *   `organizationName` / `organization_name` / `org_name` -> `org_name`
        *   `organizationId` / `org_id` -> `org_id`
        *   `eventType` / `event_type` -> `event_type`
        *   `eventName` / `event_name` -> `event_name`
        *   `eventId` / `event_id` -> `event_id`
        *   `deviceName` / `device_name` -> `device_name`
        *   `deviceId` / `device_id` -> `device_id`
        *   `mac` / `macAddress` -> `mac`
        *   `deviceGroupName` / `device_group_name` -> `device_group_name`
        *   `deviceGroupId` / `device_group_id` / `deviceGroupID` -> `device_group_id`
        *   `localTime` / `local_time` -> `local_time` (raw integer)
        *   `localISOTime` / `local_iso_time` -> `local_iso_time`
        *   `utcTime` / `utc_time_val` -> `utc_time_val`
        *   `utcISOTime` / `utc_iso_time` -> `utc_iso_time`
        *   `timezone` -> `timezone`
        *   `alarmId` / `alarm_id` -> `alarm_id`
        *   `profileName` / `profile_name` -> `profile_name`
        *   `imageFace` / `image_face` -> `image_face`
        *   `imagePerson` / `image_person` -> `image_person`
        *   `thumbnail` / `Thumbnail` -> `thumbnail`
*   **Timestamp Normalization**:
    *   MUST resolve a unified `utc_time` display timestamp using the priority: `utcISOTime` > `utcTime` > `localISOTime` > `localTime` > Server Current Time.

### 1.2 SSE Broadcaster Endpoint (`GET /events`)
*   **Path**: `/events`
*   **HTTP Method**: `GET`
*   **Headers**: `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `Connection: keep-alive`.
*   **Streaming Rules**:
    *   Upon client connection, the server MUST emit a `history` event with a JSON array of the last 50 processed events stored in-memory.
    *   As new webhooks are received, the server MUST emit a `message` event with a single processed event JSON object.
    *   The server MUST emit a `: keep-alive` comment line every 15 seconds of silence to prevent connection timeouts.

### 1.3 Static Handler (`GET /`)
*   **Path**: `/`
*   **HTTP Method**: `GET`
*   **Description**: Serves the single-page application dashboard `templates/index.html`.

---

## 2. Frontend Dashboard Specifications

### 2.1 Connection & Error Recovery (SSE Client)
*   **Initialization**: Establishes a native `EventSource` connection to `/events`. Updates the connection status badge to green (`connected`) on success.
*   **Error Recovery**: On connection failure, updates the badge to red (`disconnected`), closes the source, and schedules automatic reconnection after 5 seconds.
*   **Data Updates**: Prepends incoming real-time events to the list, limiting the client-side list size to the last 50 events. Automatically highlights the latest active event.

### 2.2 Layout & Styling
*   **Theme**: Glassmorphism dark-mode backdrop (`background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%)`).
*   **Grid layout**: Left scrollable event list & statistics grid. Right details panel showing parsed parameters, debug HTTP headers, raw payload JSON, and media attachments.

### 2.3 Media Rendering (No-Collapse Design)
*   **Base64 Cleaning**: Before rendering, the client MUST strip all whitespace, carriage returns, and newlines from the base64 string (`.replace(/\s/g, '')`). MUST conditionally prepend the JPEG data URL prefix (`data:image/jpeg;base64,`) if absent.
*   **Left List Card Micro-thumbnails**: Rendered via `<img class="event-card-thumb" />` with explicit dimensions `width: 50px; height: 50px; object-fit: cover;`.
*   **Right Details Panel Images**:
    *   Face Crop, Person Crop, and Thumbnail images MUST be rendered as the CSS `background-image` of a wrapper `div` element to prevent flexbox rendering collapse bugs.
    *   The wrapper `div` (`.detail-image-view`) MUST be styled with `width: 100%; height: 180px; background-size: contain; background-repeat: no-repeat; background-position: center; background-color: #000;`.
    *   Clicking on the background-image block extracts the URL and opens it in a new window for zoomed view.

---

## 3. Scenarios & Behaviors

#### Scenario: Valid Webhook Received
*   **Given** a POST request to `/webhook` with header `X-Vortex-Token: vortex_default_secure_token`
*   **When** the request body contains a valid JSON payload
*   **Then** the server parses the fields, normalizes timestamps, inserts it at the front of the history, broadcasts it to all connected SSE clients, and returns HTTP `200` with `{"status": "success", "message": "Vortex Webhook processed"}`.

#### Scenario: Unauthenticated Webhook Received
*   **Given** a POST request to `/webhook` with header `X-Vortex-Token: invalid_token_value`
*   **When** the payload is processed
*   **Then** the server marks `debug_token_valid = false`, broadcasts the event to the dashboard (rendered with a red highlight boundary), and returns HTTP `200` with `{"status": "warning", "message": "...", "expected_token": "...", "received_token": "invalid_token_value"}`.

#### Scenario: Real-time Event Receival
*   **Given** the dashboard is open and connected
*   **When** a new event is emitted by the SSE broadcaster
*   **Then** the event list prepends the card, slides in with a smooth transition, updates the statistic numbers, and automatically shifts the active selection to this new event.
