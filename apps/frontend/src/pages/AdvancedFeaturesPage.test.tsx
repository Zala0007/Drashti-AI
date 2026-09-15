import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AdvancedFeaturesPage } from "./AdvancedFeaturesPage";

const response = (body: unknown) => new Response(JSON.stringify(body), {
  status: 200, headers: { "Content-Type": "application/json" },
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("enables the selected module for only the selected camera", async () => {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("/cameras?")) return response({ items: [
      { id: "camera-one", camera_name: "North gate", camera_code: "N1" },
      { id: "camera-two", camera_name: "South gate", camera_code: "S1" },
    ] });
    if (init?.method === "PUT") return response(JSON.parse(String(init.body)));
    return response({ rules: [], events: [], live: null });
  });
  vi.stubGlobal("fetch", fetcher);
  render(<AdvancedFeaturesPage />);
  await screen.findByRole("option", { name: "North gate · N1" });
  fireEvent.change(screen.getByLabelText("Camera / stream"), { target: { value: "camera-one" } });
  fireEvent.click(screen.getByRole("button", { name: /Object Path/ }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Enable on this feed" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Enable on this feed" }));
  await screen.findByText("Module saved and enabled for this camera.");
  const writes = fetcher.mock.calls.filter(([, init]) => init?.method === "PUT");
  expect(writes).toHaveLength(1);
  expect(writes[0][0]).toContain("/streams/camera-one/spatial");
  expect(JSON.parse(String(writes[0][1]?.body))).toMatchObject({ feature: "object_path", enabled: true });
  fireEvent.change(screen.getByLabelText("Camera / stream"), { target: { value: "camera-two" } });
  expect(screen.getByRole("button", { name: /Border Line/ })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "Enable on this feed" })).toBeDisabled();
});

it("normalizes a border drawing against the displayed feed", async () => {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("/cameras?")) return response({ items: [{ id: "one", camera_name: "Gate", camera_code: "G" }] });
    if (init?.method === "PUT") return response(JSON.parse(String(init.body)));
    return response({ rules: [], events: [], live: null });
  });
  vi.stubGlobal("fetch", fetcher);
  render(<AdvancedFeaturesPage />);
  await screen.findByRole("option", { name: "Gate · G" });
  fireEvent.change(screen.getByLabelText("Camera / stream"), { target: { value: "one" } });
  const image = screen.getByAltText("Selected camera live feed");
  fireEvent.load(image);
  const drawing = screen.getByRole("img", { name: "Draw the module area on the camera feed" });
  vi.spyOn(drawing, "getBoundingClientRect").mockReturnValue({ left: 10, top: 20, width: 400, height: 200 } as DOMRect);
  fireEvent.click(drawing, { clientX: 110, clientY: 120 });
  fireEvent.click(drawing, { clientX: 310, clientY: 120 });
  await waitFor(() => expect(screen.getByRole("button", { name: "Enable on this feed" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Enable on this feed" }));
  await screen.findByText("Module saved and enabled for this camera.");
  const write = fetcher.mock.calls.find(([, init]) => init?.method === "PUT");
  expect(JSON.parse(String(write?.[1]?.body)).points).toEqual([{ x: .25, y: .5 }, { x: .75, y: .5 }]);
});
