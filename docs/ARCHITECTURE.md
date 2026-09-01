# Drishti AI architecture

## Delivered processing path

```text
P01 Camera Registry
        |
P03 encrypted connection profile + adapter / ONVIF negotiation
        |
P04 source resolver (network policy, IP pinning, short-lived credential lease)
        |
P04 isolated stream session -> FFmpeg decoder -> 1-3 frame latest buffer
        |                                      |
        |                                      +-> health and resource metrics
        v
fair batch scheduler -> bounded P05 consumer queue -> FramePacket
        |
        +-> operator MJPEG preview from the same decoded frame
        +-> vehicle + padded plate crops -> Google-primary/Groq-fallback OCR
        +-> accepted observations -> SIE / ReID / exact watchlist alerts
        +-> provider conflicts -> officer-review quarantine
        +-> five-minute health aggregates -> incidents / maintenance
                                            |
Registry + health + investigation state ---> coverage intelligence
Reviewed intelligence ---------------------> controlled case evidence
```

P04 is a processing unit, not a statewide singleton. One deployed unit admits a
configured maximum of streams (32 by default for the 30-feed evaluation grid).
District and regional schedulers
will partition the 80,000-camera estate across many identical units using
`district`, `department`, `edge_node`, and measured load as placement keys.

## Responsibility boundaries

| Module | Owns | Must not know |
|---|---|---|
| P03 | vendor/VMS integration, encrypted endpoints, ONVIF negotiation | frame queues, AI models |
| P04 | decode, lifecycle, timestamps, freshness, buffering, batching | watchlists, ANPR rules |
| P05+ | detection, tracking, plate recognition | RTSP credentials, reconnect logic |

The P05 boundary is `StreamEngine.next_batch() -> FrameBatch[FramePacket]`.
Each packet carries camera, stream, connection, timestamps, frame number,
dimensions, source kind, health state, pixel format, and frame bytes.

## Deployment topology

```text
Camera / departmental VMS
          |
District edge stream unit (P03 + P04 + P05-P08 GPU workers)
          |
normalized events + selected evidence only
          |
regional event bus -> central command platform / GIS / watchlists
```

This avoids backhauling every full-resolution feed to one central site. Detection
can use a substream continuously; a separate main-stream connection profile can
later be activated for plate crops or evidence. P04 never assumes one URL per
camera—the selected P03 connection profile identifies the stream role.

The evaluation catalogue is dynamically synchronized into P01/P03. Every feed
has independent encrypted RTSP/TCP and HTTPS HLS profiles. Adaptive operation
may rotate candidates; an operator-selected protocol remains pinned. Provider
location strings are authoritative input, while generated GIS centroids are
marked provisional and cannot be treated as surveyed camera positions.

## Current truthful boundary

P04 probes both the NVIDIA device and the installed FFmpeg CUDA/CUVID capabilities.
When qualified, it uses NVDEC for decode and automatically retries an incompatible
stream with CPU FFmpeg. GPU-resident zero-copy frames and a GStreamer/appsink path
are not implemented or claimed.
Development uses actor headers to exercise role and case policy; they are not
authentication. A production ingress must strip client copies, authenticate the
principal, inject trusted identity context, and deny operational endpoints when
that boundary is unavailable. See [SECURITY.md](SECURITY.md).

The advanced modules are persistent operational baselines: provider-neutral
ReID ranking with manual review, controlled case/evidence metadata, measured
camera health with explainable maintenance, and registry-backed coverage
planning. None claims calibrated identity, complete legal custody, ML failure
probability, or verified road visibility.

See [STREAM_PROCESSING.md](STREAM_PROCESSING.md) for the engine design and
[P0.4 performance report](testing/P0.4-PERFORMANCE-REPORT.md) for measured results.
