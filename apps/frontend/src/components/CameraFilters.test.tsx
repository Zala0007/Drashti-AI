import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CameraFilters as Filters } from "../types/registry";
import { CameraFilters } from "./CameraFilters";

const filters: Filters = {
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

describe("CameraFilters", () => {
  it("emits a server-side search filter", () => {
    const onChange = vi.fn();
    render(
      <CameraFilters
        value={filters}
        departments={[{ id: "dept-1", code: "HOME", name: "Home Department" }]}
        onChange={onChange}
        resultCount={42}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText("Search camera ID, name, location or department"), {
      target: { value: "Ashram" },
    });
    expect(onChange).toHaveBeenCalledWith({ ...filters, search: "Ashram" });
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Home Department" })).toBeInTheDocument();
  });
});
