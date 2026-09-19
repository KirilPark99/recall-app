// Типизированный API-клиент: CSRF, 401→login, единые ошибки.
export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

let csrfToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn;
}

export async function api<T = unknown>(
  path: string,
  options: { method?: string; body?: unknown; formData?: FormData } = {}
): Promise<T> {
  const method = options.method ?? (options.body || options.formData ? "POST" : "GET");
  const headers: Record<string, string> = {};

  if (!csrfToken && method !== "GET" && path !== "/auth/csrf") {
    try {
      const csrfRes = await fetch("/api/v1/auth/csrf", { credentials: "same-origin" });
      if (csrfRes.ok) {
        const csrfData = (await csrfRes.json()) as { csrf_token?: string };
        if (csrfData.csrf_token) {
          csrfToken = csrfData.csrf_token;
        }
      }
    } catch {
      // ignore
    }
  }

  if (csrfToken && method !== "GET") {
    headers["X-CSRF-Token"] = csrfToken;
  }
  let body: BodyInit | undefined;
  if (options.formData) {
    body = options.formData;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  let res = await fetch(`/api/v1${path}`, { method, headers, body, credentials: "same-origin" });

  let data = await res.json().catch(() => ({}));

  // Auto-retry on CSRF_INVALID with fresh token
  if (!res.ok && res.status === 403 && (data as { error?: { code?: string } })?.error?.code === "CSRF_INVALID" && method !== "GET") {
    try {
      const csrfRes = await fetch("/api/v1/auth/csrf", { credentials: "same-origin" });
      if (csrfRes.ok) {
        const csrfData = (await csrfRes.json()) as { csrf_token?: string };
        if (csrfData.csrf_token) {
          csrfToken = csrfData.csrf_token;
          headers["X-CSRF-Token"] = csrfToken;
          res = await fetch(`/api/v1${path}`, { method, headers, body, credentials: "same-origin" });
          data = await res.json().catch(() => ({}));
        }
      }
    } catch {
      // ignore
    }
  }

  const isAuthEntrypoint = path === "/auth/login" || path === "/auth/register" || path === "/auth/csrf";
  if (res.status === 401) {
    csrfToken = null;
    if (onUnauthorized && !isAuthEntrypoint) onUnauthorized();
  }
  if (!res.ok) {
    const err = (data as { error?: { code?: string; message?: string; details?: Record<string, unknown> } }).error;
    throw new ApiError(res.status, err?.code ?? "UNKNOWN", err?.message ?? "Ошибка запроса", err?.details ?? {});
  }
  return data as T;
}
