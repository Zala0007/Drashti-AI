import { AlertCircle, AlertTriangle, CheckCircle2, Download, FileSpreadsheet, LoaderCircle, UploadCloud, X } from "lucide-react";
import { useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { ApiError, registryApi } from "../lib/api";
import type { ImportResult } from "../types/registry";
import { Modal } from "./Modal";

interface CsvImportModalProps {
  open: boolean;
  onClose: () => void;
  onImported: (result: ImportResult) => void;
}

const templateHeaders = [
  "camera_code", "camera_name", "department_code", "district", "city",
  "location_description", "latitude", "longitude", "camera_type", "vendor",
  "model", "vms", "connectivity_type", "stream_protocol", "rtsp_capable", "onvif_capable",
  "storage_details", "ai_capabilities", "ownership", "owner_name", "is_public_facing", "tags",
];

export function CsvImportModal({ open, onClose, onImported }: CsvImportModalProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);

  const chooseFile = (candidate?: File) => {
    setResult(null);
    setFileError(null);
    if (!candidate) return;
    if (!candidate.name.toLowerCase().endsWith(".csv")) {
      setFileError("Choose a .csv file exported as UTF-8.");
      setFile(null);
      return;
    }
    if (candidate.size > 10 * 1024 * 1024) {
      setFileError("The CSV must be 10 MB or smaller.");
      setFile(null);
      return;
    }
    setFile(candidate);
  };

  const upload = async () => {
    if (!file) return;
    setUploading(true);
    setFileError(null);
    try {
      const response = await registryApi.importCsv(file);
      setResult(response);
      const allFailed = (response.total_rows ?? 0) > 0 && response.failed === response.total_rows;
      if (!allFailed) onImported(response);
    } catch (error) {
      setFileError(error instanceof ApiError ? error.message : "Bulk import failed.");
    } finally {
      setUploading(false);
    }
  };

  const close = () => {
    if (uploading) return;
    setFile(null);
    setFileError(null);
    setResult(null);
    onClose();
  };

  const downloadTemplate = () => {
    const blob = new Blob([`${templateHeaders.join(",")}\r\n`], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "drishti-camera-import-template.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (!uploading) chooseFile(event.dataTransfer.files[0]);
  };

  return (
    <Modal open={open} onClose={close} title="Bulk onboard camera assets" eyebrow="P0.1 · CSV import" busy={uploading}>
      <div className="modal__body csv-import">
        <div className="import-guidance">
          <span><FileSpreadsheet aria-hidden="true" size={20} /></span>
          <div><strong>Standardized registry import</strong><p>Records are validated by the registry API before any camera is created. Secret fields and stream URLs are not accepted here.</p></div>
        </div>
        <button type="button" className="template-download" onClick={downloadTemplate}><Download aria-hidden="true" size={15} /> Download header template</button>

        <div
          className={`dropzone${file ? " dropzone--selected" : ""}`}
          onDragOver={(event) => event.preventDefault()}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") inputRef.current?.click(); }}
        >
          <input ref={inputRef} type="file" accept=".csv,text/csv" hidden onChange={(event: ChangeEvent<HTMLInputElement>) => chooseFile(event.target.files?.[0])} />
          {file ? (
            <><span className="dropzone__file"><FileSpreadsheet aria-hidden="true" size={24} /></span><strong>{file.name}</strong><small>{(file.size / 1024).toFixed(1)} KB · ready for validation</small><button type="button" aria-label="Remove selected file" onClick={(event) => { event.stopPropagation(); setFile(null); }}><X size={16} /></button></>
          ) : (
            <><UploadCloud aria-hidden="true" size={30} /><strong>Drop the camera CSV here</strong><small>or click to browse · maximum 10 MB</small></>
          )}
        </div>

        {fileError ? <div className="form-alert" role="alert"><AlertCircle aria-hidden="true" size={18} /><span><strong>Import not completed</strong>{fileError}</span></div> : null}
        {result ? <ImportSummary result={result} /> : null}

        <div className="import-contract">
          <strong>Required columns</strong>
          <code>camera_code · camera_name · department_code · district · latitude · longitude</code>
          <small>Use pipe-separated values inside <code>ai_capabilities</code> and <code>tags</code>; <code>storage_details</code> accepts a JSON object.</small>
        </div>
      </div>
      <footer className="modal__footer">
        <p>Rows with validation errors are reported by line number.</p>
        <button type="button" className="button button--quiet" onClick={close} disabled={uploading}>{result ? "Close" : "Cancel"}</button>
        {!result ? <button type="button" className="button button--primary" disabled={!file || uploading} onClick={upload}>{uploading ? <LoaderCircle className="spin" size={16} /> : <UploadCloud size={16} />}{uploading ? "Validating & importing…" : "Start import"}</button> : null}
      </footer>
    </Modal>
  );
}

function ImportSummary({ result }: { result: ImportResult }) {
  const rowErrors = result.results?.filter((row) => row.status === "failed") ?? [];
  const allFailed = (result.total_rows ?? 0) > 0 && result.failed === result.total_rows;
  const partial = !allFailed && (result.failed ?? 0) > 0;
  const ResultIcon = allFailed || partial ? AlertTriangle : CheckCircle2;
  const heading = allFailed
    ? "No cameras were imported"
    : result.replayed
      ? "Previous import result replayed safely"
      : partial
        ? "Import completed with validation issues"
        : result.message || "Import processing completed";
  return (
    <div className={`import-result${allFailed ? " import-result--error" : partial ? " import-result--warning" : ""}`} role={allFailed ? "alert" : "status"}>
      <ResultIcon aria-hidden="true" size={20} />
      <div>
        <strong>{heading}</strong>
        <div>
          {typeof result.total_rows === "number" ? <span><b>{result.total_rows}</b> rows</span> : null}
          {typeof result.created === "number" ? <span><b>{result.created}</b> created</span> : null}
          {typeof result.updated === "number" ? <span><b>{result.updated}</b> updated</span> : null}
          {typeof result.skipped === "number" ? <span><b>{result.skipped}</b> skipped</span> : null}
          {typeof result.failed === "number" ? <span className="import-result__failed"><b>{result.failed}</b> failed</span> : null}
          {result.replayed ? <span className="import-result__replayed">Idempotent replay</span> : null}
        </div>
        {rowErrors.length ? <details><summary>Review {rowErrors.length} validation issue(s)</summary><ul>{rowErrors.slice(0, 20).map((row) => <li key={`${row.row_number}-${row.camera_code ?? "unknown"}`}>Row {row.row_number}{row.camera_code ? ` (${row.camera_code})` : ""}: {row.error?.message ?? "Validation failed"}</li>)}</ul></details> : null}
        {!rowErrors.length && result.errors?.length ? <details><summary>Review {result.errors.length} validation issue(s)</summary><ul>{result.errors.slice(0, 20).map((issue, index) => <li key={`${issue.row}-${issue.field}-${index}`}>{issue.row ? `Row ${issue.row}: ` : ""}{issue.field ? `${issue.field} — ` : ""}{issue.message}</li>)}</ul></details> : null}
      </div>
    </div>
  );
}
