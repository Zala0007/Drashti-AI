import { Filter, RotateCcw, Search, X } from "lucide-react";
import { titleCase } from "../lib/format";
import { emptyCameraFilters } from "../lib/registryView";
import {
  aiCapabilityOptions,
  cameraStatuses,
  healthStatuses,
  type CameraFilters as Filters,
  type CameraFilterOptions,
  type Department,
} from "../types/registry";

interface CameraFiltersProps {
  value: Filters;
  departments: Department[];
  onChange: (next: Filters) => void;
  resultCount?: number;
  options?: CameraFilterOptions;
  advanced?: boolean;
}

const optionList = (values: string[], placeholder: string) => (
  <>
    <option value="">{placeholder}</option>
    {values.map((item) => <option key={item} value={item}>{titleCase(item)}</option>)}
  </>
);

export function CameraFilters({
  value,
  departments,
  onChange,
  resultCount,
  options,
  advanced = false,
}: CameraFiltersProps) {
  const update = <K extends keyof Filters>(field: K, next: Filters[K]) =>
    onChange({ ...value, [field]: next });
  const activeCount = Object.values(value).filter(Boolean).length;

  return (
    <div className="filters">
      <label className="search-control">
        <span className="sr-only">Search cameras</span>
        <Search aria-hidden="true" size={18} />
        <input
          value={value.search}
          onChange={(event) => update("search", event.target.value)}
          placeholder="Search camera ID, name, location or department"
          type="search"
        />
        {value.search ? (
          <button type="button" aria-label="Clear search" onClick={() => update("search", "")}>
            <X aria-hidden="true" size={15} />
          </button>
        ) : null}
        {typeof resultCount === "number" ? <small>{resultCount.toLocaleString("en-IN")}</small> : null}
      </label>

      <div className="filter-row" aria-label="Camera filters">
        <span className="filter-row__label"><Filter aria-hidden="true" size={15} /> Filters</span>
        <select
          aria-label="Department"
          value={value.department_id}
          onChange={(event) => update("department_id", event.target.value)}
        >
          <option value="">All departments</option>
          {departments.map((department) => (
            <option key={department.id} value={department.id}>{department.name}</option>
          ))}
        </select>
        {options?.districts.length ? (
          <select aria-label="District" value={value.district} onChange={(event) => update("district", event.target.value)}>
            {optionList(options.districts, "All districts")}
          </select>
        ) : (
          <input aria-label="District" value={value.district} onChange={(event) => update("district", event.target.value)} placeholder="Any district" />
        )}
        {advanced ? (
          <>
            <select aria-label="City" value={value.city} onChange={(event) => update("city", event.target.value)}>
              {optionList(options?.cities ?? [], "All cities")}
            </select>
            <select aria-label="Vendor" value={value.vendor} onChange={(event) => update("vendor", event.target.value)}>
              {optionList(options?.vendors ?? [], "All vendors")}
            </select>
            <select aria-label="VMS" value={value.vms} onChange={(event) => update("vms", event.target.value)}>
              {optionList(options?.vms ?? [], "All VMS")}
            </select>
          </>
        ) : null}
        <select
          aria-label="Lifecycle status"
          value={value.status}
          onChange={(event) => update("status", event.target.value as Filters["status"])}
        >
          <option value="">Any lifecycle</option>
          {cameraStatuses.map((status) => <option key={status} value={status}>{titleCase(status)}</option>)}
        </select>
        <select
          aria-label="Health status"
          value={value.health}
          onChange={(event) => update("health", event.target.value as Filters["health"])}
        >
          <option value="">Any health</option>
          {healthStatuses.map((status) => <option key={status} value={status}>{titleCase(status)}</option>)}
        </select>
        <select
          aria-label="AI capability"
          value={value.ai_capability}
          onChange={(event) => update("ai_capability", event.target.value)}
        >
          <option value="">Any analytics</option>
          {(options?.ai_capabilities.length ? options.ai_capabilities : aiCapabilityOptions).map((capability) => (
            <option key={capability} value={capability}>{titleCase(capability)}</option>
          ))}
        </select>
        {activeCount > 0 ? (
          <button className="filter-reset" type="button" onClick={() => onChange(emptyCameraFilters)}>
            <RotateCcw aria-hidden="true" size={14} /> Reset {activeCount}
          </button>
        ) : null}
      </div>
    </div>
  );
}
