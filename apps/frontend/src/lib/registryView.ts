import type {
  Camera,
  CameraFilterOptions,
  CameraFilters,
  CameraGeoFeature,
  CameraGeoJson,
  HealthStatus,
} from "../types/registry";

export const emptyCameraFilters: CameraFilters = {
  search: "",
  department_id: "",
  district: "",
  city: "",
  vendor: "",
  vms: "",
  status: "",
  health: "",
  ai_capability: "",
};

export const emptyFilterOptions: CameraFilterOptions = {
  districts: [],
  cities: [],
  vendors: [],
  vms: [],
  ai_capabilities: [],
  camera_types: [],
  connectivity_types: [],
  stream_protocols: [],
};

export const geoFeatureId = (feature: CameraGeoFeature): string =>
  feature.properties.camera_uuid
  ?? feature.properties.id
  ?? feature.id
  ?? feature.properties.camera_code;

export const geoFeatureHealth = (feature: CameraGeoFeature): HealthStatus =>
  feature.properties.health_status ?? feature.properties.health ?? "unknown";

const uniqueSorted = (values: Array<string | null | undefined>): string[] =>
  [...new Set(values.map((value) => value?.trim()).filter((value): value is string => Boolean(value)))]
    .sort((left, right) => left.localeCompare(right));

export function deriveFilterOptions(
  geoJson: CameraGeoJson | null,
  cameras: Camera[],
): CameraFilterOptions {
  const properties = (geoJson?.features ?? []).map((feature) => feature.properties);
  const arrayValues = (key: "ai_capabilities") => properties.flatMap((property) => property[key] ?? []);
  return {
    districts: uniqueSorted([...properties.map((item) => item.district), ...cameras.map((item) => item.district)]),
    cities: uniqueSorted([...properties.map((item) => item.city), ...cameras.map((item) => item.city)]),
    vendors: uniqueSorted([...properties.map((item) => item.vendor), ...cameras.map((item) => item.vendor)]),
    vms: uniqueSorted([...properties.map((item) => item.vms), ...cameras.map((item) => item.vms)]),
    ai_capabilities: uniqueSorted([...arrayValues("ai_capabilities"), ...cameras.flatMap((item) => item.ai_capabilities)]),
    camera_types: uniqueSorted([...properties.map((item) => item.camera_type), ...cameras.map((item) => item.camera_type)]),
    connectivity_types: uniqueSorted([...properties.map((item) => item.connectivity_type), ...cameras.map((item) => item.connectivity_type)]),
    stream_protocols: uniqueSorted([...properties.map((item) => item.stream_protocol), ...cameras.map((item) => item.stream_protocol)]),
  };
}

export function mergeFilterOptions(
  canonical: CameraFilterOptions | null,
  fallback: CameraFilterOptions,
): CameraFilterOptions {
  if (!canonical) return fallback;
  return Object.fromEntries(
    Object.keys(emptyFilterOptions).map((key) => {
      const optionKey = key as keyof CameraFilterOptions;
      return [optionKey, canonical[optionKey]?.length ? canonical[optionKey] : fallback[optionKey]];
    }),
  ) as unknown as CameraFilterOptions;
}
