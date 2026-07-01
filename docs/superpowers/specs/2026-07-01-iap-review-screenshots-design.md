# IAP Review Screenshots Design

Date: 2026-07-01

## Goal

Add a dedicated way to upload missing App Store review screenshots for in-app purchases and subscriptions without running the full IAP creation/update flow.

The feature must:

- Query App Store Connect to find products that currently have no review screenshot.
- Include all one-time IAP products and all subscriptions in the app.
- Let the user provide screenshot paths for missing products in CLI and Web.
- Upload all selected screenshots in one run.
- Avoid writing selected Web paths back to `iap_packages.json`.
- Preserve the existing `asc iap --iap-file ...` behavior.

## Non-Goals

- Do not replace screenshots for products that already have one.
- Do not create or update IAP products, subscription groups, prices, localizations, offers, or availability.
- Do not make local JSON the source of truth for the missing screenshot list.
- Do not write Web-selected paths into `iap_packages.json`.

## Recommended Approach

Implement a shared core module for review screenshot scanning, matching, validation, and upload. The CLI and Web UI will both call this module.

This keeps the App Store Connect querying rules, path validation, and upload behavior in one place. It also avoids duplicating logic between terminal and Web workflows.

## Core Data Model

The shared module will normalize missing screenshot products into a small internal structure with these fields:

- `kind`: `iap` or `subscription`
- `id`: App Store Connect resource id
- `productId`: App Store product id
- `name`: display/reference name when available
- `groupName`: subscription group reference name for subscriptions, otherwise empty
- `defaultPath`: local path matched from JSON when available
- `pathStatus`: valid, missing, invalid, or empty

The structure can be a dataclass or simple typed dictionary, following the surrounding code style.

## App Store Connect Scan

The scan must use online App Store Connect state:

1. One-time IAP products:
   - Call `api.list_in_app_purchases(app_id)`.
   - For each product, call `api.list_in_app_purchase_review_screenshots(iap_id)`.
   - Add the product to the missing list only when the screenshot response is empty.

2. Subscriptions:
   - Call `api.list_subscription_groups(app_id)`.
   - For each group, call `api.list_subscriptions(group_id)`.
   - For each subscription, call `api.list_subscription_review_screenshots(sub_id)`.
   - Add the subscription to the missing list only when the screenshot response is empty.

The scan should continue when a single product check fails, record that failure, and still return other missing products. A full authentication or app-level failure should fail the scan.

## JSON Path Matching

`iap_packages.json` is optional input for default paths only.

When an IAP file is provided or available from the profile:

- Load it with the existing relative-path behavior so `review.screenshot` remains relative to the JSON file.
- Build a `productId -> review.screenshot` lookup from both `items` and `subscriptionGroups[].subscriptions`.
- Attach the matched path to missing online products with the same product id.
- Do not require every product to exist in JSON.
- Do not fail the online scan when the JSON file is absent; simply report no default paths.

For this feature, JSON validation should not block scanning because existing subscription upload validation requires review screenshots and full pricing/localization fields. The implementation should either use a lighter path-extraction loader or make the matching path tolerant of incomplete files.

## CLI Flow

Add an independent command:

```bash
asc --app myapp iap-screenshots
```

This avoids turning the existing `iap` command into a nested Typer app and preserves compatibility with current calls.

CLI options:

- `--iap-file, -f`: optional JSON file used only for default path matching.
- `--dry-run, -d`: scan and show what would be uploaded without uploading.
- `--no-prompt`: only upload products with valid matched/default paths; skip products that need manual input.
- `--yes, -y`: skip final confirmation before upload.

CLI behavior:

- Query App Store Connect for all missing review screenshots.
- Print missing consumable/non-consumable IAP products and subscriptions separately.
- Use matched JSON paths when valid.
- Prompt once per missing product without a valid path, unless `--no-prompt` is set.
- Allow empty input to skip that product.
- Validate image paths before upload.
- Upload all selected screenshots in one run.
- Return exit code `1` if any selected product fails to upload; return `0` when all selected uploads succeed or there was nothing selected to upload.

## Web Flow

Extend the existing `/iap` page with a separate "补审核截图" area.

The Web flow is two-step:

1. Scan:
   - User clicks "扫描缺截图".
   - Web calls a new API endpoint that queries App Store Connect.
   - The response lists missing products and any default path matched from JSON.

2. Upload:
   - Each missing product row shows type, product id, name, subscription group when relevant, and a path input.
   - The existing file browser is reused for choosing `.png`, `.jpg`, or `.jpeg` files.
   - User clicks "上传所选截图".
   - Web submits a temporary mapping of online product ids to selected local paths.
   - A background task uploads the selected screenshots and streams logs/progress like the existing IAP upload task.

Web-selected paths are only request payload data. They must not be written back to `iap_packages.json`.

## Upload Rules

Only products that were found missing online and have a valid selected path are uploaded.

Path validation:

- Path must exist.
- Path must be a file.
- Extension must be `.png`, `.jpg`, or `.jpeg`.
- Files over 5 MB should warn and continue, matching existing review screenshot behavior.

Before each upload, re-check the online screenshot relationship:

- If a screenshot now exists, skip the product.
- If it is still missing, reserve, upload, and commit the screenshot.

The implementation should reuse the existing reservation/upload/commit API methods for IAP and subscription screenshots. Existing helper behavior can be shared or factored to avoid duplicate upload code.

## Error Handling

Scanning:

- App-level API, credential, or profile errors fail the scan.
- Per-product screenshot relationship errors are reported but do not prevent other products from being scanned.

Uploading:

- Per-product upload failures are logged and collected.
- The batch continues after individual failures.
- CLI exits non-zero if any selected upload fails.
- Web task should surface failures clearly in logs and result data. If any selected upload fails, mark the task as error so the UI does not imply a fully successful run.

## Progress And Logs

The core upload function should emit progress lines compatible with the existing Web parser:

```text
[PROGRESS:50:IAP 审核截图 3/6]
```

Logs should distinguish:

- Missing online products found.
- Products skipped because no path was provided.
- Products skipped because a screenshot appeared before upload.
- Products uploaded successfully.
- Products that failed with the error message.

## Tests

Add focused tests for:

- Online scan finds missing IAP review screenshots.
- Online scan finds missing subscription review screenshots across groups.
- Existing screenshots are excluded from the missing list.
- JSON path matching attaches default paths by `productId`.
- Missing or incomplete JSON does not block online scanning.
- Path validation accepts `.png/.jpg/.jpeg` and rejects missing files or unsupported extensions.
- Upload skips products that gained a screenshot after scan.
- Upload continues after one product fails and reports failures.
- CLI command registration and `--no-prompt` behavior.
- Web scan endpoint response shape.
- Web upload task starts with a temporary path mapping and does not write to `iap_packages.json`.

## Documentation

Update the IAP tutorial with:

- The new `asc iap-screenshots` command.
- The distinction between App Store Connect online missing screenshot detection and optional JSON default path matching.
- Web UI instructions for scanning, selecting paths, and uploading selected screenshots.

