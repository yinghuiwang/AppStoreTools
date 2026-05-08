# 07 Guard 安全守卫

**适用场景：** 了解 Guard 系统如何保护你的凭证、解决绑定冲突，或在 CI/CD 环境中关闭 Guard。

---

## Guard 是什么？

Guard 将你的 API 凭证绑定到特定的机器和 IP 地址。当同一凭证从未知机器或 IP 使用时，Guard 会发出警告或阻止操作，防止凭证被意外共享或滥用。

Guard **默认启用**，绑定数据存储在 `~/.config/asc/guard.json`。

---

## 查看当前状态

```bash
asc guard status
```

输出示例：

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

## 启用 / 禁用 Guard

```bash
asc guard enable
asc guard disable
```

禁用 Guard 后，所有绑定检查都会跳过。适用于每次运行机器和 IP 都会变化的 CI/CD 环境。

---

## 解除特定绑定

**解除当前机器和 IP 的绑定：**

```bash
asc guard unbind --current
```

**按机器指纹解绑：**

```bash
asc guard unbind --machine a1b2c3d4e5f6g7h8
```

**按 IP 地址解绑：**

```bash
asc guard unbind --ip 203.0.113.42
```

**按凭证（Key ID）解绑：**

```bash
asc guard unbind --credential XXXXXXXXXX
```

---

## 重置所有绑定

```bash
asc guard reset
```

清除所有绑定记录，Guard 的启用/禁用状态保持不变。

---

## CI/CD：通过环境变量禁用 Guard

在自动化流水线中，可以通过环境变量跳过 Guard 检查：

```bash
export ASC_GUARD_DISABLE=1
asc --app myapp upload
```

或在 CI 环境变量中设置。完整示例请参考 [08 CI/CD 自动化](08-ci-cd.zh-CN.md)。

---

## 常见问题

**Q: Guard 阻止了从新机器的合法操作**
在旧机器上执行 `asc guard unbind --current`，或执行 `asc guard reset` 清除所有绑定，然后从新机器重新运行以创建新的绑定记录。

**Q: 收到冲突警告但想继续操作**
警告表示该凭证之前绑定到了不同的机器/IP。如果这是有意为之（例如换了新机器），解除旧绑定后重新运行即可。

**Q: Guard 文件在哪里？**
`~/.config/asc/guard.json` — 不要将此文件提交到 git。

---

## 下一步

- [08 CI/CD 自动化](08-ci-cd.zh-CN.md)
- [06 多 App Profile 管理](06-multi-app-profiles.zh-CN.md)
