import { ElNotification } from "element-plus";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

type Extra = { skipNotify?: boolean };

function notifyGuard(err: ApiError, skip?: boolean) {
  if (skip) return;
  if (err.status === 403 || err.status === 409) {
    const msg =
      typeof err.detail === "string"
        ? err.detail
        : JSON.stringify((err.detail as { detail?: unknown })?.detail ?? err.detail);
    ElNotification({ type: "error", message: msg, duration: 6000 });
  }
}

async function parse(res: Response, skipNotify?: boolean): Promise<unknown> {
  const text = await res.text();
  let data: unknown = text;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail =
      data && typeof data === "object" && "detail" in data
        ? (data as { detail: unknown }).detail
        : data && typeof data === "object" && "error" in data
          ? (data as { error: unknown }).error
          : data;
    const err = new ApiError(res.status, detail);
    notifyGuard(err, skipNotify);
    throw err;
  }
  return data;
}

export async function httpJson<T>(url: string, init: RequestInit & Extra = {}): Promise<T> {
  const { skipNotify, ...rest } = init;
  const headers = new Headers(rest.headers);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (rest.body && !(rest.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(url, { ...rest, headers, credentials: "same-origin" });
  return (await parse(res, skipNotify)) as T;
}

export async function httpForm<T>(
  url: string,
  body: URLSearchParams | FormData,
  extra: Extra = {},
): Promise<T> {
  const headers = new Headers({ Accept: "application/json" });
  if (body instanceof URLSearchParams) {
    headers.set("Content-Type", "application/x-www-form-urlencoded");
  }
  const res = await fetch(url, {
    method: "POST",
    body,
    headers,
    credentials: "same-origin",
  });
  return (await parse(res, extra.skipNotify)) as T;
}
