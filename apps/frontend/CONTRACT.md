# P0.1–P0.3 Command Centre, Registry, GIS and Federation Frontend Contract

The operator frontend calls the FastAPI registry directly. It contains no production camera records or mocked API fallback. The default base path is `/api/v1`; set `VITE_API_BASE_URL` when the API is hosted under another origin or prefix.

## Endpoints

| Method | Path | Frontend use |
| --- | --- | --- |
| `GET` | `/departments?page_size=100` | Department selector and filter |
| `GET` | `/cameras` | Paginated, searchable inventory |
| `POST` | `/cameras` | Validated manual onboarding |
| `GET` | `/cameras/statistics` | Operational summary cards |
| `GET` | `/cameras/filter-options` | Canonical distinct GIS filter values |
| `GET` | `/cameras/geojson` | Clustered GIS marker layer |
| `GET` | `/cameras/{id}` | Camera detail panel |
| `GET` | `/cameras/{id}/audit?page_size=100` | Append-only camera history |
| `POST` | `/cameras/import` | Multipart CSV bulk onboarding |

List responses use `{ items, total, page, page_size, pages }`. Camera list, statistics and GeoJSON requests share `search`, `department_id`, `district`, `city`, `vendor`, `vms`, `status`, `health`, and `ai_capability` query filters. A retired-only filter also sends `include_retired=true` because retired records are excluded by the API by default.

`GET /cameras/filter-options` returns sorted distinct `districts`, `cities`, `vendors`, `vms`, `ai_capabilities`, `camera_types`, `connectivity_types`, and `stream_protocols`. If this additive endpoint is unavailable during a rolling deployment, GIS remains functional and derives temporary choices from the currently loaded camera list and GeoJSON. Server-side filtering remains authoritative.

## Application routes and data integrity

The lightweight hash routes are:

- `#/command` — default Command Centre hero using real registry statistics, departments, camera health and GeoJSON;
- `#/federation` — secure adapter catalogue, encrypted connection profiles, bounded probes and activation controls;
- `#/gis` — operational clustered GIS, complete filters, search-to-map focus, and registry detail access;
- `#/registry` — manual and CSV onboarding, filtered inventory, GIS, pagination and asset details/audit.

The sidebar exposes only these implemented destinations as buttons. Future sustained streaming, ANPR, watchlist, alert and evidence capabilities are shown as explicit readiness states, not clickable navigation or simulated output. The top bar reports **reachable probes** from the federation API and never treats registry capability metadata or a bounded probe as active analytics.

## Camera create payload

JSON uses snake_case and matches FastAPI's strict `CameraCreate` schema. The UI sends:

- identity: `camera_code`, `camera_name`, `department_id`;
- GIS: `district`, optional `city`/`location_description`, `latitude`, `longitude`;
- integration metadata: `camera_type`, `vendor`, `model`, `vms`, `connectivity_type`, `stream_protocol`, `rtsp_capable`, `onvif_capable`;
- governance: `status`, `ownership`, optional `owner_name`, `is_public_facing`;
- readiness: `ai_capabilities`, `storage_details`, and `tags`.

The browser deliberately does **not** collect, store, render, or log `stream_reference`, `credential_reference`, CCTV passwords, tokens, or vendor secrets. Those belong in the federation/adapter layer. `ai_enabled` is derived by the API from `ai_capabilities` and is not sent on create.

`storage_details` is generated from the operator's storage type and retention fields as a non-secret JSON object. Empty optional values are omitted.

## CSV import

The multipart field name is `file`. The backend derives an idempotency key from file content if the caller does not supply one and defaults duplicate handling to `skip`. The synchronous importer accepts at most 10 MiB, 10,000 data rows, and 65,536 characters per field. The downloadable template uses `department_code`; the API also accepts `department_id`. `ai_capabilities` and `tags` are pipe-separated, while `storage_details` is a JSON object.

The import response is expected to contain aggregate counts plus per-row `results` entries with `row_number`, `status`, and optional structured `error`.

## GeoJSON

The map expects a GeoJSON `FeatureCollection` with point coordinates in `[longitude, latitude]` order. Each feature uses its top-level UUID `id`; properties include at least `camera_code`, `camera_name`, `health`, and the operational metadata used in its tooltip and selection card. Markers are clustered and distinguish health with both colour and a glyph (`✓`, `×`, `!`, `?`). Search results focus the selected point before the operator explicitly opens the camera details drawer.

`CameraRouteLayer` accepts ordered, externally verified camera observations through the `CameraRoutePoint` interface. It is intentionally dormant until the cross-camera event module supplies real points; the GIS does not synthesize a route.

## Runtime assumptions

- Vite proxies `/api` to `VITE_DEV_API_TARGET` (default `http://127.0.0.1:8000`) during local development.
- Deployments can point `VITE_MAP_TILE_URL` at a government-hosted or offline raster tile service. OpenStreetMap is only the development default.
- Authentication/RBAC is intentionally not fabricated in P0.1. The UI is ready to use same-origin sessions; authorization must remain server-enforced when the identity module is introduced.
- The Command Centre performs explicit refreshes and does not claim real-time alert or ANPR updates because no event/WebSocket contract exists yet.

## P0.3 Stream Federation

The `#/federation` route is the P0.3 control plane for adapter discovery, encrypted connection-profile onboarding, bounded probing, activation control, inventory, and profile audit. It contains no mocked stream data and does not persist endpoint or credential material in the browser.

| Method | Path | Frontend use |
| --- | --- | --- |
| `GET` | `/federation/adapters` | Runtime adapter manifests and declared capabilities |
| `GET` | `/federation/connections` | Paginated, filtered safe connection profiles |
| `POST` | `/federation/connections` | One-time endpoint submission for server-side encryption |
| `GET` | `/federation/connections/statistics` | Profile, activation, and bounded-probe posture |
| `GET` | `/federation/connections/{id}` | Safe detail; raw endpoint is never returned |
| `PATCH` | `/federation/connections/{id}` | Mutable non-secret profile metadata |
| `POST` | `/federation/connections/{id}/probe` | Bounded adapter capability/reachability probe |
| `POST` | `/federation/connections/{id}/enable` | Controlled activation state change |
| `POST` | `/federation/connections/{id}/disable` | Controlled deactivation state change |
| `GET` | `/federation/connections/{id}/audit` | Append-only profile state history |

### Create payload and secret boundary

`POST /federation/connections` sends `camera_id`, `name`, `adapter_kind`, `endpoint`, `stream_role`, optional `credential_reference`, `priority`, and `enabled`. Valid stream roles are `primary`, `substream`, `playback`, and `metadata`; priority is an integer from 0 through 1000. Credential references use only the opaque prefixes `credential-profile:`, `vault-ref:`, or `kms-ref:`. The form has no username, password, token, or certificate-value field.

The safe connection response contains an `endpoint_display` and `has_credential_reference`; it never contains the source endpoint, ciphertext, or credential reference. The frontend also discards any additive `endpoint`, `endpoint_ciphertext`, or `credential_reference` property before data enters React state. It reduces endpoint display to scheme, host, optional port, and a redacted path. Secret-like normalized metadata keys and URL-like values are redacted before rendering.

The adapter API uses `supports_probe`, `supports_discovery`, `supports_stream_handoff`, `available`, and `unavailable_reason`. These are manifest declarations—not observed runtime guarantees. The statistics API uses `by_status` and `by_adapter_kind`. Connection responses nest registry identity under `camera`; the client normalizes only safe identity and location fields for display.

### Probe truth boundary

A P0.3 probe is a bounded handshake or metadata-level reachability check. The interface calls successful results **reachable probes**, not active feeds, healthy streams, or edge-ready cameras. Enabled profiles are labelled **candidate profiles**. Sustained decoding, FPS stability, codec compatibility, frame quality, and inference eligibility remain explicitly gated behind P0.4 stream qualification. No live-video, ANPR, alert, or route counters are inferred from federation profiles.

Attention grouping includes `authentication_required`, `blocked`, `misconfigured`, `adapter_unavailable`, unreachable, failed, timeout, error, and degraded variants. Disabled is a neutral activation state, not a failure. Exact token grouping prevents `unreachable` from being counted as `reachable`.

Adapter catalogue, statistics, and connection inventory expose loading, empty, retry, and operator-safe error states. Backend 5xx bodies are never rendered. Probe and activation actions expose per-row busy state; enable/disable changes require explicit confirmation. If federation is unavailable, Command Centre and the top bar state that it is pending instead of substituting registry counts.

The browser submits source material across a protected server-side API boundary for encryption. TLS, authentication, authorization/RBAC, and production secret-manager policy remain deployment gates and are not claimed as implemented by this frontend.
