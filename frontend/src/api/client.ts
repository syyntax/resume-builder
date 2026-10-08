/** Thin fetch wrapper: same-origin cookies, the CSRF header on writes, and typed errors. */

export interface FieldIssue {
  field?: string;
  path?: string;
  message: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly errors: FieldIssue[];
  readonly body: unknown;

  constructor(status: number, message: string, errors: FieldIssue[] = [], body: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.errors = errors;
    this.body = body;
  }

  fieldError(field: string): string | undefined {
    return this.errors.find((e) => e.field === field)?.message;
  }
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface RequestOptions {
  json?: unknown;
  body?: BodyInit;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

let csrfToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

/** Headers for a write made outside `api()` (for example a keepalive save while the page closes). */
export function csrfHeaders(): Record<string, string> {
  return csrfToken ? { "X-CSRF-Token": csrfToken } : {};
}

/** Called when a request comes back 401 (the session expired or was revoked elsewhere). */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

export async function api<T>(method: Method, path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  let body = options.body;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  }
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;

  let response: Response;
  try {
    response = await fetch(path, { method, headers, body, credentials: "same-origin", signal: options.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
  }

  if (response.status === 401 && !path.startsWith("/api/auth/")) onUnauthorized?.();
  if (response.status === 204) return undefined as T;

  const isJson = response.headers.get("content-type")?.includes("json") ?? false;
  const data: unknown = isJson ? await response.json().catch(() => null) : null;
  if (!response.ok) {
    const payload = data as { detail?: unknown; errors?: unknown } | null;
    const message =
      typeof payload?.detail === "string" ? payload.detail : `Something went wrong (HTTP ${response.status}).`;
    const errors = Array.isArray(payload?.errors) ? (payload.errors as FieldIssue[]) : [];
    throw new ApiError(response.status, message, errors, data);
  }
  return data as T;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}
