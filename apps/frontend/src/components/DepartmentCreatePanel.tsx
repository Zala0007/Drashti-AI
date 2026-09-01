import { AlertCircle, Building2, LoaderCircle, Plus, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { ApiError, registryApi } from "../lib/api";
import type { Department } from "../types/registry";

interface DepartmentCreatePanelProps {
  inline?: boolean;
  onCancel: () => void;
  onCreated: (department: Department) => void;
}

const validCode = /^[A-Z0-9][A-Z0-9_.:/-]{1,49}$/;

export function DepartmentCreatePanel({ inline = false, onCancel, onCreated }: DepartmentCreatePanelProps) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const create = async () => {
    const normalizedCode = code.trim().toUpperCase();
    const normalizedName = name.trim();
    if (!validCode.test(normalizedCode)) {
      setError("Code must be 2–50 characters using letters, numbers, dot, underscore, colon, slash or hyphen.");
      return;
    }
    if (normalizedName.length < 2) {
      setError("Department name must contain at least 2 characters.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const department = await registryApi.createDepartment({
        code: normalizedCode,
        name: normalizedName,
        description: description.trim() || null,
      });
      onCreated(department);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Department could not be created.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section
      className={`department-create-panel${inline ? " department-create-panel--inline" : ""}`}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          if (!submitting) void create();
        }
      }}
    >
      <header className="department-create-panel__intro">
        <span><Building2 aria-hidden="true" size={18} /></span>
        <div><strong>Department identity</strong><small>Create an owning authority for camera assets and credentials.</small></div>
      </header>
      {error ? <div className="form-alert" role="alert"><AlertCircle aria-hidden="true" size={17} /><span><strong>Department not created</strong>{error}</span></div> : null}
      <div className="department-create-grid">
        <label className="form-field">
          <span>Department code <b aria-label="required">*</b></span>
          <input autoFocus value={code} onChange={(event) => setCode(event.target.value.toUpperCase())} placeholder="TRAFFIC" maxLength={50} aria-label="Department code" />
          <small>Short unique code, for example TRAFFIC</small>
        </label>
        <label className="form-field">
          <span>Department name <b aria-label="required">*</b></span>
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Traffic Police Department" maxLength={160} aria-label="Department name" />
        </label>
        <label className="form-field department-create-grid__wide">
          <span>Description</span>
          <textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Operational responsibility and camera ownership" maxLength={2000} rows={3} aria-label="Department description" />
        </label>
      </div>
      <footer className="department-create-panel__actions">
        <span><ShieldCheck aria-hidden="true" size={14} /> Saved to the authoritative registry</span>
        <button type="button" className="button button--quiet" onClick={onCancel} disabled={submitting}>Cancel</button>
        <button type="button" className="button button--primary" onClick={() => void create()} disabled={submitting}>
          {submitting ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />}
          {submitting ? "Creating…" : "Create department"}
        </button>
      </footer>
    </section>
  );
}
