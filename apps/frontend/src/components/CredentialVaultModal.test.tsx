import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { CredentialVaultModal } from "./CredentialVaultModal";

const jsonResponse = (body: unknown): Response => new Response(JSON.stringify(body), {
  status: 200,
  headers: { "Content-Type": "application/json" },
});

afterEach(() => vi.unstubAllGlobals());

it("writes credentials once, clears browser fields, and renders only safe metadata", async () => {
  const department = { id: "dept-1", code: "home", name: "Home Department" };
  let profiles: unknown[] = [];
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url.includes("/departments")) return Promise.resolve(jsonResponse([department]));
    if (url.includes("/federation/credentials") && method === "POST") {
      const profile = {
        id: "credential-1",
        reference: "credential-profile:credential-1",
        department,
        name: "District camera account",
        auth_type: "username_password",
        enabled: true,
        has_username: true,
        has_secret: true,
        encryption_key_id: "key-v1",
        created_by: "operator",
        last_used_at: null,
        created_at: "2026-08-27T10:00:00Z",
        updated_at: "2026-08-27T10:00:00Z",
      };
      profiles = [profile];
      return Promise.resolve(jsonResponse(profile));
    }
    if (url.includes("/federation/credentials")) {
      return Promise.resolve(jsonResponse({ items: profiles, total: profiles.length, page: 1, page_size: 200, pages: profiles.length ? 1 : 0 }));
    }
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<CredentialVaultModal open onClose={() => undefined} />);
  expect(await screen.findByText("No credential profiles created yet.")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Owning department *"), { target: { value: department.id } });
  fireEvent.change(screen.getByLabelText("Profile name *"), { target: { value: "District camera account" } });
  fireEvent.change(screen.getByLabelText("Device username *"), { target: { value: "camera-user-canary" } });
  fireEvent.change(screen.getByLabelText("Device password *"), { target: { value: "camera-password-canary" } });
  fireEvent.click(screen.getByRole("button", { name: "Encrypt credential profile" }));

  expect(await screen.findByText("District camera account")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByLabelText("Device username *")).toHaveValue(""));
  expect(screen.getByLabelText("Device password *")).toHaveValue("");
  expect(screen.queryByText("camera-user-canary")).not.toBeInTheDocument();
  expect(screen.queryByText("camera-password-canary")).not.toBeInTheDocument();

  const createCall = fetchMock.mock.calls.find(([input, init]) =>
    String(input).includes("/federation/credentials") && init?.method === "POST");
  expect(JSON.parse(String(createCall?.[1]?.body))).toEqual({
    department_id: department.id,
    name: "District camera account",
    username: "camera-user-canary",
    password: "camera-password-canary",
    enabled: true,
  });
});
