# Camera Graph and Route Semantics

`camera_graph_edges` stores directed, verified transitions between registered cameras.
Each edge records road distance, expected travel time, confidence, provenance, and an
enabled flag. Predictions prefer these edges and label the method
`verified_camera_topology`.

When no verified outgoing edge exists, SIE performs a bounded fallback across active,
non-offline cameras within 75 km. Ranking combines movement-bearing compatibility,
distance decay, camera health, and registered ANPR capability. The result is labelled
`geospatial_directional_fallback`; it does not imply road connectivity.

Route reconstruction connects accepted observations in time order. A segment is always
classified as inferred. Verified topology raises its confidence; otherwise it remains
a geodesic visualization with a lower confidence label.

Before deployment, populate edges from an approved road-network process, retain source
provenance, review one-way/turn restrictions, and periodically expire stale topology.
