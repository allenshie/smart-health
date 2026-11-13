# smart_health 規格書

- **狀態：** 定稿
- **版本：** 1.8（2026-11-12）

各版本的變更見 [CHANGELOG.md](../CHANGELOG.md)。

## 1. 目標與範圍

`smart_health` 是通用的 Health App，讓任何服務都能回報「邏輯架構」與「各節點目前的狀態」，並在同一個畫面查看。

| 組成 | 職責 | 交付方式 | 使用者 |
|---|---|---|---|
| 函式庫 `smart-health-record` | 記錄事實、評估狀態、提供 `/topology`、`/status` | PyPI | 被監控的專案 |
| 後端 | 管理監控目標、定期拉取、保留最新狀態與變化 | Docker 映像檔 | Health App 實體 |
| 前端 | 架構圖、燈號、點擊顯示原因 | 包進後端映像檔 | 瀏覽器 |

資料流向固定為後端主動拉取：

```text
被監控服務（函式庫 + /topology、/status） <── 定期拉取 ── 後端 <── 前端
```

Health App 掛掉不能影響被監控服務，只會看不到燈號。

### 不在範圍內

- 修改 Edge、App、`edge_core`、`integration_core`、`smart_workflow`、`monitoring-service`。
- 連接真實的 Edge 或 App。本 repo 的開發與測試一律使用模擬資料（第 8 節）。
- 取代 k8s 的 `/startupz`、`/healthz`、`/readyz`。
- 終止或重啟被監控服務。本專案只回報狀態。
- 登入驗證、長期歷史儲存、告警通知。
- 函式庫以外語言的 SDK。

## 2. 核心概念

| 名詞 | 定義 |
|---|---|
| Service | 一種服務，例如 `edge` |
| Instance | 服務的一個實體，例如 `CamA-northbound-1` |
| Lane | 邏輯執行線。**不等於實際執行緒數量**，只呈現專案想讓人看到的架構 |
| Node | 有獨立燈號的工作單位，屬於一條 lane |
| Sequential lane | lane 內節點依序執行，一個卡住其他也無法前進 |

### 2.1 記錄與評估分離

這是最重要的設計原則：

- **記錄事實**放在實際工作的執行緒，只有那裡能確認真實情況。
- **判斷狀態**放在獨立的評估執行緒，因為卡住的執行緒無法回報自己卡住。
- 節點不直接設定狀態，只記錄事實。
- 不做完整狀態機：健康狀態由事實推導，失效也沒有事件可以觸發。只用一層薄的追蹤器保存狀態變化。

```text
工作執行緒 ── record_*() ──▶ NodeRecorder（有鎖）
                                  │
評估執行緒（每秒） ── evaluate() ◀─┘ ──▶ 狀態有變才更新 since、log、變化紀錄
                                  │
HTTP 執行緒 /status ◀── 讀取快取結果 ┘
```

### 2.2 狀態

只有 5 種，燈號顏色由後端依此對應（前端不重複實作）：

| 狀態 | 意義 | 顏色 |
|---|---|---|
| `ok` | 正常產出 | `green` |
| `degraded` | 仍有產出，但有異常 | `yellow` |
| `unavailable` | 應該產出但沒有產出 | `red` |
| `waiting` | 啟動中或上游沒有產出，節點本身沒有已知故障 | `gray` |
| `disabled` | 設定上已關閉 | `gray` |

共通原則：

- 沒有工作成果不等於異常，例如沒有偵測到物件仍可以是 `ok`。
- FPS 等數值只呈現，不判定狀態，門檻由外部決定。

## 3. 評估規則

由上往下，符合第一條就回傳。`stale_after_s` 等欄位定義見第 5 節。尚未就緒時改用第 3.1 節的規則。

| # | 條件 | 狀態 | `reason` |
|---|---|---|---|
| 1 | `enabled` 為 false | `disabled` | `disabled` |
| 2 | 已設定 fatal | `unavailable` | fatal 的 reason |
| 3 | 從未成功，且未超過 `startup_grace_s` | `waiting` | `starting` |
| 4 | 工作進行中超過 `stuck_after_s` | `unavailable` | `stuck` |
| 5 | 任一 dependency 為 false | `unavailable` | `dependency_unavailable` |
| 6 | 同一條 sequential lane 有其他節點符合第 4 條 | `waiting` | `lane_blocked` |
| 7 | 任一上游不是 `ok`、`degraded` | `waiting` | `upstream_not_ready` |
| 8 | 從未成功，且有設定 `stale_after_s` | `unavailable` | `never_succeeded` |
| 9 | 距離上次成功超過 `stale_after_s` | `unavailable` | `stale_reason`，預設 `stale_success` |
| 10 | `error_window_s` 內有錯誤 | `degraded` | 最近一次錯誤的 reason |
| 11 | 其他 | `ok` | `null` |

補充規則：

- `stale_after_s`、`stuck_after_s` 為 `None` 時跳過對應檢查，讓閒置也正常的節點（如 API server）不會誤報。
- dependency 為 `None` 代表無法判斷，視同通過。
- `startup_grace_s` 從就緒時刻開始計算（見第 3.1 節）。`wait_for_ready=False`（預設）時，就緒時刻就是 `HealthMonitor.start()`，`/status` 的 `started_at` 也是這個時間。
- 規則 9 的 `message` 固定為 `已 N 秒沒有成功紀錄`，N 取整數秒；規則 3、6、7、8 也使用函式庫內建的固定文字。
- dependency 的 `message` 要指出是哪個依賴，例如 `依賴 messaging 無法使用`。
- 上游的判斷使用同一輪評估的結果，節點依拓樸順序評估。
- 所有時間差使用 monotonic clock，不受系統時間調整影響。對外的時間字串使用含時區的 ISO 8601。

已知限制（本版不處理）：節點在 sequential lane 中拋例外時，同一輪後面的節點不會執行，可能因 stale 顯示 `unavailable`。

### 3.1 等待就緒（`wait_for_ready`）

啟動時要載入模型或暖機的服務，載入時間不固定。這類服務以 `wait_for_ready=True` 建立 `HealthMonitor`，在 `start()` 後就能提供 `/status`，載入完成後呼叫 `mark_ready()`，之後才開始判定。

| 項目 | `wait_for_ready=False`（預設） | `wait_for_ready=True` |
|---|---|---|
| 就緒時刻 | `start()` 的時刻，和 1.4 完全相同 | 第一次呼叫 `mark_ready()` 的時刻 |
| `mark_ready()` | 不做任何事，不拋例外 | 第一次呼叫時記錄就緒時刻，之後重複呼叫不做任何事 |

**就緒之前**，每個節點依序套用以下規則，符合第一條就回傳：

| # | 條件 | 狀態 | `reason` |
|---|---|---|---|
| 1 | 已設定 fatal | `unavailable` | fatal 的 reason |
| 2 | 其他 | `waiting` | `starting` |

- `message` 使用固定文字 `服務啟動中，尚未就緒`。不沿用規則 3 的文字，因為就緒前可能已經有成功紀錄。
- **就緒之前不呼叫 `enabled` 和 `dependencies` 的 callable**，因為它們可能引用還沒初始化的物件。
- 不判定 stuck、stale、`never_succeeded`、上游、lane、錯誤視窗。
- `NodeRecorder` 的所有方法照常接受呼叫並保存紀錄，業務執行緒不需要知道目前是否已就緒。

**就緒之後**套用第 3 節的規則。`wait_for_ready=True` 時再加上一條原則：**時間相關的判斷一律從就緒時刻起算**，也就是取「事件時間」和「就緒時刻」中較晚的一個。

| 規則 | `wait_for_ready=False`（同 1.4） | `wait_for_ready=True` |
|---|---|---|
| 3、8：`startup_grace_s` | `start()` | 就緒時刻 |
| 4：stuck（含規則 6） | `record_start()` 的時間 | `max(record_start 時間, 就緒時刻)` |
| 9：stale | 最後一次成功的時間 | `max(最後一次成功時間, 就緒時刻)` |
| 10：`error_window_s` | 錯誤發生的時間 | 就緒之前發生的錯誤不計入 |

- 「是否曾經成功」（規則 3、8）包含就緒之前的成功紀錄。
- 剛好發生在就緒時刻的錯誤要計入（時間 ≥ 就緒時刻）。
- 規則 9 的 `已 N 秒沒有成功紀錄`，N 也從較晚的那個時間起算。
- **`wait_for_ready=False` 時完全沿用 1.4 的公式，不取較晚時間。** `add_node()` 在 `start()` 前就回傳 recorder，事件可能早於 `start()`，既有行為依賴這點。

## 4. 通用契約（`schema_version: 1`）

契約文件和 JSON Schema 放在 `contract/`，範例放在 `contract/fixtures/`。函式庫和後端都必須以它們做測試。

### 4.1 共通規則

- `id` 格式：`^[a-z][a-z0-9_-]*$`。套用在 `service`，以及 lane、node、dependency、target 的 id。
- `instance` 不套用 `id` 格式，只要求是非空字串。
- `reason` 格式：`^[a-z][a-z0-9_]*$`，是固定代碼，不含動態內容。
- `message` 是遮蔽過的人類可讀文字，最多 200 字元，可為 `null`。
- 接受新增欄位：解析時要忽略未知欄位。
- `schema_version` 改變才代表不相容。後端必須同時支援目前版本和前一版。

### 4.2 `GET /topology`

```json
{
  "schema_version": 1,
  "service": "edge",
  "instance": "CamA-northbound-1",
  "topology_version": "3f9a1c7b2d4e6f80",
  "lanes": [
    {"id": "main", "label": "Main", "parent": null, "sequential": true,
     "nodes": ["ingest", "infer", "stream", "publish"]},
    {"id": "ingest-bg", "label": "Ingest worker", "parent": "ingest", "sequential": false,
     "nodes": ["ingest-worker"]},
    {"id": "stream-bg", "label": "Stream output", "parent": "stream", "sequential": false,
     "nodes": ["stream-output"]}
  ],
  "nodes": [
    {"id": "ingest", "label": "Ingest", "upstream": ["ingest-worker"], "dependencies": []},
    {"id": "publish", "label": "Publish", "upstream": ["infer"], "dependencies": ["messaging"]}
  ]
}
```

- `lanes[].parent` 是節點 id，代表這條 lane 從該節點分出；可以巢狀。`null` 表示頂層 lane。
- `lanes[].nodes` 的順序就是畫面上的箭頭順序。
- `upstream` 是判斷依據，不畫成箭頭，因為執行順序和資料依賴不一定相同。例如 `publish` 排在 `stream` 後面執行，但資料上游是 `infer`。
- `topology_version` 是 `lanes`、`nodes` 正規化 JSON（`sort_keys=True`、無空白）的 SHA-256 前 16 個十六進位字元。
- 被關閉的節點也要列出，畫面結構才會固定。

### 4.3 `GET /status`

```json
{
  "schema_version": 1,
  "service": "edge",
  "instance": "CamA-northbound-1",
  "topology_version": "3f9a1c7b2d4e6f80",
  "started_at": "2026-11-05T10:00:00+08:00",
  "ready_at": "2026-11-05T10:00:00+08:00",
  "evaluated_at": "2026-11-05T10:32:15+08:00",
  "evaluation_age_s": 0.4,
  "nodes": {
    "ingest-worker": {
      "state": "unavailable",
      "reason": "no_new_frame",
      "message": "已 12 秒沒有成功紀錄",
      "since": "2026-11-05T10:32:03+08:00",
      "metrics": {"fps": 0.0}
    }
  },
  "recent_transitions": [
    {"node": "ingest-worker", "from": "ok", "to": "unavailable",
     "reason": "no_new_frame", "at": "2026-11-05T10:32:03+08:00"}
  ]
}
```

- 正常評估時一律回 HTTP 200。節點異常不反映在 HTTP 狀態碼。
- `evaluation_age_s` 用 monotonic clock 在回應當下計算，**不受跨主機時鐘差異影響**。後端靠它判斷評估執行緒是否已停止。
- `since` 只有狀態改變才更新。reason 或 message 改變不更新 `since`、不算一筆變化。
- `recent_transitions` 由新到舊，最多 50 筆。第一次評估到的狀態也算一筆，`from` 為 `null`。
- `metrics` 的值只能是數字、字串、布林或 `null`。
- `ready_at`（1.5 新增）：就緒時刻，含時區的 ISO 8601 字串或 `null`；`null` 代表還沒就緒。`wait_for_ready=False` 時等於 `started_at`。這是新增欄位，`schema_version` 維持 1，JSON Schema 中為非必要欄位，1.4 函式庫的輸出仍然有效。後端與前端不使用這個欄位。

**第一輪評估完成前：** 回 HTTP 200，內容符合 schema，範例見 `contract/fixtures/status_before_first_evaluation.json`：

- `evaluated_at` 為 `null`，`nodes` 為 `{}`，`recent_transitions` 為 `[]`。
- `ready_at` 依上一段的規則輸出，同樣包含在回應中。
- `started_at` 已有值，`evaluation_age_s` 從 `start()` 起算。如果第一輪被阻塞，這個值會持續增加，後端因此判定為 `stale`。

**`HealthMonitor.start()` 之前：** `GET /topology`、`GET /status` 都回 HTTP 503 JSON。

### 4.4 敏感資訊

`/status` 沒有驗證，所有 `message` 寫入時都必須自動遮蔽：

| 輸入 | 輸出 |
|---|---|
| `rtsp://admin:secret@10.0.0.1/live` | `rtsp://***@10.0.0.1/live` |
| `password=secret`、`token: abc` | `password=***`、`token: ***` |
| `Authorization: Bearer abc`、`Authorization: Basic dXNlcjpwYXNz` | `Authorization: Bearer ***`、`Authorization: Basic ***` |
| `api-key=abc`、`x-api-key: abc` | `api-key=***`、`x-api-key: ***` |

- 關鍵字至少涵蓋 `password`、`passwd`、`pwd`、`secret`、`token`、`api_key`、`apikey`、`authorization`，不分大小寫，鍵名含有關鍵字就遮蔽（例如 `db_password`、`x-api-key`）。
- 比對關鍵字時，鍵名中的 `-` 和 `_` 視為相同，所以 `api-key`、`x-api-key`、`API-KEY` 都會遮蔽。
- `Authorization` 的值為「scheme、空白、憑證」時，保留 scheme，只遮蔽憑證，例如 `Authorization: Bearer ***`；值只有一段時整段遮蔽。值加了引號時，和其他鍵一樣整段遮蔽，例如 `"Authorization": "***"`。
- metrics 的字串值也一樣遮蔽。
- 已知限制要寫進導入指南，見第 11 節。

## 5. 函式庫 `smart-health-record`

- PyPI 名稱 `smart-health-record`，匯入名稱 `smart_health_record`，目前 `0.1.1`。
- MIT 授權（`packages/health_record/LICENSE`）。wheel 和 sdist 都包含 `LICENSE`，METADATA 有 `License-Expression: MIT`；作者只寫名稱，不寫 email。
- sdist 只包含 `src/`、`README.md`、`LICENSE`、`pyproject.toml`（以及建置產生的 `PKG-INFO`）。測試需要 repo 的 `contract/`，只在 repo 中執行。
- `requires-python = ">=3.10"`。**執行時只用標準函式庫，不綁任何框架**。
- 測試工具（`pytest`、`jsonschema`）只放在 `dev` extras。

### 5.1 公開 API

```python
class HealthMonitor:
    def __init__(self, service: str, instance: str, *,
                 tick_interval_s: float = 1.0,
                 max_transitions: int = 200,
                 logger: logging.Logger | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], datetime] = <含本地時區的現在時間>,
                 wait_for_ready: bool = False) -> None: ...

    def add_lane(self, lane_id: str, label: str, *,
                 parent: str | None = None, sequential: bool = False) -> None: ...

    def add_node(self, node_id: str, label: str, lane: str, *,
                 upstream: Sequence[str] = (),
                 dependencies: Mapping[str, Callable[[], bool | None]] | None = None,
                 enabled: bool | Callable[[], bool] = True,
                 stale_after_s: float | None = None,
                 stuck_after_s: float | None = None,
                 startup_grace_s: float = 30.0,
                 error_window_s: float = 30.0,
                 stale_reason: str = "stale_success") -> NodeRecorder: ...

    def start(self) -> None: ...          # 驗證架構並啟動評估執行緒，可重複呼叫
    def stop(self) -> None: ...           # 可重複呼叫
    def evaluate_once(self) -> None: ...  # 執行一輪評估，供測試使用；未 start() 時視為以當下時間開始，但不啟動執行緒
    def topology(self) -> dict: ...       # start() 前拋 RuntimeError
    def status(self) -> dict: ...         # start() 前拋 RuntimeError
    def mark_ready(self) -> None: ...     # 宣告已就緒（第 3.1 節）；start() 前拋 RuntimeError
    def recorder(self, node_id: str) -> NodeRecorder: ...  # 依 id 取得 add_node() 回傳的同一個物件；不存在時拋 KeyError


class NodeRecorder:
    def record_start(self) -> None: ...
    def record_success(self) -> None: ...
    def record_skip(self) -> None: ...
    def record_error(self, reason: str, message: str | None = None) -> None: ...
    def set_fatal(self, reason: str, message: str | None = None) -> None: ...
    def clear_fatal(self) -> None: ...
    def set_metric(self, name: str, value: float | int | str | bool | None) -> None: ...
    def track(self) -> ContextManager[None]: ...


class StatusServer:
    def __init__(self, monitor: HealthMonitor, *, port: int, host: str = "127.0.0.1") -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    @property
    def port(self) -> int: ...  # 實際 port；傳入 0 時由系統分配


def mask_text(text: str) -> str: ...
```

`smart_health_record/__init__.py` 只公開以上 4 個名稱，以及 `__version__`。

### 5.2 行為要求

**啟動階段（設定錯誤要立即拋 `ValueError`）**

下列情況由 `add_lane`、`add_node` 或 `start()` 拋出：id 重複或格式錯誤、lane 不存在、upstream 或 `parent` 指向不存在的節點、upstream 形成循環、`parent` 形成循環、`start()` 後再新增 lane 或節點、數值參數為負。

**執行階段（`NodeRecorder` 的方法絕對不能讓例外跑進業務執行緒）**

- `reason` 格式錯誤時改用 `invalid_reason`，並記一次警告。
- `set_metric` 的值型別錯誤時忽略，並記一次警告。
- `record_success`、`record_error`、`record_skip` 都會清除進行中狀態。
- `record_skip()`（1.5 新增）：這次執行的結果是「跳過」，例如沒有新畫面。只清除進行中狀態，其他紀錄都不變：最後一次成功時間、錯誤、fatal、metrics 都保持原樣。
  - 跳過不算成功，所以不會讓 stale 重新計時；節點持續跳過時，最後仍會依規則 9 判定為 stale（前提是上游正常）。這樣上游斷線時，下游不會因為「有在執行」而顯示綠燈。
  - 沒有進行中的工作時呼叫，不做任何事。
- `track()` 進入時 `record_start`；正常結束時 `record_success`；發生例外時 `record_error("exception", <例外訊息>)`，然後**原樣往外拋**。

**就緒（`mark_ready()`）**

- 不論 `wait_for_ready` 為何，`start()` 之前呼叫都拋 `RuntimeError`，和 `topology()`、`status()` 一致。`evaluate_once()` 的隱含 start 也算已開始。
- `start()` 之後：`wait_for_ready=False` 時不做任何事；`wait_for_ready=True` 時第一次呼叫記錄就緒時刻，重複呼叫不改變就緒時刻。
- 可以從任何執行緒呼叫，不能阻塞，也不做 I/O。多個執行緒同時呼叫時，以第一個為準。只短暫取用記錄用的鎖，不碰評估鎖。
- 新的就緒狀態在下一輪評估時反映即可，不立即觸發評估。

**依 id 取得 recorder（`recorder()`，1.6 新增）**

- 回傳 `add_node(node_id, ...)` 回傳的**同一個物件**，不建立新物件。
- `add_node()` 之後的任何時候都可以呼叫：`start()` 之前、執行中、`stop()` 之後都可以。
- 執行緒安全：和 `add_node()` 使用同一把鎖，只短暫持有，不碰評估鎖，不做 I/O。
- 節點不存在時拋 `KeyError`，訊息為繁體中文，並以 `repr` 顯示傳入的 id。傳入的不是字串時（包括無法雜湊的值），同樣視為不存在，拋 `KeyError` 而不是 `TypeError`。
- 不改變 `add_node()` 的回傳值和其他任何行為。

**評估執行緒**

- 每個 `HealthMonitor` 一條 daemon 執行緒。
- 執行緒啟動後立刻跑第一輪評估，不等第一個 tick。
- `dependencies`、`enabled` 的 callable 在評估執行緒呼叫，就緒之前不呼叫。專案必須提供不阻塞的 callable，這點要寫進文件。
- callable 拋例外時，dependency 視為 `None`、`enabled` 視為 `True`，同一個 callable 連續失敗只記一次警告。
- 評估本身拋例外時，記錄後繼續下一輪，不能讓執行緒結束。
- 狀態改變時寫 log：進入 `unavailable` 用 WARNING，其他用 INFO。

**HTTP server**

- 使用標準函式庫 `ThreadingHTTPServer`，daemon 執行緒。
- 只接受 `GET /topology`、`GET /status`，其他路徑回 404 JSON，其他方法回 405。
- `HealthMonitor` 尚未 `start()` 時，`StatusServer` 把 `RuntimeError` 轉成 503 JSON。
- `port` 為必填，沒有預設值，因為同一台主機可能有多個實體。
- 預設只綁定 `127.0.0.1`，對外要由專案明確設定。
- 綁定失敗時 `start()` 拋 `OSError`，由專案決定如何處理。
- `/status` 只讀取快取結果，不觸發評估，也不等待評估中的鎖。
- 不提供 CORS，瀏覽器不直接呼叫這些接口。

### 5.3 效能要求

`record_success`、`record_skip` 會在主迴圈高頻呼叫，只能寫時間戳或旗標：

- 不做 I/O，不產生大量物件。
- 單次平均低於 20 微秒。以 `benchmarks/bench_recorder.py` 量測，不放進 CI 判定。
- `bench_recorder.py` 同時量測 `record_skip`，耗時要和 `record_success` 同一量級。

## 6. 後端

- FastAPI、Pydantic v2、httpx、uvicorn、PyYAML，Python 3.11。
- 設定路徑由環境變數 `SMART_HEALTH_CONFIG` 指定，預設 `config/targets.yaml`。
- `config/targets.yaml` 不進版控，只追蹤 `config/targets.example.yaml`。
- 例外：`config/targets.dev.yaml` 供 `docker-compose.dev.yml` 使用，也進版控，內容只能是模擬服務的位址。

```yaml
poll_interval_s: 5        # 拉取與前端更新的間隔
request_timeout_s: 2
evaluation_stale_after_s: 10
history_limit: 200
max_response_bytes: 1048576   # 單次回應本文的上限（1 MiB）
targets:
  - id: mock-edge-a
    name: Mock Edge A
    base_url: http://mock-edge-a:18081
```

設定無效（格式錯誤、`id` 重複、數值不是正數、`base_url` 不是 http 或 https）時，啟動就要失敗，並指出是哪個欄位。

### 6.1 拉取行為

- 每個目標一個獨立的 async 工作，**慢或掛掉的目標不能影響其他目標**。
- 先取 `/topology`，之後定期取 `/status`。
- `/status` 的 `topology_version` 改變，或 `started_at` 改變（服務重啟）時，重新取 `/topology`。
- 不跟隨重新導向。
- 回應本文超過 `max_response_bytes` 時立即停止讀取，不把整份內容讀入記憶體，本輪判為 `invalid_response`。`Content-Length` 已超過上限時不讀取本文。`request_timeout_s` 涵蓋包含讀取本文在內的整個請求。

每個目標的連線狀態：

| `connection` | 條件 |
|---|---|
| `unknown` | 尚未完成第一次拉取 |
| `online` | 最近一次拉取成功，且資料有效 |
| `offline` | 連線失敗或逾時，或回應不是 2xx |
| `stale` | 有回應，但 `evaluation_age_s` 超過 `evaluation_stale_after_s` |
| `incompatible` | `schema_version` 不受支援 |
| `invalid_response` | 回應不是 JSON、不符合契約，或本文超過 `max_response_bytes` |

不是 `online` 時，保留上一次的架構讓畫面維持結構，但**所有節點一律回傳 `gray`**，不能保留上一次的顏色，也不回傳舊狀態。每個節點的內容固定為：

| 欄位 | 值 |
|---|---|
| `state`、`message`、`since` | `null` |
| `metrics` | `{}` |
| `reason` | 連線代碼，也就是 `connection` 的值 |
| `color` | `gray` |

狀態和架構不一致時：

- 架構有、狀態沒有的節點：`state`、`message`、`since` 為 `null`，`metrics` 為 `{}`，`color` 為 `gray`，`reason` 為 `status_missing`。第一輪評估前 `nodes` 為 `{}`，所以此時連線為 `online`，所有節點都是這個結果。
- 狀態有、架構沒有的節點：忽略並記 log。

### 6.2 API

| 端點 | 內容 |
|---|---|
| `GET /api/config` | `{"poll_interval_s": 5}` |
| `GET /api/targets` | 目標清單：`id`、`name`、`connection`、`summary_color`、`last_success_at` |
| `GET /api/targets/{id}` | 目標資訊，加上 `topology` 和帶 `color` 的節點狀態 |
| `GET /api/targets/{id}/transitions?limit=` | 由新到舊的狀態變化，`limit` 預設 50，超過 `history_limit` 時壓到上限，小於 1 回 422 |
| `GET /healthz` | 後端自身狀態 |
| `GET /` 等 | 前端靜態檔案 |

- `summary_color`：不是 `online` 時為 `gray`；否則依序取 `red` > `yellow` > `green` > `gray` 中最嚴重且存在的顏色。
- 找不到目標時回 404。
- 回應**不包含 `base_url`** 和原始錯誤字串，錯誤以 `connection` 代碼呈現。
- 記憶體內保留狀態變化，依 `(node, at, to)` 去重，每個目標最多 `history_limit` 筆。後端重啟就會消失。
- 被監控服務回傳的內容視為不可信資料，只驗證後轉傳。

## 7. 前端

- React 18、TypeScript、Vite 5（與 `mcmot_inspector` 一致），不引入 UI 框架。
- 介面文字使用繁體中文。
- 只呼叫同源的後端 API，建置成靜態檔案，由後端提供。
- 更新間隔依 `/api/config` 的 `poll_interval_s`。

### 7.1 畫面

畫面分成**服務總覽**與**服務畫面**兩層，以網址的 hash 區分，後端不需要配合：

| hash | 畫面 |
|---|---|
| `#/`、空白 | 總覽第 1 頁 |
| `#/?page=N` | 總覽第 N 頁 |
| `#/targets/<id>` | 服務畫面 |
| 其他 | 以 replace 改寫成 `#/`，不新增瀏覽紀錄 |

- 上一頁、下一頁、重新整理和書籤都要能用。
- `#/?page=N` 只看 `page`，`N` 必須是正整數（`^[1-9][0-9]*$`），否則顯示第 1 頁並以 replace 改寫成 `#/`。
- `#/targets/` 之後的內容解碼後當作 id。解碼失敗（例如不完整的 `%`）、空白或不符合第 4.1 節的 id 格式時，視為找不到服務，不改寫網址。
- 沒有目標下拉選單，一律從總覽切換服務；也不會自動選第一個目標。

#### 服務總覽

```text
服務總覽                                  最後更新 10:32:15（每 5 秒）
正常 6　注意 1　異常 1　離線或等待 2

┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│ [G] Mock Edge A  │ │ [Y] Mock Edge B  │ │ [-] Mock API     │
│ 正常             │ │ 注意             │ │ 無法連線         │
│ online           │ │ online           │ │ offline          │
│ 最後更新 10:32:15│ │ 最後更新 10:32:14│ │ 最後成功 10:20:01│
└──────────────────┘ └──────────────────┘ └──────────────────┘

        [上一頁]  第 1 / 2 頁（共 30 個服務）  [下一頁]
```

- **頂端：** 標題「服務總覽」，以及「最後更新 HH:MM:SS（每 N 秒）」。時間是前端最後一次成功取得 `/api/targets` 的時間，從未成功時顯示「尚未取得」。
- **統計列：** 一律顯示「正常」「注意」「異常」「離線或等待」4 類，依**全部目標**（不只目前這一頁）的 `summary_color`（`green`、`yellow`、`red`、`gray`）計數，0 也顯示。後端請求失敗時 4 類的數字都顯示「—」，恢復後重新計數。
- **卡片：** 每個目標一張，順序和 `/api/targets` 相同（也就是 `targets.yaml` 的順序），內容為：
  - 燈號：顏色取 `summary_color`。
  - 名稱：最多顯示兩行，超過的部分用省略號，完整名稱放在 `title`。
  - 狀態文字（下表）：顏色不能是唯一線索。
  - 連線代碼與時間：`online` 顯示「最後更新 HH:MM:SS」；其他顯示「最後成功 HH:MM:SS」，從未成功時顯示「尚未取得」。

  | `connection` | `summary_color` | 狀態文字 |
  |---|---|---|
  | `online` | `green` | 正常 |
  | `online` | `yellow` | 注意 |
  | `online` | `red` | 異常 |
  | `online` | `gray` | 等待中 |
  | `unknown` | — | 尚未取得 |
  | `offline` | — | 無法連線 |
  | `stale` | — | 資料過舊 |
  | `incompatible` | — | 版本不相容 |
  | `invalid_response` | — | 回應無效 |

- **卡片是連結**（`<a href="#/targets/<id>">`），可以用鍵盤操作，也可以在新分頁開啟。
- **尺寸固定：** 卡片的最小寬度與高度固定，每列張數依視窗寬度自動調整（`repeat(auto-fill, minmax(220px, 1fr))`），不縮小卡片來塞更多。
- **分頁：**
  - 每頁 24 個。目標不超過 24 個時不顯示分頁列。
  - 分頁列有「上一頁」「下一頁」和「第 N / M 頁（共 K 個服務）」，頁碼寫在 hash（第 1 頁為 `#/`）。
  - 頁碼超過最後一頁時（例如目標減少）顯示最後一頁，以 replace 改寫 hash。只在取得目標清單後判斷；還沒取得或後端請求失敗時不改寫。沒有目標時最後一頁是第 1 頁。
- **後端請求失敗：** 顯示錯誤橫幅並繼續重試；卡片保留，燈號一律轉灰，狀態文字顯示「未知」。
- **沒有任何目標：** 顯示「尚未設定任何服務」。
- 總覽只輪詢 `/api/targets`，不呼叫各目標的詳細資料。

#### 服務畫面

```text
(<) Mock Edge A   [G] 正常                最後更新 10:32:15（每 5 秒）

MAIN     [G] ingest --> [G] infer --> [G] stream --> [G] publish
              4.00/s       4.00/s
              |                            |
              v                            v
BG       [G] ingest-worker            [G] stream-output
```

點擊節點後顯示：

```text
ingest-worker
  狀態：unavailable
  原因：no_new_frame
  說明：已 12 秒沒有成功紀錄
  開始時間：10:32:03
  指標：duration_ms = 12.35
```

- **頂端：** 「回到總覽」圖示連結（見「視覺」）、服務名稱、總體燈號與狀態文字（同總覽的狀態文字表），以及最後更新時間。
- **回到總覽：** 回到這次瀏覽中最後看過的總覽頁；直接開啟服務網址時回到第 1 頁。
- 服務畫面只輪詢 `/api/targets/{id}`。
- **找不到服務**（404，或 id 不符合格式）：顯示「找不到服務 `<id>`」和同一個「回到總覽」圖示連結，並照常輪詢；目標之後加回設定時，畫面自動恢復。

#### 數值格式

指標值只在顯示時格式化，`/status` 與後端 API 保留完整精度：

| 值 | 顯示 |
|---|---|
| 整數 | 原樣，例如 `7` |
| 非整數的數字 | 小數 2 位（四捨五入），例如 `3.998789` → `4.00`、`0.023092` → `0.02`；`-0.001` → `0.00`，不顯示 `-0.00` |
| 字串、布林 | 原樣 |
| `null` | `—` |

- 指標維持原本的鍵名（例如 `duration_ms`），不翻譯。
- **每秒次數：** 節點的 `metrics.rate_per_s` 是數字時，在燈號的狀態文字下方顯示 `N.NN/s`：**整數也一律小數 2 位**（四捨五入，不顯示 `-0.00`），例如 `0` → `0.00/s`、`4` → `4.00/s`、`3.998789` → `4.00/s`、`-0.001` → `0.00/s`。`rate_per_s` 是 count/elapsed，實務上只有停住的節點會是整數 0，一律 2 位才會和其他節點一致；詳細面板的指標仍依上表（整數原樣）。沒有這個指標或不是數字時不顯示。服務不是 `online` 或後端請求失敗時也不顯示。`rate_per_s` 是 smart-workflow 為每個節點產生的標準指標；其他整合方式只要提供同名指標就會顯示。單位寫 `/s` 而不是 `fps`，因為節點處理的不一定是畫面。

#### 視覺

只改外觀，顏色的判斷規則（`summary_color`、節點的 `color`、不是 `online` 或後端請求失敗時轉灰）與狀態文字都不變；顏色不是唯一線索。

**發光燈號：** 節點燈號、總覽卡片、服務畫面頂端的總體燈號、統計列的圓點都用同一種燈號。所有燈號都有 `1px solid rgba(0,0,0,.18)` 的邊框；亮燈（綠、黃、紅）有中心高光與同色光暈，灰色是沒亮的燈，只有內陰影、沒有光暈。

| 顏色 | 背景 | `box-shadow` |
|---|---|---|
| 綠 | `radial-gradient(circle at 35% 30%, #c8f7d3 0, #34c759 38%, #1e8e3e 80%)` | `0 0 5px 1px rgba(52,199,89,.42)` |
| 黃 | `radial-gradient(circle at 35% 30%, #fff3c4 0, #ffc107 40%, #c98f00 85%)` | `0 0 5px 1px rgba(255,193,7,.45)` |
| 紅 | `radial-gradient(circle at 35% 30%, #ffd0cb 0, #ff4d3d 40%, #c5221f 85%)` | `0 0 5px 1px rgba(255,77,61,.45)` |
| 灰 | `radial-gradient(circle at 35% 30%, #eceef1 0, #bfc5cc 60%, #9aa0a6 100%)` | `inset 0 1px 2px rgba(0,0,0,.22)`（沒有光暈） |

尺寸：節點燈號與卡片 14px，統計列 12px，服務畫面頂端 18px。

**總覽卡片的底色：** 依 `summary_color`（後端請求失敗時為灰）。不加左側色邊；hover、focus 的樣式不變。文字（`--fg`、`--muted`）在這些底色上的對比都在 4.5:1 以上。

| 顏色 | 背景 | 邊框 |
|---|---|---|
| 綠（正常） | `#ffffff` | `--border` |
| 黃（注意） | `#fffcf2` | `#f1e2b8` |
| 紅（異常） | `#fef7f6` | `#f3d2ce` |
| 灰（離線、等待、未知） | `#f8f9fa` | `#e1e4e8` |

**回到總覽：** 仍是 `<a href>`（可以在新分頁開啟），44×44px 的圓形圖示：白底、`--border` 邊框，內容是向左的箭頭（inline SVG，`stroke="currentColor"`，路徑 `M15 18l-6-6 6-6`，`aria-hidden="true"`）。`aria-label` 與 `title` 都是「回到總覽」，沒有可見文字。放在服務名稱左側的同一行，窄螢幕時照常換行；找不到服務的畫面也用同一個連結。目的地規則不變。

**主迴圈的光點流動：**

- **範圍：** 服務畫面中每一條 `sequential` 且有 2 個以上節點的 lane（含巢狀的）各自判斷；非 sequential 的 lane 不流動。不寫死 lane 或節點名稱。上層 lane 流動不影響子 lane。
- **條件（每次輪詢後重新判斷）：** 目標是 `online`、後端請求沒有失敗、而且這條 lane 的每個節點顏色都是綠。任一條件不成立時停止，燈號維持靜態的發光樣式。lane 元素的 `data-flowing` 為 `"true"` 或 `"false"`，依上述條件判斷。
- **箭頭：** 相鄰節點之間是寬 40px 的線條加箭頭：線 2px `#c5cbd3`，右端是同色三角形；元素保留 `lane-arrow` class 與 `aria-hidden="true"`。
- **順序與時間：** 以 0.32 秒為一格，依序為「節點 1、箭頭 1、節點 2、箭頭 2……最後一個節點」，接著停頓 3 格，然後重來。n 個節點時一輪為 `(2n + 2) × 0.32` 秒；第 k 個節點延遲 `2(k − 1) × 0.32` 秒，第 k 個箭頭延遲 `(2k − 1) × 0.32` 秒。例如 4 個節點一輪 3.20 秒，第 3 個節點延遲 1.28 秒。
  - **節點經過時：** 燈號外框加上光暈 `0 0 0 4px rgba(52,199,89,.12), 0 0 16px 2px rgba(52,199,89,.30)`，圓點光暈加強為 `0 0 12px 4px rgba(52,199,89,.75)`；約 0.1 秒達到最亮，約 0.38 秒回到原樣。選取中的燈號在光暈中保留選取框。
  - **箭頭經過時：** 8px 的光點（`#7bf09a`，光暈 `0 0 8px 3px rgba(52,199,89,.75)`）在這一格內由左移到右，淡入淡出。
  - 速度固定，不和 `rate_per_s` 連動。光點是裝飾，不代表實際的畫面或事件。
- **不流動：** 系統設定 `prefers-reduced-motion: reduce`，或視窗寬度 640px 以下。這時 `data-flowing` 仍依資料判斷，只由 CSS 把動畫關掉（`animation-name` 為 `none`）。
- **實作：** 只用 CSS 動畫（`transform`、`opacity`、`box-shadow`），不用計時器或 `requestAnimationFrame` 逐格更新 React state。keyframes 的百分比依一輪的長度而定，因此由架構圖輸出一個 `<style>`，依畫面上出現的節點數各產生一組 keyframes（例如 `flow-node-n4`），內容只由整數 n 與計算出的數字組成，同樣的 n 產生同樣的文字。輪詢更新資料時燈號與箭頭的 DOM 元素保留，不重新掛載，動畫不會重新開始。選取節點的樣式照常，可以和流動同時出現。

要求：

1. **由 `/topology` 動態產生，不寫死任何節點名稱**。要支援任意 lane 數量、每條任意節點數、巢狀 lane，並用不同架構的模擬服務驗證。
2. 燈號顏色不能是唯一線索，還要有狀態文字或圖示，讓色弱使用者也能分辨。`state` 為 `null` 時顯示「未知」。
3. 不是 `online` 時，顯示橫幅和最後成功時間，例如「無法連線到此服務，最後更新 10:32:15」，所有燈號轉灰。
4. 更新後保留目前選取的節點和詳細面板；節點不存在或切換到其他服務時才關閉。
5. 前後端連線失敗時也要顯示錯誤並繼續重試，不能白畫面；總覽與服務畫面的燈號都轉灰並顯示「未知」。
6. 所有來自被監控服務的文字都以純文字呈現，不使用 `dangerouslySetInnerHTML`。
7. 寬度 360px 時總覽與服務畫面都不能水平捲動，架構圖可在自己的區域內捲動。
8. 網址、總覽、分頁、服務畫面、數值格式與每秒次數的行為都要有單元測試；端對端測試涵蓋「總覽 → 卡片 → 服務 → 回到總覽」與直接開啟服務網址。

## 8. 模擬資料

使用者要求：**先用模擬資料完成前後端對接與測試，全部通過後才導入真實專案**。

模擬服務放在 `examples/mock_service/`，必須使用真實的 `smart-health-record` 函式庫，讓契約得到實際驗證。

```bash
python -m mock_service --profile edge --instance mock-edge-a --host 0.0.0.0 \
  --port 18081 --control-port 19081
```

控制接口：`POST /scenario {"name": "camera_down"}`、`GET /scenario`。模擬執行緒以真實的呼叫方式操作 recorder。

控制接口在獨立的 port 上獨立運作，不會隨 monitor 或 server 重建。

### 8.1 `edge` 模擬架構

與第 4.2 節相同，共 6 個節點。

| 節點 | lane | 上游 | 依賴 | 其他設定 |
|---|---|---|---|---|
| `ingest-worker` | `ingest-bg` | 無 | 無 | `stale_reason="no_new_frame"` |
| `ingest` | `main` | `ingest-worker` | 無 | |
| `infer` | `main` | `ingest` | 無 | `stuck_after_s` 有設定 |
| `stream` | `main` | `infer` | 無 | |
| `stream-output` | `stream-bg` | `stream` | `stream_sink` | |
| `publish` | `main` | `infer` | `messaging` | |

`main` 是 sequential lane，所有節點都設定 `stale_after_s`。依賴使用抽象角色名稱，不使用具體實作名稱。`stream_sink` 依賴只有在有畫面時才回傳 true 或 false，否則回傳 `None`，避免相機斷線被誤判成推流問題。

`stale_after_s`、`startup_grace_s` 等門檻可用命令列參數調短，讓測試不用等太久。

### 8.2 必須通過的情境

`G` = `ok`，`Y` = `degraded`，`R` = `unavailable`，`灰` = `waiting`（`disabled` 另外標註）。

| 情境 | `ingest-worker` | `ingest` | `infer` | `stream` | `stream-output` | `publish` |
|---|---|---|---|---|---|---|
| `normal` | G | G | G | G | G | G |
| `starting` | 灰 | 灰 | 灰 | 灰 | 灰 | 灰 |
| `camera_down` | R | 灰 | 灰 | 灰 | 灰 | 灰 |
| `messaging_down` | G | G | G | G | G | R |
| `stream_sink_down` | G | G | G | G | R | G |
| `infer_stuck` | G | 灰 | R | 灰 | 灰 | 灰 |
| `infer_exception` | G | G | R | 灰 | 灰 | 灰 |
| `camera_and_messaging_down` | R | 灰 | 灰 | 灰 | 灰 | R |
| `read_errors` | Y | G | G | G | G | G |
| `publish_errors` | G | G | G | G | G | Y |
| `worker_fatal` | R | 灰 | 灰 | 灰 | 灰 | 灰 |
| `stream_disabled` | G | G | G | `disabled` | `disabled` | G |
| `loading` | 灰 | 灰 | 灰 | 灰 | 灰 | 灰 |
| `loading_fatal` | R | 灰 | 灰 | 灰 | 灰 | 灰 |

- `starting`：規則 3 要求「從未成功」，所以切到這個情境時，mock 會重建 `HealthMonitor` 和 `StatusServer` 來模擬服務重啟，`started_at` 也會改變，函式庫不提供重置 API。此情境不記錄成功，`startup_grace_s` 要大於觀察所需的時間。重建期間 `/status` 會短暫連不上，後端可能短暫顯示 `offline`，這是預期行為。
- `infer_exception`：`infer` 持續以 `track()` 拋例外。依規則 9 為 `R`，超過 stale 門檻前是 `Y`。
- `camera_and_messaging_down`：依賴檢查排在上游檢查之前，所以 messaging 問題仍看得到。
- `stream_disabled`：`stream`、`stream-output` 的 `enabled` 為 false，下游 `publish` 依賴 `infer`，不受影響。
- `loading`、`loading_fatal`：以 `wait_for_ready=True` 重建 `HealthMonitor` 和 `StatusServer`，期間不呼叫 `mark_ready()`。`loading` 期間模擬執行緒仍持續記錄成功，用來驗證就緒之前不會判定；`loading_fatal` 在 `ingest-worker` 設定 fatal。灰色節點的 `reason` 都是 `starting`，`ready_at` 為 `null`。從這兩個情境切換到其他情境時呼叫 `mark_ready()`，不重建。既有的 `starting` 情境維持原做法，作為 `wait_for_ready=False` 的對照。

### 8.3 其他模擬服務

| 名稱 | 用途 |
|---|---|
| `api` 架構 | 驗證通用性：非 Edge 命名；節點有 2 個依賴（`database`、`cache`）、多個上游；有巢狀 lane；`stale_after_s=None`，閒置仍為 `ok` |
| `raw_mock` | 驗證後端防護，模式包含 `hang`（不回應）、`http_500`、`invalid_json`、`wrong_schema`（`schema_version: 999`）、`missing_nodes`（缺少節點）、`topology_change`（改變版本）、`evaluation_stale`（`evaluation_age_s` 過大） |

`raw_mock` 不使用函式庫，才能回傳不符合契約的內容。

## 9. Repo 結構

```text
smart_health/
├── README.md
├── CHANGELOG.md                   # 各版本的變更
├── contract/                      # 契約文件、JSON Schema、fixtures
├── packages/health_record/        # smart-health-record 函式庫
│   ├── pyproject.toml
│   ├── src/smart_health_record/
│   ├── tests/
│   └── benchmarks/
├── apps/
│   ├── backend/                   # FastAPI
│   └── frontend/                  # React + Vite
├── examples/
│   ├── mock_service/              # 使用函式庫的模擬服務
│   └── raw_mock/                  # 不符合契約的模擬服務
├── e2e/                           # Playwright 端對端測試
├── config/
│   ├── targets.example.yaml
│   └── targets.dev.yaml           # 只含模擬服務的位址
├── deploy/
│   ├── Dockerfile
│   ├── docker-compose.yml         # Health App 實體
│   ├── docker-compose.host.yml    # host 網路，用於 Orin 這類環境
│   └── docker-compose.dev.yml     # Health App + 所有模擬服務
├── docs/                          # 規格書、導入指南、部署說明與截圖
└── .github/workflows/
```

**依賴邊界：** `apps/` 可以依賴 `contract/`；函式庫不能依賴 `apps/`；`mock_service` 只依賴函式庫。每個檔案只負責一件事，避免單檔過大。

## 10. 發布與部署

- 映像檔支援 `linux/amd64`、`linux/arm64`，因為部署主機尚未決定，可能是 Orin。`linux/amd64` 已驗證；`linux/arm64` 由 CI 建置並以 QEMU smoke test，實機（例如 Orin）尚未驗證，部署到 arm64 主機前必須驗證。
- 提供 `docker-compose.host.yml`：已知部分 Orin 的 kernel 沒有 iptables `raw` 表，Docker bridge 網路無法建立。
- 函式庫 tag 用 `record-vX.Y.Z`，App tag 用 `app-vX.Y.Z`，兩者獨立。
- CI 有兩個 workflow。`ci.yml` 是唯一的入口，push 到 `main`、push `app-vX.Y.Z` tag、pull request 與手動執行時觸發，只改 `**/*.md`、`docs/**` 時跳過（tag 不套用路徑過濾）；測試全部通過後才呼叫 `docker.yml`：
  - `ci.yml`：用固定版本的 ruff（0.8.4）檢查 `packages`、`contract`、`examples`、`apps`；契約與函式庫測試（Python 3.10、3.11）；後端測試；模擬服務測試；前端 lint、typecheck、測試與建置。測試 job 不使用 secrets。tag 推送也會重跑測試。
  - `docker.yml`：reusable workflow，GitHub 上的 job 名稱是 `docker / image`。任一測試 job 失敗時不執行。建置 Health App 映像檔（`linux/amd64`、`linux/arm64`），兩個平台都 smoke test 後推到 Docker Hub。
    - pull request 只建置與 smoke test，不推送。
    - push 到 `main` 推送 `sha-<commit 前 7 碼>`；`app-vX.Y.Z` 推送 `X.Y.Z`，版本必須等於前端 `package.json` 的 `version`。
    - 不推送 `latest`，已存在的 tag 不覆寫。
- e2e 與函式庫的打包檢查（build、`twine check`）不在 CI 執行，由維護者在本機執行。
- **PyPI 發布由維護者手動執行。**

## 11. 驗收標準

1. 所有測試和 lint 通過，輸出沒有未說明的警告。
2. `docker compose -f deploy/docker-compose.dev.yml up --build` 能在乾淨環境啟動全部服務。
3. 第 8.2 節的每個情境都有自動化測試，在函式庫層和端對端層都驗證。
4. 第 8.3 節每個模式都有自動化測試，其他目標不受影響。
5. `api` 架構不修改前端程式就能正確顯示。
6. 被監控服務的所有回應中都查不到第 4.4 節的敏感內容。
7. `smart-health-record` 的 wheel 安裝在只有標準函式庫的 Python 3.10 虛擬環境中可以正常運作。
8. `bench_recorder.py` 的量測結果符合第 5.3 節。
9. 文件完整：README、契約文件、函式庫導入指南、部署說明。
10. 導入指南要說明 callable 不能阻塞、port 由專案指定、`message` 會被遮蔽，並列出遮蔽的已知限制。
11. 前端網址：第 7.1 節 hash 表的每一種情況、上一頁、下一頁、重新整理後停在同一畫面，都有單元測試。
12. 總覽：狀態文字表的每一列、統計列以全部目標計數、卡片是連結、後端失敗時轉灰並顯示「未知」，都有單元測試。
13. 分頁：以 30 個目標驗證每頁 24 個、頁碼不合法、目標減少時的頁碼；24 個以下不顯示分頁列。
14. 服務畫面：回到總覽回到原本的頁碼；404 與 id 格式不符時顯示找不到服務；目標加回後自動恢復。
15. 數值格式：整數、非整數、負數、`-0.001`、字串、布林、`null` 都有單元測試；每秒次數涵蓋有、沒有 `rate_per_s`、`N.NN/s` 格式（含整數 `0`、`4` 與 `-0.001`），以及不是 `online` 或後端失敗時不顯示。
16. 端對端測試包含「總覽 → 卡片 → 服務 → 回到總覽」與直接開啟服務網址；寬度 360px 時總覽與服務畫面都不能水平捲動。
17. 發光燈號：四種顏色的燈號有對應的 class 或 `data-color`（單元測試）；e2e 以 `getComputedStyle` 確認綠燈有光暈、灰燈沒有。
18. 卡片底色：四種 `summary_color` 與後端失敗時的卡片 class（單元測試）；e2e 以 `getComputedStyle` 確認四種背景色。
19. 回到總覽：是 `<a>`、有 `aria-label` 與 `title`、沒有可見文字、`href` 規則不變，找不到服務的畫面也有（單元測試）。
20. 光點流動：全綠時 `data-flowing="true"`；任一節點非綠、不是 `online`、後端失敗、非 sequential、只有 1 個節點時為 `"false"`，條件改變後跟著切換；一輪時間與各元素延遲依節點數計算；連續兩次輪詢後燈號與箭頭仍是同一個 DOM 元素（單元測試）。
21. e2e：reduced motion 與寬度 360px 時燈號與光點的 `animation-name` 為 `none`；正常情境 `data-flowing="true"`，斷相機情境為 `"false"`。截圖以 `animations: "disabled"` 產生。
