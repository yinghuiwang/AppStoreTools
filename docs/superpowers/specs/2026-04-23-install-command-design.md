# 安装命令设计文档

**日期：** 2026-04-23  
**状态：** 已批准

## 概述

两段式安装体系：

1. **`install.sh`** — Shell 脚本，负责环境检查和 `asc` 工具本身的安装（在 `asc` 尚未存在时运行）
2. **`asc install`** — CLI 子命令，负责项目级初始化和可选的 App profile 配置引导

## 第一部分：`install.sh`

**文件位置：** `install.sh`（项目根目录）

**用法：**
```bash
bash install.sh
# 或通过 curl 一键安装
curl -fsSL https://raw.githubusercontent.com/.../install.sh | bash
```

**执行流程：**

1. 检测操作系统（macOS / Linux）
2. 检查 Python 3.9+
   - 不存在或版本过低 → 打印平台专属安装提示并退出
   - macOS：`brew install python@3.12`
   - Linux：`apt install python3` / 推荐使用 `pyenv`
3. 检查 pip
   - 不存在 → 尝试运行 `python3 -m ensurepip --upgrade` 自动修复
   - 修复失败 → 打印手动安装说明并退出
4. 检查 git（不存在时打印警告，不阻断流程）
5. 检查 brew（仅 macOS，不存在时打印建议，不阻断流程）
6. 执行 `pip install asc-appstore-tools`
7. 验证 `asc --version` 可正常运行
8. 打印成功提示，引导用户运行 `asc install`

**退出码：**
- `0` — 成功
- `1` — 致命错误（Python 缺失 / 版本不兼容 / pip 安装失败）

## 第二部分：`asc install`

**实现位置：** `src/asc/commands/app_config.py` 中新增 `cmd_install`，在 `cli.py` 中注册为 `asc install` 命令

**复用逻辑：** 内部调用 `cmd_app_add`、`cmd_app_default`，不重复实现任何逻辑

**执行流程：**

1. 打印欢迎信息
2. 检查当前目录状态：
   - `.asc/config.toml` 已存在且包含 `default_app` → 打印"环境已就绪"，显示当前配置后退出
   - 否则 → 继续
3. 列出已有 profiles（调用 `config.list_apps()`）：
   - 有 profile → 显示列表，询问是否设置其中一个为默认
   - 无 profile → 跳至第 4 步
4. 询问："现在配置 App profile 吗？[y/N]"
   - 是 → 进入 `asc app add` 交互流程，完成后询问是否设为默认
   - 否 → 打印后续操作提示后退出
5. 完成后打印常用命令速查表

**命令关系：**

| 命令 | 职责 |
|------|------|
| `asc app add <name>` | 添加单个 profile（已有） |
| `asc app default <name>` | 设置默认 profile（已有） |
| `asc install` | 引导式初始化：添加 + 设默认（新增） |

## 涉及文件

| 文件 | 变更说明 |
|------|----------|
| `install.sh` | 新建文件 |
| `src/asc/commands/app_config.py` | 新增 `cmd_install` |
| `src/asc/cli.py` | 注册 `asc install` 命令 |
