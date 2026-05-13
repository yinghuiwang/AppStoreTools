# 用户友好错误提示优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 所有用户级错误消息在非 debug 模式下包含下一步行动指引，不再让用户无所适从。

**Architecture:** 在 `error_handler.py` 中新增 `get_action_hint()` 函数，基于异常类型/消息模式返回操作指引；在各命令的 `except` 块中集成该函数，输出 `💡` 提示。

**Tech Stack:** Python, typer, pytest

---

## 文件结构

```
src/asc/
  error_handler.py       # 修改：新增 get_action_hint()
  exceptions.py          # 新增：自定义异常类
  commands/
    build.py             # 修改：集成 get_action_hint
    build_inputs.py      # 修改：ValueError 增加操作指引
    metadata.py          # 修改：CSV not found 增加提示
    iap.py               # 修改：IAP 配置错误增加提示
    whats_new.py         # 修改：文件不存在增加提示
    screenshots.py       # 修改：截图目录不存在增加提示
    subscriptions.py     # 修改：subscription 错误增加提示
    app_config.py        # 修改：配置缺失增加提示
  guard.py               # 修改：RuntimeError 改为用户友好消息
  utils.py               # 修改：配置缺失增加提示
tests/
  test_error_handler.py  # 修改：新增 get_action_hint 测试
```

---

## Task 1: 在 error_handler.py 新增 get_action_hint() 函数

**Files:**
- Modify: `src/asc/error_handler.py`

- [ ] **Step 1: 添加 get_action_hint() 函数和 HINT_MESSAGES 字典**

在 `ERROR_MESSAGES` 字典后添加：

```python
# Action hints for user-friendly error messages
ACTION_HINTS: dict[str, dict[str, str]] = {
    # MissingFileError patterns
    'No Xcode project': {
        'en': 'Use --project to specify project path, or run "asc init" in your Xcode project root.',
        'zh': '可使用 --project 指定项目路径，或在 Xcode 项目根目录运行 asc init。',
    },
    'CSV 文件不存在': {
        'en': 'Use --csv to specify another CSV file path.',
        'zh': '可使用 --csv 参数指定其他路径，或参考 "asc upload --help"。',
    },
    'IAP 配置文件不存在': {
        'en': 'Use --iap-file to specify another IAP config file path.',
        'zh': '可使用 --iap-file 参数指定其他路径。',
    },
    'IPA 文件不存在': {
        'en': 'Use --ipa to specify the .ipa file path.',
        'zh': '可使用 --ipa 参数指定 .ipa 文件路径。',
    },
    '文件不存在': {
        'en': 'Check the file path or use --file to specify another file.',
        'zh': '请检查文件路径是否正确，或使用 --file 参数指定其他文件。',
    },
    # MissingConfigError patterns
    'Missing required config': {
        'en': 'Run "asc app edit <name>" to add missing config, or run "asc init" to set up.',
        'zh': '请先运行 "asc app edit <name>" 补充配置，或在项目根目录运行 "asc init"。',
    },
    'issuer_id': {
        'en': 'Run "asc app edit <name>" to add credentials.',
        'zh': '请先运行 "asc app edit <name>" 补充凭证信息。',
    },
    # GuardError patterns
    'IOPlatformUUID not found': {
        'en': 'Guard requires macOS. Disable guard with "asc guard disable" if running in CI.',
        'zh': '机器标识获取失败，Guard 功能仅支持 macOS。在 CI 环境可使用 "asc guard disable" 禁用。',
    },
    'All IP endpoints failed': {
        'en': 'Network error. Check your internet connection. Disable guard with "asc guard disable" if issue persists.',
        'zh': '网络连接失败，请检查网络。在 CI 环境可使用 "asc guard disable" 禁用 Guard。',
    },
    # BuildError patterns
    'security cms failed': {
        'en': 'Provisioning profile may be corrupted. Try re-downloading from Apple Developer portal.',
        'zh': '签名证书解析失败，请尝试重新从 Apple Developer 下载证书。',
    },
    'missing ExpirationDate': {
        'en': 'Provisioning profile is invalid. Please re-download from Apple Developer portal.',
        'zh': '证书已过期或损坏，请重新从 Apple Developer 下载。',
    },
    'xcodebuild archive failed': {
        'en': 'Build failed. Check the log file for details. Common causes: code signing issues, missing entitlements.',
        'zh': '构建失败，请查看日志文件。常见原因：签名配置错误、Entitlements 缺失。',
    },
    'xcodebuild exportArchive failed': {
        'en': 'Export failed. Check the log file for details.',
        'zh': '导出失败，请查看日志文件。',
    },
    'No .ipa found': {
        'en': 'Build completed but .ipa not found. Check build logs for export errors.',
        'zh': '构建完成但未找到 .ipa 文件，请查看构建日志中的导出错误。',
    },
    # GuardViolationError
    '绑定冲突': {
        'en': 'Run "asc guard unbind" to resolve the conflict, or "asc guard disable" to disable guard.',
        'zh': '运行 "asc guard unbind" 解除绑定冲突，或使用 "asc guard disable" 禁用 Guard。',
    },
    'credential': {
        'en': 'Run "asc guard unbind --credential" to unbind this credential.',
        'zh': '请运行 "asc guard unbind --credential" 解除凭证绑定。',
    },
    # API errors
    '401': {
        'en': 'Authentication failed. Check your credentials in "asc app edit <name>".',
        'zh': '认证失败，请检查 "asc app edit <name>" 中的凭证配置。',
    },
    '403': {
        'en': 'Permission denied. Check your Apple Developer account permissions.',
        'zh': '权限不足，请检查您的 Apple Developer 账户权限。',
    },
    '404': {
        'en': 'Resource not found. The app or version may have been deleted in App Store Connect.',
        'zh': '资源未找到，App 或版本可能在 App Store Connect 中已被删除。',
    },
    '429': {
        'en': 'Rate limited by App Store Connect. Wait a few minutes and retry.',
        'zh': '请求过于频繁，请稍后重试。',
    },
    'API 连接失败': {
        'en': 'Network error. Check your connection to App Store Connect.',
        'zh': '网络错误，请检查与 App Store Connect 的连接。',
    },
    # General
    'No such file': {
        'en': 'File not found. Check the path or use --help for correct usage.',
        'zh': '文件不存在，请检查路径是否正确，或参考 --help。',
    },
}


def get_action_hint(exc: BaseException) -> Optional[str]:
    """Return user-friendly action hint based on exception type/message.

    Returns None if no specific hint is available.
    """
    exc_str = str(exc)
    exc_name = type(exc).__name__

    # Guard specific exceptions
    if exc_name == 'GuardViolationError':
        if 'machine' in exc_str.lower():
            return t(ACTION_HINTS['machine'])
        if 'credential' in exc_str.lower():
            return t(ACTION_HINTS['credential'])
        return t(ACTION_HINTS['绑定冲突'])

    # Check hint patterns by message content
    for pattern, hint in ACTION_HINTS.items():
        if pattern in exc_str:
            return t(hint)

    return None
```

- [ ] **Step 2: 运行测试验证现有功能未被破坏**

Run: `pytest tests/test_error_handler.py -v`
Expected: All existing tests PASS

- [ ] **Step 3: 提交**

```bash
git add src/asc/error_handler.py
git commit -m "feat(error_handler): add get_action_hint() for user-friendly error guidance"
```

---

## Task 2: 创建 src/asc/exceptions.py 定义自定义异常类

**Files:**
- Create: `src/asc/exceptions.py`

- [ ] **Step 1: 创建 exceptions.py**

```python
"""Custom exception classes for asc CLI."""

from __future__ import annotations


class AscError(Exception):
    """Base exception for asc CLI errors."""
    pass


class MissingConfigError(AscError):
    """Raised when required configuration is missing."""
    def __init__(self, missing: list[str], suggestion: str = ""):
        self.missing = missing
        self.suggestion = suggestion
        super().__init__(f"Missing required config: {', '.join(missing)}")


class MissingFileError(AscError):
    """Raised when a required file is not found."""
    def __init__(self, file_path: str, suggestion: str = ""):
        self.file_path = file_path
        self.suggestion = suggestion
        super().__init__(f"File not found: {file_path}")


class InvalidInputError(AscError):
    """Raised when user input is invalid."""
    def __init__(self, message: str, valid_options: list[str] = None):
        self.valid_options = valid_options or []
        super().__init__(message)


class GuardViolationError(AscError):
    """Raised when guard security check fails."""
    pass
```

- [ ] **Step 2: 在 error_handler.py 中导入并处理这些新异常**

在 `src/asc/error_handler.py` 文件顶部添加导入：

```python
from asc.exceptions import GuardViolationError
```

在 `ACTION_HINTS` 字典中添加：

```python
    # GuardViolationError
    'GuardViolationError': {
        'en': 'Guard binding conflict. Run "asc guard unbind" or "asc guard disable".',
        'zh': 'Guard 绑定冲突。请运行 "asc guard unbind" 或 "asc guard disable" 禁用 Guard。',
    },
```

- [ ] **Step 3: 提交**

```bash
git add src/asc/exceptions.py src/asc/error_handler.py
git commit -m "feat: add custom exception classes (MissingConfigError, MissingFileError, InvalidInputError, GuardViolationError)"
```

---

## Task 3: 改造 build.py 集成 get_action_hint

**Files:**
- Modify: `src/asc/commands/build.py`

- [ ] **Step 1: 在 build.py 顶部添加导入**

在 `from asc.commands.build_inputs import prepare_build_inputs` 后添加：

```python
from asc.error_handler import get_action_hint
```

- [ ] **Step 2: 改造所有 except 块**

将所有 `except (RuntimeError, ValueError) as e:` 块改为：

```python
except (RuntimeError, ValueError) as e:
    typer.echo(f"❌ {e}", err=True)
    hint = get_action_hint(e)
    if hint:
        typer.echo(f"💡 {hint}", err=True)
    raise typer.Exit(1)
```

（共有 5 处需要修改：line 307, 321, 451, 526, 550）

- [ ] **Step 3: 运行测试验证**

Run: `pytest tests/test_build.py -v`
Expected: All tests PASS

- [ ] **Step 4: 提交**

```bash
git add src/asc/commands/build.py
git commit -m "feat(build): add action hints to error messages"
```

---

## Task 4: 改造 build_inputs.py 错误消息

**Files:**
- Modify: `src/asc/commands/build_inputs.py`

- [ ] **Step 1: 导入 get_action_hint**

在文件顶部添加：

```python
from asc.error_handler import get_action_hint
```

- [ ] **Step 2: 在 detect_project 函数中改进 ValueError 消息**

修改 `build_inputs.py:291`：
```python
# 旧
raise ValueError(f"No Xcode project or workspace found in: {path}")
# 保持异常不变（get_action_hint 根据消息模式提供 hint）
```

- [ ] **Step 3: 修改 find_profiles 函数中的错误消息**

修改 `build_inputs.py:247`：
```python
# 旧
raise RuntimeError(f"找不到可用的{label}")
# 新
raise RuntimeError(f"找不到可用的{label}，请在 Apple Developer 下载并安装")
```

- [ ] **Step 4: 修改 security cms 错误消息**

修改 `build_inputs.py:65`：
```python
# 旧
raise RuntimeError(f"security cms failed for {path}")
# 新
raise RuntimeError(f"签名证书解析失败（security cms failed）。请尝试重新从 Apple Developer 下载证书：{path}")
```

- [ ] **Step 5: 修改 missing ExpirationDate 错误消息**

修改 `build_inputs.py:82`：
```python
# 旧
raise RuntimeError(f"Provisioning profile missing ExpirationDate: {path}")
# 新
raise RuntimeError(f"证书已过期或损坏：{path}。请重新从 Apple Developer 下载。")
```

- [ ] **Step 6: 修改 xcodebuild -list failed 消息**

修改 `build_inputs.py:302`：
```python
# 旧
raise RuntimeError(f"xcodebuild -list failed:\n{result.stderr}")
# 新
raise RuntimeError(f"无法获取 Xcode scheme 列表。请确认 --project 路径指向有效的 Xcode 项目。")
```

- [ ] **Step 7: 在 prepare_build_inputs 的 except 块添加 hint**

修改 `build_inputs.py:357` 附近的 except 块（如果存在），确保调用 `get_action_hint`。

- [ ] **Step 8: 运行测试验证**

Run: `pytest tests/test_build_inputs.py -v`
Expected: All tests PASS

- [ ] **Step 9: 提交**

```bash
git add src/asc/commands/build_inputs.py
git commit -m "feat(build_inputs): improve error messages with actionable hints"
```

---

## Task 5: 改造 metadata.py 错误消息

**Files:**
- Modify: `src/asc/commands/metadata.py`

- [ ] **Step 1: 导入 get_action_hint**

在文件顶部导入部分添加：

```python
from asc.error_handler import get_action_hint
```

- [ ] **Step 2: 为 CSV not found 添加 hint**

在所有 `CSV 文件不存在` 的 echo 后添加 hint：

```python
typer.echo(f"❌ CSV 文件不存在: {csv_path}", err=True)
typer.echo(f"💡 可使用 --csv 参数指定其他路径，或参考 'asc upload --help'", err=True)
```

找到所有相关位置（行 401, 447, 494, 548, 601）。

- [ ] **Step 3: 为 API 连接失败添加 hint**

修改 `metadata.py:789`：
```python
# 旧
typer.echo(f"❌ API 连接失败: {e}", err=True)
# 新
typer.echo(f"❌ API 连接失败: {e}", err=True)
typer.echo(f"💡 请检查网络连接，或稍后重试。", err=True)
```

- [ ] **Step 4: 为 GuardViolationError 添加 hint**

修改所有 `GuardViolationError` 的 echo 后添加 hint：
```python
typer.echo(f"❌ {e}", err=True)
typer.echo(f"💡 请运行 'asc guard unbind' 解除绑定，或 'asc guard disable' 禁用 Guard。", err=True)
```

- [ ] **Step 5: 提交**

```bash
git add src/asc/commands/metadata.py
git commit -m "feat(metadata): add action hints to error messages"
```

---

## Task 6: 改造 guard.py 错误消息

**Files:**
- Modify: `src/asc/guard.py`

- [ ] **Step 1: 修改 IOPlatformUUID not found 错误**

修改 `guard.py:33`：
```python
# 旧
raise RuntimeError("IOPlatformUUID not found")
# 新
raise RuntimeError("无法获取机器标识符。Guard 功能仅在 macOS 上可用。在 CI 环境请使用 'asc guard disable' 禁用。")
```

- [ ] **Step 2: 修改 All IP endpoints failed 错误**

修改 `guard.py:44`：
```python
# 旧
raise RuntimeError("All IP endpoints failed")
# 新
raise RuntimeError("无法获取公网 IP 地址。请检查网络连接，或使用 'asc guard disable' 禁用 Guard。")
```

- [ ] **Step 3: 运行测试验证**

Run: `pytest tests/test_guard.py -v`
Expected: All tests PASS

- [ ] **Step 4: 提交**

```bash
git add src/asc/guard.py
git commit -m "feat(guard): improve system error messages with user-friendly guidance"
```

---

## Task 7: 改造 utils.py 配置缺失错误

**Files:**
- Modify: `src/asc/utils.py`

- [ ] **Step 1: 导入 get_action_hint**

在文件顶部添加：

```python
from asc.error_handler import get_action_hint
```

- [ ] **Step 2: 改进 make_api_from_config 的 Missing required config 消息**

修改 `utils.py:313-318`：
```python
# 旧
typer.echo(
    f"❌ Missing required config: {', '.join(missing)}\n"
    "Run 'asc app add <name>' to configure an app profile, or set environment variables.",
    err=True,
)
raise typer.Exit(1)
# 新
typer.echo(
    f"❌ Missing required config: {', '.join(missing)}",
    err=True,
)
typer.echo(
    f"💡 Run 'asc app edit <name>' to add missing config, or run 'asc init' to set up.",
    err=True,
)
raise typer.Exit(1)
```

- [ ] **Step 3: 提交**

```bash
git add src/asc/utils.py
git commit -m "feat(utils): improve config missing error with actionable hint"
```

---

## Task 8: 改造 iap.py 错误消息

**Files:**
- Modify: `src/asc/commands/iap.py`

- [ ] **Step 1: 导入 get_action_hint 并修改错误消息**

```python
from asc.error_handler import get_action_hint
```

修改 `iap.py:231`（IAP 配置文件不存在）：
```python
typer.echo(f"❌ IAP 配置文件不存在: {iap_path}", err=True)
typer.echo(f"💡 可使用 --iap-file 参数指定其他路径。", err=True)
```

- [ ] **Step 2: 提交**

```bash
git add src/asc/commands/iap.py
git commit -m "feat(iap): add action hints to error messages"
```

---

## Task 9: 改造 whats_new.py 错误消息

**Files:**
- Modify: `src/asc/commands/whats_new.py`

- [ ] **Step 1: 导入 get_action_hint**

```python
from asc.error_handler import get_action_hint
```

- [ ] **Step 2: 修改文件不存在错误**

修改 `whats_new.py:151`：
```python
typer.echo(f"❌ 文件不存在: {file_path}", err=True)
typer.echo(f"💡 请检查文件路径是否正确，或使用 --text 直接指定内容。", err=True)
```

- [ ] **Step 3: 提交**

```bash
git add src/asc/commands/whats_new.py
git commit -m "feat(whats_new): add action hints to error messages"
```

---

## Task 10: 改造 screenshots.py 错误消息

**Files:**
- Modify: `src/asc/commands/screenshots.py`

- [ ] **Step 1: 导入 get_action_hint**

```python
from asc.error_handler import get_action_hint
```

- [ ] **Step 2: 修改截图目录不存在错误**

在 `screenshots.py:60` 的 echo 后添加：
```python
typer.echo(f"💡 可使用 --screenshots-dir 参数指定其他路径。", err=True)
```

- [ ] **Step 3: 提交**

```bash
git add src/asc/commands/screenshots.py
git commit -m "feat(screenshots): add action hints to error messages"
```

---

## Task 11: 改造 subscriptions.py 错误消息

**Files:**
- Modify: `src/asc/commands/subscriptions.py`

- [ ] **Step 1: 导入 get_action_hint**

```python
from asc.error_handler import get_action_hint
```

- [ ] **Step 2: 为 GuardViolationError 添加 hint**

在所有 `except GuardViolationError as e:` 块中添加 hint。

- [ ] **Step 3: 提交**

```bash
git add src/asc/commands/subscriptions.py
git commit -m "feat(subscriptions): add action hints to error messages"
```

---

## Task 12: 为 get_action_hint 编写测试

**Files:**
- Modify: `tests/test_error_handler.py`

- [ ] **Step 1: 编写 get_action_hint 测试**

在 `test_error_handler.py` 末尾添加：

```python
class TestGetActionHint:
    """Tests for get_action_hint() function."""

    def test_hint_for_missing_xcode_project(self):
        """No Xcode project error returns actionable hint."""
        from asc.error_handler import get_action_hint
        exc = ValueError("No Xcode project or workspace found in: .")
        hint = get_action_hint(exc)
        assert hint is not None
        assert "asc init" in hint or "--project" in hint

    def test_hint_for_csv_not_found(self):
        """CSV not found returns actionable hint."""
        from asc.error_handler import get_action_hint
        exc = ValueError("CSV 文件不存在: data/appstore_info.csv")
        hint = get_action_hint(exc)
        assert hint is not None
        assert "--csv" in hint or "asc upload" in hint

    def test_hint_for_guard_violation(self):
        """Guard violation returns actionable hint."""
        from asc.error_handler import get_action_hint
        exc = ValueError("GuardViolationError: credential conflict")
        hint = get_action_hint(exc)
        assert hint is not None
        assert "asc guard" in hint

    def test_hint_for_401_error(self):
        """401 error returns hint about credentials."""
        from asc.error_handler import get_action_hint
        exc = ValueError("API error [401]")
        hint = get_action_hint(exc)
        assert hint is not None
        assert "credentials" in hint.lower() or "凭证" in hint

    def test_no_hint_for_unknown_error(self):
        """Unknown error returns None."""
        from asc.error_handler import get_action_hint
        exc = ValueError("Some completely unknown error")
        hint = get_action_hint(exc)
        assert hint is None
```

- [ ] **Step 2: 运行测试验证**

Run: `pytest tests/test_error_handler.py::TestGetActionHint -v`
Expected: All tests PASS

- [ ] **Step 3: 提交**

```bash
git add tests/test_error_handler.py
git commit -m "test: add get_action_hint tests"
```

---

## Task 13: 集成测试 - 端到端验证

- [ ] **Step 1: 测试 asc build 在无 Xcode 项目时的错误消息**

Run: `cd /tmp && python -m asc build --app AppStore`
Expected: 显示 `❌ No Xcode project...` 和 `💡 可使用 --project 指定...`（而非 traceback）

- [ ] **Step 2: 测试 asc upload 在 CSV 不存在时的错误消息**

Run: `python -m asc --app AppStore upload --dry-run`
Expected: 显示 CSV not found 和 hint 建议使用 --csv

- [ ] **Step 3: 确认 debug 模式仍然显示完整 traceback**

Run: `ASC_DEBUG=1 python -m asc build --app AppStore`
Expected: 显示完整 traceback（不受影响）

---

## 实施检查清单

完成所有 Task 后，确认：

- [ ] `get_action_hint()` 覆盖所有用户级错误场景
- [ ] 所有 `except` 块输出 `💡` hint（除了真正的内部错误）
- [ ] `asc build` 在无项目时不再显示 traceback
- [ ] `asc guard disable` 能解决所有 Guard 相关错误
- [ ] 所有测试通过
