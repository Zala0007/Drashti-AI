# Camera Health Intelligence (P-S03)

Camera Health converts measured stream-engine metrics, edge aggregates, or registry heartbeats into persistent five-minute operational states.

## Inputs and states

Inputs include availability, decoded/processing FPS, latency, frame age, reconnect count, decoder errors, freeze events, authentication failures, image-quality state, edge node, and AI worker state. The classifier emits `healthy`, `degraded`, `critical`, `offline`, `unknown`, or `maintenance` using deterministic thresholds.

`POST /camera-health/snapshot` reads actual P04 `StreamEngine` sessions. A camera without an active session uses its registry heartbeat and is labelled `registry_heartbeat`; it is not assigned a random value.

## Incident behavior

- An individual incident requires two consecutive severe aggregate intervals.
- Three or more severe cameras on one edge node become one grouped edge incident.
- Grouped incidents suppress duplicate individual alerts.
- Recovery resolves open incidents and writes an audit event.
- Per-camera history returns bounded persisted aggregates and no raw frames or credentials.

Production should publish aggregates asynchronously from edge workers, enforce source identity, partition history, and apply retention/downsampling. Dashboard capture is a development/operator action, not the statewide collection design.
