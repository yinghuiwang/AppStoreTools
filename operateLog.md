# 操作日志

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
