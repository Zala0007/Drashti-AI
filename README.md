# Drishti AI

**Federated Edge Intelligence Platform for Unified CCTV Analytics and Smart Policing**

Drishti AI is a vendor-neutral integration layer for Gujarat's heterogeneous government CCTV estate. It is designed to preserve departmental VMS investments, process video near its source, and correlate security-relevant events centrally.

> Integrate existing infrastructure -> process at the edge -> correlate centrally -> act in real time.

## Current delivery: Registry, federation, video intelligence and operations

The current implementation contains the connected camera-to-investigation path plus four advanced operational modules:

- **P0.1 Camera Registry — complete:** department and camera registration, manual and CSV onboarding, normalized non-secret metadata, lifecycle/heartbeat/health handling, statistics, audit history, and location-aware registry APIs.
- **P0.2 GIS Operations — implementation baseline:** a command-centre entry page, a dedicated statewide GIS workspace, API-backed filters and search, camera focus/details, health markers with shape/glyph cues, and viewport clustering. The map reads the registry's real GeoJSON and statistics; it does not invent operational events.
- **P0.3 Stream Federation — implementation baseline:** encrypted write-only connection profiles, six protocol adapter manifests, SSRF-aware endpoint admission, bounded server-side probes, normalized verification evidence, reversible enable/disable controls, and a redacted audit-driven operator workspace.
- **P0.3R Media Runtime — implementation baseline:** supervised FFmpeg sessions for eligible RTSP, HLS, MJPEG, and recorded-file profiles; bounded same-origin HLS playback; freshness watchdogs; capped retry/backoff; capacity admission; safe session telemetry; and operator start, stop, and restart controls.
- **P0.4 Video Stream Processing — implementation baseline:** independent FFmpeg raw-frame sessions, latest-frame bounded buffers, frame-age rejection, per-camera FPS control, failure isolation, reconnect/freeze supervision, an AI batch contract, CPU/RAM metrics, and a dedicated Live Operations wall.
- **Special Investigation Engine — implementation baseline:** immutable ANPR events, indexed historical target search, confusion-aware plate correlation, temporal feasibility checks, auditable case state, inferred routes, bounded next-camera ranking, prediction backtesting, and a map-first restricted workspace.
- **Vehicle ReID — operational baseline:** provider-neutral quality-gated observation ingestion, bounded multi-signal ranking, physical feasibility rejection, manual audited review, and confirmed-match pursuit recalculation.
- **Cases & Evidence — operational baseline:** authorized case files, assignment filtering, controlled source links, canonical SHA-256 manifests, redacted retrieval references, activity history, and structured exports with explicit custody limitations.
- **Camera Health & Maintenance — operational baseline:** persisted stream/edge/heartbeat aggregates, deterministic states, debounced and grouped incidents, automatic recovery, per-camera history, and explainable rule-based maintenance findings.
- **Coverage Intelligence — operational baseline:** actual registry/health counts, temporary and permanent location-based gaps, critical nodes, candidate deployment areas, persisted assumptions, and non-mutating outage simulation.

The dedicated **AI Intelligence Workspace** at `#/ai` exposes real searchable vehicle crops, dedicated `.pt` plate localization, Google-primary/Groq-fallback OCR evidence, provider decisions, review boundaries, model provenance, and live queue state. The **Visual Intelligence Workspace** at `#/visual` exposes Groq-enriched appearance/condition profiles with camera, date, time, plate-visibility, image-quality and damage filters. Accepted live OCR events are matched exactly against the API-backed watchlist and create idempotent, reviewable alerts at `#/alerts`.

The government evaluation connector reads the provider catalogue dynamically instead of assuming camera numbers or constructing stream URLs. It maintains one encrypted RTSP/TCP profile and one encrypted HTTPS HLS profile per imported camera. Operators can select adaptive transport, HLS-only for restricted networks, or RTSP/TCP-only for an edge node. Provider location text is imported, but inferred map centroids remain explicitly provisional until surveyed coordinates are supplied.

PostgreSQL/PostGIS is the production target, while SQLite remains a zero-Docker local-development fallback. P0.3R can continuously ingest and transcode authorized direct or credentialed RTSP/HLS/MJPEG sources into a bounded live HLS window. Department-scoped device identities are encrypted at rest and write-only through the portal. ONVIF Media1 negotiation resolves an authorized primary/substream RTSP URI through `GetCapabilities`, `GetProfiles`, and `GetStreamUri`. It is not yet a recording system: stopping a session removes its generated media. ANPR inference and investigation correlation are now integrated baselines, but operational accuracy still requires a labelled local evaluation set, approved identity integration, calibrated thresholds, verified camera topology, and production evidence storage.

The portal is the secure statewide **control plane**, not one oversized server expected to decode 80,000 feeds. Production media, inference, buffering, and site-specific protocol work run in horizontally scalable regional/edge worker pools; the central plane stores policy, safe metadata, normalized events, investigations, and audit history.

## Architecture position

```text
P0.1 Registry ---- safe identity/location/capability metadata
       |
       +----> P0.2 GIS Operations + Command Centre
       |
       +----> P0.3 encrypted VMS/stream federation
                          |
                          v
              P0.3R supervised media runtime             (current)
                          |
                          v
              P0.4 AI-ready stream processing            (current)
                          |
                          v
              P0.5-P0.8 detection/tracking/ANPR          (baseline)
                          |
                    events + evidence
                          v
                 Special Investigation Engine            (baseline)
                   cases, correlation and routes
```

The registry records what a camera is, where it is, who owns it, and what it can support. GIS Operations turns that safe metadata into an operational map. Connection secrets are never camera metadata. P0.3 encrypts protected connection material in a separate profile store and returns only a masked display hint. P0.3R resolves local encrypted credential profiles inside the camera's department boundary, negotiates ONVIF media when selected, and passes the effective endpoint to FFmpeg through a protected stdin manifest instead of exposing it in process arguments. External Vault/KMS references remain fail-closed until their workload-identity adapters are configured.

## Repository layout

```text
apps/
  backend/                 FastAPI registry API
  frontend/                React operator interface
database/
  migrations/              database schema evolution
  seeds/                   non-sensitive representative data
deployment/
  docker/                  versioned P0.1 and P0.3 container manifests
docs/
  api/                     API contract
  architecture/            module architecture, decisions, and boundaries
  deployment/              local/deployment runbook
AI-Features/               .pt plate detection, Cloud Vision OCR, and evaluation
```

## Start locally without Docker

The backend defaults to SQLite for the fastest development path. From PowerShell at the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e "apps/backend[analytics,dev]"
$env:GOVERNMENT_FEED_CATALOGUE_URL = "https://live.corp8.cloud/api/ingest"
python -m uvicorn app.main:app --reload --app-dir apps/backend --no-access-log
```

In a second PowerShell terminal at the repository root:

```powershell
npm --prefix apps/frontend install
npm --prefix apps/frontend run dev
```

Open `http://localhost:5173/#/federation`, use **Government grid** to discover/synchronize the current catalogue, then open `#/live` for the P04 wall. The Vite development server proxies `/api/v1` to the backend at `http://localhost:8000`. In development only, the backend creates one persistent ignored key at `.runtime/secrets/federation.key`; this preserves encrypted profiles across restarts. Production and test environments remain fail-closed and require an explicitly managed key. Use only authorized sources and configure exact private-network CIDRs before probing. The complete procedure is in [the deployment runbook](docs/DEPLOYMENT.md).

Open `http://localhost:5173/#/investigation` for the SIE workspace. The disclosed judge scenario requires at least three active registered cameras; four or more lets it reserve a defensible next-camera candidate. It is disabled when `APP_ENV=production`.

Advanced workspaces are available at `#/ai`, `#/visual`, `#/cases`, `#/health`, and `#/coverage`. The AI workspaces read the local evidence database configured by `AI_SHOWCASE_DATABASE`; see [the AI feature guide](AI-Features/README.md) for the live and offline evidence paths. See [the demonstration guide](docs/DEMO.md) for the full reviewed ReID-to-evidence workflow.

The production-shaped path uses PostGIS and the full Compose manifest:

```powershell
Copy-Item .env.example .env
# Supply the same valid Fernet key from approved secret custody on every restart.
$env:FEDERATION_ENCRYPTION_KEY = "<stable-managed-secret>"
docker compose -f deployment/docker/compose.p0.3.yml up --build
```

Do not place real credentials in `.env` on a shared machine. The included values are development-only placeholders.

## Module documentation

- [How to add a camera](README-CAMERA-ONBOARDING.md)
- [Architecture and acceptance criteria](docs/architecture/P0.1-CAMERA-REGISTRY.md)
- [GIS Operations architecture and boundaries](docs/architecture/P0.2-GIS-OPERATIONS.md)
- [Stream federation architecture and boundaries](docs/architecture/P0.3-STREAM-FEDERATION.md)
- [Supervised media runtime architecture](docs/architecture/P0.3R-MEDIA-RUNTIME.md)
- [Overall and P04 architecture](docs/ARCHITECTURE.md)
- [P04 stream processing design](docs/STREAM_PROCESSING.md)
- [P04 stream API](docs/api/P0.4-STREAM-API.md)
- [P04 deployment runbook](docs/DEPLOYMENT.md)
- [P04 measured performance](docs/testing/P0.4-PERFORMANCE-REPORT.md)
- [Special Investigation Engine](docs/INVESTIGATION_ENGINE.md)
- [Camera graph semantics](docs/CAMERA_GRAPH.md)
- [Vehicle correlation baseline](docs/VEHICLE_CORRELATION.md)
- [Route reconstruction](docs/ROUTE_RECONSTRUCTION.md)
- [Route prediction and backtesting](docs/ROUTE_PREDICTION.md)
- [Vehicle Re-Identification](docs/VEHICLE_REID.md)
- [Case and Evidence Management](docs/CASE_EVIDENCE_MANAGEMENT.md)
- [Camera Health Intelligence](docs/CAMERA_HEALTH.md)
- [Explainable Predictive Maintenance](docs/PREDICTIVE_MAINTENANCE.md)
- [Coverage Intelligence](docs/COVERAGE_INTELLIGENCE.md)
- [Advanced security boundary](docs/SECURITY.md)
- [Advanced module demonstration](docs/DEMO.md)
- [AI model layout and hybrid plate OCR](AI-Features/README.md)
- [Hybrid ANPR and watchlist flow](docs/HYBRID_ANPR_WATCHLIST.md)
- [Groq Visual Intelligence pipeline](docs/VISUAL_INTELLIGENCE.md)
- [REST API contract](docs/api/P0.1-API.md)
- [Federation API contract](docs/api/P0.3-FEDERATION-API.md)
- [P0.3 threat model](docs/security/P0.3-THREAT-MODEL.md)
- [P0.3R media threat model](docs/security/P0.3R-MEDIA-THREAT-MODEL.md)
- [P0.3R physical-device acceptance matrix](docs/testing/P0.3R-DEVICE-ACCEPTANCE.md)
- [Local and container deployment](docs/deployment/P0.3-LOCAL.md)
- [Representative seed data](database/seeds/README.md)

## Engineering guardrails

- No secrets, embedded usernames/passwords, tokens, or credential-bearing RTSP URLs in registry metadata, CSV files, logs, or browser responses.
- Government feed details and topology are sensitive even when they are not credentials. Use least-privilege access and sanitized demonstration data.
- SQLite is a developer convenience, not the statewide deployment database and not proof of PostGIS behavior.
- Retiring a camera preserves its history; destructive deletion is not part of the operator workflow.
- API/UI claims must be supported by a repeatable test or demonstration. See the module architecture documents for current acceptance boundaries.

## Roadmap

- **P0.1 Camera Registry:** complete.
- **P0.2 GIS Operations:** current implementation baseline; statewide metadata map and operator workflows are present, while event-driven route and alert overlays await real upstream events.
- **P0.3 Stream Onboarding / Federation Adapter:** current implementation baseline; encrypted profiles, adapter catalog, restricted endpoint validation, measured lightweight probes, lifecycle controls, and safe audit evidence.
- **P0.3R Supervised Media Runtime:** current implementation baseline; bounded concurrent sessions, actual FFmpeg ingestion/transcoding, media-freshness supervision, browser-safe viewing, restart/backoff, cleanup, and safe runtime telemetry.
- **P0.4 Video Stream Processing:** current implementation baseline; concurrent decode, bounded latest frames, AI scheduling, lifecycle/health APIs, live operations UI, and measured 28-source synthetic load.
- **P0.5-P0.8 baseline:** checksum-verified vehicle/plate detection, retained crops, lightweight per-camera track IDs, Google-primary/Groq-fallback OCR, track-scoped temporal consensus, conflict quarantine, Groq visual enrichment, durable Re-ID/ANPR handoffs, exact provider attribution, evaluation scripts, and evidence publication are present. Labelled project-data calibration remains release work.
- **Special Investigation Engine baseline:** event database, target search, cross-camera correlation, route reconstruction, bounded predictions, audit history, and backtesting are present.
- **Advanced operational modules:** exact active-watch matching, idempotent real-time alerts, alert disposition, ReID review, controlled cases/evidence metadata, measured health/maintenance, and coverage planning are delivered baselines.
- **Later production hardening:** multi-approver watchlist governance, verified road topology ingestion, trusted gateway identity, WORM evidence objects, and locally calibrated appearance embeddings.

P0.3 consumes camera UUIDs and safe capability metadata from P0.1 without moving vendor logic, feed endpoints, or secrets into the registry or browser. A successful P0.3 probe is connectivity evidence, not proof of a decodable live stream or AI readiness.
