# ASC 中期性能：429 Cancel + Fingerprint 缓存 + 统一分页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 ASC HTTP 热路径在限流等待时可协同取消、Guard 不再每次跑 `ioreg`、列表接口统一走分页，并为改价 DELETE 策略留下可独立交付的下一批设计。

**Architecture:** 在现有 `AppStoreConnectAPI._request` / `_get_paginated_data` 与 `Guard` 进程级 IP 缓存模式上增量增强：429 sleep 改为可中断分段等待（读 `api.cancel_event`）；机器指纹进程级缓存；凡单页 `limit` 可能截断的 list 方法改为 `_get_paginated_data`。改价 DELETE 并行/差异删作为后续独立任务，不阻塞本批。

**Tech Stack:** Python 3.9+、`threading.Event`、`requests`、现有 `ProcessCanceled`、`pytest` + `unittest.mock`。

## Global Constraints

- 取消必须协同：只检查 `cancel_event` / 抛 `ProcessCanceled`，禁止强杀线程。
- 不引入新依赖；不改 ASC REST 对外语义（返回完整 data 列表，调用方无感知）。
- 测试禁止真实 ASC / 真实 `ioreg` 网络；用 mock + `tmp_path`。
- 公共方法签名尽量不变；`api.cancel_event` 为可选属性，默认 `None`（CLI 无取消时行为与现在一致）。
- 429 等待期间继续持有 `_asc_request_slot`（避免限流时 thundering herd）。
- 本计划不重做 Web TaskStore / 有界并发（已在 `2026-08-07-web-task-single-writer-bounded-concurrency.md` 完成）。

---

## 1. 目标与非目标

### 目标（本批 + 下一批）

| 优先级 | 项 | 本批？ | 说明 |
|--------|----|--------|------|
| P0 | 429 等待可 cancel | ✅ | `_request` 分段检查 `cancel_event` |
| P0 | ioreg / machine fingerprint 缓存 | ✅ | Guard 热路径进程级缓存 |
| P1 | 列表 API 统一分页 | ✅ | territories / prices / localizations / offers / price points 等 |
| P2 | 改价 DELETE 策略 | ❌ 下一批 | `--update-existing` 逐地区 DELETE 并行或差异删 |
| P3 | queue_position 等小项 | ❌ 低优 | 短期计划「默认不做」；仅列 backlog |

### 非目标

- 不把 CLI 同步命令改成强制绑定 cancel_event。
- 不重写订阅/IAP 业务编排（除 DELETE 策略任务需要的最小改动）。
- 不实现 availability 的 `included.availableTerritories` 深层分页（ASC include 分页模型不同；本批仅保证主 `data` 列表完整；若实测 territories 截断再单开任务）。
- 不跨进程共享 fingerprint / cancel 状态。

---

## 2. 现状调研摘要

| 组件 | 现状 | 问题 |
|------|------|------|
| `api._request` 429 分支 | `time.sleep(retry_after)` | Web/任务取消后仍可能卡在最长 Retry-After（常见 30s+） |
| `api.cancel_event` | 不存在 | 业务层有 `cancel_event`，但进不了 `_request` |
| `Guard._get_machine_fingerprint` | 每次可能 `subprocess` 跑 `ioreg` | Web 多 profile 状态检查反复 fork |
| `Guard._get_public_ip` | 已有 10min TTL 缓存 | 指纹侧应对齐「进程内缓存」模式 |
| `list_territories` | 单次 `get(..., limit=200)` + 实例缓存 | 地区数接近/超过页大小时截断（Apple ~175，边界风险） |
| `list_subscription_prices` 等 | 单次 `get` + `limit=200` | 全地区价格/本地化可能丢页 |
| `list_*_price_points` / equalizations | `limit=8000` 单次 get | ASC 实际 page size 常 ≤200；大结果可能不完整 |
| `_sync_subscription_price` DELETE | `for p in existing: delete` 串行 | `--update-existing` 改价极慢、易触发 429 |

### 已完成短期（勿重复做）

- Web 单 writer、日志上限、有界 worker、ASC inflight 信号量、截图/订阅短期优化。
- 计划文件：`docs/superpowers/plans/2026-08-07-web-task-single-writer-bounded-concurrency.md`。

---

## File Structure

| 文件 | 职责 |
|------|------|
| `src/asc/api.py` | `_interruptible_sleep`、429 cancel、`cancel_event` 属性、列表改 `_get_paginated_data` |
| `src/asc/guard.py` | 机器指纹进程级缓存 + 测试用 clear helper |
| `src/asc/commands/subscriptions.py` | 绑定 `api.cancel_event`；下一批：DELETE 策略 |
| `src/asc/commands/iap.py` | 绑定 `api.cancel_event` |
| `src/asc/commands/metadata.py` | 绑定 `api.cancel_event`（metadata / URL cores） |
| `src/asc/commands/screenshots.py` | 绑定 `api.cancel_event` |
| `src/asc/commands/whats_new.py` | 绑定 `api.cancel_event` |
| `tests/test_api.py` | 429 cancel、分页补齐断言 |
| `tests/test_guard.py` | fingerprint 缓存断言 |

---

### Task 1: 429 等待可 cancel

**Files:**
- Modify: `src/asc/api.py`（`AppStoreConnectAPI.__init__`、`_request`，新增模块级或方法 `_interruptible_sleep`）
- Modify: `src/asc/commands/subscriptions.py`、`iap.py`、`metadata.py`、`screenshots.py`、`whats_new.py`（core 入口绑定 `api.cancel_event`）
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `threading.Event`（可选）、`asc.progress.ProcessCanceled`
- Produces:
  - `AppStoreConnectAPI.cancel_event: Optional[threading.Event]`（默认 `None`）
  - `_interruptible_sleep(seconds: float, cancel_event=None, chunk: float = 0.5) -> None`：若 `cancel_event.wait(chunk)` 为 True 则 `raise ProcessCanceled("ASC request canceled during rate-limit wait")`
  - `_request` 在 429 分支调用 `_interruptible_sleep(retry_after, self.cancel_event)` 替代 `time.sleep`

- [ ] **Step 1: Write the failing test**

在 `tests/test_api.py` 追加：

```python
def test_request_429_wait_respects_cancel_event(api):
    import threading
    from asc.progress import ProcessCanceled

    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.headers = {"Retry-After": "30"}

    cancel = threading.Event()
    api.cancel_event = cancel

    def set_cancel_soon():
        time.sleep(0.05)
        cancel.set()

    with patch("requests.request", return_value=rate_limited):
        t = threading.Thread(target=set_cancel_soon)
        t.start()
        with pytest.raises(ProcessCanceled):
            api._request("GET", "/v1/apps/123")
        t.join(timeout=2.0)
```

另保留/微调现有 `test_request_retries_on_429`（`Retry-After: 0` + mock sleep）确保无 cancel 时仍重试成功。

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api.py::test_request_429_wait_respects_cancel_event -v`  
Expected: FAIL（尚无 cancel 路径，会卡满 sleep 或超时；实现前可用短 timeout 观察未抛 `ProcessCanceled`）

- [ ] **Step 3: Write minimal implementation**

```python
# src/asc/api.py
from asc.progress import ProcessCanceled

def _interruptible_sleep(
    seconds: float,
    cancel_event: Optional[threading.Event] = None,
    chunk: float = 0.5,
) -> None:
    if seconds <= 0:
        return
    if cancel_event is None:
        time.sleep(seconds)
        return
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        if cancel_event.wait(timeout=min(chunk, remaining)):
            raise ProcessCanceled("ASC request canceled during rate-limit wait")


class AppStoreConnectAPI:
    def __init__(...):
        ...
        self.cancel_event: Optional[threading.Event] = None

    def _request(...):
        ...
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 30))
            print(..., file=sys.stderr, flush=True)
            _interruptible_sleep(retry_after, self.cancel_event)
            continue
```

各 core 入口（有 `cancel_event` 参数处）加：

```python
if cancel_event is not None:
    api.cancel_event = cancel_event
```

覆盖：`_upload_iap_core`、`_upload_subscriptions_core`（或等价入口）、metadata/screenshots/whats_new 的带 cancel 的 core。

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_api.py -q`  
Expected: PASS（含既有 429 / inflight 测试）

- [ ] **Step 5: Commit**

```bash
git add src/asc/api.py src/asc/commands/subscriptions.py src/asc/commands/iap.py \
  src/asc/commands/metadata.py src/asc/commands/screenshots.py src/asc/commands/whats_new.py \
  tests/test_api.py
git commit -m "$(cat <<'EOF'
feat(api): make 429 Retry-After waits cooperatively cancelable

Segmented sleep checks api.cancel_event so Web/task cancel is not blocked
on long rate-limit waits.
EOF
)"
```

---

### Task 2: ioreg / machine fingerprint 缓存

**Files:**
- Modify: `src/asc/guard.py`（模块级缓存，对齐 `_ip_cache`）
- Test: `tests/test_guard.py`

**Interfaces:**
- Consumes: 现有 `_get_machine_fingerprint_macos()` / fallback
- Produces:
  - `_machine_fp_cache: Optional[str]`（进程级，无 TTL；机器指纹在进程生命周期内不变）
  - `_clear_machine_fingerprint_cache() -> None`（测试 helper）
  - `Guard._get_machine_fingerprint` 先读缓存，未命中再计算并写入

- [ ] **Step 1: Write the failing test**

```python
def test_get_machine_fingerprint_cached_across_calls(tmp_path):
    from asc.guard import Guard, _clear_machine_fingerprint_cache
    _clear_machine_fingerprint_cache()
    with patch("asc.guard.GUARD_FILE", tmp_path / "guard.json"), \
         patch(
             "asc.guard._get_machine_fingerprint_macos",
             side_effect=["SERIAL-A", "SERIAL-B"],
         ) as mock_fp:
        g = Guard()
        assert g._get_machine_fingerprint() == "SERIAL-A"
        assert g._get_machine_fingerprint() == "SERIAL-A"
        assert mock_fp.call_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_guard.py::test_get_machine_fingerprint_cached_across_calls -v`  
Expected: FAIL（`call_count == 2`）

- [ ] **Step 3: Write minimal implementation**

```python
# src/asc/guard.py
_machine_fp_cache: str | None = None

def _clear_machine_fingerprint_cache() -> None:
    global _machine_fp_cache
    _machine_fp_cache = None

class Guard:
    def _get_machine_fingerprint(self) -> str:
        global _machine_fp_cache
        if _machine_fp_cache is not None:
            return _machine_fp_cache
        try:
            fp = _get_machine_fingerprint_macos()
        except Exception:
            fp = f"{platform.node()}-{uuid.getnode()}"
        _machine_fp_cache = fp
        return fp
```

注意：现有测试若直接 patch `Guard._get_machine_fingerprint` 不受影响；测 ioreg 的用例在断言前调用 `_clear_machine_fingerprint_cache()`，避免污染。

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_guard.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/asc/guard.py tests/test_guard.py
git commit -m "$(cat <<'EOF'
perf(guard): cache machine fingerprint for process lifetime

Avoid repeated ioreg subprocess calls on Guard hot paths (Web profile
status checks).
EOF
)"
```

---

### Task 3: 列表 API 统一分页

**Files:**
- Modify: `src/asc/api.py`（下列方法改用 `_get_paginated_data`）
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: 现有 `_get_paginated_data(path, **params) -> list`
- Produces: 下列方法返回完整 `data` 列表（多页拼接）；`list_territories` 仍保留实例级 `_territories_cache`，但填充时走分页

**必须迁移的方法（单页 `get` + `data`）：**

| 方法 | 建议 limit | 备注 |
|------|------------|------|
| `list_territories` | 200 | 缓存前 `_get_paginated_data` |
| `list_subscription_prices` | 200 | 改价 DELETE 前置依赖完整列表 |
| `list_subscription_localizations` | 200 | |
| `list_subscription_group_localizations` | 200 | |
| `list_subscription_intro_offers` | 200 | |
| `list_subscription_promo_offers` | 200 | |
| `get_app_info_localizations` | 200 | 方法名保持 |
| `get_in_app_purchase_localizations` | 200 | |
| `list_in_app_purchase_price_points` | 200 | 原 8000 单页不可靠 |
| `list_subscription_price_points` | 200 | 同上 |
| `list_in_app_purchase_price_point_equalizations` | 200 | 保留 filter/include 参数 |
| `list_subscription_price_point_equalizations` | 200 | 同上 |
| `find_in_app_purchase_price_point` | 200 | 内部循环改分页，语义不变 |
| `find_subscription_price_point` | 200 | 同上 |

**本批不做：** `get_*_availability` 的 `include=availableTerritories` 深层分页（需 ASC relationship pagination；单开任务）。

- [ ] **Step 1: Write the failing tests**

```python
def test_list_territories_follows_pagination(api):
    with patch.object(
        api,
        "get",
        side_effect=[
            {
                "data": [{"id": "USA"}],
                "links": {"next": "https://api.appstoreconnect.apple.com/v1/territories?cursor=2"},
            },
            {"data": [{"id": "CHN"}], "links": {}},
        ],
    ) as mock_get:
        result = api.list_territories()

    assert [t["id"] for t in result] == ["USA", "CHN"]
    assert mock_get.call_count == 2
    # 第二次 list 仍走缓存
    assert api.list_territories() == result
    assert mock_get.call_count == 2


def test_list_subscription_prices_follows_pagination(api):
    with patch.object(
        api,
        "get",
        side_effect=[
            {
                "data": [{"id": "p1"}],
                "links": {"next": "https://api.appstoreconnect.apple.com/v1/prices2"},
            },
            {"data": [{"id": "p2"}], "links": {}},
        ],
    ):
        result = api.list_subscription_prices("sub1")
    assert [p["id"] for p in result] == ["p1", "p2"]
```

为 localizations / offers / price_points 各补至少一条「follows pagination」或合并为一个 parametrize。

更新 `test_list_territories_cached_across_calls`：若仍断言 `get(..., limit=200)` 单次调用，改为断言分页 helper 行为（首呼可多页，次呼零次）。

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py::test_list_territories_follows_pagination tests/test_api.py::test_list_subscription_prices_follows_pagination -v`  
Expected: FAIL（第二页未合并）

- [ ] **Step 3: Write minimal implementation**

示例：

```python
def list_territories(self) -> list:
    if self._territories_cache is None:
        self._territories_cache = self._get_paginated_data("/v1/territories", limit=200)
    return self._territories_cache

def list_subscription_prices(self, sub_id: str) -> list:
    return self._get_paginated_data(
        f"/v1/subscriptions/{sub_id}/prices", limit=200
    )

def list_subscription_price_points(self, sub_id: str, territory: str) -> list:
    return self._get_paginated_data(
        f"/v1/subscriptions/{sub_id}/pricePoints",
        limit=200,
        **{"filter[territory]": territory},
    )

def find_subscription_price_point(self, sub_id, territory, amount):
    target = str(amount).strip()
    for pp in self.list_subscription_price_points(sub_id, territory):
        price = str(pp.get("attributes", {}).get("customerPrice", "")).strip()
        if price == target:
            return pp["id"]
    return None
```

其余方法同理。equalizations 保留 `include` / filter kwargs 传入 `_get_paginated_data`。

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_api.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/asc/api.py tests/test_api.py
git commit -m "$(cat <<'EOF'
fix(api): paginate ASC list endpoints that truncated at one page

Route territories, prices, localizations, offers, and price-point lists
through _get_paginated_data so large catalogs are complete.
EOF
)"
```

---

### Task 4: 改价 DELETE 策略（下一批，本批不实现）

**Files（预留）：**
- Modify: `src/asc/commands/subscriptions.py`（`_sync_subscription_price` 中 `update_existing` DELETE 循环）
- Test: `tests/test_subscriptions_core.py`

**设计选项（实现时二选一或组合）：**

1. **有界并行 DELETE**  
   - 复用价格创建 的 `max_workers`（默认 6）+ `ThreadPoolExecutor`  
   - 每个 DELETE 前检查 `cancel_event`  
   - 与现有 ASC inflight 信号量叠加，避免打爆 429  

2. **差异删（更省请求）**  
   - 先解析目标 `price_points`（含 equalizations）  
   - 仅删除「地区不在目标集」或「price point 与目标不同」的现有价格  
   - 已匹配的跳过 delete+recreate  

**建议交付顺序：** 先做 (1) 并行（改动面小、收益直观），再视需要做 (2)。

**验收草案：**

```python
def test_update_existing_deletes_prices_in_parallel(fake_api, ...):
    # existing N prices; update_existing=True
    # assert delete 调用次数 == N，且 wall time 显著低于串行（或 mock 记录并发度）
```

**Commit 消息草案：**

```text
perf(subscriptions): parallelize price DELETE on --update-existing
```

---

### Task 5（Backlog，默认不做）

来自短期计划「默认不做」的低优项，仅登记，不排期：

- Web `queue_position` 展示
- 跨进程任务队列
- availability included-territories 深层分页
- 其它 UX 锦上添花

---

## Self-Review

1. **Spec coverage:** P0 429 cancel、P0 fingerprint 缓存、P1 分页、P2 DELETE、P3 backlog 均有对应 Task。  
2. **Placeholder scan:** 无 TBD；Task 4 以「下一批」明确范围而非空实现。  
3. **Type consistency:** `cancel_event` / `ProcessCanceled` / `_get_paginated_data` 命名与现有代码一致。

---

## Execution Handoff

本会话按用户指示：**写计划后立即 inline 执行 Task 1→2→3**；Task 4 留给下一批。本地按逻辑拆 commit，**不 push、不开 PR**。
