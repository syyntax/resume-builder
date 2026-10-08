import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, setCsrfToken, setUnauthorizedHandler } from "./client";

function mockFetch(status: number, body?: unknown) {
  const fetchMock = vi.fn(async () =>
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: body === undefined ? {} : { "content-type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
  setUnauthorizedHandler(null);
});

describe("api client", () => {
  it("sends the CSRF token on writes but not reads", async () => {
    setCsrfToken("tok-123");
    const fetchMock = mockFetch(200, { ok: true });
    await api("GET", "/api/x");
    await api("POST", "/api/x", { json: { a: 1 } });
    const [getInit, postInit] = fetchMock.mock.calls.map((call) => (call as unknown as [string, RequestInit])[1]);
    expect((getInit?.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
    const postHeaders = postInit?.headers as Record<string, string>;
    expect(postHeaders["X-CSRF-Token"]).toBe("tok-123");
    expect(postHeaders["Content-Type"]).toBe("application/json");
    expect(postInit?.body).toBe('{"a":1}');
    expect(postInit?.credentials).toBe("same-origin");
  });

  it("turns error responses into ApiError with field issues", async () => {
    mockFetch(422, { detail: "Choose a stronger password.", errors: [{ field: "password", message: "too common" }] });
    const error = await api("POST", "/api/auth/register").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(422);
    expect((error as ApiError).message).toBe("Choose a stronger password.");
    expect((error as ApiError).fieldError("password")).toBe("too common");
  });

  it("returns undefined for 204 responses", async () => {
    mockFetch(204);
    await expect(api("DELETE", "/api/x")).resolves.toBeUndefined();
  });

  it("reports expired sessions, except on auth endpoints", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    mockFetch(401, { detail: "You're not signed in." });
    await api("GET", "/api/master-resumes").catch(() => undefined);
    await api("GET", "/api/auth/me").catch(() => undefined);
    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenLastCalledWith("signed-out");
  });

  it("tells an unfinished sign-in from an ended one, and exposes error codes", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    mockFetch(403, { detail: "Set up two-step verification to continue.", code: "mfa_enrollment_required" });
    const error = await api("GET", "/api/master-resumes").catch((e: unknown) => e);
    expect((error as ApiError).code).toBe("mfa_enrollment_required");
    expect(handler).toHaveBeenLastCalledWith("incomplete");
    mockFetch(401, { detail: "Enter the code.", code: "mfa_required" });
    await api("GET", "/api/master-resumes").catch(() => undefined);
    expect(handler).toHaveBeenLastCalledWith("incomplete");
    mockFetch(403, { detail: "This action is limited to admins." });
    await api("GET", "/api/admin/users").catch(() => undefined);
    expect(handler).toHaveBeenCalledTimes(2);  // an ordinary 403 isn't about signing in
  });
});
