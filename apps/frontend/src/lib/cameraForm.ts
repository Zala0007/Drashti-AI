import type { AiCapability, CameraCreate, CameraStatus, CameraType, ConnectivityType, OwnershipType, StreamProtocol } from "../types/registry";

export interface CameraFormState {
  camera_code: string;
  camera_name: string;
  department_id: string;
  district: string;
  city: string;
  location_description: string;
  latitude: string;
  longitude: string;
  camera_type: CameraType;
  status: CameraStatus;
  vendor: string;
  model: string;
  vms: string;
  connectivity_type: ConnectivityType;
  stream_protocol: StreamProtocol;
  rtsp_capable: boolean;
  onvif_capable: boolean;
  ai_enabled: boolean;
  ai_capabilities: AiCapability[];
  storage_type: string;
  retention_days: string;
  ownership: OwnershipType;
  owner_name: string;
  is_public_facing: boolean;
  tags: string;
}

export type CameraFormErrors = Partial<Record<keyof CameraFormState, string>>;

export const initialCameraForm: CameraFormState = {
  camera_code: "",
  camera_name: "",
  department_id: "",
  district: "",
  city: "",
  location_description: "",
  latitude: "",
  longitude: "",
  camera_type: "fixed",
  status: "active",
  vendor: "",
  model: "",
  vms: "",
  connectivity_type: "unknown",
  stream_protocol: "rtsp",
  rtsp_capable: true,
  onvif_capable: false,
  ai_enabled: false,
  ai_capabilities: [],
  storage_type: "",
  retention_days: "",
  ownership: "government",
  owner_name: "",
  is_public_facing: true,
  tags: "",
};

export function validateCameraForm(form: CameraFormState): CameraFormErrors {
  const errors: CameraFormErrors = {};
  if (!/^[A-Z0-9][A-Z0-9_.:/-]{1,63}$/.test(form.camera_code.trim().toUpperCase())) {
    errors.camera_code = "Use 2–64 letters, numbers, '.', '_', ':', '/' or '-'.";
  }
  if (form.camera_name.trim().length < 2) errors.camera_name = "Enter a descriptive camera name.";
  if (!form.department_id) errors.department_id = "Select the responsible department.";
  if (form.district.trim().length < 2) errors.district = "District is required.";
  const latitude = Number(form.latitude);
  if (!form.latitude.trim() || !Number.isFinite(latitude) || latitude < -90 || latitude > 90) {
    errors.latitude = "Latitude must be between -90 and 90.";
  }
  const longitude = Number(form.longitude);
  if (!form.longitude.trim() || !Number.isFinite(longitude) || longitude < -180 || longitude > 180) {
    errors.longitude = "Longitude must be between -180 and 180.";
  }
  if (form.retention_days) {
    const days = Number(form.retention_days);
    if (!Number.isInteger(days) || days < 0 || days > 3650) {
      errors.retention_days = "Retention must be a whole number from 0 to 3650.";
    }
  }
  if (form.ai_enabled && form.ai_capabilities.length === 0) {
    errors.ai_capabilities = "Select at least one enabled analytic.";
  }
  return errors;
}

export function toCameraCreate(form: CameraFormState): CameraCreate {
  const optional = (value: string): string | undefined => value.trim() || undefined;
  return {
    camera_code: form.camera_code.trim().toUpperCase(),
    camera_name: form.camera_name.trim(),
    department_id: form.department_id,
    district: form.district.trim(),
    city: optional(form.city),
    location_description: optional(form.location_description),
    latitude: Number(form.latitude),
    longitude: Number(form.longitude),
    camera_type: form.camera_type,
    vendor: optional(form.vendor),
    model: optional(form.model),
    vms: optional(form.vms),
    connectivity_type: form.connectivity_type,
    stream_protocol: form.stream_protocol,
    rtsp_capable: form.rtsp_capable,
    onvif_capable: form.onvif_capable,
    status: form.status,
    ai_capabilities: form.ai_enabled ? form.ai_capabilities : [],
    storage_details: {
      ...(form.storage_type.trim() ? { type: form.storage_type.trim() } : {}),
      ...(form.retention_days ? { retention_days: Number(form.retention_days) } : {}),
    },
    ownership: form.ownership,
    owner_name: optional(form.owner_name),
    is_public_facing: form.is_public_facing,
    tags: form.tags.split(",").map((tag) => tag.trim()).filter(Boolean),
  };
}
