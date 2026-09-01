# How to Add a Camera to Drishti AI

This guide covers manual onboarding for RTSP, ONVIF, HLS, and MJPEG cameras.
Adding a camera has two separate stages:

1. Register the non-secret camera asset.
2. Attach an encrypted stream connection.

The computer running the backend must be able to reach the camera. A stream working
in VLC on a different computer does not prove that the Drishti backend can reach it.

## Current 30-camera public gateway

The evaluation grid is registered as `GOV-LIVE-1` through `GOV-LIVE-30` and maps
in order to `cam01` through `cam30`:

```text
RTSP primary:  rtsp://103.250.160.189:8554/stream/cam01 ... cam30
HLS fallback:  https://cctv.corp8.cloud/cam01/index.m3u8 ... cam30/index.m3u8
WHEP preview:  http://103.250.160.189:8889/stream/cam01/whep ... cam30/whep
Catalogue:     https://cctv.corp8.cloud/cameras.json
```

Drishti uses RTSP over TCP for AI processing and retains HLS as the restricted-
network fallback. WHEP is a browser-preview endpoint and is not used as an AI
decoder source. To reapply this gateway migration safely from the repository root:

```powershell
$env:PYTHONPATH = "apps/backend"
python apps/backend/scripts/migrate_camera_gateway.py       # dry run
python apps/backend/scripts/migrate_camera_gateway.py --apply
```

The migration refuses partial or ambiguous camera sets, updates all profiles in
one transaction, and never prints decrypted endpoints or credentials.

## 1. Allow the camera address

Open the repository-root `.env` file:

```text
C:\Users\Vishvarajsinh\Desktop\GPCIH\.env
```

Add only the exact approved camera addresses. For one camera:

```env
FEDERATION_ALLOWED_CIDRS=192.168.1.50/32
```

For multiple cameras, use a comma-separated list:

```env
FEDERATION_ALLOWED_CIDRS=192.168.1.50/32,192.168.1.51/32
```

Do not use `0.0.0.0/0`, `::/0`, or an unnecessarily broad private network range.
Restart the backend after changing `.env`:

```powershell
python -m uvicorn app.main:app `
  --reload `
  --app-dir apps/backend `
  --env-file .env `
  --no-access-log
```

Start the frontend in a second terminal when it is not already running:

```powershell
npm --prefix apps/frontend run dev
```

## 2. Register the camera asset

Open:

```text
http://localhost:5173/#/registry
```

Select **Register camera** and enter:

- a unique camera code, such as `GJ-AHD-ANPR-031`;
- camera name and owning department;
- district, locality, latitude, and longitude;
- camera type, vendor, model, and connectivity;
- the declared stream protocol;
- **RTSP capable** or **ONVIF capable**, when applicable;
- analytics capabilities such as ANPR or vehicle detection, when authorized.

Select **Register camera** to save it.

Do not enter an endpoint, username, password, token, or certificate in the registry
form. The registry stores camera identity and operational metadata only.

## 3. Create a managed camera identity

Skip this section only when the stream genuinely requires no authentication.

Open:

```text
http://localhost:5173/#/federation
```

Open **Credential vault**, then select **Create device identity**. Enter:

- the same department that owns the camera;
- a clear profile name;
- the device username;
- the device password.

Use a dedicated, read-only camera account where the device supports one. Drishti
encrypts these values server-side and does not return them to the browser.

## 4. Onboard the stream connection

On the Stream Federation page, select **Onboard connection** and configure:

| Field | Recommended value |
|---|---|
| Registered camera | The asset created in step 2 |
| Adapter | `RTSP`, `ONVIF`, `HLS`, or `MJPEG` |
| Profile name | For example, `Detection substream` |
| Stream role | `Low-bandwidth substream` for the camera wall |
| Source endpoint | The exact vendor/VMS endpoint |
| Managed credential profile | The identity created in step 3 |
| Routing priority | Lower values are preferred |
| Enable after creation | Enabled |
| Probe immediately | Enabled |

A direct RTSP endpoint normally has this structure:

```text
rtsp://192.168.1.50:554/vendor-specific-stream-path
```

Obtain the exact path from the camera configuration, vendor documentation, NVR, or
VMS. Do not guess it. Never embed credentials in the URI:

```text
# Incorrect and rejected
rtsp://username:password@192.168.1.50/stream
```

Select **Encrypt and onboard**. After submission, the raw endpoint is intentionally
removed from the browser and only a masked display value remains.

## 5. Configure primary and fallback profiles

A camera may have several enabled profiles. The lowest routing-priority number is
tried first. A practical configuration is:

| Profile | Role | Priority |
|---|---|---:|
| RTSP low-bandwidth substream | Substream | 10 |
| RTSP primary stream | Primary | 20 |
| HTTPS HLS fallback | Playback | 30 |

For a 30-camera wall, prefer an H.264 substream around:

- `640x360` or `640x480` resolution;
- `8-12 FPS`;
- `300-800 Kbps` bitrate;
- a `1-2 second` keyframe interval.

The primary high-resolution stream can remain a separate profile for focused review.

## 6. Verify and open the camera

On the Stream Federation page:

1. Confirm the connection is enabled.
2. Run **Probe** if the automatic probe was not completed.
3. Confirm the result is **Reachable**.

Then open:

```text
http://localhost:5173/#/live
```

Find the camera and start it individually, or use **Start grid**. Visible cameras are
started first and previews use short, staggered snapshot requests so the remaining
portal operations stay responsive while the full grid connects.

## 7. GPU decode and per-camera AI overlay

Keep `STREAM_ENGINE_DECODER_BACKEND=auto`. At backend startup the platform checks:

1. an NVIDIA device is visible through `nvidia-smi` or `/dev/nvidia*`;
2. the selected FFmpeg build advertises the `cuda` hardware accelerator; and
3. that build advertises an NVDEC/CUVID decoder.

When all checks pass, Live Operations reports **NVDEC active**. If the host has no
qualified GPU path it reports **FFmpeg ready** and uses CPU decoding. If NVDEC is
available globally but cannot decode one camera's codec/profile, only that stream
retries on CPU before normal source failover; the other cameras continue on NVDEC.

Install the backend with live analytics dependencies:

```powershell
python -m pip install -e "apps/backend[analytics,dev]"
```

For a Docker GPU host, use the separate GPU override so CPU-only deployments remain
valid:

```text
docker compose -f deployment/docker/compose.p0.3.yml -f deployment/docker/compose.gpu.yml up --build -d
```

The live inference worker fairly samples every active camera using newest-frame-first
batches. General detections are shown as boxes on that camera's tile and vehicle crops
are routed to the searchable Video Analytics archive. Plate detections are routed to
the plate showcase; Google Cloud Vision OCR is invoked only for cameras whose registry
capabilities contain `anpr`, with a per-camera cooldown so cloud latency and quota can
never block the live overlay.

Check the runtime truth reported by the backend:

```text
GET /api/v1/streams/capabilities
GET /api/v1/streams/analytics/capabilities
GET /api/v1/streams/analytics
GET /api/v1/streams/{camera-uuid}/analytics
```

`status=active` confirms the model worker is consuming batches. `status=unavailable`
includes a safe reason, usually a missing analytics dependency/model or unavailable
Google credentials. The local `.env` points `GOOGLE_APPLICATION_CREDENTIALS` to the
workspace service-account JSON; on the SSH host, copy that file outside source control
and update the path for that host.

## Troubleshooting

### Blocked

- Confirm that the camera IP is listed as an exact `/32` entry in
  `FEDERATION_ALLOWED_CIDRS`.
- Restart the backend after editing `.env`.
- Confirm the backend host is authorized to access that camera network.

### Authentication required

- Create or enable a managed credential profile.
- Confirm it belongs to the same department as the camera.
- Bind that profile to the stream connection.

### Unreachable

- Confirm the camera is online.
- Check the IP address, port, adapter, and vendor-specific path.
- Test connectivity from the backend machine, not only from an operator laptop.
- Confirm the camera/NVR firewall permits the backend host.

### Decoder failed or no preview

- Confirm FFmpeg is available on the backend.
- Prefer H.264 for broad decoder compatibility.
- Verify that the selected endpoint returns video rather than metadata or audio only.
- Try the camera's low-bandwidth substream.
- Inspect the safe connection and stream error code in the portal.

### ONVIF does not start

- Confirm ONVIF is enabled on the physical camera.
- Use a managed credential profile.
- Confirm the endpoint is the ONVIF device-service URL rather than an RTSP URL.
- Check that the account can call Media1 `GetProfiles` and `GetStreamUri`.

## Security rules

- Never commit `.env`, camera endpoints, usernames, passwords, or service credentials.
- Never place credentials inside RTSP/HLS URLs.
- Use exact approved CIDRs and least-privilege camera accounts.
- Do not publish screenshots containing endpoints or network topology.
- Camera previews and metadata must be accessed only by authorized operators.
