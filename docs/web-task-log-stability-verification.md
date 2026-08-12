# Web Task Log Stability 部署验收

本清单分为自动安全检查与真实部署检查。自动回归**不得运行真实 App Store
上传**；包含 `asc release` 或 Web `mode=full` 的命令只能由验收人员在明确
授权的测试应用、测试凭据和 TestFlight 目标上手工执行。

## 1. 准备变量并启动服务

先把所有尖括号占位符替换为本机真实值：

```bash
export ASC_PROFILE='<APP_PROFILE>'
export ASC_PROJECT='<ABSOLUTE_PATH_TO_XCODEPROJ_OR_XCWORKSPACE>'
export ASC_SCHEME='<XCODE_SCHEME>'
export ASC_WEB_URL='http://127.0.0.1:8080'
export ASC_TASK_DB="$HOME/.config/asc/tasks.db"
export ASC_OUTPUT_DIR="$PWD/build"
export ASC_VERIFY_DIR="$ASC_OUTPUT_DIR/web-task-verification"
mkdir -p "$ASC_VERIFY_DIR"

asc web stop
asc web --host 127.0.0.1 --port 8080 --no-open
asc web status
WEB_PID="$(pgrep -f 'uvicorn.*asc.web' | awk 'NR==1 {print; exit}')"
test -n "$WEB_PID"
lsof -p "$WEB_PID" | wc -l
tail -n 200 "$HOME/.config/asc/web.log"
```

启动日志必须同时显示当前 `asc` version 和短 commit，并与部署产物一致。
服务预热后记录基线：

```bash
sleep 10
BASE_FD="$(lsof -p "$WEB_PID" | wc -l | tr -d ' ')"
printf 'baseline_fd=%s\n' "$BASE_FD" | tee "$ASC_VERIFY_DIR/fd-baseline.txt"
```

## 2. Web full task

Web task、SSE 和 SQLite 验收通过 Web API 启动完整任务。以下命令会真实执行
Archive、Export、Upload，只能在授权测试应用上手工执行。带独立 raw capture
的完整 `asc release` 命令见第 6 节：

```bash
TASK_JSON="$(
  curl -fsS -X POST \
    -H 'Accept: application/json' \
    -b "asc_profile=$ASC_PROFILE" \
    -F 'mode=full' \
    -F "project=$ASC_PROJECT" \
    -F "scheme=$ASC_SCHEME" \
    -F 'destination=testflight' \
    -F 'signing=auto' \
    -F 'reuse_archive=rebuild' \
    -F 'verbose=on' \
    "$ASC_WEB_URL/api/build/run"
)"
TASK_ID="$(
  printf '%s' "$TASK_JSON" |
    python -c 'import json,sys; print(json.load(sys.stdin)["task_id"])'
)"
test -n "$TASK_ID"
printf 'task_id=%s\n' "$TASK_ID"
```

## 3. 至少 5 个 SSE、断开与重连

任务启动后立即开 5 个客户端并记录 PID：

```bash
: > "$ASC_VERIFY_DIR/sse.pids"
for client_id in 1 2 3 4 5; do
  curl -N -fsS \
    "$ASC_WEB_URL/api/task/$TASK_ID/stream?after=0" \
    > "$ASC_VERIFY_DIR/sse-$client_id.log" &
  printf '%s\n' "$!" >> "$ASC_VERIFY_DIR/sse.pids"
done
sleep 5
```

主动断开第 1 个客户端，读取其最后 cursor，并带
`Last-Event-ID`（同时保留兼容 `after`）重连：

```bash
FIRST_SSE_PID="$(awk 'NR==1 {print; exit}' "$ASC_VERIFY_DIR/sse.pids")"
kill "$FIRST_SSE_PID"
wait "$FIRST_SSE_PID" 2>/dev/null || true
LAST_EVENT_ID="$(
  awk '/^id: / {last=$2} END {if (last == "") last=0; print last}' \
    "$ASC_VERIFY_DIR/sse-1.log"
)"
curl -N -fsS \
  -H "Last-Event-ID: $LAST_EVENT_ID" \
  "$ASC_WEB_URL/api/task/$TASK_ID/stream?after=$LAST_EVENT_ID" \
  > "$ASC_VERIFY_DIR/sse-1-reconnected.log" &
RECONNECTED_PID="$!"
printf '%s\n' "$RECONNECTED_PID" >> "$ASC_VERIFY_DIR/sse.pids"
```

验收后使用 `wait "$RECONNECTED_PID"`，并检查 5 组日志序号连续、不重复、不
倒序；每组最大 `id:` 帧必须位于 `event: done`/`error_event`/`canceled`
终态帧之前。

## 4. 每 10 秒 FD 采样

下面循环在任务运行时每 10 秒采样；终态后继续 12 次，即 2 分钟：

```bash
: > "$ASC_VERIFY_DIR/fd-samples.tsv"
while :; do
  TASK_STATE="$(
    sqlite3 "$ASC_TASK_DB" \
      "select status from task_runs where id='$TASK_ID';"
  )"
  printf '%s\t%s\t%s\n' \
    "$(date -u +%FT%TZ)" \
    "$(lsof -p "$WEB_PID" | wc -l | tr -d ' ')" \
    "$TASK_STATE" | tee -a "$ASC_VERIFY_DIR/fd-samples.tsv"
  case "$TASK_STATE" in
    done|error|canceled) break ;;
  esac
  sleep 10
done

for _sample in $(seq 1 12); do
  sleep 10
  printf '%s\t%s\tpost-terminal\n' \
    "$(date -u +%FT%TZ)" \
    "$(lsof -p "$WEB_PID" | wc -l | tr -d ' ')" |
    tee -a "$ASC_VERIFY_DIR/fd-samples.tsv"
done

FINAL_FD="$(awk 'END {print $2}' "$ASC_VERIFY_DIR/fd-samples.tsv")"
test "$FINAL_FD" -le "$((BASE_FD + 10))"
```

## 5. SQLite 终态与日志

```bash
sqlite3 "$ASC_TASK_DB" \
  "select id,kind,status,result_json,progress_pct,progress_msg from task_runs order by created_at desc limit 10;"
sqlite3 "$ASC_TASK_DB" \
  "select task_id,count(*) from task_logs group by task_id order by count(*) desc limit 10;"
sqlite3 "$ASC_TASK_DB" \
  "select status,result_json from task_runs where id='$TASK_ID';"
```

task 必须为终态且 `result_json` 非空。日志必须有 Archive、Export、Upload、
0/25/50/75/100 里程碑、warning、错误上下文和摘要，不得出现逐文件洪水。
raw 错误上下文严格为错误前 5 行 + 错误行 + 错误后 10 行；失败尾部 20 行
与该窗口按 `(source, raw_line_no)` 去重，不能重复显示交叠行。10 万行自动
fixture 的持久化 `task_logs` 必须不超过 500。

## 6. 同一次 release 的 raw 字节保真

生产代码通过 `PATH` 调用 `xcodebuild` 和 `xcrun altool --upload-app`。以下
zsh 命令在临时 `PATH` 前置 wrapper：wrapper 直接调用预先保存的真实绝对
路径，避免递归；只对 archive、export 和 altool upload 分支做 byte tee，
其他探测命令原样 `exec`。`${pipestatus[1]}` 保留真实子进程退出码。

本节的 `asc release` 会真实上传，只能在授权测试应用上手工执行；wrapper
capture 与 asc raw 文件来自**同一次子进程字节流**，不得为比对重复 Upload。

```bash
set -euo pipefail

REAL_XCODEBUILD="${REAL_XCODEBUILD:-$(command -v xcodebuild)}"
REAL_XCRUN="${REAL_XCRUN:-$(command -v xcrun)}"
test -x "$REAL_XCODEBUILD"
test -x "$REAL_XCRUN"
export REAL_XCODEBUILD REAL_XCRUN

WRAPPER_DIR="$(mktemp -d "${TMPDIR:-/tmp}/asc-raw-wrapper.XXXXXX")"
cleanup_wrapper() {
  exit_status=$?
  trap - EXIT INT TERM
  rm -rf "${WRAPPER_DIR:-}"
  exit "$exit_status"
}
cleanup_signal() {
  exit_status="$1"
  trap - EXIT INT TERM
  rm -rf "${WRAPPER_DIR:-}"
  exit "$exit_status"
}
trap cleanup_wrapper EXIT
trap 'cleanup_signal 130' INT
trap 'cleanup_signal 143' TERM

export ASC_ARCHIVE_CAPTURE="$ASC_VERIFY_DIR/archive.capture.log"
export ASC_EXPORT_CAPTURE="$ASC_VERIFY_DIR/export.capture.log"
export ASC_UPLOAD_CAPTURE="$ASC_VERIFY_DIR/upload.capture.log"
rm -f \
  "$ASC_ARCHIVE_CAPTURE" \
  "$ASC_EXPORT_CAPTURE" \
  "$ASC_UPLOAD_CAPTURE"

cat > "$WRAPPER_DIR/xcodebuild" <<'ZSH'
#!/bin/zsh
set -u
capture=''
for argument in "$@"; do
  if [[ "$argument" == '-exportArchive' ]]; then
    capture="$ASC_EXPORT_CAPTURE"
    break
  fi
done
if [[ -z "$capture" ]]; then
  for argument in "$@"; do
    if [[ "$argument" == 'archive' ]]; then
      capture="$ASC_ARCHIVE_CAPTURE"
      break
    fi
  done
fi
if [[ -z "$capture" ]]; then
  exec "$REAL_XCODEBUILD" "$@"
fi
"$REAL_XCODEBUILD" "$@" 2>&1 | tee "$capture"
exit_code="${pipestatus[1]}"
exit "$exit_code"
ZSH

cat > "$WRAPPER_DIR/xcrun" <<'ZSH'
#!/bin/zsh
set -u
is_upload=0
if [[ "${1:-}" == 'altool' ]]; then
  for argument in "$@"; do
    if [[ "$argument" == '--upload-app' ]]; then
      is_upload=1
      break
    fi
  done
fi
if (( ! is_upload )); then
  exec "$REAL_XCRUN" "$@"
fi
"$REAL_XCRUN" "$@" 2>&1 | tee "$ASC_UPLOAD_CAPTURE"
exit_code="${pipestatus[1]}"
exit "$exit_code"
ZSH

chmod +x "$WRAPPER_DIR/xcodebuild" "$WRAPPER_DIR/xcrun"

PATH="$WRAPPER_DIR:$PATH" \
asc --app "$ASC_PROFILE" release \
  --project "$ASC_PROJECT" \
  --scheme "$ASC_SCHEME" \
  --destination testflight \
  --signing auto \
  --output "$ASC_OUTPUT_DIR" \
  --no-interactive \
  --rebuild \
  --verbose

test -s "$ASC_ARCHIVE_CAPTURE"
test -s "$ASC_EXPORT_CAPTURE"
test -s "$ASC_UPLOAD_CAPTURE"
cmp -- "$ASC_OUTPUT_DIR/build.log" "$ASC_ARCHIVE_CAPTURE"
cmp -- "$ASC_OUTPUT_DIR/export.log" "$ASC_EXPORT_CAPTURE"
cmp -- "$ASC_OUTPUT_DIR/export/upload.log" "$ASC_UPLOAD_CAPTURE"
shasum -a 256 "$ASC_OUTPUT_DIR/build.log" "$ASC_ARCHIVE_CAPTURE"
shasum -a 256 "$ASC_OUTPUT_DIR/export.log" "$ASC_EXPORT_CAPTURE"
shasum -a 256 "$ASC_OUTPUT_DIR/export/upload.log" "$ASC_UPLOAD_CAPTURE"
```

三次 `cmp` 均须 exit 0，每对 `shasum` 必须相同。自动环境可用以下安全 fixture
验证二进制 tee 和分类器异常均不改变 raw bytes：

```bash
pytest -q \
  tests/test_reporting.py::test_spinner_tees_exact_binary_bytes_and_decodes_safe_text_lines \
  tests/test_reporting.py::test_spinner_classifier_failure_does_not_change_raw_bytes
```

## 7. metadata、IAP 与 update 安全路径

metadata 和 IAP 使用 dry-run；把路径占位符替换为真实测试数据：

```bash
asc --app "$ASC_PROFILE" upload \
  --csv '<PATH_TO_APPSTORE_INFO_CSV>' \
  --screenshots '<PATH_TO_SCREENSHOTS_DIR>' \
  --dry-run \
  --verbose

asc --app "$ASC_PROFILE" iap \
  --iap-file '<PATH_TO_IAP_PACKAGES_JSON>' \
  --dry-run \
  --verbose
```

确认 locale、product、screenshot 的成功/跳过/失败标识未被聚合。`asc update`
没有 `--dry-run`，不得伪造该参数。只读检查与 deferred（不执行 pip）用：

```bash
curl -fsS "$ASC_WEB_URL/api/update/check" | python -m json.tool
pytest -q \
  tests/test_update_cmd.py::TestPipInstallStreaming::test_update_core_defer_install_skips_pip
```

检查输出保留目标 ref 与 commit；deferred 用例必须证明未调用 pip，且 pip
类别摘要由既有 update 聚焦回归覆盖。不要在生产验收机调用
`POST /api/update/run`，该接口会安排停服安装和重启。

## 8. 安全故障注入与恢复

不要破坏真实 `~/.config/asc/tasks.db`。使用隔离的 pytest `tmp_path` 注入 DB
写失败和分类器异常：

```bash
pytest -q \
  tests/test_web_task_log_fidelity.py::test_terminal_db_failure_is_visible_and_never_fakes_success \
  tests/test_reporting.py::test_spinner_classifier_failure_does_not_change_raw_bytes
```

两个用例均须通过：DB 失败必须留下 task/operation/path 上下文且不能伪造成功
终态；分类器异常不得中断 subprocess 或改变 raw bytes。pytest 自动删除隔离
目录，无需修改或恢复真实 DB。最后检查真实服务仍健康：

```bash
asc web status
tail -n 200 "$HOME/.config/asc/web.log"
sqlite3 "$ASC_TASK_DB" \
  "select id,kind,status,result_json,progress_pct,progress_msg from task_runs order by created_at desc limit 10;"
```

## 9. 发布判定

只有 Web Task Log Stability 规格第 13 节全部成功指标，以及本清单的启动
身份、完整 release、至少 5 个 SSE、断线重连、FD、SQLite、raw 字节保真、
业务 dry-run、update deferred 和安全故障注入全部满足，才可宣布真实修复
完成。任一项未执行、无证据或超阈值均判定为未通过。
