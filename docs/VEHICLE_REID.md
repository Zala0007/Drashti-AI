# Vehicle Re-Identification (P-S01)

Vehicle ReID is an investigator-reviewed fallback for cases where ANPR is unreadable, hidden, or changed. It ranks observations; it never confirms identity autonomously.

## Delivered workflow

1. Analytics publishes a quality-scored `VehicleObservation` through `POST /api/v1/reid/observations`.
2. Low-quality or very small crops retain metadata but their embeddings are rejected.
3. `POST /reid/investigations/{id}/rank` compares up to 500 bounded observations and returns at most 50 candidates.
4. Available visual, plate, colour, class, time, route, and direction signals are weighted and renormalized. Missing signals are not silently treated as zero.
5. Physically impossible travel is rejected. HIGH/MEDIUM/LOW is an uncalibrated technical assessment, not identity probability.
6. An investigator confirms, rejects, or retains a candidate. The action and note are audited.
7. A confirmed candidate with a linked ANPR event becomes an observed pursuit point and recalculates next-camera candidates.

## Model boundary

`VehicleEmbeddingProvider` is provider-neutral. The current runtime compares supplied vectors with cosine similarity; it does not pretend that an appearance model is bundled. The development-only judge scenario supplies synthetic vectors and labels them as non-operational evidence. Production disables that scenario.

Before operational use, an approved embedding provider needs local vehicle data evaluation, bias/error analysis, version pinning, protected crop storage, retention policy, and threshold calibration. Plate or visual appearance alone must never be treated as conclusive identity.

## Scale and security

- Ranking is time-bounded and capped; production should retrieve candidates from a vector index partitioned by time and region.
- Crop references are controlled server-side and never exposed as storage paths in list APIs.
- Only analytics/operations publishers ingest profiles; investigator/supervisor roles rank and review.
- Production identity must come from a trusted gateway. Development actor headers are not authentication.

Tests cover disclosed scenario ranking, manual confirmation, audit attribution, pursuit reacquisition, and downstream candidate recalculation.
