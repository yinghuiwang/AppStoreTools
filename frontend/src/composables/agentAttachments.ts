export const AGENT_ATTACH_MAX = 8;
export const AGENT_ATTACH_MAX_BYTES = 10 * 1024 * 1024;
export const AGENT_ATTACH_MAX_TOTAL_BYTES = 32 * 1024 * 1024;
export const AGENT_ATTACH_ACCEPT =
  ".txt,.md,.json,.csv,.xml,.html,.htm,.yaml,.yml,.toml,.log,.plist,.strings,.js,.ts,.tsx,.jsx,.py,.swift,.sh,.rb,.go,.rs,.java,.kt,.css,.scss,.png,.jpg,.jpeg,.webp,.gif";

const ALLOWED_SUFFIXES = new Set(
  AGENT_ATTACH_ACCEPT.split(",").map((item) => item.trim().toLowerCase()),
);

export type AgentAttachmentKind = "path" | "inline";

export type AgentAttachmentPayload = {
  kind: AgentAttachmentKind;
  name: string;
  path?: string;
  content?: string;
  content_b64?: string;
  size?: number;
};

export type AgentDraftAttachment = AgentAttachmentPayload & {
  key: string;
  status: "progress" | "success" | "fail";
  description?: string;
  url?: string;
};

export type AttachmentRejectReason = "limit" | "too_large" | "total_too_large" | "type_blocked" | "missing";

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

function formatSize(size: number): string {
  if (!size) return "";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.floor(size / 1024)} KB`;
  const mb = size / (1024 * 1024);
  return mb < 10 ? `${mb.toFixed(1)} MB` : `${Math.floor(mb)} MB`;
}

export function attachmentSuffix(name: string): string {
  const base = String(name || "").split(/[/\\]/).pop() || "";
  const index = base.lastIndexOf(".");
  return index >= 0 ? base.slice(index).toLowerCase() : "";
}

export function isBlockedAttachmentName(name: string): boolean {
  const base = String(name || "").split(/[/\\]/).pop() || "";
  const lower = base.toLowerCase();
  if (lower === ".env" || lower.startsWith(".env.")) return true;
  const suffix = attachmentSuffix(lower);
  return [".p8", ".pem", ".key"].includes(suffix) || lower.includes("credential");
}

export function isAllowedAttachmentName(name: string): boolean {
  if (isBlockedAttachmentName(name)) return false;
  return ALLOWED_SUFFIXES.has(attachmentSuffix(name));
}

export function isImageAttachmentName(name: string): boolean {
  return [".png", ".jpg", ".jpeg", ".webp", ".gif"].includes(attachmentSuffix(name));
}

export function rejectAttachment(
  name: string,
  size: number,
  currentCount: number,
  currentTotalBytes = 0,
): AttachmentRejectReason | null {
  if (currentCount >= AGENT_ATTACH_MAX) return "limit";
  if (!isAllowedAttachmentName(name)) return "type_blocked";
  if (size > AGENT_ATTACH_MAX_BYTES) return "too_large";
  if (currentTotalBytes + size > AGENT_ATTACH_MAX_TOTAL_BYTES) return "total_too_large";
  return null;
}

export function toSenderItem(item: AgentDraftAttachment) {
  const image = isImageAttachmentName(item.name);
  const suffix = attachmentSuffix(item.name).replace(".", "");
  const mime = image ? `image/${suffix === "jpg" ? "jpeg" : suffix || "png"}` : undefined;
  return {
    key: item.key,
    name: item.name,
    size: item.size || 0,
    status: item.status,
    description: item.description || formatSize(item.size || 0),
    url: item.url,
    fileType: image ? ("image" as const) : ("txt" as const),
    type: mime,
    extension: suffix || undefined,
  };
}

export function toPayload(item: AgentDraftAttachment): AgentAttachmentPayload {
  const payload: AgentAttachmentPayload = {
    kind: item.kind,
    name: item.name,
    size: item.size,
  };
  if (item.path) payload.path = item.path;
  if (item.content) payload.content = item.content;
  if (item.content_b64) payload.content_b64 = item.content_b64;
  return payload;
}

export function composeAttachmentPrompt(text: string, items: AgentDraftAttachment[]): string {
  const body = text.trim();
  if (!items.length) return body;
  const lines = items.map((item) => `- ${item.name}${item.path ? ` — ${item.path}` : ""}`);
  const block = `[attachments]\n${lines.join("\n")}`;
  return body ? `${body}\n\n${block}` : block;
}

export async function draftFromFile(file: File, key: string): Promise<AgentDraftAttachment> {
  const name = file.name || "file";
  const size = file.size || 0;
  const row: AgentDraftAttachment = {
    key,
    kind: "inline",
    name,
    size,
    status: "success",
    description: formatSize(size),
  };
  if (isImageAttachmentName(name) || /image\//.test(file.type)) {
    row.url = URL.createObjectURL(file);
    const bytes = new Uint8Array(await file.arrayBuffer());
    row.content_b64 = bytesToBase64(bytes);
    return row;
  }
  row.content = await file.text();
  return row;
}

export function draftFromPath(path: string, key: string): AgentDraftAttachment {
  const name = path.split(/[/\\]/).pop() || path;
  return {
    key,
    kind: "path",
    name,
    path,
    size: 0,
    status: "success",
    description: path,
  };
}

export function revokeAttachmentUrl(item: AgentDraftAttachment) {
  if (item.url && item.url.startsWith("blob:")) URL.revokeObjectURL(item.url);
}
