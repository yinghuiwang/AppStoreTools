# Install Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现两段式安装体系：`install.sh` 负责环境检查与工具安装，`asc install` 负责项目初始化引导。

**Architecture:** `install.sh` 是纯 shell 脚本，顺序执行环境检查后调用 `pip install`；`asc install` 是新增的 typer 子命令，注册在顶层（非 `app` 子组），内部复用 `cmd_app_add` 和 `cmd_app_default` 的核心逻辑，不重复实现。

**Tech Stack:** Bash (install.sh), Python 3.9+, typer, pytest

---

## 文件清单

| 文件 | 操作 |
|------|------|
| `install.sh` | 新建 |
| `src/asc/commands/app_config.py` | 新增 `cmd_install` 函数 |
| `src/asc/cli.py` | 导入并注册 `cmd_install` 为 `asc install` |
| `tests/test_install_cmd.py` | 新建，测试 `cmd_install` |

---

## Task 1：新建 `install.sh`

**Files:**
- Create: `install.sh`

- [ ] **Step 1：写入 `install.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

info()    { echo -e "${GREEN}[✓]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*" >&2; }
fatal()   { error "$*"; exit 1; }

echo "================================================"
echo "  App Store Connect Tools — 安装程序"
echo "================================================"
echo ""

# ── 1. 检测操作系统 ──
OS="$(uname -s)"
case "$OS" in
  Darwin) PLATFORM="macOS" ;;
  Linux)  PLATFORM="Linux" ;;
  *)      fatal "不支持的操作系统: $OS" ;;
esac
info "操作系统: $PLATFORM"

# ── 2. 检查 Python 3.9+ ──
PYTHON=""
for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null; then
    VER=$("$cmd" -c 'import sys; print(sys.version_info[:2])' 2>/dev/null || true)
    MAJOR=$("$cmd" -c 'import sys; print(sys.version_info.major)' 2>/dev/null || true)
    MINOR=$("$cmd" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || true)
    if [ "${MAJOR:-0}" -ge 3 ] && [ "${MINOR:-0}" -ge 9 ]; then
      PYTHON="$cmd"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  error "未找到 Python 3.9 或更高版本。"
  if [ "$PLATFORM" = "macOS" ]; then
    echo "  安装方式：brew install python@3.12"
    echo "  或使用 pyenv：https://github.com/pyenv/pyenv"
  else
    echo "  安装方式：sudo apt install python3  （Debian/Ubuntu）"
    echo "  或使用 pyenv：https://github.com/pyenv/pyenv"
  fi
  exit 1
fi
info "Python: $($PYTHON --version)"

# ── 3. 检查 pip ──
if ! "$PYTHON" -m pip --version &>/dev/null; then
  warn "pip 未安装，尝试自动修复..."
  if "$PYTHON" -m ensurepip --upgrade &>/dev/null; then
    info "pip 已通过 ensurepip 安装"
  else
    error "pip 安装失败，请手动安装："
    echo "  https://pip.pypa.io/en/stable/installation/"
    exit 1
  fi
else
  info "pip: $($PYTHON -m pip --version | cut -d' ' -f1-2)"
fi

# ── 4. 检查 git（非阻断）──
if ! command -v git &>/dev/null; then
  warn "git 未安装（非必须，但建议安装）"
  if [ "$PLATFORM" = "macOS" ]; then
    echo "  安装方式：brew install git"
  else
    echo "  安装方式：sudo apt install git"
  fi
else
  info "git: $(git --version)"
fi

# ── 5. 检查 brew（仅 macOS，非阻断）──
if [ "$PLATFORM" = "macOS" ] && ! command -v brew &>/dev/null; then
  warn "Homebrew 未安装（可选）"
  echo "  安装方式：https://brew.sh"
fi

# ── 6. 安装 asc-appstore-tools ──
echo ""
echo "正在安装 asc-appstore-tools ..."
if "$PYTHON" -m pip install asc-appstore-tools; then
  info "asc-appstore-tools 安装成功"
else
  fatal "pip install 失败，请检查网络或权限后重试"
fi

# ── 7. 验证安装 ──
if ! command -v asc &>/dev/null; then
  warn "asc 命令未在 PATH 中找到，可能需要重新打开终端或添加 pip bin 到 PATH"
  echo "  尝试：$PYTHON -m asc --version"
else
  info "asc $(asc --version 2>/dev/null || $PYTHON -m asc --version)"
fi

# ── 8. 收尾 ──
echo ""
echo "================================================"
echo -e "  ${GREEN}安装完成！${NC}"
echo "================================================"
echo ""
echo "下一步：在你的项目目录中运行："
echo ""
echo "  asc install"
echo ""
echo "这将引导你配置 App Store Connect 凭证。"
```

- [ ] **Step 2：设置可执行权限**

```bash
chmod +x install.sh
```

- [ ] **Step 3：手动验证脚本语法无错误**

```bash
bash -n install.sh
```

预期输出：无任何输出（语法正确）

- [ ] **Step 4：Commit**

```bash
git add install.sh
git commit -m "feat: add install.sh for environment check and tool installation"
```

---

## Task 2：实现 `cmd_install`

**Files:**
- Modify: `src/asc/commands/app_config.py`
- Create: `tests/test_install_cmd.py`

- [ ] **Step 1：写入测试文件**

```python
"""Tests for cmd_install."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from typer.testing import CliRunner

from asc.cli import app

runner = CliRunner(mix_stderr=False)


def test_install_already_configured(tmp_path, monkeypatch):
    """When .asc/config.toml exists with default_app, print ready message and exit 0."""
    monkeypatch.chdir(tmp_path)
    asc_dir = tmp_path / ".asc"
    asc_dir.mkdir()
    (asc_dir / "config.toml").write_text('[defaults]\ndefault_app = "myapp"\n')

    with patch("asc.commands.app_config.Config") as MockConfig:
        mock_cfg = MagicMock()
        mock_cfg.list_apps.return_value = ["myapp"]
        MockConfig.return_value = mock_cfg

        result = runner.invoke(app, ["install"])

    assert result.exit_code == 0
    assert "已就绪" in result.output or "ready" in result.output.lower()


def test_install_no_profiles_user_skips(tmp_path, monkeypatch):
    """When no profiles exist and user says no, print next steps and exit 0."""
    monkeypatch.chdir(tmp_path)

    with patch("asc.commands.app_config.Config") as MockConfig:
        mock_cfg = MagicMock()
        mock_cfg.list_apps.return_value = []
        MockConfig.return_value = mock_cfg

        result = runner.invoke(app, ["install"], input="n\n")

    assert result.exit_code == 0
    assert "asc app add" in result.output


def test_install_shows_cheatsheet_on_completion(tmp_path, monkeypatch):
    """After successful setup, a command cheatsheet is printed."""
    monkeypatch.chdir(tmp_path)

    with patch("asc.commands.app_config.Config") as MockConfig:
        mock_cfg = MagicMock()
        mock_cfg.list_apps.return_value = []
        MockConfig.return_value = mock_cfg

        result = runner.invoke(app, ["install"], input="n\n")

    assert result.exit_code == 0
    assert "asc upload" in result.output
```

- [ ] **Step 2：运行测试，确认失败（命令尚未实现）**

```bash
pytest tests/test_install_cmd.py -v
```

预期：FAILED — `No such command 'install'`

- [ ] **Step 3：在 `app_config.py` 末尾添加 `cmd_install`**

在文件末尾追加：

```python
def cmd_install():
    """引导式项目初始化：检查环境，配置 App profile（可选）。

    适合首次在新项目中使用 asc 时运行。安装 asc 工具本身请先运行 install.sh。

    \b
    Example:
        asc install
    """
    typer.echo("=" * 52)
    typer.echo("  App Store Connect Tools — 项目初始化")
    typer.echo("=" * 52)
    typer.echo("")

    # ── 检查当前目录是否已配置 ──
    local_config = Path.cwd() / ".asc" / "config.toml"
    config = Config()
    apps = config.list_apps()

    if local_config.exists():
        content = local_config.read_text()
        if "default_app" in content:
            typer.echo("✅ 环境已就绪！当前目录已有默认配置：")
            typer.echo(f"   {local_config.relative_to(Path.cwd())}")
            typer.echo("")
            if apps:
                typer.echo("已配置的 profiles：")
                for name in apps:
                    typer.echo(f"  • {name}")
            typer.echo("")
            _print_cheatsheet()
            return

    # ── 列出已有 profiles ──
    if apps:
        typer.echo("已有以下 App profiles：")
        for name in apps:
            typer.echo(f"  • {name}")
        typer.echo("")
        set_default = typer.confirm("是否将其中一个设为默认？")
        if set_default:
            if len(apps) == 1:
                chosen = apps[0]
            else:
                typer.echo("请输入要设为默认的 profile 名称：")
                for i, name in enumerate(apps, 1):
                    typer.echo(f"  {i}. {name}")
                chosen = typer.prompt("Profile 名称")
                if chosen not in apps:
                    typer.echo(f"❌ '{chosen}' 不在列表中，跳过", err=True)
                    chosen = None
            if chosen:
                from asc.commands.app_config import cmd_app_default
                cmd_app_default(chosen)
                typer.echo("")
                _print_cheatsheet()
                return

    # ── 询问是否现在配置 ──
    typer.echo("尚未配置任何 App profile。")
    typer.echo("")
    configure_now = typer.confirm("现在配置 App profile 吗？")
    if not configure_now:
        typer.echo("")
        typer.echo("好的，稍后可运行：")
        typer.echo("")
        typer.echo("  asc app add <profile-name>")
        typer.echo("  asc app default <profile-name>")
        typer.echo("")
        _print_cheatsheet()
        return

    # ── 引导添加 profile ──
    profile_name = typer.prompt("请为此 App 起一个 profile 名称（如 myapp）")
    typer.echo("")
    cmd_app_add(profile_name)
    typer.echo("")

    set_as_default = typer.confirm(f"将 '{profile_name}' 设为本项目的默认 profile？")
    if set_as_default:
        cmd_app_default(profile_name)

    typer.echo("")
    _print_cheatsheet()


def _print_cheatsheet():
    """Print a quick-reference command cheatsheet."""
    typer.echo("─" * 52)
    typer.echo("  常用命令速查")
    typer.echo("─" * 52)
    typer.echo("  asc upload                上传元数据 + 截图")
    typer.echo("  asc metadata              仅上传元数据")
    typer.echo("  asc screenshots           仅上传截图")
    typer.echo("  asc whats-new --text '...'  更新版本描述")
    typer.echo("  asc iap --iap-file <f>    上传 IAP / 订阅")
    typer.echo("  asc check                 验证 API 连接")
    typer.echo("  asc app list              查看所有 profiles")
    typer.echo("─" * 52)
```

- [ ] **Step 4：运行测试，确认通过**

```bash
pytest tests/test_install_cmd.py -v
```

预期：3 个测试全部 PASSED

- [ ] **Step 5：Commit**

```bash
git add src/asc/commands/app_config.py tests/test_install_cmd.py
git commit -m "feat: add cmd_install with guided project initialization"
```

---

## Task 3：在 `cli.py` 中注册 `asc install`

**Files:**
- Modify: `src/asc/cli.py`

- [ ] **Step 1：更新导入并注册命令**

在 `src/asc/cli.py` 中找到以下行：

```python
from asc.commands.app_config import cmd_app_add, cmd_app_list, cmd_app_remove, cmd_app_default
```

替换为：

```python
from asc.commands.app_config import cmd_app_add, cmd_app_list, cmd_app_remove, cmd_app_default, cmd_install
```

在文件末尾的注册部分追加：

```python
app.command("install")(cmd_install)
```

- [ ] **Step 2：验证命令出现在帮助中**

```bash
asc --help
```

预期输出包含 `install` 行：
```
│ install    引导式项目初始化：检查环境，配置 App profile（可选）。
```

- [ ] **Step 3：运行全部测试确保无回归**

```bash
pytest tests/ -v
```

预期：全部 PASSED

- [ ] **Step 4：Commit**

```bash
git add src/asc/cli.py
git commit -m "feat: register asc install command in cli"
```

---

## Task 4：更新 README

**Files:**
- Modify: `README.md`

- [ ] **Step 1：更新快速开始章节**

在 README.md 的"快速开始"代码块中，将：

```bash
# 2. 添加应用配置（交互式）
asc app add myapp

# 3. 设置为默认配置（可省略 --app）
asc app default myapp

# 4. 运行
asc upload
```

替换为：

```bash
# 2. 初始化项目（引导式配置）
asc install

# 3. 运行
asc upload
```

- [ ] **Step 2：在用法章节新增 install 和 install.sh 说明**

在"管理应用配置"注释块之前插入：

```bash
# 全新机器：先运行环境安装脚本
bash install.sh        # 检查 Python/pip/git，安装 asc 工具

# 然后在项目目录中初始化
asc install            # 引导配置 App profile，设置默认 profile
```

- [ ] **Step 3：Commit**

```bash
git add README.md
git commit -m "docs: update README with asc install and install.sh usage"
```

---

## Task 5：推送

- [ ] **Step 1：推送所有提交**

```bash
git push
```

预期：推送成功，无冲突
