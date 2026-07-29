# CSV 列标题默认英文（兼容中文）设计文档

**日期：** 2026-07-29  
**状态：** 待实现

---

## 目标

将 App Store 元数据 CSV 的**默认列标题**改为与 App Store Connect API 对齐的英文 canonical 名称；解析时**继续兼容现有中文列名**及历史中文同义别名。新建模板、示例数据、README、教程、Web UI 说明与 CLI help 全部以英文默认为准，并注明中文仍可用。

**非目标：**

- 不提供「中文 CSV → 英文表头」迁移子命令
- 不按 `ASC_LANG` 切换 `init` 模板语言
- 不改变 locale 单元格取值格式（`简体中文(zh-Hans)` / `en-US` 等仍有效）
- 不改变截图目录命名规则

---

## 背景

当前实现中：

- `parse_csv()` 清洗表头后原样作为 dict key 返回
- `metadata.py` 等业务层硬编码中文 key（`语言`、`应用名称`、…），并散落少量中文同义别名（如 `关键词`/`关键字`）
- `asc init` 的 `_CSV_TEMPLATE`、仓库 `data/appstore_info.csv`、文档与 Web UI 均以中文列名为唯一规范

这导致英文用户与 ASC API 字段名不一致，且别名逻辑分散、难维护。

---

## 决策摘要

| 项 | 选择 |
|---|---|
| 默认英文命名 | ASC API 风格 camelCase |
| 旧 CSV 兼容 | 只读兼容（解析认中英文；模板只产英文） |
| 解析后内部 key | 统一归一化为英文 canonical |
| 实现位置 | 中央别名表 + 在 `parse_csv` 唯一归一化 |

---

## Canonical 列与别名

权威映射放在 `src/asc/constants.py`（名称可微调，语义固定）：

| Canonical（默认表头 / 内部 key） | 可接受别名（读入） |
|---|---|
| `locale` | `语言` |
| `name` | `应用名称` |
| `subtitle` | `副标题` |
| `description` | `长描述`, `描述` |
| `keywords` | `关键词`, `关键字` |
| `supportUrl` | `技术支持链接`, `技术支持网址` |
| `marketingUrl` | `营销网站`, `营销网址` |
| `privacyPolicyUrl` | `隐私政策网址`, `隐私政策链接`, `隐私政策URL` |

**规则：**

1. 表头先 `strip` 并去掉包裹引号（保持现有清洗）；英文匹配**大小写敏感**，须与 canonical 完全一致（如 `supportUrl`，不认 `SupportUrl`）
2. 经别名表映射为 canonical；**未知列忽略**，不进入结果 dict
3. 冲突解析：按 CSV 列从左到右扫描非空值；若目标 canonical 尚未赋值则写入；若已赋值，**仅当当前列表头恰好是英文 canonical 名时才覆盖**（因此英文列优先于中文别名；多个中文同义列同时有值时，左侧先出现的生效）
4. 必填：至少能解析出 `locale`；无 `locale` 的行跳过（与现「无语言行跳过」一致）
5. `locale` 值仍走 `extract_locale()` / `normalize_locale_code()`

---

## 架构与数据流

```
CSV（中或英表头，可混用）
  → parse_csv()
      → 清洗表头
      → canonicalize → 仅 canonical key
      → extract_locale(locale)
  → list[dict[str, str]]
  → metadata / keywords / URL 命令、Web 上传任务
```

`parse_csv` 是**唯一**归一化点。业务层（`metadata.py`、Web `routes_api` 等）只读英文 key，不再出现中文 `.get()` 链。

建议提供小工具函数，例如 `canonicalize_csv_header(raw: str) -> str | None`，由 `parse_csv` 调用；别名表可被测试与文档对照表复用。

---

## 组件改动范围

| 区域 | 改动 |
|---|---|
| `constants.py` | 新增别名映射 + canonicalize 助手 |
| `utils.parse_csv` | 归一化；必填检查改为 `locale` |
| `commands/metadata.py` | 全部改为英文 key；删除中文别名查找 |
| `commands/app_config.py` | `_CSV_TEMPLATE` 改为英文表头与示例行 |
| `data/appstore_info.csv` | 表头改为英文 |
| Web UI | `metadata.html`、`profiles.html` 等列说明改为英文，并注明中文兼容 |
| 稳定文档 | 见下一节 |
| CLI help / docstring | 示例列名改为英文，一句说明中文别名仍可用 |
| 测试 | 英默认、中兼容、混用、冲突优先、init 模板断言 |

---

## 文档（稳定面）

以下凡写死中文列名处，改为**英文默认示例**，并附「兼容的中文列名」对照（与 constants 映射一致）：

- `README.md` / `README.zh-CN.md`
- `docs/tutorials/02-metadata-and-screenshots.md` 与 `.zh-CN.md`
- 其他教程/架构文中引用 CSV 列处（如 `ARCHITECTURE.md`、`CLAUDE.md`）
- Web 模板内嵌说明
- 相关命令 docstring / help 文案（`i18n` 中若硬编码列名则同步）

中文文档也以英文列为默认规范书写，避免「中文文档只教中文列」造成双标准。

---

## 错误处理

- 文件完全没有可识别的 `locale`/`语言` 列，或所有行被跳过：得到空列表；上传层沿用现有空数据提示；文案改为提及 `locale`（及兼容名 `语言`）
- 有 `locale` 但缺其他字段：仍为「有值才更新」，行为不变
- 不因存在未知列而失败

---

## 测试计划

1. **英表头**：`locale,name,...` → canonical dict，上传路径正常  
2. **中表头**：现有中文 CSV → 与改前语义一致  
3. **混用**：如 `locale` + `应用名称` → 正确归一  
4. **冲突**：`keywords` 与 `关键字` 同时有值 → 取英文列；仅 `关键词`+`关键字` 时 → 取左侧先出现的列  
5. **init 模板**：断言生成文件含英文表头，不含中文必填列名作为表头  
6. **文档/Web 断言**：现有检查中文列说明的测试改为英文（或英文+兼容说明）

---

## 成功标准

- 新项目 / `asc init` 默认英文 CSV 表头  
- 旧中文 CSV 无需修改即可继续上传  
- 业务代码与对外稳定文档以英文 canonical 为唯一规范  
- 中文别名集中在 constants，不再散落在命令层  

---

## 推荐实现路径

**中央别名表 + `parse_csv` 归一化**（相对「业务层多别名查找」或「Typed Dict 大重构」）：改动面可控、调用方只认一套 key、与只读兼容目标一致。
