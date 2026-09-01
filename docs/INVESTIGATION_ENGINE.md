# Drishti Special Investigation Engine

The Special Investigation Engine (SIE) converts shared ANPR observations into an
auditable, map-first investigation workspace. It is deliberately conservative:
camera detections are **observed**, route lines are **inferred**, and next-camera
recommendations are **predicted**. The interface and API never present a prediction
as a confirmed sighting.

## Investigation flow

1. An authorized investigator creates a case with a normalized target plate,
   purpose, priority, and optional district/time bounds.
2. Existing indexed ANPR events are correlated immediately. Common OCR confusions
   such as `B/8`, `O/0`, and `I/1` receive a small substitution cost, not a free match.
3. New events are stored once and evaluated against every eligible active case.
4. Physically impossible camera transitions are rejected. Accepted observations
   update the route reconstruction and bounded next-camera ranking.
5. Every create, transition, and correlation action is written to investigation
   activity and the shared audit log.

The browser currently refreshes an active workspace every five seconds. That is a
polling baseline, not a WebSocket claim. A failed refresh keeps the last coherent
view and displays degraded sync state.

## Authorization and evidence

Investigation endpoints require `X-Actor-ID` and an investigator or supervisor role.
ANPR event ingestion additionally accepts the analytics role. These headers form a
development integration gate; production must replace them with verified identity
claims at the gateway and retain the resulting actor identity in the audit record.

The demonstration scenario is disabled in production and its synthetic observations
carry `source=demonstration_scenario` plus an explicit disclosure. They must never be
exported as operational evidence.

## Main endpoints

- `POST /api/v1/investigations` — create and hydrate a case.
- `POST /api/v1/investigations/events` — ingest one immutable ANPR event.
- `GET /api/v1/investigations/{id}` — return the complete workspace.
- `GET /api/v1/investigations/{id}/prediction-backtest` — replay accepted route
  transitions and report top-1/top-3/top-5 candidate accuracy.
- `POST /api/v1/investigations/{id}/transition` — suspend, resume, complete, or cancel.

Backtest percentages are engineering evaluation metrics. They are not the probability
that a vehicle is present at a camera.

## Operational limitations

- The fallback graph uses straight-line distance and trajectory direction when a
  verified road/topology edge is unavailable.
- Appearance similarity is neutral unless an upstream analytics service supplies it.
- The baseline retains at most 1,000 history candidates per bounded query and 12
  predicted cameras per recalculation.
- The present build does not claim person identification, automatic enforcement,
  or continuous national-scale deployment.
