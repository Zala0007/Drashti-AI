import {
  Building2,
  CheckCircle2,
  KeyRound,
  LoaderCircle,
  LockKeyhole,
  Plus,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, federationApi, registryApi } from "../lib/api";
import { formatTimestamp } from "../lib/format";
import type { CredentialProfile } from "../types/federation";
import type { Department } from "../types/registry";
import { Modal } from "./Modal";

interface CredentialVaultModalProps {
  open: boolean;
  onClose: () => void;
  onChanged?: () => void;
}

const safeMessage = (error: unknown): string => error instanceof ApiError
  ? error.message
  : "The credential service could not complete this operation.";

export function CredentialVaultModal({ open, onClose, onChanged }: CredentialVaultModalProps) {
  const [profiles, setProfiles] = useState<CredentialProfile[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [form, setForm] = useState({ departmentId: "", name: "", username: "", password: "" });
  const [rotation, setRotation] = useState<{ id: string; username: string; password: string } | null>(null);

  const load = useCallback(() => setRefreshKey((value) => value + 1), []);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    Promise.all([
      federationApi.credentials({}, controller.signal),
      registryApi.departments(controller.signal),
    ]).then(([credentialPage, departmentList]) => {
      setProfiles(credentialPage.items);
      setDepartments(departmentList);
      setForm((current) => ({
        ...current,
        departmentId: current.departmentId || departmentList[0]?.id || "",
      }));
    }).catch((cause) => {
      if (!(cause instanceof DOMException && cause.name === "AbortError")) setError(safeMessage(cause));
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [open, refreshKey]);

  useEffect(() => {
    if (!open) {
      setForm({ departmentId: "", name: "", username: "", password: "" });
      setRotation(null);
      setError(null);
    }
  }, [open]);

  const activeCount = useMemo(() => profiles.filter((profile) => profile.enabled).length, [profiles]);

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!form.departmentId || !form.name.trim() || !form.username || !form.password) {
      setError("Department, profile name, username, and password are required.");
      return;
    }
    setBusy("create");
    setError(null);
    try {
      await federationApi.createCredential({
        department_id: form.departmentId,
        name: form.name.trim(),
        username: form.username,
        password: form.password,
        enabled: true,
      });
      setForm((current) => ({ ...current, name: "", username: "", password: "" }));
      onChanged?.();
      load();
    } catch (cause) {
      setError(safeMessage(cause));
    } finally {
      setBusy(null);
    }
  };

  const rotate = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!rotation || (!rotation.username && !rotation.password)) {
      setError("Enter a replacement username, password, or both.");
      return;
    }
    setBusy(`rotate:${rotation?.id}`);
    setError(null);
    try {
      await federationApi.patchCredential(rotation.id, {
        username: rotation.username || undefined,
        password: rotation.password || undefined,
      });
      setRotation(null);
      onChanged?.();
      load();
    } catch (cause) {
      setError(safeMessage(cause));
    } finally {
      setBusy(null);
    }
  };

  const toggle = async (profile: CredentialProfile) => {
    setBusy(`toggle:${profile.id}`);
    setError(null);
    try {
      const updated = await federationApi.patchCredential(profile.id, { enabled: !profile.enabled });
      setProfiles((current) => current.map((item) => item.id === updated.id ? updated : item));
      onChanged?.();
    } catch (cause) {
      setError(safeMessage(cause));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal open={open} onClose={onClose} busy={Boolean(busy)} title="Credential profiles" eyebrow="Secure federation / Device access" wide>
      <div className="modal__body credential-vault">
        <section className="credential-vault__posture">
          <span><ShieldCheck size={21} /></span>
          <div><strong>Write-only, department-scoped device identities</strong><p>Usernames and passwords are encrypted server-side and are never returned to this browser. Connections use only an opaque profile reference.</p></div>
          <dl><div><dt>Total</dt><dd>{profiles.length}</dd></div><div><dt>Enabled</dt><dd>{activeCount}</dd></div></dl>
        </section>

        {error ? <div className="form-alert" role="alert"><KeyRound size={18} /><span><strong>Credential operation did not complete</strong>{error}</span></div> : null}

        <div className="credential-vault__grid">
          <form className="credential-create" onSubmit={create} autoComplete="off">
            <header><span><Plus size={17} /></span><div><strong>Create device identity</strong><small>Use a dedicated read-only camera account where supported.</small></div></header>
            <label className="form-field"><span>Owning department <b>*</b></span><select value={form.departmentId} onChange={(event) => setForm((current) => ({ ...current, departmentId: event.target.value }))}><option value="">Select department</option>{departments.map((department) => <option value={department.id} key={department.id}>{department.name}</option>)}</select></label>
            <label className="form-field"><span>Profile name <b>*</b></span><input value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} maxLength={160} placeholder="District camera service account" /></label>
            <label className="form-field"><span>Device username <b>*</b></span><input value={form.username} onChange={(event) => setForm((current) => ({ ...current, username: event.target.value }))} autoComplete="off" maxLength={256} /></label>
            <label className="form-field"><span>Device password <b>*</b></span><input type="password" value={form.password} onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))} autoComplete="new-password" maxLength={1024} /></label>
            <div className="credential-create__note"><LockKeyhole size={15} />Values are cleared from browser state immediately after a successful write.</div>
            <button className="button button--primary" type="submit" disabled={Boolean(busy)}>{busy === "create" ? <LoaderCircle className="spin" size={16} /> : <ShieldCheck size={16} />}{busy === "create" ? "Encrypting…" : "Encrypt credential profile"}</button>
          </form>

          <section className="credential-inventory">
            <header><div><span><KeyRound size={17} /></span><div><strong>Managed profiles</strong><small>Safe metadata only; secret values cannot be read back.</small></div></div><button type="button" onClick={load} disabled={loading || Boolean(busy)} aria-label="Refresh credential profiles"><RefreshCw className={loading ? "spin" : undefined} size={15} /></button></header>
            {loading ? <div className="credential-inventory__state"><LoaderCircle className="spin" size={20} />Loading credential inventory…</div> : null}
            {!loading && !profiles.length ? <div className="credential-inventory__state"><KeyRound size={22} />No credential profiles created yet.</div> : null}
            {!loading && profiles.length ? <div className="credential-profile-list">{profiles.map((profile) => (
              <article className={`credential-profile${profile.enabled ? " credential-profile--enabled" : ""}`} key={profile.id}>
                <span className="credential-profile__icon"><Building2 size={17} /></span>
                <div className="credential-profile__identity"><strong>{profile.name}</strong><small>{profile.department.name} · {profile.reference}</small><em>{profile.last_used_at ? `Last used ${formatTimestamp(profile.last_used_at)}` : "Not used by a runtime yet"}</em></div>
                <span className="credential-profile__state">{profile.enabled ? <CheckCircle2 size={14} /> : <LockKeyhole size={14} />}{profile.enabled ? "Enabled" : "Disabled"}</span>
                <div className="credential-profile__actions"><button type="button" onClick={() => setRotation({ id: profile.id, username: "", password: "" })}><RotateCcw size={14} />Rotate</button><button type="button" onClick={() => void toggle(profile)} disabled={busy === `toggle:${profile.id}`}>{busy === `toggle:${profile.id}` ? <LoaderCircle className="spin" size={14} /> : null}{profile.enabled ? "Disable" : "Enable"}</button></div>
              </article>
            ))}</div> : null}
          </section>
        </div>

        {rotation ? <form className="credential-rotation" onSubmit={rotate} autoComplete="off"><header><span><RotateCcw size={17} /></span><div><strong>Rotate protected values</strong><small>Leave a field blank to retain its current encrypted value.</small></div></header><label className="form-field"><span>Replacement username</span><input value={rotation.username} onChange={(event) => setRotation((current) => current ? { ...current, username: event.target.value } : current)} autoComplete="off" /></label><label className="form-field"><span>Replacement password</span><input type="password" value={rotation.password} onChange={(event) => setRotation((current) => current ? { ...current, password: event.target.value } : current)} autoComplete="new-password" /></label><button className="button button--secondary" type="button" onClick={() => setRotation(null)}>Cancel</button><button className="button button--primary" type="submit" disabled={Boolean(busy)}>{busy === `rotate:${rotation.id}` ? <LoaderCircle className="spin" size={15} /> : <RotateCcw size={15} />}Rotate now</button></form> : null}
      </div>
      <footer className="modal__footer"><p><ShieldCheck size={14} /> Encrypted local resolver · Vault/KMS adapter boundary preserved</p><button className="button button--secondary" type="button" onClick={onClose} disabled={Boolean(busy)}>Close</button></footer>
    </Modal>
  );
}
