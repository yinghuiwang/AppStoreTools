# Version updates

keywords: version what's new whatsNew whatsnew 4000 PREPARE_FOR_SUBMISSION editable submit review phased release 分阶段

## What’s New (official)

- **4000** characters, localizable, plain text.
- **Not available on the first version**; **required** on later versions.
- Tell users what changed (features, UI, fixes). Appears on the product page and Updates tab.

Source: https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information
Also: https://developer.apple.com/app-store/product-page/

Writing tips (skill `app-store-changelog`, not Apple law): 5–10 user-facing bullets; verbs; drop CI/refactors; no ticket IDs. Still must fit **4000**.

This tool: `asc whats-new` / web What’s New updates `whatsNew` on version localizations. Not a CSV column.

## App statuses (official)

Editable metadata depends on status. Source:
https://developer.apple.com/help/app-store-connect/reference/app-information/app-and-submission-statuses/

| Status | Meaning | Edit notes |
| --- | --- | --- |
| Prepare for Submission | Preparing the version | Fully editable |
| Ready for Review | Ready but not sent | Images/videos **not** editable |
| Waiting for Review | Apple received it | Some text ok; **no** screenshot/preview upload |
| In Review | Under review | Can remove from review |
| Pending Developer Release | Approved, you release | Release settings |
| Ready for Distribution | Live / ready | New version needed for most listing edits |
| Rejected / Metadata Rejected / Developer Rejected | Fix and resubmit | Editable again |
| Invalid Binary | Need a new build | |

API state strings this tool recognizes: `PREPARE_FOR_SUBMISSION`, `READY_FOR_REVIEW`, `WAITING_FOR_REVIEW`, `IN_REVIEW`, `PENDING_DEVELOPER_RELEASE`, `READY_FOR_DISTRIBUTION`, `REJECTED`, `METADATA_REJECTED`, `DEVELOPER_REJECTED`, …

## This tool: “editable version”

`get_editable_version()` looks for:
`PREPARE_FOR_SUBMISSION`, `DEVELOPER_REJECTED`, `REJECTED`, `METADATA_REJECTED`, `WAITING_FOR_REVIEW`, `IN_REVIEW`.

It returns **none** when the only versions are live / ready-for-review / pending-release. It does **not** fall back to `READY_FOR_SALE`.

**This tool does not create an App Store version.** If none exists (or none is editable), metadata / screenshots / What’s New fail with “no editable version”. Create the version in App Store Connect first.

What’s New web path can additionally require `PREPARE_FOR_SUBMISSION` / `DEVELOPER_REJECTED` / `REJECTED`.

## Submit for review (official)

- One **app version** submission per platform at a time.
- A platform may also have a second submission **without** a version (IAP events, custom pages).
- First IAP of each type must go **with** a version; later ones can be separate.

https://developer.apple.com/help/app-store-connect/manage-submissions-to-app-review/submit-for-review/

This CLI/web upload writes metadata/screenshots/IAP; it is **not** a full “Submit for Review” button replacement unless a specific web action exists. Do not claim the app was submitted if only files were uploaded.

## Release options (official)

- **Manual** — Pending Developer Release, you tap release.
- **Automatic** — live after approval.
- **Automatic, no earlier than** — hold until a date.
- **Phased release** — 7 days, only users with Automatic Updates. Can pause up to 30 days. Can release to all remaining users anytime after Ready for Distribution.

https://developer.apple.com/help/app-store-connect/update-your-app/release-a-version-update-in-phases
