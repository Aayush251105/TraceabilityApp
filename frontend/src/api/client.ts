/** Thin fetch wrapper for the Tracelight API (same origin; Vite proxies /api in development). */

export class ApiError extends Error {
  status: number;
  /** review item keys the server named (409 on review completion) */
  keys: string[];

  constructor(status: number, message: string, keys: string[] = []) {
    super(message);
    this.status = status;
    this.keys = keys;
  }
}

async function parse<T>(res: Response): Promise<T> {
  const text = await res.text();
  let body: any = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!res.ok) {
    const detail = body?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: any) => d.msg).join("; ")
          : `${res.status} ${res.statusText}`;
    throw new ApiError(res.status, message, body?.keys ?? []);
  }
  return body as T;
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(0, "Cannot reach the Tracelight server. Is it running (python -m tracelight.api)?");
  }
  return parse<T>(res);
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  json: <T>(method: "POST" | "PUT" | "DELETE", path: string, body?: unknown) =>
    request<T>(path, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  form: <T>(path: string, form: FormData) => request<T>(path, { method: "POST", body: form }),
};
