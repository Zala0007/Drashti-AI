import { BrainCircuit, ChevronLeft, ChevronRight, MapPin, Radio, Rows3 } from "lucide-react";
import { cameraHealth, cameraId, departmentLabel, relativeTime, titleCase } from "../lib/format";
import type { Camera, Page } from "../types/registry";
import { EmptyState, ErrorState, LoadingState } from "./Feedback";
import { StatusBadge } from "./StatusBadge";

interface CameraTableProps {
  data: Page<Camera> | null;
  loading: boolean;
  error: string | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onRetry: () => void;
  onPageChange: (page: number) => void;
}

export function CameraTable({
  data,
  loading,
  error,
  selectedId,
  onSelect,
  onRetry,
  onPageChange,
}: CameraTableProps) {
  if (loading && !data) return <LoadingState label="Loading camera inventory…" />;
  if (error && !data) return <ErrorState message={error} onRetry={onRetry} />;
  if (!data || data.items.length === 0) return <EmptyState />;

  return (
    <>
      {error ? <ErrorState message={error} onRetry={onRetry} compact /> : null}
      <div className={`table-wrap${loading ? " table-wrap--refreshing" : ""}`}>
        <table className="camera-table">
          <thead>
            <tr>
              <th>Camera identity</th>
              <th>Jurisdiction</th>
              <th>Integration</th>
              <th>AI capability</th>
              <th>Operational health</th>
              <th><span className="sr-only">View details</span></th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((camera) => {
              const id = cameraId(camera);
              const health = cameraHealth(camera);
              return (
                <tr
                  className={selectedId === id ? "camera-table__row--selected" : undefined}
                  key={id}
                  onClick={() => onSelect(id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") onSelect(id);
                  }}
                  tabIndex={0}
                >
                  <td>
                    <div className="camera-identity">
                      <span className={`camera-identity__glyph camera-identity__glyph--${health}`}>
                        <Radio aria-hidden="true" size={16} />
                      </span>
                      <span>
                        <strong>{camera.camera_name}</strong>
                        <small>{camera.camera_code}</small>
                      </span>
                    </div>
                  </td>
                  <td>
                    <span className="cell-primary">{departmentLabel(camera)}</span>
                    <small className="cell-secondary"><MapPin aria-hidden="true" size={12} /> {camera.city ? `${camera.city}, ` : ""}{camera.district}</small>
                  </td>
                  <td>
                    <span className="cell-primary">{titleCase(camera.camera_type)}</span>
                    <small className="cell-secondary">{titleCase(camera.stream_protocol)} · {titleCase(camera.connectivity_type)}</small>
                  </td>
                  <td>
                    {camera.ai_enabled || camera.ai_capabilities?.length ? (
                      <div className="capability-cell">
                        <BrainCircuit aria-hidden="true" size={14} />
                        <span>{camera.ai_capabilities?.slice(0, 2).map(titleCase).join(", ") || "Enabled"}</span>
                        {(camera.ai_capabilities?.length ?? 0) > 2 ? <small>+{camera.ai_capabilities.length - 2}</small> : null}
                      </div>
                    ) : <span className="muted">Not enabled</span>}
                  </td>
                  <td>
                    <StatusBadge value={health} pulse />
                    <small className="heartbeat">{relativeTime(camera.last_heartbeat)}</small>
                  </td>
                  <td><ChevronRight aria-hidden="true" className="row-chevron" size={18} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <footer className="table-pagination">
        <span><Rows3 aria-hidden="true" size={14} /> Showing {((data.page - 1) * data.page_size) + 1}–{Math.min(data.page * data.page_size, data.total)} of {data.total.toLocaleString("en-IN")}</span>
        <div>
          <button
            type="button"
            aria-label="Previous page"
            disabled={data.page <= 1 || loading}
            onClick={() => onPageChange(data.page - 1)}
          ><ChevronLeft aria-hidden="true" size={16} /></button>
          <span>Page <strong>{data.page}</strong> / {Math.max(data.pages, 1)}</span>
          <button
            type="button"
            aria-label="Next page"
            disabled={data.page >= data.pages || loading}
            onClick={() => onPageChange(data.page + 1)}
          ><ChevronRight aria-hidden="true" size={16} /></button>
        </div>
      </footer>
    </>
  );
}
