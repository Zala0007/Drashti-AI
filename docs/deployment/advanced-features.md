# Advanced Features

Open **Advanced Features** in the Intelligence menu (`#/advanced`). Select a
registered camera, start its processing stream if needed, and choose a module:

- **Border Line:** place two endpoints, select a direction, and enable. Counts
  confirmed person crossings across the finite line using the feet position.
- **Virtual Fence:** place three or more corners and enable. Counts people inside
  and records confirmed entry events.
- **Night Movement:** draw the area to monitor on a stationary visible-light or
  infrared feed. Background learning takes at least two seconds of processed
  frames; filtering suppresses noise and broad lighting changes. This detects
  motion, not a person's identity, and runs whenever enabled (no time schedule).
- **Object Path:** enable without drawing. Paths follow tracked object centers
  and break when observations are missing.

One module is enabled per camera. Switching cameras does not change saved rules.
Drawings use normalized video coordinates and survive backend restarts. Changes
to a camera's physical view require redrawing the region. Runtime counts and
tracks restart when the processing stream restarts; recent events remain saved.
Events are listed on this page, separately from vehicle watchlist alerts.

The algorithms are adapted from the four supplied `AI-Features` scripts into
`app/analytics/spatial_algorithms.py`. They use the existing shared SAHI object
detections and per-camera tracker, rather than opening another camera connection
or launching desktop OpenCV windows. Recognition quality depends on those tracks.
The scripts themselves remain available for standalone use.

Object detection uses SAHI with overlapping slices and a full-frame prediction,
merged with non-maximum suppression before tracking. The full-frame pass helps
retain objects spanning slice boundaries, at the cost of additional inference
time. Night Movement retains background subtraction and motion confirmation;
it does not require a recognized person or vehicle to trigger. Plate detection
continues to use direct YOLO without SAHI.

The backend must run with analytics dependencies installed and
`LIVE_ANALYTICS_ENABLED=true`. Processing requires a running stream; opening the
preview alone does not start inference. Preview and analytics arrive separately,
so overlays can lag the live picture. Results older than ten seconds are hidden.

Rules and events live in additional tables in the configured analytics SQLite
database, already persisted by the deployed backend's AI evidence volume.
No database migration or extra hosted provider is required. Restart the backend
after updating source; rebuild frontend assets for production deployment.
