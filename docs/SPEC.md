# smart_health 規格書

- **狀態：** 定稿
- **版本：** 1.3（2026-11-07）
- **實作計畫：** [PLAN.md](PLAN.md)

**1.3 變更摘要：** 依最終審查加入後端的回應大小上限 `max_response_bytes`（第 6、6.1 節）：被監控服務的回應超過上限時停止讀取，判為 `invalid_response`，避免單一服務的異常回應耗盡後端記憶體。

**1.2 變更摘要：** 依驗收關卡 1 回饋補強第 4.4 節的遮蔽：`Authorization` 標頭保留 scheme、遮蔽憑證；關鍵字中的 `-` 和 `_` 視為相同。CI 加入 Python lint（ruff）；導入指南要列出遮蔽的已知限制。

**1.1 變更摘要：** 定義第一輪評估前與 `start()` 前的回應；明確 `id` 格式的適用範圍；定義非 `online` 時的節點內容；定義 `starting` 情境的模擬方式；補上 `config/targets.dev.yaml` 例外與 `limit` 的邊界行為。

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

### 不在這次範圍內

- 修改 Edge、App、`edge_core`、`integration_core`、`smart_workflow`、`monitoring-service`。
- 連接真實的 Edge 或 App。本階段一律使用模擬資料，全部測試通過後才另外導入。
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

由上往下，符合第一條就回傳。`stale_after_s` 等欄位定義見第 5 節。

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
- `startup_grace_s` 從 `HealthMonitor.start()` 開始計算，`/status` 的 `started_at` 也是這個時間。
- 規則 9 的 `message` 固定為 `已 N 秒沒有成功紀錄`，N 取整數秒；規則 3、6、7、8 也使用函式庫內建的固定文字。
- dependency 的 `message` 要指出是哪個依賴，例如 `依賴 mqtt 無法使用`。
- 上游的判斷使用同一輪評估的結果，節點依拓樸順序評估。
- 所有時間差使用 monotonic clock，不受系統時間調整影響。對外的時間字串使用含時區的 ISO 8601。

已知限制（本版不處理）：節點在 sequential lane 中拋例外時，同一輪後面的節點不會執行，可能因 stale 顯示 `unavailable`。

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
    {"id": "publish", "label": "Publish", "upstream": ["infer"], "dependencies": ["mqtt"]}
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

**第一輪評估完成前：** 回 HTTP 200，內容符合 schema，範例見 `contract/fixtures/status_before_first_evaluation.json`：

- `evaluated_at` 為 `null`，`nodes` 為 `{}`，`recent_transitions` 為 `[]`。
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

- PyPI 名稱 `smart-health-record`，匯入名稱 `smart_health_record`，初版 `0.1.0`。
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
                 wall_clock: Callable[[], datetime] = <含本地時區的現在時間>) -> None: ...

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


class NodeRecorder:
    def record_start(self) -> None: ...
    def record_success(self) -> None: ...
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
- `record_success`、`record_error` 都會清除進行中狀態。
- `track()` 進入時 `record_start`；正常結束時 `record_success`；發生例外時 `record_error("exception", <例外訊息>)`，然後**原樣往外拋**。

**評估執行緒**

- 每個 `HealthMonitor` 一條 daemon 執行緒。
- 執行緒啟動後立刻跑第一輪評估，不等第一個 tick。
- `dependencies`、`enabled` 的 callable 在評估執行緒呼叫。專案必須提供不阻塞的 callable，這點要寫進文件。
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

`record_success` 會在主迴圈高頻呼叫，只能寫時間戳：

- 不做 I/O，不產生大量物件。
- 單次平均低於 20 微秒。以 `benchmarks/bench_recorder.py` 量測，不放進 CI 判定。

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

```text
服務：[ Mock Edge A ▼ ]                最後更新 10:32:15（每 5 秒）

MAIN     [G] ingest --> [G] infer --> [G] stream --> [G] publish
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
  指標：fps = 0.0
```

要求：

1. **由 `/topology` 動態產生，不寫死任何節點名稱**。要支援任意 lane 數量、每條任意節點數、巢狀 lane，並用不同架構的模擬服務驗證。
2. 燈號顏色不能是唯一線索，還要有狀態文字或圖示，讓色弱使用者也能分辨。`state` 為 `null` 時顯示「未知」。
3. 不是 `online` 時，顯示橫幅和最後成功時間，例如「無法連線到此服務，最後更新 10:32:15」，所有燈號轉灰。
4. 更新後保留目前選取的節點和詳細面板；節點不存在時才關閉。
5. 前後端連線失敗時也要顯示錯誤並繼續重試，不能白畫面。
6. 所有來自被監控服務的文字都以純文字呈現，不使用 `dangerouslySetInnerHTML`。
7. 寬度 360px 時頁面不能水平捲動，架構圖可在自己的區域內捲動。

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
| `stream-output` | `stream-bg` | `stream` | `ffmpeg` | |
| `publish` | `main` | `infer` | `mqtt` | |

`main` 是 sequential lane，所有節點都設定 `stale_after_s`。`ffmpeg` 依賴只有在有畫面時才回傳 true 或 false，否則回傳 `None`，避免相機斷線被誤判成推流問題。

`stale_after_s`、`startup_grace_s` 等門檻可用命令列參數調短，讓測試不用等太久。

### 8.2 必須通過的情境

`G` = `ok`，`Y` = `degraded`，`R` = `unavailable`，`灰` = `waiting`（`disabled` 另外標註）。

| 情境 | `ingest-worker` | `ingest` | `infer` | `stream` | `stream-output` | `publish` |
|---|---|---|---|---|---|---|
| `normal` | G | G | G | G | G | G |
| `starting` | 灰 | 灰 | 灰 | 灰 | 灰 | 灰 |
| `camera_down` | R | 灰 | 灰 | 灰 | 灰 | 灰 |
| `mqtt_down` | G | G | G | G | G | R |
| `mediamtx_down` | G | G | G | G | R | G |
| `infer_stuck` | G | 灰 | R | 灰 | 灰 | 灰 |
| `infer_exception` | G | G | R | 灰 | 灰 | 灰 |
| `camera_and_mqtt_down` | R | 灰 | 灰 | 灰 | 灰 | R |
| `read_errors` | Y | G | G | G | G | G |
| `publish_errors` | G | G | G | G | G | Y |
| `worker_fatal` | R | 灰 | 灰 | 灰 | 灰 | 灰 |
| `stream_disabled` | G | G | G | `disabled` | `disabled` | G |

- `starting`：規則 3 要求「從未成功」，所以切到這個情境時，mock 會重建 `HealthMonitor` 和 `StatusServer` 來模擬服務重啟，`started_at` 也會改變，函式庫不提供重置 API。此情境不記錄成功，`startup_grace_s` 要大於觀察所需的時間。重建期間 `/status` 會短暫連不上，後端可能短暫顯示 `offline`，這是預期行為。
- `infer_exception`：`infer` 持續以 `track()` 拋例外。依規則 9 為 `R`，超過 stale 門檻前是 `Y`。
- `camera_and_mqtt_down`：依賴檢查排在上游檢查之前，所以 MQTT 問題仍看得到。
- `stream_disabled`：`stream`、`stream-output` 的 `enabled` 為 false，下游 `publish` 依賴 `infer`，不受影響。

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
├── SESSION.md                     # 本專案的進度紀錄
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
├── docs/
└── .github/workflows/
```

**依賴邊界：** `apps/` 可以依賴 `contract/`；函式庫不能依賴 `apps/`；`mock_service` 只依賴函式庫。每個檔案只負責一件事，避免單檔過大。

## 10. 發布與部署

- 映像檔支援 `linux/amd64`、`linux/arm64`，因為部署主機尚未決定，可能是 Orin。本機環境目前無法建置 arm64，實作階段只驗證 amd64；arm64 標明「未驗證，部署到 Orin 前必須補驗」，這項要求仍然有效。
- 提供 `docker-compose.host.yml`：已知部分 Orin 的 kernel 沒有 iptables `raw` 表，Docker bridge 網路無法建立。
- 函式庫 tag 用 `record-vX.Y.Z`，App tag 用 `app-vX.Y.Z`，兩者獨立。
- CI 依路徑分開：
  - `packages/**`、`contract/**`：函式庫測試（Python 3.10、3.11），build，`twine check`。
  - Python lint：用固定版本的 ruff（0.8.4）檢查 `packages`、`contract`、`examples`、`apps`，兩個 workflow 都執行。
  - `apps/**`、`contract/**`、`deploy/**`、`examples/**`、`e2e/**`：後端測試、前端 lint 和測試和建置、映像檔建置、e2e。
- CI 不自動發布。**PyPI 發布和建立遠端 repo 都由使用者操作。**

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
