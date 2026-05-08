# 04 What's New & Store URLs

**When to use:** Update release notes (What's New) and store URLs (support, marketing, privacy policy) for your app.

---

## Prerequisites

- Completed [01 Install & Project Init](01-install-and-init.md)
- An editable app version in App Store Connect

---

## Step 1: Update What's New (release notes)

**Single locale, inline text:**

```bash
asc --app myapp whats-new --text "Bug fixes and performance improvements."
```

**Multiple locales, inline text:**

```bash
asc --app myapp whats-new --text "Bug fixes." --locales en-US zh-Hans
```

**Multi-locale from file:**

Create `data/whats_new.txt`:

```
en-US:
- Bug fixes
- Performance improvements
---
zh-Hans:
- 修复已知问题
- 性能优化
```

Then run:

```bash
asc --app myapp whats-new --file data/whats_new.txt
```

---

## Step 2: Set store URLs

**Support URL:**

```bash
asc --app myapp set-support-url --text "https://example.com/support"
```

**Marketing URL (with locales):**

```bash
asc --app myapp set-marketing-url --text "https://example.com" --locales en-US zh-Hans
```

**Privacy Policy URL:**

```bash
asc --app myapp set-privacy-policy-url --text "https://example.com/privacy"
```

---

## Step 3: View current URLs

```bash
asc --app myapp support-url
asc --app myapp marketing-url
asc --app myapp privacy-policy-url
```

---

## FAQ

**`whats_new.txt` format not recognized**
Ensure each locale section ends with `---` (three dashes on its own line). Locale codes must match App Store Connect locales.

**URL not updating**
URLs are app-level settings, not version-specific. Changes apply immediately.

---

## Next steps

- [05 Build & Deploy](05-build-and-deploy.md)
- [02 Metadata & Screenshots](02-metadata-and-screenshots.md)
