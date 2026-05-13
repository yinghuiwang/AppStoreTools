# asc update --version 指定版本更新设计

## 目标

扩展 `asc update` 命令，支持安装指定版本、分支或历史版本。

## 现状

`asc update` 仅支持更新到 GitHub latest。

## 方案

### 1. 新增 CLI 参数

在 `update_cmd.py` 的 `cmd_update` 函数中新增：

| 参数 | 说明 | 示例 |
|------|------|------|
| `--version <version>` | 安装指定版本 | `asc update --version 0.1.5` |
| `--branch <branch>` | 从指定分支安装 | `asc update --branch main` |
| `--yes / -y` | 跳过确认（已有） | `asc update --version 0.1.5 --yes` |

**互斥约束：**
- `--version` 和 `--branch` 不可同时使用
- 不带参数时行为不变（更新到 latest）

### 2. 版本解析

- 自动补全 `v` 前缀（`0.1.5` → `v0.1.5`）
- 支持预发布版本（`0.2.0-beta`）

### 3. 版本不存在时的处理

调用 GitHub API `GET /repos/yinghuiwang/AppStoreTools/releases` 获取所有版本列表，计算相似版本：

```python
def _similar_versions(target: str, all_versions: list[str], limit=3) -> list[str]:
    """返回与目标版本最相似的版本列表"""
    # 使用版本距离算法，返回最接近的 N 个版本
```

**输出示例：**
```
❌ 版本 0.1.5 不存在。类似版本：0.1.6, 0.1.7, 0.1.8
```

### 4. 分支安装

```python
pip install git+https://github.com/yinghuiwang/AppStoreTools.git@<branch>
```

### 5. README 文档更新

在安装命令部分新增：

```markdown
### 更新到指定版本

```bash
asc update                    # 更新到最新版本
asc update --version 0.1.5    # 安装指定版本
asc update --branch main      # 从指定分支安装
```
```

### 6. 文件变更

- `src/asc/commands/update_cmd.py` — 新增 `--version`/`--branch` 参数
- `README.md` — 新增版本安装说明

## API 变更

| 用途 | API 端点 |
|------|---------|
| 获取 latest 版本 | `GET /repos/yinghuiwang/AppStoreTools/releases/latest` |
| 获取所有版本 | `GET /repos/yinghuiwang/AppStoreTools/releases` |

## 测试场景

1. `asc update --version 0.1.5` — 成功安装指定版本
2. `asc update --version 0.1.5 --yes` — 跳过确认
3. `asc update --version 0.1.5` — 版本不存在，提示类似版本
4. `asc update --version 0.1.5 --branch main` — 两者同时使用，报错
5. `asc update` — 更新到 latest（不变）
6. `asc update --branch feat-new` — 从分支安装
