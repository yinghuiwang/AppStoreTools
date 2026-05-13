# 用户友好错误提示优化设计

## 问题

CLI 在用户输入参数不足或数据缺失时，错误提示只告知"什么错了"，不告知"如何修复"。大量 `❌ {e}` 直接透传异常消息，用户无所适从。

## 目标

所有用户级错误消息必须包含**下一步行动指引**（除非是真正的内部错误）。

---

## 方案

### 1. 错误分类

| 类别 | 例子 | 策略 |
|------|------|------|
| `MissingFileError` | CSV not found, IPA not found | 告知可用 CLI 参数指定路径 |
| `MissingConfigError` | issuer_id missing | 告知具体缺失字段 + `asc app edit` |
| `InvalidInputError` | invalid locale | 告知无效输入 + 列出有效选项 |
| `GuardViolationError` | credential conflict | 告知冲突 + `asc guard unbind` |
| `BuildError` | provisioning profile invalid | 指向日志文件 + 常见解决方案 |
| `APIError` | network/auth failure | 告知检查网络或凭证 |
| `InternalError` | unexpected exception | 指向日志 + `--debug` 获取详情 |

### 2. 通用错误处理模式

在 `src/asc/error_handler.py` 新增 `get_action_hint(e: Exception) -> Optional[str]` 函数：

```python
def get_action_hint(e: Exception) -> Optional[str]:
    """根据异常类型/消息返回用户可操作的下一步指引，无可操作建议时返回 None。"""
```

修改全局错误处理（`build.py`、`metadata.py`、`iap.py` 等）：

```python
except (RuntimeError, ValueError) as e:
    typer.echo(f"❌ {e}", err=True)
    hint = get_action_hint(e)
    if hint:
        typer.echo(f"💡 {hint}", err=True)
    raise typer.Exit(1)
```

### 3. 具体错误消息优化

#### `build_inputs.py:291`
```python
# 旧
raise ValueError(f"No Xcode project or workspace found in: {path}")
# 新（不修改异常本身，而是在 handler 层增强）
# 💡 可使用 --project 指定项目路径，或在 Xcode 项目根目录运行 asc init
```

#### `utils.py:318`
```python
# 旧
raise ValueError(f"Missing required config: {', '.join(missing)}")
# 新
raise MissingConfigError(
    missing=missing,
    suggestion="请先运行 'asc app edit <name>' 补充配置，或在项目根目录运行 'asc init'"
)
```

#### `metadata.py` — CSV not found
```python
# 旧
typer.echo(f"❌ CSV 文件不存在: {csv_path}", err=True)
# 新
typer.echo(f"❌ CSV 文件不存在: {csv_path}", err=True)
typer.echo(f"💡 可使用 --csv 参数指定其他路径，参考 'asc upload --help'", err=True)
```

#### `guard.py` — 机器/IP 绑定错误
```python
# 旧
raise GuardError("IOPlatformUUID not found")
# 新
raise GuardError("无法获取机器标识符。请确保在受支持的 macOS 系统上运行。")
```

### 4. 实施步骤

**Step 1.** 完善 `src/asc/error_handler.py`，新增 `get_action_hint()` 函数

**Step 2.** 创建 `src/asc/exceptions.py`，定义以下异常类：
- `MissingConfigError`
- `MissingFileError`
- `InvalidInputError`
- `GuardViolationError`

**Step 3.** 改造 `src/asc/commands/build.py` 中的 `except` 块，集成 `get_action_hint`

**Step 4.** 改造 `src/asc/commands/metadata.py` 中的 CSV not found 等错误

**Step 5.** 改造 `src/asc/commands/build_inputs.py` 中的 `detect_project` 等错误

**Step 6.** 改造 `src/asc/utils.py` 中的配置缺失错误

**Step 7.** 改造其余命令文件（`iap.py`, `whats_new.py`, `screenshots.py`, `subscriptions.py`）

**Step 8.** 统一测试所有错误场景

---

## 影响范围

- 新增文件：`src/asc/exceptions.py`
- 修改文件：`src/asc/error_handler.py`、所有 `commands/` 下的文件
- 向后兼容：异常消息内容不变，仅在 handler 层增强输出
