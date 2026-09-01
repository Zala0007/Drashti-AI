# P04 deployment and operations

## Local start

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
$env:GOVERNMENT_FEED_CATALOGUE_URL = "https://live.corp8.cloud/api/ingest"
python -m uvicorn app.main:app --app-dir apps/backend --host 127.0.0.1 --port 8000 --no-access-log
```

In a second terminal:

```powershell
npm --prefix apps/frontend run dev
```

Open `http://127.0.0.1:5173/#/federation`, synchronize **Government grid**, and
then open `#/live`. HLS-only is the practical default on networks where port
8554 is blocked; adaptive mode tries the configured primary/fallback order.
Stop both foreground processes with `Ctrl+C`.

Development creates and reuses `.runtime/secrets/federation.key`, which is
ignored by Git. Do not replace it after onboarding unless encrypted profiles
are intentionally migrated. `APP_ENV=production` must use an explicit key from
approved secret custody; automatic key creation is development-only.

## Required configuration

All P04 values are documented in `.env.example`. Important defaults are:

| Setting | Default | Purpose |
|---|---:|---|
| `STREAM_ENGINE_RTSP_TRANSPORT` | `tcp` | Reliable remote RTSP transport |
| `STREAM_ENGINE_OUTPUT_WIDTH/HEIGHT` | `640x360` | AI/preview working frame |
| `STREAM_ENGINE_DECODE_FPS` | `12` | decoder output limit |
| `STREAM_ENGINE_TARGET_FPS` | `10` | per-camera AI scheduling target |
| `STREAM_ENGINE_BUFFER_SIZE` | `2` | bounded newest-frame buffer |
| `STREAM_ENGINE_MAX_FRAME_AGE_MS` | `750` | stale-frame rejection |
| `STREAM_ENGINE_BATCH_SIZE` | `8` | maximum AI batch |
| `STREAM_ENGINE_BATCH_TIMEOUT_MS` | `40` | partial-batch deadline |
| `STREAM_ENGINE_HEALTH_TIMEOUT_SECONDS` | `5` | RTSP frame watchdog |
| `STREAM_ENGINE_HTTP_HEALTH_TIMEOUT_SECONDS` | `30` | established HLS/HTTP segment watchdog |
| `STREAM_ENGINE_HTTP_STARTUP_TIMEOUT_SECONDS` | `30` | initial HLS manifest/keyframe deadline |
| `STREAM_ENGINE_MAX_ACTIVE_SESSIONS` | `32` | one node's admission limit |

Per-camera start requests may override target/decode FPS, TCP/UDP, connection
profile, and maximum frame age. Start with the analytics substream for continuous
detection and reserve the main stream for evidence/plate detail.

## Network admission

Private camera networks are denied unless their exact CIDRs are in
`FEDERATION_ALLOWED_CIDRS`. Never use `0.0.0.0/0` as a shortcut. Place the edge
unit inside the authorized departmental/Police network segment, restrict egress
to enrolled camera/VMS ranges, and terminate user access through an authenticated
mTLS/TLS gateway. HLS/MJPEG hostname sources should pass through a pinned egress
proxy to close hostname re-resolution risk.

## Capacity and GPU

The measured workstation result is in
[P0.4-PERFORMANCE-REPORT.md](testing/P0.4-PERFORMANCE-REPORT.md). It validates 28
software-decoded 320x180 synthetic sources, not 28 production 1080p feeds.
Production sizing must be repeated with the actual codec, bitrate, resolution,
network loss, analytics model, and target hardware.

For NVIDIA edge nodes, qualify GStreamer/NVDEC and a GPU-resident `FramePacket`
adapter before enabling hardware-decode claims. Keep decode and inference on the
same node to minimize GPU-CPU-GPU copies. Do not place 80,000 feeds in one
process; use district/region clusters with load-aware placement.

## High availability and recovery

- Run at least two stream units per region with external durable assignments.
- A future lease controller must ensure one active processing owner per camera.
- Use readiness probes for API, FFmpeg availability, database, and scheduler.
- Restart individual sessions on media failure; restart a pod only for node-level
  failures.
- P04 stores no recording. P03 configuration and audit records live in Postgres;
  back them up and restore-test them. P09 evidence/event storage receives its own
  retention and disaster-recovery policy.
- Export metrics/logs centrally and alert on reconnect storms, high p95 frame
  age, decoder errors, memory slope, and capacity saturation.

## Security limitation

The current build has audit attribution but no real authentication/RBAC. Do not
expose it to a shared or public network. Production deployment is blocked until
OIDC/workload identity, permission checks, protected media authorization, secret
manager integration, and regional session leases are implemented and tested.

## Repeat the load test

```powershell
.\.venv\Scripts\python.exe apps/backend/scripts/benchmark_stream_engine.py --counts 1 5 10 28 --duration 5
```

The script creates temporary unique recorded-file paths, launches actual FFmpeg
processes, drains the P05 batch interface, prints JSON, shuts down every session,
and removes its temporary assets.
