import { AlertCircle, BrainCircuit, Building2, Camera, Check, LoaderCircle, MapPin, Network, Plus, Save } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ApiError, registryApi } from "../lib/api";
import { initialCameraForm, toCameraCreate, validateCameraForm, type CameraFormState } from "../lib/cameraForm";
import { titleCase } from "../lib/format";
import {
  aiCapabilityOptions,
  cameraStatuses,
  cameraTypes,
  connectivityTypes,
  ownershipTypes,
  streamProtocols,
  type Camera as CameraRecord,
  type Department,
} from "../types/registry";
import { Modal } from "./Modal";
import { DepartmentCreatePanel } from "./DepartmentCreatePanel";

interface OnboardCameraModalProps {
  open: boolean;
  departments: Department[];
  onClose: () => void;
  onCreated: (camera: CameraRecord) => void;
  onDepartmentCreated: (department: Department) => void;
}

export function OnboardCameraModal({ open, departments, onClose, onCreated, onDepartmentCreated }: OnboardCameraModalProps) {
  const [form, setForm] = useState<CameraFormState>(initialCameraForm);
  const [errors, setErrors] = useState<ReturnType<typeof validateCameraForm>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [departmentCreatorOpen, setDepartmentCreatorOpen] = useState(false);

  const update = <K extends keyof CameraFormState>(field: K, value: CameraFormState[K]) => {
    setForm((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: undefined }));
  };

  const close = () => {
    if (submitting) return;
    setForm(initialCameraForm);
    setErrors({});
    setSubmitError(null);
    setDepartmentCreatorOpen(false);
    onClose();
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const nextErrors = validateCameraForm(form);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const camera = await registryApi.createCamera(toCameraCreate(form));
      setForm(initialCameraForm);
      onCreated(camera);
      onClose();
    } catch (error) {
      setSubmitError(error instanceof ApiError ? error.message : "Camera registration failed.");
    } finally {
      setSubmitting(false);
    }
  };

  const toggleCapability = (capability: (typeof aiCapabilityOptions)[number]) => {
    update(
      "ai_capabilities",
      form.ai_capabilities.includes(capability)
        ? form.ai_capabilities.filter((item) => item !== capability)
        : [...form.ai_capabilities, capability],
    );
  };

  return (
    <Modal open={open} onClose={close} title="Register camera asset" eyebrow="P0.1 · Manual onboarding" wide busy={submitting}>
      <form className="camera-form" onSubmit={submit} noValidate>
        <div className="modal__body">
          {submitError ? <div className="form-alert" role="alert"><AlertCircle aria-hidden="true" size={18} /><span><strong>Registration not completed</strong>{submitError}</span></div> : null}

          <fieldset className="form-section">
            <legend><span><Camera aria-hidden="true" size={17} /></span><div><strong>Asset identity</strong><small>Unique identifiers and administrative ownership</small></div></legend>
            <div className="form-grid form-grid--3">
              <Field label="Camera code" error={errors.camera_code} required>
                <input autoFocus value={form.camera_code} onChange={(event) => update("camera_code", event.target.value.toUpperCase())} placeholder="GJ-AHD-TRF-001" maxLength={50} />
              </Field>
              <Field label="Camera name" error={errors.camera_name} required span={2}>
                <input value={form.camera_name} onChange={(event) => update("camera_name", event.target.value)} placeholder="Ashram Road northbound" maxLength={160} />
              </Field>
              <div className="form-field form-field--span-2">
                <span>Department <b aria-label="required">*</b></span>
                <div className="department-select-control">
                  <select aria-label="Department" value={form.department_id} onChange={(event) => update("department_id", event.target.value)}>
                    <option value="">Select owning department</option>
                    {departments.map((department) => <option key={department.id} value={department.id}>{department.name} ({department.code})</option>)}
                  </select>
                  <button type="button" className="button department-select-control__add" onClick={() => setDepartmentCreatorOpen((value) => !value)} aria-expanded={departmentCreatorOpen}>
                    {departmentCreatorOpen ? <Building2 size={15} /> : <Plus size={15} />} {departmentCreatorOpen ? "Close" : "Add department"}
                  </button>
                </div>
                {errors.department_id ? <small className="field-error">{errors.department_id}</small> : null}
              </div>
              <Field label="Ownership type">
                <select value={form.ownership} onChange={(event) => update("ownership", event.target.value as CameraFormState["ownership"])}>{ownershipTypes.map((type) => <option key={type} value={type}>{titleCase(type)}</option>)}</select>
              </Field>
              <Field label="Custodian / owner" span={2}>
                <input value={form.owner_name} onChange={(event) => update("owner_name", event.target.value)} placeholder="Control room, agency or establishment" />
              </Field>
              {departmentCreatorOpen ? (
                <div className="department-create-inline form-field--span-3">
                  <DepartmentCreatePanel
                    inline
                    onCancel={() => setDepartmentCreatorOpen(false)}
                    onCreated={(department) => {
                      onDepartmentCreated(department);
                      update("department_id", department.id);
                      setDepartmentCreatorOpen(false);
                    }}
                  />
                </div>
              ) : null}
            </div>
          </fieldset>

          <fieldset className="form-section">
            <legend><span><MapPin aria-hidden="true" size={17} /></span><div><strong>Location & GIS</strong><small>Coordinates power map visibility and future route intelligence</small></div></legend>
            <div className="form-grid form-grid--4">
              <Field label="District" error={errors.district} required>
                <input value={form.district} onChange={(event) => update("district", event.target.value)} placeholder="Ahmedabad" />
              </Field>
              <Field label="City / locality">
                <input value={form.city} onChange={(event) => update("city", event.target.value)} placeholder="Ahmedabad" />
              </Field>
              <Field label="Latitude" error={errors.latitude} required>
                <input inputMode="decimal" value={form.latitude} onChange={(event) => update("latitude", event.target.value)} placeholder="23.0225" />
              </Field>
              <Field label="Longitude" error={errors.longitude} required>
                <input inputMode="decimal" value={form.longitude} onChange={(event) => update("longitude", event.target.value)} placeholder="72.5714" />
              </Field>
              <Field label="Location description" span={4}>
                <input value={form.location_description} onChange={(event) => update("location_description", event.target.value)} placeholder="Junction, lane direction, landmark or coverage notes" />
              </Field>
            </div>
          </fieldset>

          <fieldset className="form-section">
            <legend><span><Network aria-hidden="true" size={17} /></span><div><strong>Camera & integration profile</strong><small>Non-secret metadata only; credentials remain in the federation layer</small></div></legend>
            <div className="form-grid form-grid--4">
              <Field label="Camera type">
                <select value={form.camera_type} onChange={(event) => update("camera_type", event.target.value as CameraFormState["camera_type"])}>{cameraTypes.map((type) => <option key={type} value={type}>{titleCase(type)}</option>)}</select>
              </Field>
              <Field label="Lifecycle status">
                <select value={form.status} onChange={(event) => update("status", event.target.value as CameraFormState["status"])}>{cameraStatuses.filter((status) => status !== "retired").map((status) => <option key={status} value={status}>{titleCase(status)}</option>)}</select>
              </Field>
              <Field label="Vendor">
                <input value={form.vendor} onChange={(event) => update("vendor", event.target.value)} placeholder="Manufacturer" />
              </Field>
              <Field label="Model">
                <input value={form.model} onChange={(event) => update("model", event.target.value)} placeholder="Device model" />
              </Field>
              <Field label="Existing VMS">
                <input value={form.vms} onChange={(event) => update("vms", event.target.value)} placeholder="VMS / NVR name" />
              </Field>
              <Field label="Connectivity">
                <select value={form.connectivity_type} onChange={(event) => update("connectivity_type", event.target.value as CameraFormState["connectivity_type"])}>{connectivityTypes.map((type) => <option key={type} value={type}>{titleCase(type)}</option>)}</select>
              </Field>
              <Field label="Stream protocol">
                <select value={form.stream_protocol} onChange={(event) => update("stream_protocol", event.target.value as CameraFormState["stream_protocol"])}>{streamProtocols.map((protocol) => <option key={protocol} value={protocol}>{titleCase(protocol)}</option>)}</select>
              </Field>
              <Field label="Storage type">
                <input value={form.storage_type} onChange={(event) => update("storage_type", event.target.value)} placeholder="NVR, cloud, local" />
              </Field>
              <Field label="Retention days" error={errors.retention_days}>
                <input type="number" min="0" max="3650" value={form.retention_days} onChange={(event) => update("retention_days", event.target.value)} placeholder="15" />
              </Field>
            </div>
            <div className="switch-row">
              <Toggle checked={form.rtsp_capable} label="RTSP capable" onChange={(checked) => update("rtsp_capable", checked)} />
              <Toggle checked={form.onvif_capable} label="ONVIF capable" onChange={(checked) => update("onvif_capable", checked)} />
              <Toggle checked={form.is_public_facing} label="Public-facing camera" onChange={(checked) => update("is_public_facing", checked)} />
            </div>
          </fieldset>

          <fieldset className="form-section">
            <legend><span><BrainCircuit aria-hidden="true" size={17} /></span><div><strong>AI readiness</strong><small>Declare supported analytics; this does not activate a video feed</small></div></legend>
            <Toggle checked={form.ai_enabled} label="Analytics processing enabled for this camera" onChange={(checked) => update("ai_enabled", checked)} />
            {form.ai_enabled ? (
              <div className="capability-picker">
                {aiCapabilityOptions.map((capability) => {
                  const checked = form.ai_capabilities.includes(capability);
                  return <button className={checked ? "capability-option capability-option--selected" : "capability-option"} type="button" key={capability} onClick={() => toggleCapability(capability)}><span>{checked ? <Check size={13} /> : null}</span>{titleCase(capability)}</button>;
                })}
              </div>
            ) : null}
            {errors.ai_capabilities ? <small className="field-error">{errors.ai_capabilities}</small> : null}
            <Field label="Tags" hint="Comma-separated operational labels">
              <input value={form.tags} onChange={(event) => update("tags", event.target.value)} placeholder="traffic, highway, northbound" />
            </Field>
          </fieldset>
        </div>
        <footer className="modal__footer">
          <p><ShieldNote /></p>
          <button type="button" className="button button--quiet" onClick={close} disabled={submitting}>Cancel</button>
          <button type="submit" className="button button--primary" disabled={submitting || departments.length === 0}>
            {submitting ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />} {submitting ? "Registering…" : "Register camera"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function Field({ label, error, hint, required, span, children }: { label: string; error?: string; hint?: string; required?: boolean; span?: number; children: React.ReactNode }) {
  return <label className={`form-field${span ? ` form-field--span-${span}` : ""}`}><span>{label}{required ? <b aria-label="required">*</b> : null}</span>{children}{error ? <small className="field-error">{error}</small> : hint ? <small>{hint}</small> : null}</label>;
}

function Toggle({ checked, label, onChange }: { checked: boolean; label: string; onChange: (checked: boolean) => void }) {
  return <label className="toggle"><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><span aria-hidden="true"><i /></span><strong>{label}</strong></label>;
}

function ShieldNote() {
  return <><Network aria-hidden="true" size={14} /> API-submitted · audit recorded</>;
}
