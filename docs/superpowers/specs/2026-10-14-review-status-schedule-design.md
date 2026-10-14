# 审核状态定时查询设计

**日期：** 2026-10-14
**状态：** 已批准
**范围：** 只做这一件事：按用户设定的时刻查询某个已有 App profile 的 iOS 审核状态，并通过现有 webhook 渠道发通知。不做成通用任务平台，也不接入 Web 进程内的 `TaskScheduler`。

## 目标

用户可以为已有的 App profile 添加定时任务。到点后，本机用系统定时器执行 `asc schedule tick`，查询该应用的 iOS `appStoreVersions`，把审核状态发到已经配置好的飞书、企业微信或钉钉 webhook。

Web UI 不需要保持运行。心跳由系统定时器触发；macOS 上该用户还需处于已登录的图形会话，约束见下文「心跳」。

## 非目标

- 不为每个任务单独配置 webhook URL。
- 每次到期都发送，发送与否不看状态是否和上次相同。
- 不要求 `asc web` 持续运行，也不把本功能挂到 `src/asc/web/task_runner.py` 的 `TaskScheduler` 或 Web `TaskStore` 上。
- 机器睡眠或关机错过的槽位不补发、不逐个补跑。
- 不查询 IAP 或订阅的审核状态。
- 不提供 `--timezone`，创建后也不允许修改任务时区。
- 不做 systemd timer、LaunchDaemon，或第二套调度器。
- 不轮转 `schedule-tick.log`。

## 决策

| 事项 | 选择 |
|------|------|
| 定时器 | 用户级心跳，每分钟执行一次 `asc schedule tick` |
| macOS | `~/Library/LaunchAgents/com.asc.schedule.plist` |
| 其他操作系统 | 当前用户 crontab 中的一条带标记的 cron |
| 唯一数据源 | `~/.config/asc/schedules.toml` |
| 读写入口 | CLI 与 Web 调用同一个模块；写入使用文件锁 |
| 任务与 profile | 每个任务绑定一个已有 profile；同一 profile 可以有多个任务 |
| 通知配置 | 只读现有 `~/.config/asc/webhook.toml`（沿用 `webhook_config_path()`，因此 `ASC_WEBHOOK_CONFIG_PATH` 仍然有效） |
| 通知发送 | `webhook_clients.send_provider`；不调用 `notify_task_finished` |
| 调度文件路径 | 只有这一处。没有环境变量可以改路径。测试通过函数参数传入临时路径 |

应用名在通知和 `last_result` 里都是 **profile 名称**（`asc schedule add --app` 的那个名字）。不额外请求 App Store 上的商品名称。

Webhook 正文、审核状态中文标签，以及写入任务的 `last_result` / `last_error` 使用固定中文，不随 `ASC_LANG` 翻译。CLI 的提示、校验错误和表头走 `src/asc/i18n.py` 的 `t()`，中英都要有。Web 页面文案走现有 `src/asc/web/locales/zh.json` 与 `en.json`。

## 心跳

`sys.platform == "darwin"` 时用 LaunchAgent，其余系统用 cron。

`install` 把**当前正在执行的** `asc` 可执行文件写成绝对路径：`Path(sys.argv[0]).resolve()`。该路径必须是已存在的普通文件，且文件名就是 `asc`。用 `python -m asc` 启动时，`install` 失败并说明必须通过 `asc` 可执行文件安装；此时不改 plist、crontab 和 `schedules.toml`。

macOS plist：

- `Label`：`com.asc.schedule`
- `ProgramArguments`：绝对路径、`schedule`、`tick` 三个字符串
- `StartInterval`：`60`（从加载时刻起每 60 秒一次，不对齐墙钟的 0 秒；2 分钟宽限覆盖这个抖动）
- `RunAtLoad`：`false`
- `StandardOutPath` 与 `StandardErrorPath`：都是绝对路径 `~/.config/asc/schedule-tick.log`

写入 plist 后，在该用户的 `gui/<uid>` 域 `bootout`（服务本来没加载不算失败）再 `bootstrap`。LaunchAgent 只在这个用户的图形会话里运行：机器开着但该用户未登录时不会触发。本功能不另做系统级 Daemon。

cron 行固定为：

```text
* * * * * <shell 单引号包裹的绝对路径> schedule tick # asc-schedule
```

路径里的单引号按 POSIX 写成 `'\''`。标记 `# asc-schedule` 只属于这一条心跳。`install` 结束后，crontab 里有且仅有一条这样的标记行，其他 crontab 行保持原样。

`install` 可以重复执行。重复执行时用当前 `asc` 绝对路径覆盖定时器。成功时不修改 `schedules.toml`。若 `bootstrap` 或 crontab 更新失败：`schedules.toml` 保持原字节；若此前已有可用定时器，恢复那一份；若此前没有，不留下新的 plist 或 cron 行。命令打印失败原因并以退出码 1 结束。

`uninstall` 只移除定时器。`schedules.toml` 始终保留。macOS 上 `bootout` 后删除 plist；服务未加载仍删除 plist 并视为成功。cron 上删除每一条 `# asc-schedule` 标记行。定时器本来就不存在时，`uninstall` 成功并说明当前未安装。失败时打印原因，退出码 1，且不改 `schedules.toml`，也不留下写了一半的新定时器。

“已安装”的判定：macOS 上 plist 文件存在；其他系统上当前用户 crontab 含有 `# asc-schedule` 标记行。不另发一次 launchctl 探测来决定这个布尔值。

第一次 `asc schedule add` 或 Web 创建任务时，若心跳未安装，先执行与 `install` 相同的安装。这次检查、安装和写入任务都在同一把调度文件锁里完成，避免并发创建各自安装心跳或互相覆盖任务列表。`install` 和 `uninstall` 自己不再获取这把锁；由创建流程在已持有锁时调用安装，避免重复加锁。安装失败则任务不写入，`schedules.toml` 保持原字节。心跳已经安装时，`add` 不重写 plist 或 cron；要更新可执行文件路径必须再运行 `asc schedule install`。

## 存储

任务按创建顺序放在 TOML 数组表 `[[tasks]]` 里。更新不改变顺序。写成普通表 `[tasks]`、`tasks` 不是数组，或任一任务不符合下面的字段规则，都使整份文件损坏。示例里的注释只用于说明，实际写入不必带注释。目录不存在时，只在写入调度文件时创建 `~/.config/asc/`。`tick` 看到文件不存在，或内容能解析成没有任何键的空表时，视为零个任务，退出码 0，不创建 `schedules.toml`。解析抛错则是损坏。

```toml
[[tasks]]
id = "a1b2c3d4"
profile = "myapp"
enabled = true
kind = "daily"          # daily | interval | weekly
time = "09:30"          # 严格的 HH:MM
timezone = "Asia/Shanghai"
next_run_at = "2026-10-15T09:30:00+08:00"
last_run_at = ""
last_error = ""
last_result = ""

[[tasks]]
id = "b2c3d4e5"
profile = "myapp"
enabled = true
kind = "interval"
time = "09:30"
interval_hours = 2
timezone = "Asia/Shanghai"
next_run_at = "2026-10-14T11:30:00+08:00"
last_run_at = ""
last_error = ""
last_result = ""

[[tasks]]
id = "c3d4e5f6"
profile = "myapp"
enabled = true
kind = "weekly"
time = "09:30"
weekdays = [1, 4]       # 1=周一 .. 7=周日，升序、不重复
timezone = "Asia/Shanghai"
next_run_at = "2026-10-15T09:30:00+08:00"
last_run_at = ""
last_error = ""
last_result = ""
```

`id` 由存储模块生成：`uuid4` 的 8 位小写十六进制，与文件内已有 `id` 冲突就重取。调用方不能指定 `id`。

每个任务都有公共字段：`id`、`profile`、`enabled`、`kind`、`time`、`timezone`、`next_run_at`、`last_run_at`、`last_error`、`last_result`。在此之外，`interval` 再写 `interval_hours`，不写 `weekdays`；`weekly` 再写 `weekdays`，不写 `interval_hours`；`daily` 这两个都不写。多出来的键、缺字段、类型不对、重复 `id`、非法时区、非法时间戳，都使整份文件损坏。空表是合法的零任务，不是损坏。

时间戳是带冒号偏移的 ISO 8601，精确到秒，不带小数，例如 `2026-10-15T09:30:00+08:00`。`last_run_at` 在从未执行过时为空字符串。`next_run_at` 在合法任务上必须非空。比较时用时刻，不比较字符串。

写入在同一目录写临时文件再替换，避免留下半份 TOML。替换失败则命令失败，原文件保留。

锁文件是 `schedules.toml.lock`（调度路径加 `.lock`），使用 `fcntl.flock` 独占锁。加锁时可以创建锁文件；创建锁文件不等于创建 `schedules.toml`。`tick` 用非阻塞锁：拿不到就立刻退出码 0，不读调度文件、不发通知、不改任务。CLI 与 Web 的读写用阻塞锁，最多等 30 秒；超时则失败，退出码 1 或 HTTP 409，调度文件不变。`tick` 从拿到锁到进程结束一直持有该锁，包括 App Store 请求和 webhook 请求，因此同一次 tick 里任务列表不会被并发修改。`fcntl` 不可用时，相关命令失败并说明原因，不写调度文件。

## 时区与下次触发

创建任务时捕获时区名，之后机器时区或 `TZ` 变化都不改已有任务。解析顺序：

1. 若环境变量 `TZ` 非空且是 `zoneinfo` 接受的 IANA 名称，用它。
2. 否则对 `/etc/localtime` 做 realpath，取**最后一个** `zoneinfo/` 之后的部分。本机示例：`/private/var/db/timezone/tz/2026d.1.0/zoneinfo/Asia/Shanghai` → `Asia/Shanghai`。这段必须是 `zoneinfo` 接受的名称。
3. 否则创建失败，不安装心跳，不写文件。

所有钟面计算都在任务自己的 `timezone` 里进行。`tick` 在拿到锁之后读取一次 `now`，本次 tick 里每个任务的到期判断、宽限、`next_run_at`、`last_run_at` 和通知里的检查时间都用这个时刻。`run` 使用它自己开始时的时刻。

槽位秒和微秒都是 0。计算下一槽时，取严格晚于参考时刻的最早槽位。参考时刻刚好落在槽位上时，不用这个槽位，取再下一个。因此在 `09:30:00` 整创建的每日 `09:30` 任务，第一次 `next_run_at` 是次日 `09:30`。已经写入的 `next_run_at` 是否执行，只由下文的到期判断决定：`next_run_at == now` 时迟到为 0，会执行。

### daily

任务时区每个公历日的 `time`。今天的该时刻仍严格晚于 `now` 就用今天，否则用下一个存在的公历日。

### interval

`kind` 存的是 `interval`。CLI `--every N` 写入 `interval_hours = N`，不存在名为 `every` 的 kind。

在任务时区的每个公历日，槽位是满足下面条件的本地钟面时刻：

```text
(从本地午夜起的分钟数 - time 的分钟数) mod (interval_hours × 60) == 0
```

因此锚点 `09:30`、每 2 小时的槽位是当天全部这些钟面，而不只是从 `09:30` 往后，也不是醒来后再加 2 小时：

```text
01:30, 03:30, 05:30, 07:30, 09:30, 11:30, 13:30, 15:30, 17:30, 19:30, 21:30, 23:30
```

`interval_hours` 不要求整除 24。每 7 小时、锚点 `09:30` 时，每个本地日的槽位是 `02:30`、`09:30`、`16:30`、`23:30`。`23:30` 的下一槽是次日 `02:30`，中间不补别的时刻。

### weekly

`weekdays` 使用 ISO 星期：`1` 周一至 `7` 周日，与 `date.isoweekday()` 一致。槽位是星期落在列表中的公历日的 `time`。多个星期取严格晚于 `now` 的最近一个。只选周一且周一已过，就到下周一，不在当天再找另一个时刻。`1,2,3,4,5,6,7` 合法，仍保持 `weekly`，不改写成 `daily`。例如任务时区为 `Asia/Shanghai`、星期 `1,4`、时间 `09:30`，在周三 `2026-10-14 10:00` 创建时，`next_run_at` 是周四 `2026-10-15 09:30`。

### 夏令时

每日和每周按钟面日期与 `HH:MM` 计算，不改成“加 24 小时”或“加 168 小时”。三种周期都一样：本地时刻不存在（春季拨快）时，该次槽位不存在，不通知，下一槽用其后第一个存在的槽位；本地时刻重复（秋季拨回）时，用第一次出现，即 `fold=0`，只保留一个时刻。间隔任务的取模基于本地钟面，所以在没有夏令时的时区里，`09:30` 每 2 小时始终是上面列出的钟面，不按唤醒时间重新起算。

### 宽限与跳过

`tick` 只挑选 `enabled` 且 `next_run_at <= now` 的任务。迟到时间是 `now - next_run_at`：

- 小于或等于 120 秒：执行本次。查询、按规则通知，然后把 `next_run_at` 设为严格晚于 `now` 的下一槽。
- 大于 120 秒：不查询、不通知、不补跑中间槽位。只把 `next_run_at` 跳到严格晚于 `now` 的下一槽。不修改 `last_run_at`、`last_error`、`last_result`。

边界：`09:30:00` 的计划在 `09:32:00` 执行（正好 120 秒），在 `09:32:01` 跳过（121 秒）。

`interval_hours` 是不小于 1 的整数，每日和每周在同一个本地日的同一个 `HH:MM` 只有一个槽。间隔任务相邻槽位至少相隔 1 小时；跨午夜时较短的那段仍是整数小时。因此一次执行之后的下一槽一定晚于 `now` 超过 2 分钟，同一次发生不会被下一分钟的 tick 再发一次。

例子（`Asia/Shanghai`，锚点 `09:30`，每 2 小时）：

- `now` 为 `10:00`，新建任务的 `next_run_at` 是当天 `11:30`。
- `next_run_at` 为 `11:30`，机器在 `12:10` 醒来：迟到超过 2 分钟，不通知，`next_run_at` 改为 `13:30`。不补 `11:30`，也不改成 `14:10`。
- `next_run_at` 为 `09:30`，tick 的 `now` 为 `09:31`：执行，下一槽为 `11:30`。

停用后再启用时不重算 `next_run_at`。若此时它已早于 `now` 超过 120 秒，下一次 tick 只跳槽，不补发通知。

## tick 与 run

`tick` 在文件合法时，即使某些任务失败，退出码也是 0。文件损坏时退出码 1，不发送任何消息（包括不发送 `当前无在审版本`），也不改写文件。拿不到锁时退出码 0，不把这种情况当成文件损坏。没有到期任务时不输出，退出码 0。

同一 tick 内按文件顺序处理到期任务。一个任务失败只记录该任务，然后继续后面的任务。

真正开始查询时（宽限内的到期执行，以及 `run`）把 `last_run_at` 设为这次使用的 `now`。跳过的任务不更新 `last_run_at`。

`asc schedule run <id>` 和页面上的「立即检查」立刻查询并按同一规则通知。它忽略 `enabled`：停用的任务也能手动查。它更新 `last_run_at`、`last_error`、`last_result`，**不**修改 `next_run_at`，也**不**安装心跳。未知 `id` 不发通知。

`tick` 持有锁期间，`run`、创建、删除会等待锁。等待超过 30 秒则该命令失败且不改文件；正在运行的 tick 继续。拿不到锁的另一个 `tick` 直接退出，不发送。

stdout 上每个被 tick 处理的到期任务打印一行：`{id} {profile} ok|skipped|error`。查询成功且不需要记录发送失败时为 `ok`；超过宽限为 `skipped`；查询失败或发送失败为 `error`。重叠 tick 的说明打到 stderr。

## 审核查询

使用该 profile 的 `issuer_id`、`key_id`、`key_file`、`app_id`，通过现有的 App Store Connect 客户端发起请求。JWT 刷新、HTTP 429 重试和 Guard 都沿用现有客户端，不另加一套重试，也不绕过 Guard。现有 429 重试仍失败后，按查询失败处理，并照常推进 `next_run_at`（`run` 除外，见下文）。

只请求：

```text
GET /v1/apps/{app_id}/appStoreVersions?filter[platform]=IOS
```

跟随全部分页。不按版本号排序，不截断成“最新一个”。版本顺序是各页返回顺序，重复的 version id 只保留第一次。状态读 `attributes.appStoreState`；这个键不存在时才读 `attributes.appVersionState`。两个键都不存在的版本忽略。版本号读 `attributes.versionString`，空白时用 `未知版本`。

在审状态全部列出，每条都带版本号和下面的中文标签：

| `appStoreState` | 标签 |
|-----------------|------|
| `WAITING_FOR_REVIEW` | 等待审核 |
| `IN_REVIEW` | 审核中 |
| `REJECTED` | 被拒 |
| `METADATA_REJECTED` | 被拒 |
| `PENDING_DEVELOPER_RELEASE` | 待开发者发布 |
| `PENDING_APPLE_RELEASE` | 待 Apple 发布 |

`PREPARE_FOR_SUBMISSION` 和 `READY_FOR_SALE` 都不是在审。除此之外的状态，包括 `DEVELOPER_REJECTED`，既不是在审，也不是在售。只有 `READY_FOR_SALE` 算已上架。

有任何一个在审版本时，结果里只包含在审列表，不附带已上架版本。没有任何在审版本时，才写 `当前无在审版本`，并附上已上架版本号；多个 `READY_FOR_SALE` 按 API 顺序用 `、` 连接。没有已上架版本时写 `暂无已上架版本`。

查询失败、profile 已删除、凭证缺字段或密钥文件不可读、Guard 拒绝，都**不能**写成“无在审版本”。这些走失败通知。

`last_result` 的成功或失败摘要只用下面四种形式：

- 有在审版本：`1.2.3 审核中；1.2.4 等待审核`（版本之间用 `；`，顺序与 API 一致）
- 无在审且有已上架：`当前无在审版本；已上架 1.2.0`
- 无在审且无已上架：`当前无在审版本；暂无已上架版本`
- 查询失败：`检查失败`

多个已上架版本写成 `当前无在审版本；已上架 1.2.0、1.1.0`。

## 通知

一次到期发生发送一条消息；状态与上次相同也发送。一条消息发给所有符合条件的渠道，渠道顺序是 `feishu`、`wecom`、`dingtalk`。某一个渠道失败不影响其余渠道。

真正执行查询时按这个顺序写盘，超过宽限的跳过不走这里：

1. 完成查询，确定 `last_result`，以及查询阶段的 `last_error`。
2. 先写盘，再发送。`tick` 在发送前写入 `last_run_at`、`last_result`、`last_error` 和已经推进的 `next_run_at`。`run` 写入前三项，不改 `next_run_at`。
3. 按下面的规则发送。
4. 发送失败时再写一次 `last_error`，不再改 `next_run_at`。进程若在第 3 步之前退出，这一次不再补发。

总开关 `enabled == true` 时，每个 `enabled == true` 且 `url` 去空白后非空的渠道都会收到。`notify_statuses` 和 `notify_kinds` 不参与本功能；它们只过滤 Web 任务通知。

webhook 文件不存在时，按现有默认配置处理：总开关关闭。仍然查询并写入 `last_result`，不发送。查询成功时 `last_error` 为空。

webhook 文件损坏时，使用会抛出 `WebhookConfigError` 的严格读取。查询结果照常写入 `last_result`，不把结果改成 `当前无在审版本`，不发送。这算发送失败：查询成功时 `last_error` 为 `通知配置无效`；查询也失败时，在查询摘要后加上 `；通知配置无效`，例如 `凭证不完整；通知配置无效`。`tick` 的 `next_run_at` 已在发送前推进，`run` 不改 `next_run_at`。

总开关关闭或没有可发送渠道时：查询并记录，不发送，查询成功则 `last_error` 为空。查询失败时也不发送失败通知，只把 `last_error` 写成查询摘要。

查询失败且允许发送时：发送失败通知，正文含应用名、检查时间和简短错误，不含 `当前无在审版本`。`tick` 的 `next_run_at` 已在发送前推进。失败通知本身再发送失败时，把发送失败附到 `last_error` 后面，不再发第二条消息，也不在下一分钟重试。

查询成功但发送失败时：`last_result` 保持查询摘要，`last_error` 只记录发送失败，不另发一条“通知失败”的消息。`tick` 的 `next_run_at` 已在发送前推进，因此不会每分钟重试这次发送。下一次到期是下一次槽位，到时按新的查询再发，而不是重发这一次。

`last_error` 在查询和发送都成功，或查询成功但未发送（开关关闭或没有渠道）时为空字符串。它是一行文本：换行改成空格，先做与现有 webhook 文本相同的密钥脱敏，再按 Unicode 码位截断到 200。已知摘要用这些固定中文，Guard 或 ASC 返回的原文只放在脱敏后的摘要里，不另译：

- profile 不存在：`profile 不存在`
- `issuer_id`、`key_id`、`key_file`、`app_id` 任一为空，或密钥文件不可读：`凭证不完整`
- webhook 损坏且查询成功：`通知配置无效`
- webhook 损坏且查询失败：`凭证不完整；通知配置无效`
- 发送失败：`通知发送失败：feishu HTTP 500`；多个渠道用 `；` 连接
- 查询失败后又发送失败：`凭证不完整；通知发送失败：feishu HTTP 500`

检查时间显示为任务时区的 `YYYY-MM-DD HH:MM`，秒不四舍五入，直接去掉，并带上 IANA 时区名。

有在审版本：

```text
应用：myapp
检查时间：2026-10-14 09:31（Asia/Shanghai）
在审版本：
- 1.2.3 审核中
- 1.2.4 等待审核
```

无在审版本：

```text
应用：myapp
检查时间：2026-10-14 09:31（Asia/Shanghai）
当前无在审版本
已上架：1.2.0
```

没有已上架版本时，最后一行是 `已上架：暂无已上架版本`。多个已上架版本用 `、` 连接。

查询失败：

```text
应用：myapp
检查时间：2026-10-14 09:31（Asia/Shanghai）
检查失败：凭证不完整
```

正文是纯文本，三个渠道使用同一段文本。不新增消息模板系统。

## CLI

命令组是 `asc schedule`。`--app` 是 `add` 的必填选项，不读取 `default_app`，也不读取 `.asc/config.toml` 里的默认应用。profile 必须能被现有 profile 查找读到；创建时不访问 App Store，也不要求凭证字段已经填满。凭证要到真正查询时才检查。

三种周期互斥，且必须恰好指定一种。`--time` 三种都必填。

- `asc schedule add --app myapp --daily --time 09:30`
- `asc schedule add --app myapp --every 2 --time 09:30`
- `asc schedule add --app myapp --weekly 1,4 --time 09:30`
- `asc schedule list`
- `asc schedule enable <id>`
- `asc schedule disable <id>`
- `asc schedule remove <id>`
- `asc schedule install`
- `asc schedule uninstall`
- `asc schedule tick`
- `asc schedule run <id>`

校验：

- `--time` 必须匹配 `^([01][0-9]|2[0-3]):[0-5][0-9]$`。`9:30` 和 `09:30:00` 都拒绝。
- `--every` 是整数且 `>= 1`。`0`、负数和非整数拒绝。Typer 把 `01` 解析成整数 `1`，这是合法的。
- `--weekly` 按逗号分割并去掉每段空白。每一段必须是没有前导零的 `1` 到 `7`。`1, 4` 合法；`01`、`0`、`8`、`1-4`、空段和重复数字都拒绝，重复值直接报错，不静默删掉。合法值按升序保存，因此输入 `4,1` 存成 `[1, 4]`。至少要有一个星期。
- 同时给出多种周期，或一种都不给，都拒绝。
- 未知 `id` 拒绝。文件不改。已启用时再 `enable`，或已停用时再 `disable`，成功且不改文件、不重算 `next_run_at`。

`list` 列出全部任务，包括停用的。列是 `id`、应用、周期、下次运行、上次结果、启用。`id` 必须显示，因为 enable、disable、remove 和 run 都用它。没有任务时打印一条 i18n 说明，退出码 0。

周期单元格保持与 kind 对应的英文紧凑形式，不翻译这几个词：`daily 09:30`、`every 2h 09:30`、`weekly 1,4 09:30`。下次运行显示为任务时区的 `YYYY-MM-DD HH:MM` 加时区名，例如 `2026-10-15 09:30 Asia/Shanghai`。上次结果原样显示存储的 `last_result`；从未执行且为空时显示 `-`。启用列走 i18n：中文 `启用` / `停用`，英文 `enabled` / `disabled`。

`add` 成功时打印新 `id` 和 `next_run_at`。若这次自动安装了心跳，再说明心跳已安装。新建任务的 `enabled` 固定为 `true`。校验失败或自动安装失败时退出码 1，不写入新任务。

`remove` 只删除该任务。删到零个任务也不卸载心跳。

`run` 在查询失败或发送失败时退出码 1；查询成功且不需要发送，或发送成功时退出码 0。`tick` 在文件合法时退出码 0，任务级失败不改变这个退出码。

## Web

在现有仅监听 loopback、带会话校验的 Web UI 上增加一页，不新增登录方式。

- 路由：`/schedules`
- 文案键：`nav.schedules`。中文为 `定时任务`，英文为 `Schedules`。写入 `src/asc/web/locales/zh.json` 与 `en.json`
- 侧边栏放在系统分组，`/profiles` 之后，复用已有的 `data-icon="notes"`；顶栏标题用同一个 `nav.schedules`

页面列出 `schedules.toml` 里的全部任务，不按顶栏当前 profile 过滤。每行显示与 CLI 相同的信息，并有启用开关、「立即检查」和删除。删除先在页面内确认；取消则不发请求。启用开关调用下面的 `PUT`，提交原有的 `profile`、`kind`、`time` 和该 kind 的周期字段，只把 `enabled` 改成新值，因此不重算 `next_run_at`。

新建和编辑用同一张表单：选择一个已有 profile、三种周期之一、`HH:MM`，间隔任务再填小时数，每周任务用 `1`–`7` 的多选。时区只读展示，编辑时不能改。新建时应用下拉默认顶栏当前 profile；当前没有 profile 时下拉为空，必须选中后才能提交。新建默认启用。时间控件若给出 `HH:MM:SS`，页面提交前截成 `HH:MM`，秒直接丢掉，不四舍五入。服务端仍只接受 `HH:MM`。`enabled` 在 JSON 里必须是布尔值，字符串 `"true"` 返回 HTTP 400。

页顶显示心跳是否已安装，以及定时器里记录的 `asc` 绝对路径；解析不出路径时仍显示已安装，路径为空。安装和卸载按钮调用与 CLI 相同的函数。

接口挂在现有 `/api` 下，由共享模块完成读写：

| 方法与路径 | 行为 |
|------------|------|
| `GET /api/schedules` | 全部任务，外加 `heartbeat.installed` 与 `heartbeat.path` |
| `POST /api/schedules` | 创建。规则与 `add` 相同，包括必要时自动安装。可省略 `enabled`，省略时为 `true` |
| `PUT /api/schedules/{id}` | 整体替换可编辑字段：`profile`、`kind`、`time`、`enabled`，以及当前 kind 要求的 `interval_hours` 或 `weekdays`。kind 不匹配的字段视为校验失败。时区、`id` 和 `last_*` 沿用原值。只有 `kind`、`time`、`interval_hours` 或 `weekdays` 有变化时，才按保存时刻重算 `next_run_at`。只改 `profile` 或 `enabled` 时不重算。保存本身不发起查询 |
| `DELETE /api/schedules/{id}` | 删除该任务，不卸载心跳 |
| `POST /api/schedules/{id}/run` | 与 `run` 相同 |
| `POST /api/schedules/heartbeat/install` | 与 `install` 相同 |
| `POST /api/schedules/heartbeat/uninstall` | 与 `uninstall` 相同 |

校验失败返回 HTTP 400，未知 `id` 返回 HTTP 404，锁等待超时返回 HTTP 409，正文都是 `{"error": "<说明>"}`。创建、更新、删除、安装和卸载在存储成功时返回 HTTP 200 和更新后的任务或心跳状态。`run` 只要任务存在且结果已写入，就返回 HTTP 200 和该任务；查询失败或发送失败也是 HTTP 200，页面显示返回的 `last_error`。CLI 对同一次 `run` 仍用退出码 1 表示 `last_error` 非空。这两种接口的存储结果相同，差别只在退出码和 HTTP 状态。

## 失败行为

| 情况 | 结果 |
|------|------|
| 文件锁被占用，新的 `tick` 来了 | 新 tick 立即退出码 0，不发送，不改文件 |
| CLI 或 Web 等锁超过 30 秒 | 该命令失败，文件不变 |
| `schedules.toml` 损坏 | `tick` 退出码 1，不发送，不改写文件 |
| profile 已删除、凭证不完整、Guard 拒绝、ASC 查询失败 | 该任务 `last_result` 为 `检查失败`，`last_error` 为简短摘要，发送失败通知（webhook 关闭或没有可发送渠道时不发送）。`tick` 在发送前推进 `next_run_at`；其他到期任务继续 |
| 查询成功，发送失败或 webhook 文件损坏 | 保留查询得到的 `last_result`，记录 `last_error`，不把结果改成无在审版本，不每分钟重试。`tick` 在发送前推进 `next_run_at` |
| `run` 失败 | 同样更新 `last_error` / `last_result` 并尝试通知，不改 `next_run_at` |
| `install` 或 `uninstall` 失败 | `schedules.toml` 不变，命令打印原因 |

## 测试

测试不发起真实的 App Store Connect 请求，也不真正注册 launchd 或 cron。调度路径和 webhook 路径用临时文件。心跳文本由纯函数生成，系统调用由测试替身挡住。

覆盖：

- 每日、每 N 小时、每周的下一槽。包括 `09:30` 每 2 小时的完整钟面、每 7 小时跨午夜的下一槽、锚点对齐而不是“醒来后加 N 小时”、任务时区与机器当前时区不同、刚好 120 秒执行、121 秒只跳槽且不改 `last_*`、正好落在槽位上时取再下一槽。
- 在审状态分类，以及没有在审版本时的已上架行。`PREPARE_FOR_SUBMISSION` 既不进在审列表，也不当成已上架。查询异常不得写成 `当前无在审版本`。
- 通知正文包含应用名、检查时间和在审列表，或 `当前无在审版本` 与已上架版本。总开关关闭时只写 `last_result`，`last_error` 为空。
- 同一次 tick 里一个任务失败不阻止其他到期任务。心跳锁已被占用时，新的 tick 不发送。
- CLI 拒绝非法 profile、时间、星期和间隔。Web 的创建、列表和删除与 CLI 读写同一份临时 `schedules.toml`。
- 生成的 LaunchAgent plist 和 cron 行都包含传入的绝对 `asc` 路径，cron 行以 `# asc-schedule` 结尾。

## 代码落点

共享模块是 `src/asc/schedule.py`。调度文件的读写、校验、下一槽、心跳文本与安装、查询分类、通知和 `tick` / `run` 都在这里。CLI 只在 `src/asc/commands/schedule_cmd.py` 做参数和退出码，由 `src/asc/cli.py` 挂上 `schedule` 命令组。Web 在 `src/asc/web/routes_schedule.py` 暴露上面的接口，并由 `create_app()` 以 `/api` 前缀挂入。页面是 `frontend/src/views/SchedulesView.vue`。

Web 与 CLI 都不直接写 TOML。通知只读取 webhook 配置并调用现有三个渠道的发送函数。
