# 操作日志

## 2026-08-24

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
