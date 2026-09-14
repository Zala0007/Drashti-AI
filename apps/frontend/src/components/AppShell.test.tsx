import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "./AppShell";

const props = { apiConnected: true, activePage: "command" as const, onNavigate: vi.fn(), statistics: null, federationStatistics: null, federationConnected: null };

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
  document.documentElement.style.colorScheme = "";
  vi.unstubAllGlobals();
});

describe("workspace preferences and navigation", () => {
  it("restores a saved theme and persists a change with matching native controls", () => {
    localStorage.setItem("drishti-theme", "dark");
    render(<AppShell {...props}>Workspace</AppShell>);
    expect(document.documentElement.dataset.theme).toBe("dark");
    fireEvent.click(screen.getAllByRole("button", { name: "Switch to light theme" })[0]);
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.style.colorScheme).toBe("light");
    expect(localStorage.getItem("drishti-theme")).toBe("light");
  });

  it("uses the system theme when no preference has been saved", () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true })));
    render(<AppShell {...props}>Workspace</AppShell>);
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("closes mobile navigation with Escape and supports keyboard skip navigation", () => {
    render(<AppShell {...props}>Workspace</AppShell>);
    const toggle = screen.getByRole("button", { name: "Toggle navigation" });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(screen.getByRole("link", { name: "Skip to workspace" }));
    expect(screen.getByRole("main")).toHaveFocus();
  });
});
