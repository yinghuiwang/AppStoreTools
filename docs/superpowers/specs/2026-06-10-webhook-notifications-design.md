# Webhook Notifications Design

## Goal

Add configurable Webhook notifications to the Web UI so completed background task results can be sent to office chat groups. The feature supports Feishu/Lark, WeCom, and DingTalk group robot webhooks, including optional signing secrets where each platform supports them.

Notifications are configured from the Web settings page and are sent only when a task reaches a terminal state: success, failure, or cancellation.

## Context

The repository already has a FastAPI Web UI under `src/asc/web/`.

- Page routes are registered in `src/asc/web/server.py`.
- API routes live in `src/asc/web/routes_api.py`.
- Web task state is stored by `src/asc/web/tasks.py`.
- The settings page is `src/asc/web/templates/settings.html`.
- Existing settings APIs already use `/api/settings/*`, for example LLM configuration.
- Recent tasks use task kinds such as `metadata`, `build`, `whats-new`, `iap`, `urls`, and `update`.

The current task completion logic is spread across Web run endpoints. The notification implementation should avoid putting platform-specific webhook logic into those endpoints.

## Scope

In scope:

- Web settings UI for webhook notification configuration.
- Global user-level storage at `~/.config/asc/webhook.toml`.
- Multiple provider support for Feishu/Lark, WeCom, and DingTalk.
- Optional provider secrets/signing keys.
- Configurable task kind filtering.
- Configurable terminal status filtering.
- One notification when a selected task finishes.
- Test notification action from settings.
- Unit tests for config, filtering, payloads, signing, API routes, and task notification behavior.

Out of scope:

- CLI commands for managing webhook settings.
- Progress or start notifications.
- Per-project `.asc/config.toml` webhook settings.
- Delivery retries or persistent notification queue.
- Custom arbitrary webhook JSON provider.

## Recommended Architecture

Add an independent notification layer rather than embedding webhook behavior in upload or update commands.

Proposed modules:

- `src/asc/web/notifications.py`
  - Loads and saves webhook configuration.
  - Applies enabled, task kind, and task status filters.
  - Builds a normalized task notification message.
  - Sends notifications to enabled providers.
  - Exposes `notify_task_finished(task_id, task_store=task_store)`.

- `src/asc/web/webhook_clients.py`
  - Builds platform-specific payloads.
  - Applies Feishu/Lark and DingTalk signing.
  - Performs HTTP POST with a short timeout.

The notification layer depends on the public task dictionaries returned by `TaskStore`. It should not import or call metadata, build, IAP, update, or App Store command modules.

## Configuration

Store configuration globally at:

```text
~/.config/asc/webhook.toml
```

Suggested TOML structure:

```toml
enabled = true
notify_statuses = ["done", "error", "canceled"]
notify_kinds = ["metadata", "build", "whats-new", "iap", "urls"]

[providers.feishu]
enabled = true
url = "https://open.feishu.cn/open-apis/bot/v2/hook/..."
secret = "optional"

[providers.wecom]
enabled = false
url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
secret = ""

[providers.dingtalk]
enabled = false
url = "https://oapi.dingtalk.com/robot/send?access_token=..."
secret = "optional"
```

Default behavior when the file is missing:

- Notifications are disabled.
- Terminal statuses default to `done`, `error`, and `canceled`.
- Task kind defaults include upload-related tasks: `metadata`, `build`, `whats-new`, `iap`, and `urls`.
- `update` is available in the UI but not selected by default.

Secrets must not be exposed in clear text through the settings API. When editing a provider, leaving the secret blank should preserve the existing saved secret. A separate explicit clear action or sentinel value may be used if the implementation needs to support removing a secret.

## Settings UI

Add a new card to `src/asc/web/templates/settings.html` named "群通知 / Webhook".

The card includes:

- Global enable switch.
- Task kind multi-select or checkbox group:
  - 元数据上传 (`metadata`)
  - 构建上传 (`build`)
  - 更新说明上传 (`whats-new`)
  - 内购上传 (`iap`)
  - URL 更新 (`urls`)
  - 工具更新 (`update`)
- Terminal status multi-select or checkbox group:
  - 成功 (`done`)
  - 失败 (`error`)
  - 已取消 (`canceled`)
- Provider sections for:
  - 飞书/Lark
  - 企业微信
  - 钉钉
- Each provider section has:
  - Enable switch.
  - Webhook URL input.
  - Optional secret/signing key password input.
  - Test send button.
- Save feedback and per-provider test result feedback.

The UI should follow the existing settings page style and use the existing `/api/settings/*` pattern.

## API Design

Add settings endpoints under `routes_api.py`:

- `GET /api/settings/webhooks`
  - Returns the saved configuration with secrets omitted or masked.
  - Returns defaults when no file exists.

- `POST /api/settings/webhooks`
  - Saves the complete configuration.
  - Validates provider names, booleans, URLs, task kinds, and statuses.
  - Preserves existing secrets when secret fields are omitted or intentionally left unchanged.

- `POST /api/settings/webhooks/test`
  - Sends a test message to one provider, or to all enabled providers if requested.
  - Returns success/failure details for each attempted provider.

Invalid JSON should return HTTP 400. Unexpected save or send errors should return structured JSON errors without exposing secrets.

## Message Content

Send one concise message when a task finishes.

Include:

- Title:
  - `ASC 任务完成：构建上传`
  - `ASC 任务失败：元数据上传`
  - `ASC 任务已取消：更新说明上传`
- App/profile from the task `profile`.
- Status label.
- Duration from `duration_label`.
- Completion time from `completed_at`.
- Task ID shortened for readability.
- Failure summary from `result.error` when present.
- Cancellation note for canceled tasks.
- Recent log summary only for failed tasks, limited to the last 3-5 lines.

Successful notifications should stay short. Failure notifications may include more diagnostic context but should avoid dumping full logs.

## Provider Behavior

Feishu/Lark:

- Send a text message accepted by Feishu/Lark custom bot webhooks.
- If `secret` is configured, add timestamp and HMAC-SHA256 signature according to Feishu/Lark bot signing rules.

WeCom:

- Send a markdown message accepted by WeCom group robot webhooks.
- WeCom group robot webhooks commonly do not use an additional signing secret. Keep the secret field in the model for consistency, but do not apply signing in the first implementation.

DingTalk:

- Send a markdown message accepted by DingTalk robot webhooks.
- If `secret` is configured, add timestamp and HMAC-SHA256 signature URL parameters according to DingTalk signing rules.

Each provider request should use a short timeout, for example 5 seconds. One provider failing must not prevent other enabled providers from being attempted.

## Task Completion Integration

After a Web background task sets terminal status and result, call:

```python
notify_task_finished(task_id, task_store=_task_store)
```

The call should occur after both status and result are available so notifications can include accurate state and error details.

For existing endpoints that set status and result in multiple branches, add the notification call in the terminal branches. Keep the call small and delegate all filtering and sending behavior to the notification module.

Notification failures must not change the task status or result.

## Error Handling

- Missing config file: skip notifications.
- Global disabled flag: skip notifications.
- Provider disabled or empty URL: skip provider.
- Task kind or status not selected: skip notifications.
- Invalid config TOML: skip notifications and append a warning to the task log when a task context is available.
- HTTP non-2xx, timeout, or network error: append a warning to the task log with provider and short error summary.
- Test send errors: return provider-level error details to the settings UI.

Warnings should never include webhook URLs with tokens or full secret values.

## Testing

Add or update tests under `tests/`.

Recommended coverage:

- Config loading defaults when `webhook.toml` is missing.
- Config save/load for multiple providers.
- Secret masking and preservation on settings GET/POST.
- Task kind and terminal status filtering.
- Feishu/Lark payload and signature with mocked time.
- DingTalk payload and signature with mocked time.
- WeCom payload without signing.
- HTTP success and failure behavior with mocked requests.
- `notify_task_finished` sends for `done`, `error`, and `canceled` when configured.
- Notification failures do not alter task status or result.
- `GET /api/settings/webhooks`.
- `POST /api/settings/webhooks`.
- `POST /api/settings/webhooks/test`.
- Settings page contains the webhook configuration card and key fields.

Tests must use temporary config paths or monkeypatch the home/config path so real user configuration is never read or modified.

## Acceptance Criteria

- A user can configure Feishu/Lark, WeCom, and DingTalk webhooks from the Web settings page.
- A user can choose which task kinds and terminal statuses trigger notifications.
- A user can send a test message from settings.
- Task completion sends one notification to each enabled matching provider.
- Secret values are not exposed in API responses or logs.
- Notification send failures are visible as warnings but do not change task outcomes.
- The relevant pytest tests pass.
