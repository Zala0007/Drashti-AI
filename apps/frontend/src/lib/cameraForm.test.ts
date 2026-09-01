import { describe, expect, it } from "vitest";
import { initialCameraForm, toCameraCreate, validateCameraForm } from "./cameraForm";

describe("camera onboarding contract", () => {
  it("rejects invalid identity, coordinates and enabled AI without a capability", () => {
    const errors = validateCameraForm({
      ...initialCameraForm,
      camera_code: "?",
      camera_name: "x",
      district: "",
      latitude: "91",
      longitude: "not-a-number",
      ai_enabled: true,
    });

    expect(errors).toMatchObject({
      camera_code: expect.any(String),
      camera_name: expect.any(String),
      department_id: expect.any(String),
      district: expect.any(String),
      latitude: expect.any(String),
      longitude: expect.any(String),
      ai_capabilities: expect.any(String),
    });
  });

  it("emits strict backend names without credential-bearing fields", () => {
    const payload = toCameraCreate({
      ...initialCameraForm,
      camera_code: " gj-ahd-01 ",
      camera_name: " Ashram Road North ",
      department_id: "eddb7a5d-0b75-43a0-983f-d941639f741f",
      district: " Ahmedabad ",
      latitude: "23.0225",
      longitude: "72.5714",
      vendor: "Acme Vision",
      vms: "Department VMS",
      rtsp_capable: true,
      onvif_capable: true,
      ai_enabled: true,
      ai_capabilities: ["anpr", "vehicle_detection"],
      storage_type: "department_nvr",
      retention_days: "15",
      tags: "traffic, northbound, traffic",
    });

    expect(payload).toMatchObject({
      camera_code: "GJ-AHD-01",
      vendor: "Acme Vision",
      vms: "Department VMS",
      rtsp_capable: true,
      onvif_capable: true,
      storage_details: { type: "department_nvr", retention_days: 15 },
      ai_capabilities: ["anpr", "vehicle_detection"],
    });
    expect(payload).not.toHaveProperty("camera_vendor");
    expect(payload).not.toHaveProperty("stream_reference");
    expect(payload).not.toHaveProperty("credential_reference");
    expect(payload).not.toHaveProperty("ai_enabled");
  });
});
