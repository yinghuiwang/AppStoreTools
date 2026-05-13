# asc update --version 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 扩展 `asc update` 支持安装指定版本或分支，版本不存在时提示类似版本。

**Architecture:** 在 `update_cmd.py` 新增 `--version`/`--branch` 参数，调用 GitHub API 获取版本列表并实现相似版本推荐。

**Tech Stack:** Python, requests, typer, GitHub REST API

---

## 文件结构

```
src/asc/commands/
  update_cmd.py       # 修改：新增 --version/--branch 参数
README.md            # 修改：新增版本安装说明
tests/
  test_update_cmd.py # 新建：update_cmd 单元测试
```

---

## Task 1: 修改 update_cmd.py 新增参数

**Files:**
- Modify: `src/asc/commands/update_cmd.py:54-97`

- [ ] **Step 1: 修改 cmd_update 函数签名，添加新参数**

将：
```python
def cmd_update(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt (for CI/scripts)."),
):
```

改为：
```python
def cmd_update(
    version: Optional[str] = typer.Option(None, "--version", help="Install a specific version."),
    branch: Optional[str] = typer.Option(None, "--branch", help="Install from a specific branch."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt (for CI/scripts)."),
):
```

- [ ] **Step 2: 添加互斥检查**

在函数体开头添加：
```python
if version and branch:
    typer.echo("❌ Cannot use --version and --branch at the same time.", err=True)
    raise typer.Exit(1)
```

- [ ] **Step 3: 新增 _all_versions_from_github 函数**

在 `_latest_version_from_github` 函数后添加：
```python
def _all_versions_from_github() -> Optional[list[str]]:
    """Fetch all release versions from GitHub."""
    try:
        resp = requests.get(
            "https://api.github.com/repos/yinghuiwang/AppStoreTools/releases",
            timeout=8
        )
        resp.raise_for_status()
        releases = resp.json()
        versions = []
        for release in releases:
            tag = release.get("tag_name", "")
            if tag:
                versions.append(tag.lstrip("v"))
        return versions
    except Exception:
        return None
```

- [ ] **Step 4: 新增 _similar_versions 函数**

添加：
```python
def _similar_versions(target: str, all_versions: list[str], limit: int = 3) -> list[str]:
    """Return the most similar versions to target using version distance."""
    from packaging.version import Version

    def version_distance(v1: str, v2: str) -> int:
        try:
            p1 = Version(v1.lstrip("v"))
            p2 = Version(v2.lstrip("v"))
            # Distance based on major.minor.patch difference
            d1 = abs(p1.major - p2.major) * 1000
            d2 = abs(p1.minor - p2.minor) * 100
            d3 = abs(p1.micro - p2.micro) * 10
            return d1 + d2 + d3
        except Exception:
            # Fallback: string similarity
            return abs(len(v1) - len(v2))

    scored = [(version_distance(target, v), v) for v in all_versions]
    scored.sort()
    return [v for _, v in scored[:limit]]
```

- [ ] **Step 5: 修改版本解析逻辑**

将原来的 `latest` 更新逻辑改为分支处理：

```python
if branch:
    # Branch installation
    typer.echo(f"Installing from branch '{branch}'...")
    try:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "--quiet",
            f"git+https://github.com/yinghuiwang/AppStoreTools.git@{branch}",
        ])
        typer.echo(f"Done. asc installed from branch '{branch}'.")
    except subprocess.CalledProcessError:
        typer.echo("Update failed. Try manually:", err=True)
        typer.echo(f"  pip install git+https://github.com/yinghuiwang/AppStoreTools.git@{branch}", err=True)
        raise typer.Exit(1)
    return

if version:
    # Specific version installation
    target_version = version.lstrip("v")
    typer.echo(f"Installing version {target_version}...")

    # Check if version exists
    all_versions = _all_versions_from_github()
    if all_versions and f"v{target_version}" not in [f"v{v}" for v in all_versions]:
        similar = _similar_versions(target_version, all_versions)
        similar_str = ", ".join(f"v{v}" for v in similar) if similar else "N/A"
        typer.echo(f"❌ Version v{target_version} not found.", err=True)
        if similar:
            typer.echo(f"Similar versions: {similar_str}", err=True)
        raise typer.Exit(1)

    install_version = f"v{target_version}"
    try:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "--quiet",
            f"git+https://github.com/yinghuiwang/AppStoreTools.git@{install_version}",
        ])
        typer.echo(f"Done. asc updated to v{target_version}.")
    except subprocess.CalledProcessError:
        typer.echo("Update failed. Try manually:", err=True)
        typer.echo(f"  pip install git+https://github.com/yinghuiwang/AppStoreTools.git@{install_version}", err=True)
        raise typer.Exit(1)
    return

# Original latest update logic (unchanged)
current = _current_version()
typer.echo(f"Checking for updates...")
# ... rest of original logic
```

- [ ] **Step 6: 运行测试验证**

```bash
pytest tests/ -v -k update --tb=short
```

- [ ] **Step 7: 提交**

```bash
git add src/asc/commands/update_cmd.py
git commit -m "feat(update): add --version and --branch options"
```

---

## Task 2: 更新 README.md 文档

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 在 README.md 中找到 "## Installation" 或 "## Setup" 部分，添加新内容**

在安装命令后添加：

```markdown
### 更新到指定版本

```bash
asc update                    # 更新到最新版本
asc update --version 0.1.5    # 安装指定版本
asc update --branch main        # 从指定分支安装
```
```

- [ ] **Step 2: 提交**

```bash
git add README.md
git commit -m "docs: add update --version usage to README"
```

---

## Task 3: 编写测试 test_update_cmd.py

**Files:**
- Create: `tests/test_update_cmd.py`

- [ ] **Step 1: 创建测试文件**

```python
"""Tests for update_cmd module."""

from unittest.mock import patch, MagicMock
import pytest


class TestSimilarVersions:
    """Tests for _similar_versions function."""

    def test_similar_versions_returns_closest(self):
        """Should return closest versions to target."""
        from asc.commands.update_cmd import _similar_versions
        all_versions = ["0.1.5", "0.1.6", "0.1.7", "0.1.8", "0.2.0"]
        result = _similar_versions("0.1.5", all_versions, limit=3)
        # 0.1.5 should be first (exact match), then 0.1.6, 0.1.7
        assert result[0] == "0.1.5"
        assert len(result) == 3

    def test_similar_versions_with_nonexistent(self):
        """Should return similar versions for nonexistent target."""
        from asc.commands.update_cmd import _similar_versions
        all_versions = ["0.1.6", "0.1.7", "0.1.8"]
        result = _similar_versions("0.1.5", all_versions, limit=2)
        assert "0.1.6" in result
        assert "0.1.7" in result


class TestCmdUpdateValidation:
    """Tests for cmd_update parameter validation."""

    def test_version_and_branch_mutual_exclusion(self):
        """Should error when both --version and --branch provided."""
        from typer.testing import CliRunner
        from asc.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["update", "--version", "0.1.5", "--branch", "main"])
        assert result.exit_code == 1
        assert "Cannot use --version and --branch" in result.output
```

- [ ] **Step 2: 运行测试**

```bash
pytest tests/test_update_cmd.py -v
```

- [ ] **Step 3: 提交**

```bash
git add tests/test_update_cmd.py
git commit -m "test: add tests for update --version"
```

---

## Task 4: 端到端验证

- [ ] **Step 1: 验证 --version 和 --branch 互斥**

```bash
asc update --version 0.1.5 --branch main 2>&1 || true
```
Expected: `❌ Cannot use --version and --branch at the same time.`

- [ ] **Step 2: 验证 --version 版本不存在时提示类似版本**

```bash
asc update --version 99.99.99 2>&1 || true
```
Expected: 显示 `❌ Version v99.99.99 not found.` 和类似版本

- [ ] **Step 3: 确认不带参数时行为不变**

```bash
asc update --yes 2>&1 | head -5
```
Expected: 显示当前版本和检查更新流程
