import { AlertTriangle, Inbox, LoaderCircle, RefreshCw } from "lucide-react";

export function LoadingState({ label = "Loading registry data…" }: { label?: string }) {
  return (
    <div className="state-panel" role="status">
      <LoaderCircle className="spin" aria-hidden="true" size={26} />
      <p>{label}</p>
    </div>
  );
}

export function EmptyState({
  title = "No cameras found",
  detail = "Try changing the filters or onboard the first camera.",
}: {
  title?: string;
  detail?: string;
}) {
  return (
    <div className="state-panel">
      <span className="state-panel__icon"><Inbox aria-hidden="true" size={25} /></span>
      <strong>{title}</strong>
      <p>{detail}</p>
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
  compact = false,
}: {
  message: string;
  onRetry: () => void;
  compact?: boolean;
}) {
  return (
    <div className={`state-panel state-panel--error${compact ? " state-panel--compact" : ""}`} role="alert">
      <AlertTriangle aria-hidden="true" size={22} />
      <div>
        <strong>Unable to load registry data</strong>
        <p>{message}</p>
      </div>
      <button className="button button--quiet" type="button" onClick={onRetry}>
        <RefreshCw aria-hidden="true" size={15} /> Retry
      </button>
    </div>
  );
}
