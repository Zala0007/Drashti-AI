# Route Reconstruction

SIE reconstructs a route only from accepted `confirmed` and `probable` observations,
ordered by their UTC observation time. The camera markers remain observed evidence;
the connector between them is always labelled inferred.

For each consecutive observation pair the service checks temporal feasibility from
camera separation and elapsed time. A transition requiring more than 160 km/h is
rejected and cannot alter the accepted route. A verified directed camera-graph edge
produces a `verified_camera_topology` connector. Without one, the interface draws an
`inferred_geodesic_connector` and exposes the missing topology as a coverage gap.

The current connector coordinates are camera-to-camera lines, not claimed driven road
geometry. Production road paths should come from an approved routing/topology service
and preserve its source/version on every edge. Recalculation must remain deterministic
for the same ordered evidence, graph version, and model configuration.
