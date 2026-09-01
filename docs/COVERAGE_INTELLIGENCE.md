# Coverage Intelligence (P-S04)

Coverage Intelligence uses registered camera coordinates and latest persisted health. It does not invent coverage percentages or claim verified road visibility.

## Analysis

- A permanent gap is a large separation between nearest operational registry nodes above the configured threshold.
- A temporary gap is an unavailable camera without an operational backup inside the redundancy radius.
- A critical node is an operational camera without a nearby operational backup.
- Deployment candidates are gap midpoint/affected areas, never exact installation coordinates.
- Every result stores its assumptions, actor, duration, counts, gaps, and candidate areas.

The latest statewide analysis is distinct from a district analysis. Operational count is persisted from the actual registry/health filter rather than inferred from gap counts.

## What-if simulator

`POST /coverage/what-if` estimates the removed camera's radius, nearest backup, whether a critical gap appears, and related active investigations. It performs no registry, health, or stream mutation and labels the response `simulation: true`.

Before deployment decisions, planners must verify surveyed coordinates, bearing/FOV/range, terrain, road visibility, power, network feasibility, permissions, and field constraints. Production GIS should add verified road/topology layers and spatial indexes.
