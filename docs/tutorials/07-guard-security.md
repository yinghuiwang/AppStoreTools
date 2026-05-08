# 07 Guard Security

**When to use:** Understand how the Guard system protects your credentials, resolve binding conflicts, or disable Guard for CI/CD environments.

---

## What is Guard?

Guard binds your API credentials to specific machines and IP addresses. When the same credential is used from an unexpected machine or IP, Guard warns you or blocks the operation. This prevents accidental credential sharing or misuse.

Guard is **enabled by default**. It stores binding data in `~/.config/asc/guard.json`.

---

## Check current status

```bash
asc guard status
```

Example output:

```
守卫状态: ✅ 已启用

当前环境:
  机器指纹: a1b2c3d4e5f6g7h8...
  IP 地址:  203.0.113.42

绑定记录:
  类型     标识                 绑定 App       绑定时间
  ----------------------------------------------------------------
  机器     a1b2c3d4e5f6g7h8...  myapp          2026-04-01 10:00:00
  IP       203.0.113.42         myapp          2026-04-01 10:00:00
  凭证     XXXXXXXXXX           myapp          2026-04-01 10:00:00
```

---

## Enable / disable Guard

```bash
asc guard enable
asc guard disable
```

Disabling Guard removes all binding checks. Use this for CI/CD environments where the machine and IP change on every run.

---

## Unbind specific entries

**Unbind the current machine and IP:**

```bash
asc guard unbind --current
```

**Unbind by machine fingerprint:**

```bash
asc guard unbind --machine a1b2c3d4e5f6g7h8
```

**Unbind by IP address:**

```bash
asc guard unbind --ip 203.0.113.42
```

**Unbind by credential (Key ID):**

```bash
asc guard unbind --credential XXXXXXXXXX
```

---

## Reset all bindings

```bash
asc guard reset
```

Clears all binding records. Guard remains enabled/disabled as before.

---

## CI/CD: disable Guard via environment variable

For automated pipelines where you don't want Guard to block runs:

```bash
export ASC_GUARD_DISABLE=1
asc --app myapp upload
```

Or set it in your CI environment variables. See [08 CI/CD Automation](08-ci-cd.md) for a full example.

---

## FAQ

**Guard is blocking a legitimate run from a new machine**
Run `asc guard unbind --current` on the old machine, or `asc guard reset` to clear all bindings, then re-run from the new machine to create fresh bindings.

**I'm getting a conflict warning but want to proceed**
The warning means the credential was previously bound to a different machine/IP. If this is intentional (e.g. you moved to a new machine), unbind the old entry and re-run.

**Guard file location**
`~/.config/asc/guard.json` — do not commit this file to git.

---

## Next steps

- [08 CI/CD Automation](08-ci-cd.md)
- [06 Multi-App Profiles](06-multi-app-profiles.md)
