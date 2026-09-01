# Advanced intelligence demonstration

## Preparation

1. Apply migrations: `cd apps/backend && python -m alembic upgrade head`.
2. Start backend and frontend as described in the README.
3. Register at least four nearby active cameras. The evaluation feed sync can provide a larger registry.
4. Open `#/investigation`, load disclosed judge observations, and start the target search.

## Recommended demonstration flow

1. **Special Investigation:** show observed route points, inferred connectors, predicted next cameras, and the accuracy replay disclaimer.
2. **Vehicle ReID:** open the disclosed ReID scenario. Compare the target and unreadable-plate candidate, inspect signal reasons, and confirm manually. Show the pursuit moving to `reacquired` and its predictions recalculating.
3. **Cases & Evidence (`#/cases`):** open a case linked to the investigation. Show automatically linked evidence manifests, redacted controlled references, activity attribution, and structured export limitation.
4. **Camera Health (`#/health`):** capture real P04/registry telemetry. Show state counts, per-camera history, grouped incidents where data supports them, and explainable trend findings.
5. **Coverage (`#/coverage`):** run a fresh registry analysis, inspect temporary/permanent gap explanations and candidate areas, then simulate a critical node outage. Emphasize `NO STATE CHANGED`.
6. Toggle light/dark theme and resize the portal to demonstrate responsive layouts and reduced-motion-safe animation.

## Truthful narration

Say “technical ranking,” not identity probability; “captured manifest hash,” not full legal custody; “rule-based maintenance risk,” not predicted failure probability; and “location-based planning estimate,” not verified blind spot. Synthetic records are always labelled and production disables their creation.
