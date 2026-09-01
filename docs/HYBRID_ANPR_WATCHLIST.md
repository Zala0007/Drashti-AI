# Hybrid ANPR and watchlist flow

The live ANPR path is optimized for the evaluation requirement: find a designated
registration across federated cameras, retain timestamped evidence, reconstruct its route,
and continuously cross-reference accepted reads against a representative watchlist.

## Runtime decision path

```text
latest camera frame
  -> license_plate_detector.pt
  -> padded, upscaled and contrast-enhanced plate crop
  -> Google Cloud Vision micro-batch
       | high-confidence + format-valid -> accept Google fast path
       | otherwise -> Groq vision fallback
                         | same normalized plate -> accept hybrid agreement
                         | Google invalid + strong Groq result -> accept Groq recovery
                         | different/weak/invalid results -> officer-review quarantine
  -> per-camera, per-track temporal consensus
  -> immutable ANPR event + parent vehicle observation
  -> exact active-watch match
  -> idempotent real-time alert with crop, camera, time and disposition audit
```

Provider calls, candidate text, normalized text, confidence, processing time, errors,
selected provider, decision reason, and review flag are retained in `plate_detections`.
The AI workspace displays these fields newest-first. A quarantined row has no accepted
`plate_text`; the live router also rejects review-required rows defensively.

## Configuration

```dotenv
GOOGLE_APPLICATION_CREDENTIALS=C:\secure\google-vision-service-account.json
GROQ_API_KEY=replace-with-backend-only-secret
LIVE_ANALYTICS_OCR_ENABLED=true
LIVE_ANALYTICS_OCR_BATCH_SIZE=8
LIVE_ANALYTICS_GOOGLE_ACCEPT_CONFIDENCE=0.86
LIVE_ANALYTICS_GROQ_OCR_ENABLED=true
LIVE_ANALYTICS_GROQ_ACCEPT_CONFIDENCE=0.82
LIVE_ANALYTICS_GROQ_OCR_REQUEST_INTERVAL_SECONDS=0.5
```

Neither secret may use a `VITE_` variable or be returned to the browser. Both remote
providers require outbound HTTPS from the GPU host. CUDA accelerates the local detector;
it does not accelerate either remote OCR API.

## Evaluation workflow

1. Onboard and verify the camera catalogue, then start only the required processing
   sessions at the capacity appropriate to the host.
2. Add the judge-provided registration at `#/alerts`; it becomes an active exact-match
   rule and remains visible in the watch register.
3. Open `#/live` to verify per-camera AI state and `#/ai` to inspect crops and both OCR
   candidates. Provider conflicts must remain in review state.
4. Open `#/alerts` for live matches and acknowledge the alert. Camera, timestamp,
   registration, crop reference, actor and disposition are retained.
5. Open `#/investigation` to search the same normalized registration and present its
   timestamped sightings, reconstructed route, and next-camera ranking.

## Accuracy boundary

The policy is deliberately conservative: it prefers a missed/queued review over a false
watchlist alert. No OCR system can recover characters absent from the captured pixels.
Before production acceptance, run a labelled plate-crop set from the actual evaluation
cameras and report exact full-plate accuracy, unreadable/review rate, false-alert rate,
p50/p95 OCR latency and provider fallback rate. Tune thresholds from that evidence rather
than presenting remote-provider confidence as benchmark accuracy.
