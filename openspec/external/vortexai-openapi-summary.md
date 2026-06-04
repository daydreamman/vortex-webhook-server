# VortexAI OpenAPI Summary

## Source File

Original user-provided file:

```text
/Users/small/Downloads/openapi 1 1.yaml
```

Stored project copy:

```text
openspec/external/vortexai-openapi.yaml
```

## API Identity

* OpenAPI version: `3.0.3`
* Title: `VortexAI API`
* Version: `1.0.0`
* Description: `VortexAI backend REST API`
* Default server: `https://vortexai.dev.vortexcloud.com`
* Server options:
  * `vortexai.dev.vortexcloud.com`
  * `vortexai.stage.vortexcloud.com`
  * `vortexai.vortexcloud.com`
  * `localhost`

## Authentication

Global security uses JWT bearer auth:

```yaml
security:
  - bearerAuth: []
```

Security scheme:

```yaml
bearerAuth:
  type: http
  scheme: bearer
  bearerFormat: JWT
```

The `/login` endpoint is unauthenticated and returns a JWT token.

## Operation Counts

Parsed standard HTTP operations:

* Total: `89`
* `GET`: `28`
* `POST`: `48`
* `PUT`: `3`
* `PATCH`: `1`
* `DELETE`: `9`

## Main API Areas

* Auth: login and JWT acquisition.
* UserFeedback: submit/check/query detection feedback.
* Deepsearch: object detection search, query history, camera descriptions, natural language ThinkSearch, appearance-based re-identification, object trace query.
* FaceProfile: legacy and v2 face profile CRUD, image upload/delete, detection matching, grant tokens, feedback.
* VehicleProfile: vehicle profile CRUD and batch creation.
* ObjectDetection: time buckets, counts, and fetch by record keys.
* UnifiedProfile: unified face/vehicle profile list and profile tags.
* CaseVault: case vault CRUD, export, auto description, attachments, sharing, shared case access.
* UniqueFace: beta and v1 face cluster summary/detail APIs.
* VSLC: aggregate, record, and dictionary detection APIs.
* Misc/System: archive feedback, AI proxy capability, OpenAI key grant, offensive checks, latest thumbnails, temp cleanup, version, health, message search.

## Endpoint Index

### Auth

* `POST /login` - Get JWT token.

### UserFeedback

* `POST /userFeedback` - Submit user feedback for a detection event.
* `GET /userFeedbackStatus` - Check if a detection event has been feedbacked.
* `GET /query_userfeedback` - Query user feedback records with `X-VIVOTEK-AUTH`.

Note: The original YAML also contains non-standard nested keys under `/userFeedback` named `user_feedback_status` and `query_userfeedback`. Use the top-level standard paths above for implementation unless the upstream spec is corrected.

### Deepsearch

* `POST /v2/deepsearch` - Cursor-based object detection search.
* `GET /v2/deepsearch/history` - Get query history.
* `DELETE /v2/deepsearch/history` - Clear query history.
* `GET /v2/deepsearch/descriptions` - Get camera descriptions for ThinkSearch.
* `PUT /v2/deepsearch/descriptions` - Save camera descriptions for ThinkSearch.
* `POST /v1/deepsearch` - Search object detection records.
* `POST /v1/deepsearch/count` - Count object detection records.
* `POST /thinksearch` - Natural language search using an LLM agent.
* `POST /v1/research` - Find similar objects by reference.
* `POST /deepsearch` - Legacy Deepsearch.
* `POST /deepsearch_first` - Legacy Deepsearch first step.
* `POST /deepsearch_second` - Legacy Deepsearch second step.
* `POST /v1/object_trace/query` - Query object trace records.

### FaceProfile

* `POST /faceprofile_search` - Search face profiles.
* `POST /faceprofile_create` - Create face profile.
* `POST /faceprofile_list` - List face profiles.
* `POST /faceprofile_rename` - Rename face profile.
* `POST /faceprofile_delete` - Delete face profile.
* `POST /faceprofile_update` - Update face profile.
* `POST /faceprofile_grant` - Grant face profile token.
* `POST /v1/faceprofile_grant` - Grant face profile token.
* `POST /faceprofile_feedback` - Submit face profile feedback.
* `POST /faceprofile_upload` - Upload face profile image.
* `GET /v1/profile_grant` - Get temporary S3 credentials for profile image access.
* `GET /v2/profile/face` - List face profiles.
* `POST /v2/profile/face` - Create a face profile.
* `GET /v2/profile/face/{profile_id}` - Get a face profile by ID.
* `PATCH /v2/profile/face/{profile_id}` - Update a face profile.
* `DELETE /v2/profile/face/{profile_id}` - Delete a face profile.
* `POST /v2/profile/face/{profile_id}/images` - Upload an image to a face profile.
* `DELETE /v2/profile/face/{profile_id}/images/{img_id}` - Delete an image from a face profile.
* `POST /v2/profile/face/{profile_id}/detections` - Search detections matching a face profile.

### VehicleProfile

* `POST /v1/vehicle_profile_search` - Search vehicle profiles by license plate.
* `POST /v2/profile/vehicle` - Create a vehicle profile.
* `GET /v2/profile/vehicle/{profile_id}` - Get a vehicle profile by ID.
* `PUT /v2/profile/vehicle/{profile_id}` - Update a vehicle profile.
* `DELETE /v2/profile/vehicle/{profile_id}` - Delete a vehicle profile.
* `POST /v2/profiles/vehicles` - Batch create vehicle profiles.

### ObjectDetection

* `POST /v1/object-detection-records/timebuckets` - Query object detection time buckets.
* `POST /v1/object-detection-records/timebuckets/counts` - Query object detection time bucket counts.
* `POST /v1/object-detection-records/by-record-keys` - Fetch object detection records by record keys.

### UnifiedProfile

* `GET /v2/profile` - List all face and vehicle profiles.
* `GET /v2/profile/tags` - Get profile tags used in the organization.

### CaseVault

* `GET /caseVaults` - Get case vaults.
* `POST /caseVaults` - Create a case vault.
* `DELETE /caseVaults` - Delete all case vaults for the organization.
* `GET /caseVaultExportStatus` - Get export status for all case vaults.
* `GET /listCaseVaults` - List case vaults.
* `GET /caseVault/{case_id}` - Get a case vault by ID.
* `PUT /caseVault/{case_id}` - Update a case vault.
* `DELETE /caseVault/{case_id}` - Delete a case vault.
* `GET /caseVault/{caseId}/videoStatistics` - Get video statistics.
* `GET /export/caseVault/{caseId}/{export_type}` - Get export status/download link.
* `POST /export/caseVault/{caseId}/{export_type}` - Start export.
* `DELETE /export/caseVault/{caseId}/{export_type}` - Cancel/delete export.
* `POST /caseVault/{caseId}/autoDescription` - Generate auto description.
* `GET /caseVault/{case_id}/attachment` - List attachments.
* `POST /caseVault/{case_id}/attachment` - Upload attachment.
* `DELETE /caseVault/{case_id}/attachment/{attachment_id}` - Delete attachment.
* `GET /caseVault/{case_id}/share` - Get share links.
* `POST /caseVault/{case_id}/share` - Create a share link.
* `DELETE /caseVault/{case_id}/share` - Delete a share link.
* `GET /shared/caseVault/{organization_id}/{case_id}` - Access a shared case vault without auth using share token.
* `POST /shared/caseVault/{organization_id}/{case_id}/grant` - Grant temporal credentials for a shared case vault.

### UniqueFace

* `POST /beta/faces/clusters/summary` - Get unique face cluster summary.
* `POST /beta/faces/clusters/detail-info` - Get unique face cluster detail info.
* `POST /v1/faces/clusters/daily-summary` - Get unique face daily summary.

### VSLC

* `POST /api/deepsearch/getaggregates` - Get aggregated detection data.
* `POST /api/deepsearch/getrecords` - Get detection records.
* `POST /api/deepsearch/getdictionary` - Get detection dictionary/distinct values.

### Misc And System

* `POST /deepsearch_report` - Report a false search result.
* `GET /deepsearch_report` - Query false search reports with `X-VIVOTEK-AUTH`.
* `GET /feedback/archive/{thingname}` - Get IoT shadow feedback archive.
* `POST /feedback/archive/{thingname}` - Trigger feedback archive refactoring.
* `POST /v1/userfeedback/archive` - Submit archive feedback.
* `GET /v1/userfeedback/archive` - Query archive feedback records with `X-VIVOTEK-AUTH`.
* `GET /v1/userfeedback/archive/status` - Get archive feedback processing status.
* `GET /v1/ai-proxy/capability` - Get AI proxy capability flags.
* `POST /grant` - Grant an ephemeral OpenAI API key.
* `POST /v1/offensive-checks` - Check text for offensive language.
* `GET /api/v1/things/{thingname}/thumbnails/latest` - Get latest device thumbnail.
* `GET /clean_tmp` - Clean temporary files on server.
* `GET /version` - Get backend version.
* `GET /health` - Health check.
* `POST /messagesearch/search_by_type` - Search messages by type.

## Notes For Future `/monitor` Work

* Treat `openspec/external/vortexai-openapi.yaml` as the canonical imported OpenAPI file.
* Use this summary only as a navigation aid; inspect the YAML before implementing request/response payload details.
* The VortexAI API uses bearer JWT auth, which is separate from the current dashboard's `X-Vortex-Token` webhook isolation.
* If `/monitor` calls VortexAI directly from the browser, CORS and token handling must be reviewed before implementation.
* If `/monitor` calls VortexAI through this Flask app, add backend proxy requirements to `openspec/specs/monitor.md` before coding.
