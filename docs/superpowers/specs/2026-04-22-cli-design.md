# asc CLI — 设计文档

**日期：** 2026-04-22  
**状态：** 已确认

## 目标

将现有的 `run.sh` + `upload_to_appstore.py` 脚本组合重构为一个标准 Python CLI 包，命令名 `asc`，可通过 `pip install asc-appstore-tools` 安装，支持多 App 配置管理，并通过 GitHub Actions 在打 tag 时自动发布到 PyPI。

## 包结构

```
src/
└── asc/
    ├── __init__.py          # 版本号（__version__）
    ├── __main__.py          # python -m asc 入口
    ├── cli.py               # typer app，所有子命令注册
    ├── api.py               # AppStoreConnectAPI 类（JWT 自动刷新 + REST 请求）
    ├── config.py            # 配置加载，实现全局/本地优先级
    ├── constants.py         # DISPLAY_TYPE_BY_SIZE、locale 映射表等常量
    └── commands/
        ├── __init__.py
        ├── metadata.py      # upload、metadata、keywords、URL 类命令
        ├── screenshots.py   # screenshots 命令
        ├── iap.py           # iap 命令
        └── whats_new.py     # whats-new 命令

pyproject.toml               # 包元信息、依赖声明、CLI 入口点
.github/
└── workflows/
    └── publish.yml          # tag v*.*.* 触发的 PyPI 自动发布

docs/superpowers/specs/      # 本文件所在位置
```

`run.sh` 废弃（pip 安装后依赖自动就绪，无需 shell 封装）。

## CLI 命令接口

`--app NAME` 和 `--dry-run` 是全局选项，可加在任意子命令前。

```
# 上传类
asc upload                                         全量上传（元数据 + 截图）
asc metadata                                       仅元数据
asc keywords                                       仅关键词
asc support-url                                    从 CSV 上传支持链接
asc marketing-url                                  从 CSV 上传营销链接
asc privacy-policy-url                             从 CSV 上传隐私政策链接
asc screenshots [--display-type TYPE]              截图
asc iap --iap-file PATH                            IAP 包
asc whats-new (--text TEXT | --file PATH) [--locales zh-Hans,en-US]

# 直接设置 URL
asc set-support-url --text URL [--locales ...]
asc set-marketing-url --text URL [--locales ...]
asc set-privacy-policy-url --text URL [--locales ...]

# App 配置管理
asc app add NAME       交互式添加 App 凭证，私钥复制到 ~/.config/asc/keys/
asc app list           列出所有已配置的 App
asc app remove NAME    删除一个 App 配置

# 环境检查
asc check              验证当前 App 配置是否有效（凭证 + API 连通性）
```

省略 `--app` 时，优先使用本地 `.asc/config.toml` 中的 `default_app`；若未设定则报错提示。

## 配置系统

优先级从高到低：

1. CLI 参数（`--app`、`--csv`、`--screenshots` 等）
2. 本地配置：`./.asc/config.toml`（当前项目目录，加入 `.gitignore`）
3. 全局配置：`~/.config/asc/profiles/<name>.toml`
4. 环境变量（`ISSUER_ID`、`KEY_ID` 等，向后兼容现有 `.env` 文件）

全局配置文件格式（TOML）：

```toml
# ~/.config/asc/profiles/<name>.toml
[credentials]
issuer_id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
key_id    = "XXXXXXXXXX"
key_file  = "~/.config/asc/keys/AuthKey_XXXXXXXXXX.p8"
app_id    = "1234567890"

[defaults]
csv         = "data/appstore_info.csv"
screenshots = "data/screenshots"
```

本地配置（项目级，仅存 default_app）：

```toml
# ./.asc/config.toml
default_app = "myjmhsapp"
```

`config.py` 保留对现有 `config/.env` 格式的兼容读取，迁移期间无需改动已有配置文件。

## PyPI 发布流程

`pyproject.toml` 关键配置：

```toml
[project]
name            = "asc-appstore-tools"
version         = "0.1.0"
requires-python = ">=3.9"
dependencies    = [
    "typer>=0.12",
    "PyJWT>=2.8",
    "cryptography>=41",
    "requests>=2.31",
    "Pillow>=10",
    "python-dotenv>=1.0",
]

[project.scripts]
asc = "asc.cli:app"

[build-system]
requires      = ["hatchling"]
build-backend = "hatchling.build"
```

版本号单一来源：`src/asc/__init__.py` 的 `__version__`，`pyproject.toml` 通过 hatchling 动态读取。

GitHub Actions 发布流程（`.github/workflows/publish.yml`）：

- 触发条件：`push` 且 tag 匹配 `v*.*.*`
- 步骤：checkout → `pip install build` → `python -m build` → `twine upload`（使用 `PYPI_API_TOKEN` secret）

本地开发：

```bash
pip install -e ".[dev]"        # 可编辑安装，asc 命令立即可用
git tag v1.0.0 && git push --tags   # 触发 PyPI 发布
```

## 迁移说明

- `upload_to_appstore.py` 中的 `AppStoreConnectAPI` 类迁移到 `api.py`，接口不变
- 各 `upload_*()` 函数迁移到对应 `commands/` 模块
- 常量表（`DISPLAY_TYPE_BY_SIZE` 等）迁移到 `constants.py`
- `argparse` 的 `main()` 由 `cli.py` 的 typer app 替代
- `run.sh` 不再维护，保留但标记为 deprecated
