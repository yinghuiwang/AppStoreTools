# Web Update Advanced Install Design

Date: 2026-07-01

## Goal

Make the Web update page always provide advanced install actions for a specific version or a specific branch, even when the update check reports that the current installed version is already the latest.

## Current Behavior

The Web update page checks the current and latest versions. The install options card is only rendered when `checkResult.detail.is_latest` is false. Because the specific version and specific branch controls live inside that card, users cannot install a chosen version or branch when the installed version is already current.

The backend already supports the needed update modes:

- `cmd_update(version=...)`
- `cmd_update(branch=...)`
- `/api/update/run` with `version` or `branch`
- `/api/update/branches` for branch choices

## Desired Behavior

The page should keep the current status display:

- If a newer release exists, show the available update and the latest-version install action.
- If the installed release is current, show the existing "已是最新版本" state.

Separately, the page should always show an advanced install area with:

- Specific version install.
- Specific branch install.
- Branch list refresh/loading behavior using the existing `/api/update/branches` endpoint.

This advanced area must be usable after update check succeeds, regardless of whether a newer release exists.

## Non-Goals

- Do not change CLI `asc update` behavior.
- Do not change backend update installation semantics unless a small validation fix is needed for the Web form.
- Do not force a latest-version reinstall when already current.
- Do not add package source selection beyond the existing GitHub repository behavior.

## Web Design

Refactor `src/asc/web/templates/update.html` so the "latest version" action and the "advanced install" actions are separate sections:

- A latest-version card or section is shown only when `checkResult.detail.is_latest` is false.
- The existing "已是最新版本" card remains shown when `is_latest` is true.
- A new "高级安装" card is shown whenever the update check has a usable `detail` object.

Inside "高级安装":

- Use a compact segmented control or tabs for `指定版本` and `指定分支`.
- Keep the version input and branch select/text fallback controls.
- Reuse `runUpdate(version)` for version installs.
- Reuse `runUpdateBranch(branch)` for branch installs.
- Keep `loadBranches(force)` behavior and branch fallback text input.

The existing progress/log card and SSE handling should continue to work for all three install modes.

## Backend Impact

No backend changes are expected. `/api/update/run` already accepts both `version` and `branch`, and `/api/update/branches` already returns branch options.

During implementation, if the Web form can submit empty version or branch values, the front end should avoid submitting and show a local message rather than starting a task.

## Tests

Add focused Web tests that verify:

- The update page contains the advanced install controls and `/api/update/run` logic.
- The advanced install controls are present independently of the "new update available" card.
- Existing update check and branch endpoints continue to return the expected response shapes.

If the project test harness does not execute Alpine conditions, prefer stable template-level assertions plus endpoint tests.

## Documentation

No tutorial update is required unless implementation changes user-facing command syntax or backend behavior. This is a Web UI availability fix for existing update modes.

