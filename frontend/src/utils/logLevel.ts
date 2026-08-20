export type LogLevel = "debug" | "info" | "warning" | "error";

const WARNING_RE = /⚠️|\bWARN(?:ING)?\b|警告/i;
const ERROR_RE =
  /\b(?:fail|failed|failure|error|fatal|exception|traceback)\b|[A-Z][A-Za-z0-9_]*Error|错误|失败|异常/i;
const LEVELS = new Set<LogLevel>(["debug", "info", "warning", "error"]);

function asLevel(value: string | undefined | null): LogLevel | undefined {
  if (!value) return undefined;
  const normalized = value.toLowerCase();
  return LEVELS.has(normalized as LogLevel) ? (normalized as LogLevel) : undefined;
}

function levelFromText(message: string): LogLevel {
  const text = message || "";
  if (WARNING_RE.test(text)) return "warning";
  if (ERROR_RE.test(text)) return "error";
  return "info";
}

/** Resolve a UI log level. Warning markers always win so they are never painted red. */
export function classifyLogLevel(message: string, structured?: string | null): LogLevel {
  const textLevel = levelFromText(message);
  if (textLevel === "warning") return "warning";
  const fromStructured = asLevel(structured);
  if (fromStructured) return fromStructured === "debug" ? "info" : fromStructured;
  return textLevel;
}

export function parseLogEventData(data: string): { message: string; level?: string } {
  const text = data ?? "";
  const trimmed = text.trim();
  if (trimmed.startsWith("{")) {
    try {
      const obj = JSON.parse(text) as { message?: unknown; level?: unknown };
      if (obj && typeof obj.message === "string") {
        return {
          message: obj.message,
          level: typeof obj.level === "string" ? obj.level : undefined,
        };
      }
    } catch {
      /* fall through to plain text */
    }
  }
  return { message: text };
}
