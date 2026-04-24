---
title: App Store Connect 单应用绑定守卫功能
date: 2026-04-24
status: approved
---

# App Store Connect 单应用绑定守卫功能设计文档

## 概述

为 `asc` CLI 工具添加守卫功能，限制同一机器、IP 地址或 API 凭证只能用于上传和发布一款 App。当检测到违反限制时，显示警告并要求用户确认后才能继续。此功能默认启用，可通过配置或命令关闭。

## 需求背景

防止开发者意外使用同一环境（机器、网络、凭证）发布多个不同的 App，避免配置混淆和误操作。

## 核心约束

1. **三重绑定机制**：机器指纹、公网 IP、API 凭证（key_id）各自独立绑定到一个 App ID
2. **写操作触发检查**：所有修改 App Store Connect 数据的命令触发检查（`upload`, `metadata`, `screenshots`, `iap`, `deploy`, `release` 等）
3. **警告 + 确认模式**：检测到冲突时显示详细警告，用户输入 `yes` 确认后可继续并更新绑定
4. **默认启用**：新安装或升级后首次使用时自动启用并静默创建绑定
5. **灵活管理**：提供全局配置开关和专用命令管理绑定记录

## 架构设计

### 方案选择

采用**集中式守卫模块**方案：

- 新增独立的 `src/asc/guard.py` 模块
- 绑定记录存储在 `~/.config/asc/guard.json`
- 新增 `asc guard` 子命令组管理守卫功能
- 在所有写操作命令入口处调用守卫检查

**优势**：职责分离清晰、易于测试维护、用户体验直观、性能合理。

## 数据结构与存储

### 绑定记录存储格式

**文件位置**：`~/.config/asc/guard.json`

**数据结构**：
```json
{
  "enabled": true,
  "bindings": {
    "machine": {
      "<machine_fingerprint>": {
        "app_id": "com.example.myapp",
        "app_name": "myapp",
        "bound_at": "2026-04-24T10:30:00Z",
        "last_checked": "2026-04-24T15:45:00Z"
      }
    },
    "ip": {
      "<ip_address>": {
        "app_id": "com.example.myapp",
        "app_name": "myapp",
        "bound_at": "2026-04-24T10:30:00Z",
        "last_checked": "2026-04-24T15:45:00Z"
      }
    },
    "credential": {
      "<key_id>": {
        "app_id": "com.example.myapp",
        "app_name": "myapp",
        "issuer_id": "xxx-xxx-xxx",
        "bound_at": "2026-04-24T10:30:00Z",
        "last_checked": "2026-04-24T15:45:00Z"
      }
    }
  }
}
```

### 标识符获取策略

**机器指纹生成**：
- macOS：使用 `ioreg -rd1 -c IOPlatformExpertDevice | grep IOPlatformUUID` 获取硬件 UUID
- 备用方案：`platform.node()` (主机名) + `uuid.getnode()` (MAC 地址) 的哈希值

**公网 IP 获取**：
- 使用 `https://api.ipify.org` 或 `https://ifconfig.me/ip` 获取公网 IP
- 失败时记录为 "unknown"，不阻止操作但记录警告

## 核心模块设计

### Guard 类接口

**文件**：`src/asc/guard.py`

**核心方法**：

```python
class Guard:
    def __init__(self):
        """加载守卫配置和绑定记录"""
        
    def is_enabled(self) -> bool:
        """检查守卫功能是否启用"""
        
    def check_and_enforce(self, app_id: str, app_name: str, 
                          key_id: str, issuer_id: str) -> None:
        """
        检查并强制执行限制。
        如果检测到冲突，显示警告并提示用户确认。
        用户拒绝时抛出 GuardViolationError 终止命令。
        """
        
    def bind(self, app_id: str, app_name: str, 
             key_id: str, issuer_id: str) -> None:
        """创建新的绑定记录（机器、IP、凭证）"""
        
    def unbind(self, target: str, value: str) -> None:
        """解除绑定：target 可以是 'machine', 'ip', 'credential'"""
        
    def get_status(self) -> dict:
        """返回当前所有绑定状态，用于 asc guard status 命令"""
```

### 冲突检测与用户交互

**检测逻辑**：
1. 获取当前机器指纹、IP、凭证 key_id
2. 检查三个维度是否已绑定到其他 App
3. 如果任一维度冲突，收集所有冲突信息

**用户交互示例**：
```
⚠️  检测到 App 绑定冲突：

  • 机器指纹 (a1b2c3d4...) 已绑定到: com.example.otherapp (otherapp)
    绑定时间: 2026-04-20 10:30:00
    
  • IP 地址 (203.0.113.42) 已绑定到: com.example.otherapp (otherapp)
    绑定时间: 2026-04-20 10:30:00
    
  • API 凭证 (KEY123) 已绑定到: com.example.otherapp (otherapp)
    绑定时间: 2026-04-20 10:30:00

当前尝试操作的 App: com.example.myapp (myapp)

此限制旨在防止意外使用同一环境发布多个 App。
如需继续，请输入 'yes' 确认，或使用 'asc guard unbind' 解除绑定。

是否继续? [yes/no]: 
```

**用户响应处理**：
- 输入 `yes`：更新绑定记录到当前 App，继续执行命令
- 输入 `no` 或其他内容：抛出 `GuardViolationError`，命令终止，退出码 1

## 命令行接口

### asc guard 子命令组

**新增命令**：

```bash
# 查看当前绑定状态
asc guard status

# 启用守卫功能（默认已启用）
asc guard enable

# 禁用守卫功能
asc guard disable

# 解除特定绑定
asc guard unbind --machine <fingerprint>
asc guard unbind --ip <ip_address>
asc guard unbind --credential <key_id>

# 解除所有绑定
asc guard reset

# 解除当前机器/IP/凭证的所有绑定
asc guard unbind --current
```

**status 命令输出示例**：

```
守卫状态: ✅ 已启用

当前环境:
  机器指纹: a1b2c3d4e5f6...
  IP 地址: 203.0.113.42
  API 凭证: KEY123 (issuer: ISS456)

绑定记录:
  ┌─────────────┬──────────────────────┬─────────────┬─────────────────────┐
  │ 类型        │ 标识                 │ 绑定 App    │ 绑定时间            │
  ├─────────────┼──────────────────────┼─────────────┼─────────────────────┤
  │ 机器        │ a1b2c3d4e5f6...      │ myapp       │ 2026-04-20 10:30:00 │
  │ IP          │ 203.0.113.42         │ myapp       │ 2026-04-20 10:30:00 │
  │ 凭证        │ KEY123               │ myapp       │ 2026-04-20 10:30:00 │
  └─────────────┴──────────────────────┴─────────────┴─────────────────────┘

提示: 使用 'asc guard unbind' 解除绑定
```

### 与现有命令集成

**需要添加守卫检查的命令**：
- `src/asc/commands/metadata.py` - `cmd_upload()`, `cmd_metadata()` 等
- `src/asc/commands/screenshots.py` - `cmd_screenshots()`
- `src/asc/commands/iap.py` - `cmd_iap()`
- `src/asc/commands/subscriptions.py` - 订阅相关命令
- `src/asc/commands/whats_new.py` - `cmd_whats_new()`
- `src/asc/commands/build.py` - `cmd_deploy()`, `cmd_release()`

**集成代码模式**：

```python
from asc.guard import Guard, GuardViolationError

def cmd_upload(...):
    config = Config(app)
    
    # 守卫检查
    try:
        guard = Guard()
        if guard.is_enabled():
            guard.check_and_enforce(
                app_id=config.app_id,
                app_name=config.app_name or app,
                key_id=config.key_id,
                issuer_id=config.issuer_id
            )
    except GuardViolationError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(1)
    
    # 原有逻辑...
```

## 错误处理与边缘情况

### 异常类定义

```python
class GuardError(Exception):
    """守卫功能基础异常"""
    pass

class GuardViolationError(GuardError):
    """用户拒绝继续操作时抛出"""
    pass

class GuardConfigError(GuardError):
    """配置文件损坏或无法读取"""
    pass
```

### 边缘情况处理策略

**1. 首次使用（无绑定记录）**
- 自动创建绑定，静默执行
- 在命令输出末尾显示提示：`ℹ️  已绑定当前环境到 App: myapp`

**2. IP 获取失败**
- 记录为 "unknown"，不阻止操作
- 在日志中记录警告：`⚠️  无法获取公网 IP，跳过 IP 绑定检查`
- 不影响机器指纹和凭证的检查

**3. 机器指纹获取失败**
- 降级到备用方案（主机名 + MAC 地址哈希）
- 如果备用方案也失败，记录错误但不阻止操作
- 显示警告：`⚠️  无法生成机器指纹，守卫功能部分失效`

**4. 配置文件损坏**
- 尝试备份损坏的文件到 `guard.json.backup`
- 创建新的空配置文件
- 显示警告：`⚠️  守卫配置文件损坏，已重置。旧文件备份至 guard.json.backup`

**5. 用户中断（Ctrl+C）**
- 在等待用户输入 yes/no 时按 Ctrl+C
- 捕获 `KeyboardInterrupt`，视为拒绝操作
- 显示：`❌ 操作已取消`，退出码 130

**6. 非交互式环境（CI/CD）**
- 检测 `sys.stdin.isatty()` 为 False
- 如果检测到冲突，直接终止，不提示输入
- 显示：`❌ 检测到绑定冲突且当前为非交互式环境，操作终止`
- 提供环境变量 `ASC_GUARD_DISABLE=1` 可在 CI 中临时禁用

**7. 缺少必要凭证信息**
- 如果 `config.app_id` 或 `config.key_id` 为 None
- 跳过守卫检查，显示警告：`⚠️  缺少 App ID 或凭证信息，跳过守卫检查`

## 测试策略

### 单元测试（`tests/test_guard.py`）

- 机器指纹生成（mock subprocess 和 platform 调用）
- IP 获取（mock HTTP 请求）
- 绑定记录的 CRUD 操作
- 冲突检测逻辑（各种组合场景）
- 配置文件损坏恢复
- 非交互式环境检测

### 集成测试（`tests/test_guard_integration.py`）

- 完整的用户交互流程（mock `typer.prompt`）
- 与 Config 类的集成
- 命令行参数解析（`asc guard` 子命令）
- 环境变量 `ASC_GUARD_DISABLE=1` 的效果

### 端到端测试

- 在实际命令中触发守卫检查（使用 `--dry-run` 避免真实上传）
- 测试 `asc guard status` 输出格式
- 测试 `asc guard unbind` 各种参数组合

## 实现顺序

### 阶段 1：核心守卫模块
1. 实现 `Guard` 类基础结构
2. 实现机器指纹和 IP 获取
3. 实现绑定记录的读写
4. 单元测试

### 阶段 2：冲突检测与交互
1. 实现 `check_and_enforce()` 方法
2. 实现用户交互提示
3. 异常处理
4. 集成测试

### 阶段 3：命令行接口
1. 实现 `asc guard` 子命令组
2. 实现 `status`, `enable`, `disable`, `unbind`, `reset` 命令
3. 命令行测试

### 阶段 4：集成到现有命令
1. 在所有写操作命令中添加守卫检查
2. 端到端测试
3. 文档更新（README, CLAUDE.md）

## 依赖关系

### 新增依赖

无需新增 pip 依赖，使用 Python 标准库：
- `subprocess` - 获取机器指纹
- `urllib.request` - 获取公网 IP
- `platform`, `uuid` - 备用指纹方案
- `json` - 配置文件读写
- `datetime` - 时间戳记录

### 向后兼容性

- 默认启用守卫功能，但首次使用时静默绑定
- 现有用户升级后首次运行会自动创建绑定
- 不影响现有配置文件结构（`~/.config/asc/profiles/*.toml` 保持不变）
- 守卫配置独立存储在 `~/.config/asc/guard.json`

## 配置选项

### 全局配置开关

用户可在 `~/.config/asc/config.toml` 中添加：

```toml
[guard]
enabled = false  # 全局禁用守卫功能
```

### 环境变量

- `ASC_GUARD_DISABLE=1` - 临时禁用守卫功能（适用于 CI/CD）

### 优先级

环境变量 > 命令行 `asc guard disable` > 配置文件

## 安全考虑

1. **敏感信息保护**：机器指纹和 IP 地址仅存储在本地 `~/.config/asc/guard.json`，不上传到任何服务器
2. **文件权限**：`guard.json` 创建时设置为 `0600`（仅所有者可读写）
3. **备份机制**：配置文件损坏时自动备份，防止数据丢失
4. **审计日志**：记录每次检查的时间戳（`last_checked`），便于追溯

## 用户体验优化

1. **首次使用静默绑定**：避免打断用户工作流
2. **清晰的冲突提示**：显示所有冲突维度和绑定时间
3. **灵活的解绑方式**：支持按类型、按标识符、按当前环境解绑
4. **非交互式环境友好**：自动检测 CI/CD 环境，提供环境变量开关

## 文档更新

需要更新以下文档：

1. **README.md**：添加守卫功能说明和 `asc guard` 命令示例
2. **CLAUDE.md**：更新架构说明，添加 `guard.py` 模块描述
3. **新增文档**：`docs/guard-feature.md` 详细说明守卫功能的使用场景和最佳实践

## 总结

本设计通过集中式守卫模块实现了机器、IP、凭证三重绑定机制，在保证安全性的同时提供了灵活的管理方式。默认启用但可配置关闭，适应不同使用场景。实现分四个阶段，测试覆盖全面，向后兼容现有配置。
