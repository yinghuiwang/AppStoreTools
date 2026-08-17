import { NotifyPlugin } from "tdesign-vue-next";

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

export function apiErrorMessage(err: ApiError): string {
  const d = err.detail;
  if (typeof d === "string") return d;
  if (d && typeof d === "object") {
    const o = d as Record<string, unknown>;
    if (typeof o.message === "string" && o.message) return o.message;
    if (typeof o.error === "string" && o.error) return o.error;
    if (typeof o.detail === "string" && o.detail) return o.detail;
  }
  return err.message;
}

function notifyGuard(err: ApiError, skip?: boolean) {
  if (skip) return;
  if (err.status === 403 || err.status === 409) {
    NotifyPlugin.error({ content: apiErrorMessage(err), duration: 6000 });
  }
}

function extractDetail(data: unknown): unknown {
  if (!data || typeof data !== "object") return data;
  const o = data as Record<string, unknown>;
  if (typeof o.message === "string" && o.message) return o;
  if ("detail" in o && o.detail != null && o.detail !== "") return o.detail;
  if ("error" in o) return o.error;
  return data;
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
    const err = new ApiError(res.status, extractDetail(data));
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
