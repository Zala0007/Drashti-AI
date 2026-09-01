import {
  ArrowRight,
  Camera,
  CheckCircle2,
  KeyRound,
  LoaderCircle,
  Network,
  Radar,
  Search,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { adapterIsAvailable, validateFederationEndpoint } from "../lib/federation";
import { ApiError, federationApi, registryApi } from "../lib/api";
import { emptyCameraFilters } from "../lib/registryView";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import type { CredentialProfile, FederationAdapter, FederationConnection, FederationConnectionCreate } from "../types/federation";
import type { Camera as CameraRecord } from "../types/registry";
import { FederationStatusBadge } from "./FederationStatusBadge";
import { Modal } from "./Modal";

interface FederationOnboardingModalProps {
  open: boolean;
  adapters: FederationAdapter[];
  credentialRefreshKey?: number;
  onClose: () => void;
  onCreated: (connection: FederationConnection) => void;
}

interface FormState {
  cameraId: string;
  adapterKind: string;
  name: string;
  streamRole: string;
  endpoint: string;
  credentialReference: string;
  priority: string;
  enabled: boolean;
  probeAfterCreate: boolean;
}

const initialForm: FormState = {
  cameraId: "",
  adapterKind: "",
  name: "Primary source profile",
  streamRole: "primary",
  endpoint: "",
  credentialReference: "",
  priority: "100",
  enabled: true,
  probeAfterCreate: true,
};

const safeMessage = (error: unknown): string => error instanceof ApiError
  ? error.message
  : "The federation service could not complete this operation.";

export function FederationOnboardingModal({
  open,
  adapters,
  credentialRefreshKey = 0,
  onClose,
  onCreated,
}: FederationOnboardingModalProps) {
  const [form, setForm] = useState<FormState>(initialForm);
  const [cameraSearch, setCameraSearch] = useState("");
  const debouncedCameraSearch = useDebouncedValue(cameraSearch, 250);
  const [cameras, setCameras] = useState<CameraRecord[]>([]);
  const [cameraLoading, setCameraLoading] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [result, setResult] = useState<FederationConnection | null>(null);
  const [probeNote, setProbeNote] = useState<string | null>(null);
  const [credentialProfiles, setCredentialProfiles] = useState<CredentialProfile[]>([]);
  const [credentialsLoading, setCredentialsLoading] = useState(false);

  const availableAdapters = useMemo(() => adapters.filter(adapterIsAvailable), [adapters]);
  const defaultAdapterKind = availableAdapters[0]?.kind ?? "";
  const selectedAdapter = adapters.find((adapter) => adapter.kind === form.adapterKind);
  const selectedCamera = cameras.find((camera) => camera.id === form.cameraId || camera.camera_uuid === form.cameraId);

  useEffect(() => {
    if (!open) return;
    setForm({ ...initialForm, adapterKind: defaultAdapterKind });
    setCameraSearch("");
    setResult(null);
    setSubmitError(null);
    setProbeNote(null);
    setFieldErrors({});
  }, [defaultAdapterKind, open]);

  useEffect(() => {
    if (!open || result) return;
    const controller = new AbortController();
    setCameraLoading(true);
    setCameraError(null);
    registryApi.cameras(
      { ...emptyCameraFilters, search: debouncedCameraSearch },
      1,
      50,
      controller.signal,
    ).then((page) => {
      setCameras(page.items);
      setForm((current) => current.cameraId && !page.items.some((camera) => (camera.camera_uuid ?? camera.id) === current.cameraId)
        ? { ...current, cameraId: "" }
        : current);
    }).catch((error) => {
      if (!(error instanceof DOMException && error.name === "AbortError")) setCameraError(safeMessage(error));
    }).finally(() => {
      if (!controller.signal.aborted) setCameraLoading(false);
    });
    return () => controller.abort();
  }, [debouncedCameraSearch, open, result]);

  useEffect(() => {
    if (!open || result || !selectedCamera?.department_id) {
      setCredentialProfiles([]);
      return;
    }
    const controller = new AbortController();
    setCredentialsLoading(true);
    federationApi.credentials(
      { department_id: selectedCamera.department_id, enabled: true },
      controller.signal,
    ).then((page) => {
      setCredentialProfiles(page.items);
      setForm((current) => current.credentialReference.startsWith("credential-profile:")
        && !page.items.some((profile) => profile.reference === current.credentialReference)
        ? { ...current, credentialReference: "" }
        : current);
    }).catch((error) => {
      if (!(error instanceof DOMException && error.name === "AbortError")) setSubmitError(safeMessage(error));
    }).finally(() => {
      if (!controller.signal.aborted) setCredentialsLoading(false);
    });
    return () => controller.abort();
  }, [credentialRefreshKey, open, result, selectedCamera?.department_id]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    setFieldErrors((current) => {
      if (!current[key]) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  };

  const validate = (): Record<string, string> => {
    const errors: Record<string, string> = {};
    if (!form.cameraId) errors.cameraId = "Select a registered camera.";
    if (!form.adapterKind) errors.adapterKind = "Select an available adapter.";
    if (!form.name.trim() || form.name.trim().length < 3) errors.name = "Use a profile name of at least 3 characters.";
    const endpointError = validateFederationEndpoint(form.endpoint, selectedAdapter);
    if (endpointError) errors.endpoint = endpointError;
    if (form.credentialReference && !/^(credential-profile|vault-ref|kms-ref):[a-zA-Z0-9][a-zA-Z0-9._/-]{1,470}$/.test(form.credentialReference)) {
      errors.credentialReference = "Use credential-profile:, vault-ref:, or kms-ref: followed by an opaque identifier.";
    }
    const priority = Number(form.priority);
    if (!Number.isInteger(priority) || priority < 0 || priority > 1000) errors.priority = "Priority must be an integer from 0 to 1000.";
    return errors;
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const errors = validate();
    setFieldErrors(errors);
    if (Object.keys(errors).length) return;
    setSubmitting(true);
    setSubmitError(null);
    const payload: FederationConnectionCreate = {
      camera_id: form.cameraId,
      name: form.name.trim(),
      adapter_kind: form.adapterKind,
      endpoint: form.endpoint.trim(),
      stream_role: form.streamRole,
      credential_reference: form.credentialReference.trim() || undefined,
      priority: Number(form.priority),
      enabled: form.enabled,
    };
    const shouldProbe = form.probeAfterCreate;
    try {
      let connection = await federationApi.createConnection(payload);
      // Remove source material from browser state before any result is rendered.
      setForm((current) => ({ ...current, endpoint: "", credentialReference: "" }));
      setResult(connection);
      onCreated(connection);
      if (shouldProbe && selectedAdapter?.probe_supported) {
        setProbeNote("Secure probe in progress…");
        try {
          connection = await federationApi.probe(connection.id);
          setResult(connection);
          setProbeNote("Probe completed. The profile status now reflects the adapter response.");
          onCreated(connection);
        } catch (error) {
          setProbeNote(`Profile saved; automatic probe did not complete. ${safeMessage(error)}`);
        }
      }
    } catch (error) {
      setSubmitError(safeMessage(error));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} busy={submitting} title={result ? "Connection profile secured" : "Onboard a federated stream"} eyebrow="P0.3 / Secure federation" wide>
      {result ? (
        <div className="federation-success" role="status">
          <span className="federation-success__icon"><CheckCircle2 aria-hidden="true" size={28} /></span>
          <div className="federation-success__copy">
            <span className="eyebrow">Profile created</span>
            <h3>{result.name}</h3>
            <p>The source endpoint was encrypted by the platform and has been removed from this browser view.</p>
          </div>
          <div className="federation-success__facts">
            <span><small>Camera</small><strong>{result.camera_code}</strong></span>
            <span><small>Adapter</small><strong>{result.adapter_label || result.adapter_kind}</strong></span>
            <span><small>Verification</small><FederationStatusBadge value={result.verification_status} /></span>
            <span><small>Activation</small><strong>{result.enabled ? "Enabled" : "Disabled"}</strong></span>
          </div>
          {probeNote ? <div className="probe-result-note"><Radar className={submitting ? "spin" : undefined} size={17} /><span>{probeNote}</span></div> : null}
          <div className="federation-success__security"><ShieldCheck size={18} /><span><strong>Secret-safe profile established</strong><small>No raw endpoint, username, password, or credential value is displayed.</small></span></div>
          <footer className="modal__footer">
            <button className="button button--primary" type="button" onClick={onClose}>Return to federation inventory</button>
          </footer>
        </div>
      ) : (
        <form onSubmit={submit}>
          <div className="modal__body federation-onboard-body">
            <div className="onboard-flow" aria-label="Onboarding workflow">
              <span className="onboard-flow__step onboard-flow__step--active"><Camera size={17} /><b>1</b><small>Registry asset</small></span>
              <ArrowRight size={15} />
              <span className="onboard-flow__step onboard-flow__step--active"><Network size={17} /><b>2</b><small>Adapter profile</small></span>
              <ArrowRight size={15} />
              <span className="onboard-flow__step"><ShieldCheck size={17} /><b>3</b><small>Encrypt + probe</small></span>
            </div>

            {submitError ? <div className="form-alert" role="alert"><Network size={18} /><span><strong>Connection profile was not created</strong>{submitError}</span></div> : null}

            <fieldset className="form-section">
              <legend><span><Camera size={16} /></span><div><strong>Bind an authoritative registry asset</strong><small>Every connection profile belongs to one existing camera.</small></div></legend>
              <div className="form-grid form-grid--3">
                <label className="form-field form-field--span-3">
                  <span>Find camera</span>
                  <span className="federation-camera-search"><Search size={15} /><input aria-label="Find camera" value={cameraSearch} onChange={(event) => setCameraSearch(event.target.value)} placeholder="Search camera code, name, district, or department" /></span>
                </label>
                <label className="form-field form-field--span-3">
                  <span>Registered camera <b>*</b></span>
                  <select aria-label="Registered camera" value={form.cameraId} onChange={(event) => update("cameraId", event.target.value)} disabled={cameraLoading}>
                    <option value="">{cameraLoading ? "Loading registry…" : cameras.length ? "Select a camera" : "No matching cameras"}</option>
                    {cameras.map((camera) => <option key={camera.camera_uuid ?? camera.id} value={camera.camera_uuid ?? camera.id}>{camera.camera_code} — {camera.camera_name} · {camera.city || camera.district}</option>)}
                  </select>
                  {fieldErrors.cameraId ? <small className="field-error">{fieldErrors.cameraId}</small> : null}
                  {cameraError ? <small className="field-error">{cameraError}</small> : null}
                </label>
              </div>
              {selectedCamera ? <div className="selected-registry-asset"><Camera size={16} /><span><strong>{selectedCamera.camera_name}</strong><small>{selectedCamera.camera_code} · {selectedCamera.city || selectedCamera.district}</small></span><em>Registry verified</em></div> : null}
            </fieldset>

            <fieldset className="form-section">
              <legend><span><Network size={16} /></span><div><strong>Configure the vendor-neutral adapter</strong><small>The endpoint is transmitted once and never returned by the API.</small></div></legend>
              <div className="form-grid form-grid--3">
                <label className="form-field">
                  <span>Adapter <b>*</b></span>
                  <select aria-label="Adapter" value={form.adapterKind} onChange={(event) => update("adapterKind", event.target.value)}>
                    <option value="">Select adapter</option>
                    {adapters.map((adapter) => <option key={adapter.kind} value={adapter.kind} disabled={!adapterIsAvailable(adapter)}>{adapter.label}{adapterIsAvailable(adapter) ? "" : " — unavailable"}</option>)}
                  </select>
                  {fieldErrors.adapterKind ? <small className="field-error">{fieldErrors.adapterKind}</small> : null}
                </label>
                <label className="form-field">
                  <span>Profile name <b>*</b></span>
                  <input aria-label="Profile name" value={form.name} onChange={(event) => update("name", event.target.value)} maxLength={160} />
                  {fieldErrors.name ? <small className="field-error">{fieldErrors.name}</small> : null}
                </label>
                <label className="form-field">
                  <span>Stream role <b>*</b></span>
                  <select aria-label="Stream role" value={form.streamRole} onChange={(event) => update("streamRole", event.target.value)}>
                    <option value="primary">Primary</option>
                    <option value="substream">Low-bandwidth substream</option>
                    <option value="metadata">Analytics metadata</option>
                    <option value="playback">Archive playback</option>
                  </select>
                </label>
                <label className="form-field form-field--span-3">
                  <span>Source endpoint <b>*</b></span>
                  <input aria-label="Source endpoint" type="url" autoComplete="off" spellCheck={false} value={form.endpoint} onChange={(event) => update("endpoint", event.target.value)} placeholder={selectedAdapter?.schemes?.length ? `${selectedAdapter.schemes[0]}://gateway.example/stream` : "rtsp://gateway.example/stream"} />
                  {fieldErrors.endpoint ? <small className="field-error">{fieldErrors.endpoint}</small> : <small>Accepted scheme{selectedAdapter?.schemes?.length === 1 ? "" : "s"}: {selectedAdapter?.schemes?.join(", ") || "choose an adapter"}. Embedded credentials are rejected.</small>}
                </label>
                <label className="form-field form-field--span-2">
                  <span>Managed credential profile</span>
                  <select aria-label="Managed credential profile" value={credentialProfiles.some((profile) => profile.reference === form.credentialReference) ? form.credentialReference : ""} onChange={(event) => update("credentialReference", event.target.value)} disabled={!selectedCamera || credentialsLoading}>
                    <option value="">{credentialsLoading ? "Loading department profiles…" : credentialProfiles.length ? "No managed credential" : "No enabled profiles for this department"}</option>
                    {credentialProfiles.map((profile) => <option value={profile.reference} key={profile.id}>{profile.name} — {profile.department.name}</option>)}
                  </select>
                  <small>Only profiles owned by the selected camera department are available.</small>
                </label>
                <label className="form-field">
                  <span>External resolver reference</span>
                  <input aria-label="Opaque credential reference" autoComplete="off" value={form.credentialReference} onChange={(event) => update("credentialReference", event.target.value)} placeholder="vault-ref:cctv/home/camera-001" />
                  {fieldErrors.credentialReference ? <small className="field-error">{fieldErrors.credentialReference}</small> : <small>Reference a secret manager; never paste a username, password, token, or certificate.</small>}
                </label>
                <label className="form-field form-field--span-3">
                  <span>Routing priority</span>
                  <input aria-label="Routing priority" type="number" min="0" max="1000" step="1" value={form.priority} onChange={(event) => update("priority", event.target.value)} />
                  {fieldErrors.priority ? <small className="field-error">{fieldErrors.priority}</small> : <small>Lower values are preferred.</small>}
                </label>
              </div>
              <div className="federation-switches">
                <label className="federation-check"><input type="checkbox" checked={form.enabled} onChange={(event) => update("enabled", event.target.checked)} /><span><strong>Enable after creation</strong><small>Allow probes and supervised media-runtime admission for eligible adapters.</small></span></label>
                <label className="federation-check"><input type="checkbox" checked={form.probeAfterCreate} onChange={(event) => update("probeAfterCreate", event.target.checked)} disabled={!selectedAdapter?.probe_supported} /><span><strong>Probe immediately</strong><small>{selectedAdapter?.probe_supported ? "Run a safe adapter capability probe after encryption." : "This adapter does not expose a probe capability."}</small></span></label>
              </div>
            </fieldset>

            <div className="security-boundary"><KeyRound size={19} /><span><strong>Credential boundary</strong><small>Drishti AI encrypts the endpoint and managed device identity server-side; neither is returned to the browser. ONVIF profiles negotiate an authorized RTSP URI inside the worker boundary.</small></span></div>
          </div>
          <footer className="modal__footer">
            <p><ShieldCheck size={14} /> Secret-safe by design</p>
            <button type="button" className="button button--secondary" onClick={onClose} disabled={submitting}>Cancel</button>
            <button type="submit" className="button button--primary" disabled={submitting || !availableAdapters.length}>
              {submitting ? <LoaderCircle className="spin" size={16} /> : <Network size={16} />}
              {submitting ? "Securing profile…" : "Encrypt and onboard"}
            </button>
          </footer>
        </form>
      )}
    </Modal>
  );
}
