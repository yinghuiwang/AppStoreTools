export const LISTING_THUMB_WIDTH = 320;

export function listingOriginalUrl(thumbUrl: string): string {
  const raw = (thumbUrl || "").trim();
  if (!raw) return "";
  const q = raw.indexOf("?");
  if (q < 0) return raw;
  const path = raw.slice(0, q);
  const params = new URLSearchParams(raw.slice(q + 1));
  params.delete("w");
  const search = params.toString();
  return search ? `${path}?${search}` : path;
}

export function withThumbWidth(url: string, width = LISTING_THUMB_WIDTH): string {
  const raw = (url || "").trim();
  if (!raw) return "";
  const q = raw.indexOf("?");
  const path = q < 0 ? raw : raw.slice(0, q);
  const params = new URLSearchParams(q < 0 ? "" : raw.slice(q + 1));
  params.set("w", String(width));
  return `${path}?${params.toString()}`;
}
