# Visual Intelligence Engine

Visual Intelligence enriches existing vehicle crops with conservative, structured visual descriptions. It does not run another detector, alter ANPR, or duplicate evidence images.

## Flow

```text
Retained live vehicle crop
  -> SQLite evidence row and stable evidence ID
  -> linked plate crop and Cloud Vision OCR state
  -> bounded background queue
  -> GroqVisionProvider
  -> Pydantic validation and normalization
  -> visual_vehicle_intelligence
  -> structured signature enrichment of the durable Re-ID observation
  -> local hybrid retrieval
  -> Visual Intelligence portal
```

Every vehicle crop retained by live analytics is queued immediately after its vehicle and plate evidence have been committed. Queue saturation does not lose work: pending OCR and visual jobs remain durable in SQLite and are recovered after restart. A plate found inside a vehicle crop is linked with `source_detection_id`; late OCR results are synchronized into the existing visual profile.

Live analytics intentionally retains an evidence frame at the configured `LIVE_ANALYTICS_EVIDENCE_INTERVAL_SECONDS` (two seconds by default), rather than archiving every decoded video frame. Every vehicle in that retained frame is stored and enriched. This bounds disk use and paid cloud calls while previews and overlays continue at their configured live frame rate.

Historical crops are processed through **Analyze next crop batch** or `POST /api/v1/visual-intelligence/backfill`. Backfill advances past completed records and selects a high-quality representative per source/track or five-second observation cluster.

Records carry provider, model, prompt version, content hash, analysis status, errors, processing time and evidence references. Identical crop content for the same model and prompt reuses the completed structured result, but each retained observation keeps its own evidence ID and profile row.

Statuses are `PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`, `RETRY_PENDING` and `SKIPPED`. Enrichment failures never block live analytics, ANPR or investigation services. Completed profiles update the same idempotent Re-ID observation; they do not create duplicate vehicle events.

Original vehicle and plate crops remain the evidence. Descriptions are investigator aids and always require human verification.

## Portal surfaces

- `#/ai` shows the newest vehicle evidence, linked plate crops, OCR states, model ledger and live pipeline.
- `#/visual` shows structured appearance profiles, condition filters, camera/date/time filters and source-linked evidence.
- Both screens refresh while visible, so new live evidence appears without a manual reload.

Groq and Google Cloud Vision are remote services and require outbound HTTPS from the host. The local NVIDIA GPU accelerates YOLO detection only.
