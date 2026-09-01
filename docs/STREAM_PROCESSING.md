# P04 video stream processing engine

## Status

P04 is implemented as a production-oriented processing-unit baseline. It has
real FFmpeg decode, concurrent independent sessions, bounded latest-frame
buffers, automatic reconnect, freeze and frame-timeout detection, a bounded
AI batch handoff, worker telemetry, APIs, and a dedicated Live Operations page.

The active live analytics worker consumes the P04 `FramePacket` contract, runs the
registered YOLO vehicle and plate detectors, publishes live boxes, stores retained
vehicle/plate crops, sends plate crops to Cloud Vision OCR and queues vehicle crops
for Visual Intelligence. A lightweight class-aware IoU tracker assigns per-camera
cross-frame IDs, and confidence-weighted OCR voting stabilizes repeated plate readings
inside each plate track. These metadata-only stages do not add another inference pass.
Retained vehicles, completed visual profiles, and accepted OCR results are handed to
Re-ID and Special Investigation through a durable bounded background router.

## Repository audit before implementation

P03 already provided encrypted camera-owned connection profiles, adapter kinds,
masked endpoints, department-scoped credential leases, ONVIF Media1 negotiation,
network admission, health/probe metadata, and lifecycle APIs. P03R had a robust
supervised FFmpeg-to-HLS browser runtime. It did not expose decoded frames,
frame timestamps/age, bounded latest-frame semantics, sampling, AI batching, or
processing health. No OpenCV, GStreamer, GPU decode, raw-frame queue, or existing
AI model was present. P04 therefore reuses P03 source security and the proven
FFmpeg process controls while keeping P03R's HLS playback path intact.

## Session lifecycle

```text
CREATED -> CONNECTING -> CONNECTED -> STREAMING
                |                         |
                +-> RECONNECTING <--------+
                                |
                       capped exponential backoff + jitter

STREAMING -> DEGRADED (frozen frame or frame timeout) -> RECONNECTING/STREAMING
any active state -> STOPPED
decoder unavailable -> FAILED
```

State changes are explicit and structured-log events containing `camera_id`,
`stream_id`, component, prior state, new state, error code, and timestamp. A
decoder error affects only its owning session thread.

## Freshness and backpressure

- Each stream has a deque limited to 1-3 frames (default 2).
- The reader appends the newest decoded frame and evicts the oldest buffer item.
- The scheduler selects only the most recent frame not previously dispatched.
- Frames older than `max_frame_age_ms` are discarded before AI handoff.
- Per-camera `target_fps` sampling avoids unnecessary inference.
- The P05 batch bus is bounded to two batches. When an attached AI consumer is
  slower than input, the oldest batch is dropped and
  `dropped_due_to_backpressure` increases.
- No AI queue is produced until a consumer first calls `next_batch()`. This
  avoids reporting artificial backpressure while P05 is not installed.
- A batch dispatches on the scheduler timeout with up to `batch_size` frames;
  it does not wait indefinitely for a full batch.

`frames_sampled_out` distinguishes deliberate FPS sampling from stale or
downstream-backpressure loss.

## Decode strategy

The active backend launches one supervised FFmpeg process per stream and reads
fixed-size RGB24 frames from stdout. The source URI—including credentials—is
written through a protected stdin ffconcat manifest and never placed in process
arguments. RTSP defaults to TCP and uses bounded network read timeouts,
`discardcorrupt`, low-buffer flags, and a bounded live-stream probe so FFmpeg does
not delay the first preview while over-analysing the input. Recorded inputs are
real-time paced.

Supported P03 handoffs are RTSP, ONVIF-resolved RTSP, HLS, MJPEG, and validated
recorded files. ONVIF and RTSP destinations are policy-checked and IP-pinned
before use. Camera credentials remain in a backend lease, are redacted from
errors/logs, and are cleared on session finalization.

FFmpeg `showinfo` PTS is parsed on a bounded side-channel and attached to each
`FramePacket` as `source_pts_seconds`; receive/processing timestamps remain UTC
edge-node timestamps. PTS is relative media timing, not trusted wall-clock time.
If source PTS is absent, FPS and timing safely fall back to receive time.
Production camera and edge nodes still require monitored NTP synchronization.

Each camera may expose ordered transport candidates. Adaptive mode rotates from
the primary profile to a fallback after an isolated decoder failure. An explicit
HLS-only or RTSP-only request is pinned to that adapter and never silently
crosses protocols. RTSP uses its short frame/keyframe watchdog; HTTP and rolling
HLS use separate, configurable startup and established-stream deadlines so a
delayed or expired segment does not create a reconnect storm. Decoder network
timeouts are selected per transport; an RTSP failure no longer inherits the
longer HTTP/HLS timeout before fallback.

Decoder mode `auto` detects FFmpeg NVDEC/CUDA support on the host and uses it when
available. A session that fails on NVDEC retries with ordinary FFmpeg software decode.
GPU zero-copy, GStreamer ingestion, and bitrate extraction remain extension points.

## Health and observability

Per stream:

- state, resolution, configured decode/processing FPS;
- decoded and dispatched FPS;
- frames received, sampled, stale, backpressure-dropped, and dispatched;
- current/average/p95/max frame age;
- reconnect and decoder-error counts;
- source PTS availability and transport-failover count;
- queue depth and last frame/dispatch times;
- safe error code/message.

Per processing unit:

- active/offline/degraded/reconnecting counts;
- average decode/processing FPS and latency;
- total frames, drops, reconnects;
- AI queue depth and consumer attachment;
- aggregate Python + FFmpeg CPU time, RSS memory, and process count.

GPU utilization and network receive rate are nullable until the corresponding
node exporters are connected. Metrics are API-shaped for a later Prometheus
collector; no high-cardinality per-frame logs are emitted.

## Preview and operator page

`#/live` displays a searchable, paged 2x2 or 3x3 wall so the complete onboarded
inventory remains reachable without opening every preview at once. Each active
tile uses the session's latest RGB frame converted to a low-rate JPEG; it does
not launch another decoder.
The browser requests short-lived `preview.jpg` snapshots on staggered timers instead
of holding one multipart connection per camera. Only visible tiles poll, visible
cameras are submitted first during grid startup, and at most three start requests are
in flight. This prevents a 30-camera wall from exhausting HTTP connections or crowding
normal registry, investigation, and lifecycle requests behind preview traffic.
Selecting a tile opens camera identity, department, location, hardware/VMS,
connection role, lifecycle controls, metrics, and safe diagnostics.

The page renders the latest real detector boxes and OCR text for each camera and
reports initialization, sampling and provider failures explicitly. It does not
generate simulated boxes or plates. Retained evidence is visible newest-first in
`#/ai`; structured visual profiles are visible in `#/visual`.

YOLO batching, crop persistence, hybrid OCR, Groq enrichment, Re-ID indexing, and ANPR
event publication are separated by bounded queues. Cloud or operational-service latency
therefore cannot block decode, preview, or the live detector loop. SQLite rows preserve
pending work for restart recovery; production scale should move these durable queues and
operational records to managed infrastructure.

## Graceful shutdown

Shutdown signals every session first, then closes decoders concurrently, joins
reader threads, clears buffers and credential leases, stops the scheduler and
health monitor, and reports a structured timeout error if a worker fails to
exit. The Windows load test exposed and fixed a file-handle shutdown delay; the
repeatable 28-process test now exits without orphan FFmpeg processes.
Stopped sessions release their endpoint, lease, frame payload, JPEG cache and AI
queue references. Process-local history is pruned to a bounded window.

## Tests

Automated coverage includes buffer eviction/latest semantics, start/stop,
P05 batch shape, JPEG preview, failure isolation, bounded slow-consumer behavior,
transport fallback/pinning, source-PTS parsing, real recorded-file FFmpeg decode,
non-blocking snapshots, bounded grid-start concurrency, responsive wall interaction,
API capabilities, and empty operational state.
Physical RTSP packet-loss, real Hikvision/CP Plus ONVIF, UDP, GPU decode, and
regional failover remain field-acceptance tests because those resources are not
available in this workspace.
