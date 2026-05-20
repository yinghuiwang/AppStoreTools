# Whats-New 自动翻译功能设计

## 概述

为 `asc whats-new` 命令和 Web UI 新增大模型自动翻译功能。用户输入一段更新说明（任意语言），工具自动翻译到 App 所有可用的语言 locale，并可选择预览确认后再上传。

## 背景

当前 `whats-new` 命令仅支持用户手动为每个 locale 填写内容，或通过 `--file` 传入多语言文件。对于运营人员而言，需要为每个语言分别撰写或翻译内容，体验割裂。本功能让用户只需提供一种语言的内容，工具自动完成翻译并填入所有语言版本。

## 功能规格

### 1. CLI 功能

**新增参数：**
- `--translate`：启用自动翻译模式
- `--dry-run`：预览翻译结果，不上传

**使用方式：**
```bash
asc --app myapp whats-new --translate --text "Bug fixes and improvements"
asc --app myapp whats-new --translate --text "Bug fixes" --dry-run
```

**行为：**
1. 工具自动检测输入文本的语言（源语言）
2. 获取 App 版本的所有可用 locale 列表
3. 并发翻译到每个非源语言的目标 locale
4. 调用 App Store Connect API 上传每个 locale 的翻译结果
5. 单个 locale 翻译失败：跳过并警告，继续其他 locale

---

### 2. Web UI 功能

#### 2.1 Settings 页面 — LLM 配置

在现有 Settings 页面新增 LLM 配置区块：

```
[llm]
base_url = "https://api.openai.com/v1"
api_key = "sk-..."
model = "gpt-4o"
```

配置持久化到全局 profile 或本地 `.asc/config.toml`。

#### 2.2 Whats-New 页面 — 翻译预览流程

**Step 1 — 表单：**
- 语言选择（支持 Auto Detect）
- 文本输入框（支持多行）
- 翻译模式开关
- "预览翻译" 按钮（翻译后进入 Step 2）
- "直接上传" 按钮（不翻译，直接上传文本到所有 locale）

**Step 2 — 翻译预览：**
- 显示检测到的源语言
- 显示每个目标 locale 的翻译结果（可编辑）
- "取消" 按钮（返回 Step 1）
- "确认并上传" 按钮（上传到 App Store Connect）

---

### 3. 核心模块设计

```
src/asc/
├── llm.py                      # OpenAI 兼容 API 客户端
├── services/
│   └── translator.py          # 翻译服务（抽象接口 + OpenAI 实现）
├── commands/
│   └── whats_new.py           # 新增 --translate 支持
└── web/
    ├── routes_api.py          # 新增 /api/whats-new/* 路由
    ├── tasks.py               # 新增 whats-new 任务类型
    └── templates/
        ├── settings.html      # 新增 LLM 配置区块
        └── whats_new.html     # 新增页面
```

#### 3.1 `llm.py` — LLM HTTP 客户端

```python
class LLMClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: int = 60,
    )
    def chat(self, messages: list[dict], temperature: float = 0.3) -> str:
        """发送 chat 请求，返回 assistant 的消息内容"""
```

- 支持 OpenAI 兼容接口（`base_url` 可配置）
- 自动重试（3次），遇到 HTTP 429 或 5xx 等待后重试
- 超时控制（默认 60s）
- API Key 通过配置注入，不硬编码

#### 3.2 `services/translator.py` — 翻译服务

```python
class Translator(ABC):
    @abstractmethod
    def translate(self, text: str, target_locale: str, source_locale: str) -> str:
        """将 text 从 source_locale 翻译到 target_locale"""
        ...

class OpenAITranslator(Translator):
    def __init__(self, client: LLMClient)
    def translate(self, text, target_locale, source_locale) -> str:
        # 构建 prompt，调用 LLM，返回翻译结果
```

**Prompt 模板：**
```
你是一个专业的 App Store 应用更新说明翻译专家。
请将以下更新说明翻译成 {target_locale} 语言。

要求：
- 保持原文语气和格式
- 保持专业术语一致性（如 "TestFlight" 不翻译）
- 保持字符长度与原文相近
- 不要添加解释

源语言：{source_locale}
目标语言：{target_locale}

原文：
{text}
```

#### 3.3 `config.py` — LLM 配置

```python
class Config:
    @property
    def llm_api_key(self) -> Optional[str]: ...

    @property
    def llm_base_url(self) -> Optional[str]:
        """OpenAI 兼容 API base URL，默认 https://api.openai.com/v1"""

    @property
    def llm_model(self) -> str:
        """LLM 模型，默认 gpt-4o"""
```

---

### 4. API 路由设计

| 路由 | 方法 | 功能 |
|------|------|------|
| `/api/whats-new/check` | GET | 检查环境 + 获取可用 locale 列表 |
| `/api/whats-new/translate` | POST | 执行翻译，返回所有 locale 翻译结果 |
| `/api/whats-new/run` | POST | 执行上传（translations 数组） |

#### POST /api/whats-new/translate

**请求：**
```json
{
  "text": "Bug fixes and improvements.",
  "source_locale": "en-US"
}
```

**响应：**
```json
{
  "source_locale": "en-US",
  "translations": {
    "zh-CN": "错误修复和性能提升。",
    "ja-JP": "バグ修正とパフォーマンス向上。"
  }
}
```

#### POST /api/whats-new/run

**请求：**
```json
{
  "translations": {
    "en-US": "Bug fixes and improvements.",
    "zh-CN": "错误修复和性能提升。"
  },
  "dry_run": false
}
```

---

### 5. 错误处理策略

| 场景 | 行为 |
|------|------|
| 单个 locale 翻译失败 | 跳过并警告，继续其他 locale |
| 全部翻译失败 | 返回错误，不调用 App Store Connect API |
| 上传时单个 locale 失败 | 跳过并警告，最终汇总报告 |
| LLM 配置缺失 | 返回明确的配置错误提示 |

---

### 6. 配置文件格式

```toml
[llm]
provider = "openai"
base_url = "https://api.openai.com/v1"
model = "gpt-4o"
api_key = "sk-..."
```

---

## 测试计划

1. **翻译正确性**：输入英文文本，验证各语言翻译结果
2. **Dry Run 模式**：验证翻译后不上传
3. **源语言检测**：验证 Auto Detect 逻辑
4. **错误恢复**：模拟 LLM 超时，验证重试和跳过逻辑
5. **Web UI 流程**：完整走一遍表单 → 预览 → 确认上传流程
