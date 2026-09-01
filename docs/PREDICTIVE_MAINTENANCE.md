# Explainable Predictive Maintenance

The maintenance module is deliberately rule-based. It reports observed deterioration indicators; it does not claim an ML probability of failure.

## Current rules

Over persisted seven-day aggregates, a finding can include:

- increasing reconnect count with at least three reconnects;
- decoded FPS falling below 75% of the earlier value;
- latency exceeding 500 ms and 1.5 times the earlier value;
- repeated availability below 50%;
- persistent frozen-frame events.

Multiple indicators or repeated outages raise risk. Cameras tagged `critical` or `corridor` receive critical maintenance priority. A finding explains its indicators and resolves when the current aggregate window no longer crosses a rule.

These rules are useful for maintenance triage but are not a replacement for field inspection. Operational threshold changes require versioned policy, replay against historical telemetry, false-positive review, and change approval.
