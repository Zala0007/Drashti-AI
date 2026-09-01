# AI Features

All local model binaries and their registry are stored in one canonical directory:

```text
AI-Features/models/
  license_plate_detector.pt  plate-specific detector used before hybrid OCR
  yolo26n.pt                  general object detector used by tracking and SAHI
  model_registry.json         model roles, checksums, and OCR provider attribution
  MODELS.sha256               portable checksum list
```

The runtime applies every registered inference component in this order:

1. `MDL-VEH-001` (`yolo26n.pt`) detects and stores vehicle crops.
2. `MDL-ANPR-001` (`license_plate_detector.pt`) detects and stores plate crops.
3. `SVC-OCR-HYBRID-001` uses Google Cloud Vision as the primary plate reader and
   selectively invokes Groq on invalid or low-confidence Google results.
4. `SVC-VLM-001` (Groq Vision) creates a structured visual profile for each retained
   vehicle observation, with identical content reused safely by hash.

Live streams run both local detectors in a shared batch on the selected CUDA device
when PyTorch exposes one. Per-camera IoU tracking and OCR consensus use only lightweight
metadata operations. Hybrid OCR, Groq enrichment, Re-ID indexing, and investigation-event
publication run behind bounded queues so a slow provider never blocks camera preview or
the YOLO loop.

Every stored row receives a SQLite primary key. The portal exposes those records as
`VEH-########` and `ANPR-########`, links them to the model IDs above, and returns both
vehicle and plate evidence newest-first (`created_at DESC`, then `id DESC`).

During live processing, every vehicle in each retained evidence frame is stored. A plate
crop is linked back to its containing vehicle record, OCR work remains durable if a queue
is busy, and the vehicle evidence ID is queued for Visual Intelligence and Re-ID after
persistence. A format-valid accepted plate is stabilized by track-scoped consensus,
published idempotently to the investigation event ledger, matched against active
watchlist entries, and linked back to its parent vehicle observation. Different
format-valid results from Google and Groq are stored for officer review with no accepted
plate text, so they cannot trigger investigation or watchlist actions.
The portal shows these outputs at `#/ai` and `#/visual` and refreshes them while visible.

The scripts resolve these defaults relative to their own location, so they work when
launched from either the repository root or `AI-Features/`.

Install the shared inference dependencies from the repository root:

```powershell
python -m pip install -r AI-Features/requirements.txt
```

Run the standalone plate detector and Google Cloud Vision OCR utility:

```powershell
python AI-Features/anpr_video_detect.py `
  --source traffic.mp4 `
  --google-credentials .\visitingfaculty-499513-2c2073ffd622.json `
  --output annotated.mp4 `
  --json readings.json `
  --no-show
```

The `.pt` detector runs locally and only cropped plate regions are sent to Cloud Vision.
The live portal worker adds selective Groq fallback and provider reconciliation around
this Google-primary path. Both providers require outbound HTTPS, enabled accounts, valid
credentials, quota, and billing. Keep service-account JSON files and API keys outside
source control. See `../docs/HYBRID_ANPR_WATCHLIST.md` for live decision rules.

Populate the portal's searchable AI evidence workspace from stored vehicle crops:

```powershell
python AI-Features/extract_plate_evidence.py `
  --limit 300 `
  --detector-confidence 0.5 `
  --google-credentials .\visitingfaculty-499513-2c2073ffd622.json
```

This command appends plate crops and provider-attributed OCR results to
`AI-Features/crops.db`; it does not delete or rewrite the original detections. Start the
backend from the repository root and open `#/ai` in the portal. Set
`AI_SHOWCASE_DATABASE` when the evidence database is stored elsewhere.

The portal labels stored confidence as observed model output, not benchmark accuracy,
vehicle identity, or an autonomous enforcement decision. Operational evidence must stay
outside source control and remain subject to authorized human review.

Override a default only when required:

```powershell
python AI-Features/detect_with_sqlite_db.py --source traffic.mp4 `
  --weights AI-Features/models/yolo26n.pt

python AI-Features/anpr_video_detect.py --source traffic.mp4 `
  --detector-weights AI-Features/models/license_plate_detector.pt
```
