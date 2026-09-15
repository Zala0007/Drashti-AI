import { useEffect, useState } from "react";
import { streamApi } from "../lib/api";
import type { Camera } from "../types/registry";
import type { SpatialFeature, SpatialPoint, SpatialRule, SpatialStatus } from "../types/spatial";
import "./advanced-features.css";

const modules: { id: SpatialFeature; title: string; detail: string }[] = [
  { id: "border_line", title: "Border Line", detail: "Draw two endpoints. Count confirmed person crossings in either direction." },
  { id: "night_movement", title: "Night Movement", detail: "Draw a motion area for a stationary low-light or IR camera. Allow background warm-up." },
  { id: "object_path", title: "Object Path", detail: "Show movement trails for detected objects. Paths are generated automatically." },
  { id: "virtual_fence", title: "Virtual Fence", detail: "Draw a closed area. Alert when a person's feet enter the fence." },
];
const blank = (feature: SpatialFeature): SpatialRule => ({ feature, enabled: true, points: [], direction: "both" });

export function AdvancedFeaturesPage() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [camera, setCamera] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    streamApi.spatialCameras(controller.signal).then(result => setCameras(result.items))
      .catch(cause => { if (!controller.signal.aborted) setError(String(cause)); });
    return () => controller.abort();
  }, []);
  return <div className="advanced-features">
    <header><span className="advanced-kicker">LIVE VIDEO WORKSPACE</span><h1>Advanced Features</h1>
      <p>Choose a camera and give its live feed a task.</p></header>
    <label className="advanced-camera">Camera / stream
      <select value={camera} onChange={event => setCamera(event.target.value)}>
        <option value="">Select a camera</option>
        {cameras.map(item => <option key={item.id} value={item.id}>{item.camera_name} · {item.camera_code}</option>)}
      </select>
    </label>
    {error && <p role="alert">{error}</p>}
    {camera ? <CameraWorkspace key={camera} camera={camera} /> :
      <div className="advanced-empty">Select a registered camera to configure its module and open the feed.</div>}
  </div>;
}

function CameraWorkspace({ camera }: { camera: string }) {
  const [feature, setFeature] = useState<SpatialFeature>("border_line");
  const [draft, setDraft] = useState<SpatialRule>(blank("border_line"));
  const [status, setStatus] = useState<SpatialStatus | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [generation, setGeneration] = useState(0);
  const [ratio, setRatio] = useState(16 / 9);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let initial = true;
    const poll = async () => {
      try {
        const result = await streamApi.spatial(camera, controller.signal);
        if (controller.signal.aborted) return;
        setStatus(result);
        if (initial) {
          const active = result.rules.find(rule => rule.enabled);
          if (active) { setFeature(active.feature); setDraft(active); }
          initial = false;
        }
      } catch (cause) {
        if (!controller.signal.aborted) setError(String(cause));
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 1000);
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [camera]);
  const choose = (value: SpatialFeature) => {
    setFeature(value); setDraft(status?.rules.find(rule => rule.feature === value) ?? blank(value));
    setMessage("");
  };
  const save = async (enabled: boolean) => {
    setBusy(true); setError("");
    try {
      await streamApi.saveSpatial(camera, { ...draft, enabled });
      setStatus(await streamApi.spatial(camera));
      setMessage(enabled ? "Module saved and enabled for this camera." : "Module disabled.");
    } catch (cause) { setError(String(cause)); }
    finally { setBusy(false); }
  };
  const start = async () => {
    setBusy(true); setError("");
    try { await streamApi.start(camera); setGeneration(value => value + 1); setPreviewFailed(false); }
    catch (cause) { setError(String(cause)); }
    finally { setBusy(false); }
  };
  const add = (point: SpatialPoint) => setDraft(current => ({ ...current,
    points: [...current.points, point].slice(0, feature === "border_line" ? 2 : 32) }));
  const active = status?.rules.find(rule => rule.enabled);
  const live = active?.feature === feature ? status?.live : null;
  const stale = !live || Date.now() - Date.parse(live.observed_at) > 10000;
  const geometryReady = feature === "object_path" || (feature === "border_line" ? draft.points.length === 2 : draft.points.length >= 3);
  return <>
    <div className="advanced-modules">{modules.map(module => <button key={module.id}
      aria-pressed={feature === module.id} onClick={() => choose(module.id)} disabled={busy}>
      <strong>{module.title}</strong><span>{module.detail}</span>
    </button>)}</div>
    <div className="advanced-workspace"><section>
      <div className="advanced-toolbar"><strong>{modules.find(module => module.id === feature)?.title}</strong>
        <span>{active ? `Enabled: ${modules.find(module => module.id === active.feature)?.title}` : "No module enabled"}</span>
        <button onClick={start} disabled={busy}>Start stream</button>
        <button onClick={() => { setGeneration(value => value + 1); setPreviewFailed(false); setLoaded(false); }}>Reload preview</button>
      </div>
      <div className="advanced-preview" style={{ aspectRatio: ratio }}>
        <img key={generation} src={streamApi.previewUrl(camera, String(generation))} alt="Selected camera live feed"
          onLoad={event => { const img = event.currentTarget; if (img.naturalHeight) setRatio(img.naturalWidth / img.naturalHeight); setLoaded(true); setPreviewFailed(false); }}
          onError={() => { setPreviewFailed(true); setLoaded(false); }} />
        <svg viewBox="0 0 1000 1000" preserveAspectRatio="none" role="img" aria-label="Draw the module area on the camera feed"
          onClick={event => {
            if (!loaded || feature === "object_path" || busy) return;
            const bounds = event.currentTarget.getBoundingClientRect();
            add({ x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
              y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)) });
          }}>
          {feature !== "object_path" && <>
            {feature === "border_line" ? <polyline points={draft.points.map(p => `${p.x * 1000},${p.y * 1000}`).join(" ")} /> :
              <polygon points={draft.points.map(p => `${p.x * 1000},${p.y * 1000}`).join(" ")} />}
            {draft.points.map((p, index) => <g key={index}><circle cx={p.x * 1000} cy={p.y * 1000} r="5" />
              <text x={p.x * 1000 + 10} y={p.y * 1000 - 10}>{index + 1}</text></g>)}
          </>}
          {!stale && live?.paths.map(path => <g key={path.track_id}>
            <polyline className="advanced-trail" points={path.points.map(p => `${p[0] * 1000},${p[1] * 1000}`).join(" ")} />
            {path.points.length > 0 && <text x={path.points.at(-1)![0] * 1000} y={path.points.at(-1)![1] * 1000}>{path.class_name} #{path.track_id}</text>}
          </g>)}
          {!stale && live?.motion_boxes.map((b, i) => <rect key={i} x={b[0] * 1000} y={b[1] * 1000} width={(b[2] - b[0]) * 1000} height={(b[3] - b[1]) * 1000} />)}
        </svg>
        {(!loaded || previewFailed) && <div className="advanced-preview-message">{previewFailed ? "Preview unavailable. Start the stream or check its connection, then reload." : "Connecting to camera…"}</div>}
      </div>
      <div className="advanced-toolbar">
        {feature !== "object_path" && <><button onClick={() => setDraft(d => ({ ...d, points: d.points.slice(0, -1) }))}>Undo point</button>
          <button onClick={() => setDraft(d => ({ ...d, points: [] }))}>Clear drawing</button><span>{draft.points.length} points</span></>}
        {feature === "border_line" && <label>Direction <select value={draft.direction} onChange={e => setDraft(d => ({ ...d, direction: e.target.value as SpatialRule["direction"] }))}>
          <option value="both">Both directions</option><option value="A_TO_B">A → B</option><option value="B_TO_A">B → A</option>
        </select></label>}
        <button className="advanced-primary" disabled={busy || !geometryReady || !status} onClick={() => save(true)}>Enable on this feed</button>
        <button disabled={busy || !status?.rules.some(r => r.feature === feature && r.enabled)} onClick={() => save(false)}>Disable module</button>
      </div>
      <p>{feature === "object_path" ? "Trails follow observed movement automatically; no drawing is required." : "Click on the feed to place points. Drawings are saved per camera and scale with the video."}</p>
      {feature === "border_line" && <p>For a left-to-right border, A → B means above → below. Reverse the endpoints to reverse the directions.</p>}
      <p>Enabling a module replaces the active module on this camera. Other cameras keep their own configuration.</p>
      {message && <p role="status">{message}</p>}{error && <p role="alert">{error}</p>}
    </section><aside>
      <h2>Live results</h2>
      <p>{stale ? "Waiting for fresh analytics frames. The stream and analytics worker must be running." : live?.warming_up ? "Learning the motion background…" : "Receiving analytics"}</p>
      {!stale && feature === "border_line" && <p>A → B: {live?.counts.A_TO_B ?? 0} · B → A: {live?.counts.B_TO_A ?? 0}</p>}
      {!stale && feature === "virtual_fence" && <p>People inside: {live?.inside ?? 0}</p>}
      <h3>Recent events</h3>
      <div className="advanced-events">{status?.events.length ? status.events.map(event => <article key={event.id}>
        <strong>{event.event.replaceAll("_", " ")}</strong>
        <span>{new Date(event.observed_at).toLocaleString()}{event.track_id != null ? ` · Track #${event.track_id}` : ""}</span>
        {event.direction && <span>{event.direction.replaceAll("_", " ")}</span>}
      </article>) : <p>No events for this camera yet.</p>}</div>
    </aside></div>
  </>;
}
