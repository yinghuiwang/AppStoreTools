# 操作日志

## 2026-09-05

- `asc web` 在 Python 3.9 启动失败：uvicorn 加载 `create_app` 时 FastAPI/Pydantic 无法求值路由上的 PEP 604 `str | None`（`from __future__ import annotations` 不够）。Agent 查询参数和任务 SSE 的 `Last-Event-ID` 改为 `Optional[str]`，与 dashboard 路由一致；测试会扫描路由注解里的 `|` 并走 FastAPI 的 `get_typed_annotation`。

## 2026-08-27

- MiniMax HTTP 400 / 2013（`tool result's tool id not found`）：LLM 历史只取最近 20 条，会丢掉带 `tool_calls` 的 assistant，却留下后续 `role=tool`。现将窗口提到 80，并在送模型前 `sanitize_llm_messages`：丢掉孤立 tool 行，不完整的 tool 组改成纯文案（有文案才保留）。
- 点「接受方案，写回 CSV」只是确认芯片，不会 apply；计划 `cf2760dc-…` 仍为 pending，所以预览不变。现改为：选项 id 含 apply/write 时自动 apply 最新 pending 计划；Apply 成功后 `reloadFromDisk()` 丢掉本地草稿再读磁盘，避免旧 store draft 盖住新 CSV。已重新构建 SPA（`index-D3GHLn1H.js`）。
- Agent 失败不再只显示 TDesign 默认「请求出错」：`t-chat-message` 不再传 `status=error`（该状态会丢掉自定义文案）。后端把 LLM HTTP 状态、服务商错误体、失败位置（如 `LLM HTTP 401 @ api.minimaxi.com`）写进 `RUN_ERROR` 并持久化到会话。未捕获异常改为 `agent.stream` + 异常类型，不再一律说「服务暂不可用」。已重新构建 SPA（`index-CcCA2l-g.js`）。

## 2026-08-26

- 查 MiniMax CN 文档：聊天看图走 Chat Completions `image_url`（公网 URL 或 base64），单张官方 ≤10MB、请求体 ≤64MB；`POST /v1/files/upload` 的 `mm_file://` 用于视频理解/生成，不是商品图通道。将本轮视觉上限从 2 张 / 512KiB 对齐到 8 张 / 单张 10MB / 合计 20MB（仍不把 base64 写入 SQLite）。
- Agent 效率第二批：会话 `workflow` + `offer_choices` / `choose` 确认芯片；只读 `get_asc_version` / `list_asc_iaps`；当前轮图片走 multimodal；LLM 默认超时 180s，`done` 带 `elapsed_ms` / `tool_batches` / 可选 `usage`。
- Agent 相关 pytest 209 passed；已重新构建 SPA（`index-B9ozctOl.js`）。

- Agent 效率第一批：只读领域工具（商品页/IAP 快照、校验、字数、截图盘点）、去掉对外 `search_files`、压缩工具结果与知识检索片段；`get_knowledge` 默认仍 10000 字以免截断 IAP 工作流。
- 每轮注入脱敏后的 `page_context`；失败任务 `auto_analyze` 先做规则分类（`[failure_hint]`）。空状态增加「生成商品页 / 生成 IAP / 解释失败任务」技能入口。
- 相关 pytest 124 passed；已重新构建 SPA（`index-DgQm8R8i.js`）。

## 2026-08-25

- Agent 聊天先 `ensureSession()`，`/api/agent/agui` 遇 401 只重试一次再开流；附件失败任务搜索 300ms 尾随防抖，打开菜单仍立刻搜。相关 pytest 46 passed。
- `useLocaleCatalog` 改为模块级缓存 + in-flight 去重：新实例走缓存，同实例再次 `load()` 仍刷新；presence 按需合并到同一份 rows。`tests/test_web_metadata_locales.py` 18 passed。
- 教程 02/03/索引与 Agent 知识库（`listing.md` / `iap.md` / `INDEX.md`）改为以 Web 可跳步「创建 → 预览 → 上传」为主路径，CLI 仍作等价附录；去掉 Listing「本地 / Diff / 上传」三 Tab 对照。

- Listing / IAP 对照抽到 `useCompareSession`：共用 generation 取消、in-flight 去重、SSE 等待。两边仍各自保留缓存键、compare 请求体、草稿合并和 `markDirty` 规则（Listing 编辑会失效对照，IAP 不会），避免预览/上传状态跳变。已重新构建 SPA（`index-du-DDKKf.js`）。

## 2026-08-24

- Web 性能与体验：`/api/listing/thumb` 支持 `w` 生成缓存 JPEG 缩略图（默认 320px，缓存在 `~/.cache/asc/thumbs` 或 `ASC_THUMBS_CACHE`）；非图片返回 400。Listing 预览按可见语言懒加载截图，大图查看走原图。
- Listing / IAP compare 不再 250ms 轮询 `/status`，改为等 SSE 结束后再取一次结果。任务日志按通道 `push` + 2000 行环形缓冲，最多保留 20 个通道。
- `keep-alive` 只缓存 Listing / Whats New / URLs / Build / IAP；Dashboard 离开后卸载。Dashboard 进度改为浅监听，不再 `deep` watch 全量日志。
- What's New / URLs 按 profile 写入 `asc_whatsnew_form_*` / `asc_urls_form_*`，刷新后保留文案和选项。
- 新增 `src/asc/web/thumbs.py`、`tests/test_web_thumbs.py`。已重新构建 SPA（`index-xJates2v.js`）。

- IAP / 订阅上传校验收到 `src/asc/iap/validate.py`；CLI 命令模块改为调用该模块。编辑器用的 `validate_snapshot` 仍在 `iap/local.py`。
- `_upload_iap_core` 缺少 productId 或子步骤失败不再报「上传完成」：会计失败数、`reporter.fail`，CLI / Web 整单失败；IAP 失败时不再继续传订阅。销售地区若不是列表会直接失败。
- 商店 pull 行为写清：知识库、`iap/remote.py` 与创建步文案都说明不下载审核截图、不拉等价价格矩阵，只带基准价。
- 新增 `listing/translator`、`asc check`、`asc uninstall` 单测。安装默认走 PyPI（`install.sh` 失败再回退 GitHub）；文档补充 Windows / pipx 卸载。`mypy` / `ruff` 列入 dev extra，CI 不跑。
- 已重新构建 SPA（`index-ySOPEmNu.js`），商店导入说明已打进前端包。

- Agent `form_paths` 沙箱收紧：额外根必须落在项目、家目录或临时目录内；拒绝 `/`、`$HOME`、临时目录根，以及 `~/Library` / `~/.ssh` 等过宽或敏感目录。系统路径（如 `/etc/hosts`）不能再把 `/etc` 加成可读根。父目录过宽时只把文件本身当根。
- `AgentToolContext` 会丢掉无法成为沙箱根的客户端路径；`.ssh` / `.gnupg` / `.aws` / `.kube` 视为敏感目录。
- `apply_fix` 半失败会按应用前快照回滚已成功步骤（含新建文件删除、截图 rename 还原）。原先「第一步留下、第二步失败」改为整单回滚。
- 测试：`test_apply_fix_rolls_back_previous_steps`、`test_apply_fix_rolls_back_created_file`，以及系统路径 / tmp 根 / `.ssh` 拒绝用例。

- 密钥目录统一：`ensure_keys_dir()` / `install_key_file()` 将 `~/.config/asc/keys` 设为 `0700`，`.p8` 设为 `0600`。CLI `app add/edit/import` 与 Web 上传密钥共用。
- 应用层强制本机访问：`create_app()` 拒绝非 loopback 的 `ASC_WEB_HOST`；请求中间件拒绝非 loopback 客户端（TestClient 的 `testclient` 仍放行）。即使 `uvicorn --host 0.0.0.0`，局域网请求也会 403。
- 运行时依赖改为 `PyJWT[crypto]>=2.8.0`，避免缺 `cryptography` 时 ES256 JWT 失败。
- 修复 `translator.py` 的 `from src.asc.llm` 为 `from asc.llm`。
- `CLAUDE.md` / `ARCHITECTURE.md` 补上 Web UI 与 Agent。
- Guard 收紧：`ASC_GUARD_DISABLE=1` 只在 CI 标记（`CI` / `GITHUB_ACTIONS` / `GITLAB_CI` / `ASC_CI`）下生效，本机残留环境变量不再静默关闭守卫。
- 公网 IP 探测失败且已有 IP 绑定时，`check_and_enforce` 拒绝继续；可用 `ASC_GUARD_ALLOW_UNKNOWN_IP=1` 显式放行。无 IP 绑定时仍可只绑定机器和凭证。
- `manual_bind` 不再覆盖已有指纹 / IP / 凭证；指纹须为 6-128 位安全字符，IP 必须是合法地址。Web 手动添加需 `confirm` + popconfirm。
- 教程 07/08、`CLAUDE.md`、`ARCHITECTURE.md` 已同步。新增 `tests/test_web_confirm.py` 的 manual-bind 用例。相关套件 235 passed。已重新构建 SPA。
- 已提交并推送 `58de70d` 到 `origin/feat/iap-workflow` 与 `github/feat/iap-workflow`：`feat: gate high-risk Web actions and add test CI`。`docs/asc-locale-codes.md` 未纳入提交。
- 高危操作二次确认：`POST /api/update/run` 与 `POST /api/agent/apply` 必须带 `confirm`，否则 400，不启动更新、不写文件。
- 更新页三个安装按钮、Agent 计划「应用」改为 `t-popconfirm`；前端请求同时传 `confirm=true`。
- 新增 GitHub Actions `.github/workflows/ci.yml` 与 GitLab CI：pytest（排除 e2e）、`pyproject`/`__version__` 对齐、`frontend` npm build。
- 新增 `tests/test_web_confirm.py`；已有 Agent apply 测试补上 `confirm`。
- 修正 `test_page_modules_grow_and_main_column_scrolls`：预览步语言目录 `.locale-toc` 允许内部滚动，不再误杀 CI。
- `test_large_screenshot_warns_but_passes` 改为断言 stderr（订阅校验警告走 `print(..., file=sys.stderr)`）。
- 已重新构建 SPA（`index-CvuqS-Dq.js`）。
- 已提交并推送 `3d89961` 到 `origin/feat/iap-workflow` 与 `github/feat/iap-workflow`：`fix: stop false upload success and lock down the local Web UI`。`docs/asc-locale-codes.md` 未纳入提交。
- Web 加固：`/api/listing/thumb`、`listing/iap local/save`、`/api/browse` 禁止读写 `.p8` / `~/.config/asc/keys` 以及家目录与临时目录之外的路径。
- LLM `base_url` 与 Webhook URL 拒绝 `file://`、链路本地 / 云 metadata（`169.254.169.254`）；发送时再解析一次，解析到禁网段则拒绝。本机 Ollama（`127.0.0.1`）仍可用。
- `/api/profiles` 与 `/api/guard/status` 对 issuer_id、key_id、指纹、IP 打码；编辑 Profile 留空则保留原值，前端不再把列表里的掩码填回表单。
- 新增 `src/asc/web/security.py` 与 `tests/test_web_security.py`。相关套件 273 passed。
- Web UI 增加本机会话鉴权：启动时生成随机 token；`GET /` 与 `GET /api/session` 下发 `HttpOnly` + `SameSite=Strict` 的 `asc_session` cookie；其余 `/api/*` 必须带 cookie 或 `X-ASC-Token`。
- 非 loopback 的 `Origin` / `Referer`（如 `https://evil.example`）一律 403，阻止跨站读接口或 CSRF。静态页与 `/static` 不验。
- 前端启动先 `ensureSession()`，请求遇 401 会重新领 cookie 再试一次；更新重启探测也会先打 `/api/session`。
- 现有 TestClient 通过 `conftest` 自动带 `X-ASC-Token`，无需逐个改测试。新增 `tests/test_web_auth.py`。相关套件 22 passed；Web TestClient 大套件 271 passed（另有 1 个既有 CSS 断言失败，与本次无关）。
- 已构建 SPA。已重启本地 Web UI：`http://127.0.0.1:8080`（PID 82019，工作目录为仓库根）。无 cookie 访问 `/api/profiles` 返回 401；先 `GET /api/session` 再访问可通过。
- 一次性 IAP：已有 SKU 不再整项跳过，会补齐缺失的本地化/价格/地区；`--update-existing` 在价格时间表或显式销售地区无法替换时失败，不再报成功。销售地区创建失败会上抛。
- 文案 `iap_price_cannot_replace` / `iap_availability_cannot_replace`；教程与 pitfalls 已同步。`tests/test_iap_core.py` 等相关 56 passed。
- 补齐官方截图像素映射：1260×2736 / 1206×2622 / 1080×2340 / 11" iPad 额外尺寸；无法识别的尺寸改为失败，不再静默丢掉。
- 订阅改价：地区价格创建失败会上抛并计入失败，不再带「失败」仍打勾；有失败商品时不再 `reporter.done`。inline 回退 POST 成功时不再把 inline 失败数累加进去。
- 知识库 `screenshots.md` / `pitfalls.md` 已同步。相关测试 128 passed。
- 修复 `get_editable_version`：无可编辑状态时返回 `None`，不再回退到 `READY_FOR_SALE` / 第一项。
- 截图 Apple 处理 `FAILED` 或超时现在抛 `AssetUploadError` 并 `reporter.fail`，不再报「上传完成」。
- 新增文案 `screenshot_processing_failed` / `screenshot_processing_timeout`；知识库 `version.md` 写明不回退。
- 测试：`test_api.py` 覆盖非可编辑返回 None；`test_screenshots.py` 覆盖处理失败与超时。相关套件 65 passed。
- IAP 编辑步订阅列表增加 `groupLevel` 列；一次性 IAP 与订阅都增加审核截图列，用行内 36px 缩略图展示（点击可放大）。
- 编辑弹窗不再用只读路径输入框作为主展示，改为行内 48px 缩略图 + 文件名 + 浏览。
- 相对路径按 `iap_packages.json` 所在目录解析，复用 `/api/listing/thumb`。新增 `IapReviewThumb.vue` 与 `reviewShotThumbUrl` 辅助函数。
- 中英文案 `iap.col_group_level` / `iap.col_shot`，并补充 `tests/test_web_i18n.py` 断言。已构建 SPA。
- 已提交并推送 `ccca606` 到 `origin/feat/iap-workflow` 与 `github/feat/iap-workflow`：`feat(iap): show groupLevel and review screenshot thumbs in the editor`。`operateLog.md` 与 `docs/asc-locale-codes.md` 未纳入提交。
- 商品页第二步预览（`frontend/src/views/listing/PreviewStep.vue`）增加按语言 tag 的快速导航目录：左侧粘性目录列出当前可见语言码，点击平滑滚动到对应卡片。
- 目录随筛选/搜索更新；滚动时高亮当前语言；有变更/仅本地/一致用既有状态色，缺截图显示红点。
- 窄屏改为顶部横向标签。中英文案 `listing.toc_title` / `listing.toc_jump`，并补充 `tests/test_web_i18n.py` 断言。
- 已提交并推送 `f557777` 到 `origin/feat/iap-workflow` 与 `github/feat/iap-workflow`：`feat(listing): add locale tag directory on preview step`。`operateLog.md` 与 `docs/asc-locale-codes.md` 未纳入提交。
- 新增 `docs/asc-locale-codes.md`：导出 App Store 官方 50 个地区语言码。
- 完整对照表含语言码、中文、English、CSV 别名、截图文件夹别名、skill 默认 16 语、2026-03-31 新增 11 语。
- 另附三列速查表，便于按语言码快速对照中文名。数据来自 `src/asc/data/asc_locales.json` 与 `src/asc/constants.py`。

## 2026-08-22

- 商品页创建步（`frontend/src/views/listing/CreateStep.vue`）去掉「打开并去预览」按钮，并删除仅服务于该按钮的 `openRemembered`。
- 同步移除中英文案 `listing.open_and_preview`（`src/asc/web/locales/zh.json`、`src/asc/web/locales/en.json`）。
- 打开 CSV 仍可通过「浏览」选择文件；已有内容时顶部「跳过，去预览」入口保留。
- IAP 创建步（`frontend/src/views/iap/CreateStep.vue`）去掉「打开并去编辑」按钮，并删除仅服务于该按钮的 `openRemembered`。
- 同步移除中英文案 `iap.open_and_edit`，并更新 `tests/test_web_iap.py`、`tests/test_web_i18n.py` 中对应断言。
- 打开 JSON 仍可通过「浏览」选择文件；已有内容时顶部「跳过，去编辑」入口保留。
- 本机安装：`frontend` 执行 `npm run build` 更新 SPA，再用 miniconda Python 执行 `pip install -e .`。
- 已重启本地 Web UI：`http://127.0.0.1:8080`（`asc` 0.1.27，可编辑安装指向本仓库）。
- 修复构建上传误报成功：`xcrun altool` 校验失败时仍可能退出码 0，原先只认 returncode 就会走「上传成功」。
- 现会解析 `upload.log` 中的 `UPLOAD FAILED` / `Failed to upload package`，抽出 `Validation failed ...` 后按失败处理；Spinner 同步显示失败。
- 相关测试：`tests/test_build.py`、`tests/test_progress.py`。已重启 Web UI 使修复生效。
- 已提交并推送 `97b8b28` 到 `github/feat/iap-workflow`：`fix(build): treat altool UPLOAD FAILED as a failed upload`。`operateLog.md` 未纳入提交。
- Agent 强化（对照 SparkSkills `appstore-listing` / `iap-packages`）：知识库补上收集输入、先写 en-US+zh-Hans 再确认、groupLevel 分批确认、本地化 10 选且一次一类；系统提示与创建步种子提示同步；检索默认容量加大以免长笔记挤掉 What’s New。
- 补充 Agent 工作流自动化测试 `tests/test_agent_skill_workflow.py`：用 ScriptedLLM 锁系统提示 / 知识库 / 种子文案，并走 get_knowledge → propose_fix 草稿（不写盘）。不覆盖真实模型是否遵守流程。

## 2026-08-26

- Task 2 代码审查：写入 `docs/superpowers/briefs/task-2-review.md`。结论 **Needs fixes**——计划要求的 `_DEFAULT_TOPIC_CHARS=6000` 会截断 `iap.md` 中 `one category per message` / groupLevel 分批确认等工作流（`get_knowledge(iap)` 约 5477 字符，`truncated: true`）；工具注册、写门控、缓存、精简 prompt 与 compact 实现基本符合规格。
