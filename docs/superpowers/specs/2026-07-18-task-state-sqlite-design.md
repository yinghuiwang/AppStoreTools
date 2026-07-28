# Task State SQLite Design

## Goal

Unify Web and CLI task status, progress, logs, and results in a local SQLite database while retaining local CSV/JSON/image files as business inputs and App Store Connect as the remote business source of truth.

## Design

`TaskStore` keeps its existing public methods but persists task records in SQLite at `~/.config/asc/tasks.db`, overridable with `ASC_WEB_TASKS_PATH`. The database uses WAL mode and transactions. Existing JSON task history is migrated on first open when present, so current users do not lose task history.

Tasks and logs are separate records. Each log receives a monotonic per-task sequence number. The SSE endpoint replays logs after an optional cursor and emits stable event IDs, while preserving the current HTTP task creation/status/cancel endpoints.

The Web UI remains HTTP + SSE + HTMX. Web service lifecycle files (`web.json`, `web.log`) and CLI error/build logs remain separate, with task results able to reference external log files.

## Error and restart behavior

Pending/running tasks loaded after a service restart are marked `error` with an interruption log, matching current behavior. SQLite failures do not prevent task execution from returning an error result; writes are guarded by the store layer.

## Testing

Add tests for SQLite persistence, legacy JSON migration, restart interruption normalization, concurrent-safe task updates, and SSE cursor replay/event IDs. Existing task and web route tests must remain green.
