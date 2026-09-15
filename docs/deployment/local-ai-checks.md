# Local OCR and visual intelligence

Run from the repository root using `.venv\Scripts\python.exe`.

## Check dependencies and configuration

```powershell
.\.venv\Scripts\python.exe apps/backend/scripts/check_ai_providers.py
```

Install the optional analytics dependencies on a fresh environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -e "apps/backend[analytics]"
```

## Verify cloud providers

These commands send only synthetic test images. They do not upload stored footage,
modify the evidence database, or print credentials. Run them separately to avoid
competing for the same Groq rate limit.

```powershell
.\.venv\Scripts\python.exe apps/backend/scripts/check_ai_providers.py --live --provider google_ocr
.\.venv\Scripts\python.exe apps/backend/scripts/check_ai_providers.py --live --provider groq_ocr
.\.venv\Scripts\python.exe apps/backend/scripts/check_ai_providers.py --live --provider groq_vision
```

The frontend and backend run locally; Google OCR and Groq Vision still require
internet access because they are cloud APIs.

## Start processing

1. On GCP, use `GOOGLE_OCR_AUTH_MODE=metadata`. The backend uses the VM's attached
   service account; no JSON key, local credential file, or GitHub Google key secret
   is needed. The CI/CD Compose configuration selects this mode by default.
2. Configure `GROQ_API_KEY` or numbered `GROQ_API_KEY_1`, etc., in backend `.env`.
3. Start the backend with the project virtual environment and open Live Operations.
4. Start a configured camera stream. The camera must have `anpr` in its AI
   capabilities for plate crops to enter the OCR queue.
5. Review results in Video Analytics and Visual Intelligence. Auto-analysis handles
   new vehicle crops. Existing failed profiles need an explicit retry from Visual
   Intelligence after the provider problem is resolved.

`GET /api/v1/streams/analytics/capabilities` should report `status: active`.
A running worker with zero active streams does not generate new evidence.

Google is the primary OCR provider. Low-confidence or failed reads enter the Groq
fallback queue; conflicting plate reads remain subject to review. Vehicle appearance
analysis uses a separate Groq worker.

For local Google OCR, use `GOOGLE_OCR_AUTH_MODE=adc` with
`gcloud auth application-default login`; remove stale `GOOGLE_APPLICATION_CREDENTIALS`
entries from the local environment first. A local machine cannot inherit a GCP VM's
attached identity. Google OCR using metadata is verified on GCP, not on Windows.

If Groq returns HTTP 429, respect its
retry interval and account quota before retrying. Do not repeatedly backfill a large
archive while the provider is rate limited.

## GCP deployment requirements

The VM must have an attached service account, access to the metadata server, and an
OAuth access scope allowing Cloud Vision (normally `cloud-platform`). Enable the
Cloud Vision API and billing in the account's project and grant the service account
the permissions required to consume that API. No private key is shipped in the image.

After CI/CD deploys, this command on the VM checks Google using synthetic imagery:

```sh
docker compose --env-file .env \
  -f deployment/docker/compose.p0.3.yml \
  -f deployment/docker/compose.gpu.yml \
  -f deployment/docker/compose.https.yml \
  exec -T backend python /workspace/apps/backend/scripts/check_ai_providers.py \
  --live --provider google_ocr
```

See [Google Cloud Vision authentication](https://docs.cloud.google.com/vision/docs/authentication).

## Plate detection troubleshooting

`LIVE_ANALYTICS_PLATE_IMAGE_SIZE=1280` controls the direct YOLO plate pass;
general object detection continues to use SAHI. `LIVE_ANALYTICS_PLATE_CONFIDENCE`
is now passed into the deployed container, so VM `.env` tuning takes effect.
Increasing inference size cannot restore detail already discarded by decoding.
For a plate-focused camera trial, use a high-resolution source and set
`STREAM_ENGINE_OUTPUT_WIDTH=1280` and `STREAM_ENGINE_OUTPUT_HEIGHT=720` on the VM.
These output settings affect all sessions: benchmark GPU throughput with fewer
active cameras before increasing resolution for the whole installation.
Recreate the backend and restart the selected stream to apply the settings.

Google 401/403 errors now go straight to configured Groq fallback rather than
retrying the same unauthorized request three times. They still require fixing
the attached service account, API enablement/billing, or VM access scopes.
Run the synthetic Google check above on the VM to identify the specific cause;
never commit a service-account JSON key to solve metadata authentication errors.
