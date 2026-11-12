# 函式庫導入指南（`smart-health-record`）

本文說明如何讓一個服務使用 `smart-health-record`，輸出 Health App 能讀取的 `GET /topology` 與 `GET /status`。契約定義見 `contract/README.md` 與 `docs/SPEC.md` 第 4 節。

## 1. 安裝

函式庫只使用 Python 標準函式庫，需要 Python 3.10 以上，沒有任何第三方依賴。

套件已發布到 PyPI，名稱為 `smart-health-record`，請固定版本安裝：

```bash
pip install smart-health-record==0.1.1
```

需要使用 repo 中尚未發布的版本時，可以從原始碼建置 wheel 後安裝：

```bash
python -m pip install build
python -m build packages/health_record          # 產生 packages/health_record/dist/*.whl
python -m pip install packages/health_record/dist/smart_health_record-0.1.1-py3-none-any.whl
```

匯入名稱是 `smart_health_record`，只公開 `HealthMonitor`、`NodeRecorder`、`StatusServer`、`mask_text` 與 `__version__`。`NodeRecorder` 由 `HealthMonitor.add_node` 回傳，不需自行建立。

## 2. 最小範例

以下以一個通用的 `order-service` 示範：兩條 lane、兩個節點，其中 `receiver` 有一個依賴與一個指標。

```python
import threading
import time

from smart_health_record import HealthMonitor, StatusServer

PORT = 18090  # port 由專案指定，函式庫沒有預設值

monitor = HealthMonitor("order-service", "order-1")
monitor.add_lane("intake", "接單")
monitor.add_lane("fulfil", "出貨")

queue_ok = {"value": True}  # 範例用的假資料

receiver = monitor.add_node(
    "receiver", "訂單接收", "intake",
    dependencies={"queue": lambda: queue_ok["value"]},  # 必須立即回傳
    stale_after_s=10,    # 超過 10 秒沒有成功紀錄就是 unavailable
    stuck_after_s=30,    # 單次工作超過 30 秒就是 stuck
)
packer = monitor.add_node(
    "packer", "揀貨打包", "fulfil",
    upstream=["receiver"],
    stale_after_s=30,
)

monitor.start()                                  # 驗證架構並啟動評估執行緒
server = StatusServer(monitor, port=PORT)        # 預設只綁定 127.0.0.1
server.start()


def work() -> None:
    while True:
        with receiver.track():       # 進入記 start，離開記 success，例外記 error 後原樣往外拋
            time.sleep(0.2)
        packer.record_success()
        receiver.set_metric("queue_depth", 3)
        time.sleep(1)


threading.Thread(target=work, daemon=True).start()
```

啟動後：

```bash
curl http://127.0.0.1:18090/topology
curl http://127.0.0.1:18090/status
```

把這個服務的位址（例如 `http://order-service:18090`）加進 Health App 的 `config/targets.yaml`，見 `docs/DEPLOY.md`。

### 節點記錄方法

| 方法 | 用途 |
|---|---|
| `record_start()`、`record_success()` | 工作開始與成功；`record_success` 可在主迴圈高頻呼叫，只寫時間戳 |
| `record_skip()` | 這次執行跳過（例如沒有新畫面）：只清除進行中狀態，不算成功，見 3.6 節；可高頻呼叫 |
| `record_error(reason, message=None)` | 一次錯誤；`error_window_s`（預設 30 秒）內節點為 `degraded` |
| `set_fatal(reason, message=None)`、`clear_fatal()` | 致命故障；節點為 `unavailable`，直到清除 |
| `set_metric(name, value)` | 指標，值只接受數字、字串、布林或 `None` |
| `track()` | context manager：進入記 `record_start`，正常結束記 `record_success`，例外記 `record_error("exception", ...)` 並原樣往外拋。被取消（`asyncio.CancelledError`）或 `KeyboardInterrupt` 等非 `Exception` 的 `BaseException` 中斷時，只清除進行中狀態，不記 success 也不記 error，例外同樣原樣往外拋 |

`reason` 必須符合 `^[a-z][a-z0-9_]*$`，格式錯誤時會改用 `invalid_reason` 並記一次警告。這些方法不會讓例外進入業務執行緒。

### Health App 如何顯示指標，以及每秒次數（`rate_per_s`）

- 節點詳細面板列出節點的所有指標，**鍵名原樣顯示**（例如 `duration_ms`），不翻譯。
- 數值只在畫面上格式化：整數原樣（`7`）；非整數顯示小數 2 位並四捨五入（`3.998789` → `4.00`，`-0.001` → `0.00`，不顯示 `-0.00`）；字串、布林原樣；`None` 顯示「—」。`/status` 與後端 API 保留完整精度。
- **`rate_per_s` 是每秒次數的標準指標名稱**：smart-workflow 會為每個節點產生這個指標。節點有名為 `rate_per_s` 的**數字**指標時，Health App 把它顯示在燈號的狀態文字下方，例如 `4.00/s`。其他整合方式只要提供同名指標，例如 `node.set_metric("rate_per_s", 4.0)`，也會顯示；Health App 不寫死任何節點名稱。
- 沒有這個指標、值不是數字、服務不是 `online`，或 Health App 前端連不到後端時，燈號下方不顯示每秒次數。
- 單位是 `/s` 而不是 `fps`：節點處理的不一定是畫面。數值怎麼算（例如最近一段時間的成功次數除以秒數）由整合方決定。

### 依節點 id 取得 recorder（`recorder()`）

`monitor.recorder(node_id)` 回傳 `add_node()` 回傳的**同一個** `NodeRecorder`（0.1.1 新增）。整合框架只知道節點 id 時（例如任務只宣告要記錄到哪個節點），用它取得 recorder 即可，不必自行保存 `add_node()` 的回傳值，也不要依賴私有屬性。

- `add_node()` 之後的任何時候都可以呼叫：`start()` 之前、執行中、`stop()` 之後都可以；可以從任何執行緒呼叫，不會等待評估。
- 節點不存在時拋 `KeyError`，訊息以 `repr` 顯示傳入的 id。傳入的不是字串時同樣拋 `KeyError`。
- 建議在服務啟動時就取得 recorder 並保存，讓打錯的 id 在啟動時就失敗；不要在主迴圈每次查詢。

```python
>>> from smart_health_record import HealthMonitor
>>> monitor = HealthMonitor("order-service", "order-1")
>>> monitor.add_lane("main", "主流程")
>>> worker = monitor.add_node("worker", "訂單處理", "main")
>>> monitor.recorder("worker") is worker
True
>>> monitor.recorder("wroker")
Traceback (most recent call last):
    ...
KeyError: "node 'wroker' 不存在"
>>> monitor.recorder(None)
Traceback (most recent call last):
    ...
KeyError: 'node None 不存在'

```

### 啟動階段的設定錯誤

id 重複或格式錯誤、lane 或 upstream 指向不存在的項目、upstream 或 `parent` 形成循環、`start()` 之後再新增 lane 或節點、數值參數為負，都會立即拋 `ValueError`。請在服務啟動時就讓它失敗，不要吞掉。

## 3. 使用上的規則

### 3.1 callable 不能阻塞

`dependencies` 與 `enabled` 可以是 callable，它們在**評估執行緒**中呼叫：

- 專案必須提供立即回傳的 callable，例如讀取另一個執行緒維護的旗標。不要在裡面做網路請求、磁碟 I/O 或等待鎖。
- 阻塞時評估執行緒停住，`/status` 的 `evaluation_age_s` 會持續增加；Health App 在超過 `evaluation_stale_after_s`（預設 10 秒）後把該目標顯示為 `stale`，所有節點變灰色。
- callable 拋例外時，dependency 視為 `None`（無法判斷，視同通過），`enabled` 視為 `True`；同一個 callable 連續失敗只記一次警告。
- 使用 `wait_for_ready=True` 時，就緒之前不呼叫這些 callable，見 3.5 節。

### 3.2 port 由專案指定

`StatusServer` 的 `port` 為必填，沒有預設值，因為同一台主機可能有多個實體。傳入 `0` 時由系統分配，可從 `server.port` 讀取實際值。

預設只綁定 `127.0.0.1`。要讓其他主機或容器連到，必須明確指定 `host`，例如 `StatusServer(monitor, port=18090, host="0.0.0.0")`。這兩個接口**沒有驗證**，請只開放在受信任的內網。

綁定失敗時 `start()` 拋 `OSError`，由專案決定如何處理。

### 3.3 沒有 `stale_after_s` 的閒置節點

`stale_after_s`、`stuck_after_s` 為 `None`（預設）時會跳過對應檢查，讓閒置也正常的節點（例如 API server）不會誤報。但要留意啟動初期的行為（SPEC 第 3 節規則 3、8、11）：

1. 從未成功、且還在 `startup_grace_s`（預設 30 秒，從 `HealthMonitor.start()` 起算；使用 `wait_for_ready=True` 時從就緒時刻起算，見 3.5 節）內：`waiting`，reason 為 `starting`，畫面上是「啟動中」。
2. 超過 `startup_grace_s` 仍從未成功：因為沒有設定 `stale_after_s`，規則 8 不成立，直接變成 `ok`。
3. 下游節點在上游還是 `waiting` 的期間，會顯示 `waiting`，reason 為 `upstream_not_ready`。

下面用假時鐘驗證第 1、2 點（節點 `idle` 從未成功，`startup_grace_s=5`）：

```python
>>> from smart_health_record import HealthMonitor
>>> now = [0.0]
>>> monitor = HealthMonitor("order-service", "order-1", clock=lambda: now[0])
>>> monitor.add_lane("main", "主流程")
>>> _ = monitor.add_node("idle", "閒置節點", "main", startup_grace_s=5)
>>> monitor.start()
>>> monitor.stop()
>>> monitor.evaluate_once()
>>> monitor.status()["nodes"]["idle"]["state"], monitor.status()["nodes"]["idle"]["reason"]
('waiting', 'starting')
>>> now[0] = 6.0
>>> monitor.evaluate_once()
>>> monitor.status()["nodes"]["idle"]["state"], monitor.status()["nodes"]["idle"]["reason"]
('ok', None)

```

如果節點應該持續有成功紀錄，請設定 `stale_after_s`，這樣從未成功的節點在寬限期後會是 `unavailable`（`never_succeeded`），而不是 `ok`。

### 3.5 啟動時間較長的服務

服務啟動時如果要載入模型或暖機，時間可能從數十秒到數分鐘都有。預設行為下，`startup_grace_s` 從 `start()` 起算，載入超過寬限期，節點就會被判成 `never_succeeded`；如果延後 `start()`，載入期間 `/status` 會回 503，Health App 顯示 `offline`，看起來和程式已經死掉一樣。

這類服務請以 `wait_for_ready=True` 建立 `HealthMonitor`，在 `start()` 後就提供 `/status`，載入完成後呼叫 `mark_ready()`：

```python
monitor = HealthMonitor("edge", "CamA-northbound-1", wait_for_ready=True)
# ... add_lane、add_node ...
monitor.start()
StatusServer(monitor, port=18090).start()   # 載入期間 /status 就能回應，節點為灰色「啟動中」
load_models()                               # 專案自己的載入與暖機
monitor.mark_ready()                        # 之後才開始一般的判定
```

就緒之前：

- 只判定 fatal：已設定 fatal 的節點是 `unavailable`，其他節點一律 `waiting`，reason 為 `starting`，message 為 `服務啟動中，尚未就緒`。所以載入失敗時請用 `set_fatal()` 回報。
- 不判定 stuck、stale、`never_succeeded`、上游、lane、錯誤視窗。
- **不呼叫 `enabled` 和 `dependencies` 的 callable**，它們可以引用載入完成後才建立的物件。
- `NodeRecorder` 的方法照常記錄，業務執行緒不需要知道目前是否已就緒。
- `/status` 的 `ready_at` 為 `null`。

就緒之後套用一般規則（SPEC 第 3 節），但時間相關的判斷從就緒時刻起算：

| 判斷 | 起算點 |
|---|---|
| `startup_grace_s` | 就緒時刻 |
| stuck | `max(record_start 的時間, 就緒時刻)` |
| stale | `max(最後一次成功的時間, 就緒時刻)`；`已 N 秒沒有成功紀錄` 的 N 也是 |
| `error_window_s` | 就緒之前的錯誤不計入；剛好在就緒時刻的錯誤要計入 |

- 「是否曾經成功」包含就緒之前的成功紀錄。
- `mark_ready()` 在 `start()` 之前呼叫會拋 `RuntimeError`（`evaluate_once()` 的隱含 start 也算已開始）。可以從任何執行緒呼叫，不會阻塞；重複呼叫不改變就緒時刻。新的狀態在下一輪評估時反映。
- 預設的 `wait_for_ready=False` 行為和之前完全相同：就緒時刻就是 `start()`，`mark_ready()` 不做任何事，`ready_at` 等於 `started_at`。

下面用假時鐘驗證（節點 `infer` 的 `startup_grace_s=5`，從未成功）：

```python
>>> import logging
>>> from smart_health_record import HealthMonitor
>>> quiet = logging.getLogger("integration-doc")  # 範例不輸出狀態變化的 log
>>> quiet.addHandler(logging.NullHandler())
>>> quiet.propagate = False
>>> now = [0.0]
>>> monitor = HealthMonitor("model-service", "model-1", clock=lambda: now[0],
...                         logger=quiet, wait_for_ready=True)
>>> monitor.add_lane("main", "主流程")
>>> infer = monitor.add_node("infer", "推論", "main", stale_after_s=10, startup_grace_s=5)
>>> monitor.start()
>>> monitor.stop()
>>> def show():
...     monitor.evaluate_once()
...     node = monitor.status()["nodes"]["infer"]
...     return node["state"], node["reason"], node["message"]
>>> now[0] = 120.0  # 載入了兩分鐘，遠超過 startup_grace_s，仍然是啟動中
>>> show()
('waiting', 'starting', '服務啟動中，尚未就緒')
>>> monitor.status()["ready_at"] is None
True
>>> infer.set_fatal("model_load_failed", "模型檔不存在")  # 就緒前設定 fatal
>>> show()
('unavailable', 'model_load_failed', '模型檔不存在')
>>> infer.clear_fatal()
>>> monitor.mark_ready()  # 載入完成；寬限期從這裡重新計算
>>> show()
('waiting', 'starting', '啟動中，尚未有成功紀錄')
>>> now[0] = 125.0  # 剛好等於寬限期，還沒超過
>>> show()
('waiting', 'starting', '啟動中，尚未有成功紀錄')
>>> now[0] = 126.0  # 就緒後超過 5 秒仍未成功
>>> show()
('unavailable', 'never_succeeded', '從未有成功紀錄')

```

### 3.6 跳過（`record_skip()`）與「成功但沒有結果」

呼叫 `record_start()` 之後，進行中狀態只有 `record_success()`、`record_error()`、`record_skip()` 會清除。如果某次執行既不是成功也不是錯誤，卻什麼都不呼叫，節點會一直停在進行中，超過 `stuck_after_s` 就被判成 `stuck`。

請依結果選擇：

| 結果 | 呼叫 | 效果 |
|---|---|---|
| 有處理到資料，只是沒有結果，例如畫面中沒有偵測到物件 | `record_success()` | 算成功，stale 重新計時 |
| 沒有可處理的資料，這次跳過，例如沒有新畫面 | `record_skip()` | 只清除進行中狀態；最後一次成功時間、錯誤、fatal、metrics 都不變 |

跳過不算成功，所以持續跳過的節點超過 `stale_after_s` 後仍會是 `unavailable`（前提是上游正常）。這是刻意的：上游斷線、一直沒有新畫面時，下游不應該因為「有在執行」而顯示綠燈。

```python
def run_once(frame):
    detect.record_start()
    if frame is None:              # 沒有新畫面：跳過，不算成功
        detect.record_skip()
        return
    objects = detector(frame)      # 沒有偵測到物件也是成功
    detect.record_success()
```

下面用假時鐘比較兩個節點，每秒執行一次（`stuck_after_s=2`、`stale_after_s=5`）。`detect` 每次都有畫面但沒有物件，`track` 每次都沒有新畫面：

```python
>>> import logging
>>> from smart_health_record import HealthMonitor
>>> quiet = logging.getLogger("integration-doc-skip")  # 範例不輸出狀態變化的 log
>>> quiet.addHandler(logging.NullHandler())
>>> quiet.propagate = False
>>> now = [0.0]
>>> monitor = HealthMonitor("vision", "cam-1", clock=lambda: now[0], logger=quiet)
>>> monitor.add_lane("main", "主流程")
>>> rules = dict(stale_after_s=5, stuck_after_s=2, startup_grace_s=0)
>>> detect = monitor.add_node("detect", "偵測", "main", **rules)
>>> track = monitor.add_node("track", "追蹤", "main", **rules)
>>> detect.record_success()
>>> track.record_success()
>>> def run_until(t):
...     while now[0] < t:
...         now[0] += 1
...         detect.record_start()
...         detect.record_success()  # 有畫面，沒有物件：成功
...         track.record_start()
...         track.record_skip()      # 沒有新畫面：跳過
...     monitor.evaluate_once()
...     nodes = monitor.status()["nodes"]
...     return {n: (nodes[n]["state"], nodes[n]["reason"]) for n in ("detect", "track")}
>>> run_until(3)  # 已超過 stuck_after_s，但跳過不會被判成 stuck
{'detect': ('ok', None), 'track': ('ok', None)}
>>> run_until(6)  # 持續跳過：超過 stale_after_s 後 track 是 unavailable
{'detect': ('ok', None), 'track': ('unavailable', 'stale_success')}

```

### 3.4 `message` 會被遮蔽，且後端不會重新遮蔽

寫入節點的 `message`（`record_error`、`set_fatal`）與字串型指標值，都會經過 `mask_text` 自動遮蔽並截斷到 200 字元。遮蔽在**函式庫端**完成：

- **Health App 後端只驗證、不重新遮蔽 `message`**，並原樣轉給前端。
- 因此，**不使用本函式庫、自行實作 `/topology` 與 `/status` 的服務，必須自己遮蔽帳密**，否則帳密會原樣出現在 Health App 畫面上。
- `/status` 沒有驗證，請把遮蔽當作最後一道防線，而不是把敏感資料交給它處理。不要主動把密碼、token 放進 `message`。

遮蔽規則（SPEC 第 4.4 節）：

```python
>>> from smart_health_record import mask_text
>>> mask_text("rtsp://admin:secret@10.0.0.1/live")
'rtsp://***@10.0.0.1/live'
>>> mask_text("password=secret")
'password=***'
>>> mask_text("token: abc")
'token: ***'
>>> mask_text("Authorization: Bearer abc")
'Authorization: Bearer ***'
>>> mask_text("Authorization: Basic dXNlcjpwYXNz")
'Authorization: Basic ***'
>>> mask_text("x-api-key: abc")
'x-api-key: ***'
>>> mask_text("db_password=abc")
'db_password=***'

```

關鍵字至少涵蓋 `password`、`passwd`、`pwd`、`secret`、`token`、`api_key`、`apikey`、`authorization`，不分大小寫，鍵名含關鍵字就遮蔽；鍵名中的 `-` 與 `_` 視為相同。

## 4. 遮蔽的已知限制

遮蔽採規則比對，不是萬能的。下列情況**不會**（或不完全）遮蔽，寫 `message` 時請避開。每個例子都是實際執行 `mask_text` 的輸出。

### 4.1 未加引號且含空白的值，只遮蔽到第一個空白

```python
>>> mask_text("Password: it's fine")
'Password: *** fine'

```

空白之後的內容不遮蔽。值含空白時請不要放進 `message`；加了引號的值會整段遮蔽（`password="it's fine"` 輸出 `password="***"`）。

### 4.2 沒有 scheme 的 `user:pass@host` 不遮蔽

```python
>>> mask_text("connect admin:pass@10.0.0.1 failed")
'connect admin:pass@10.0.0.1 failed'

```

只有 `scheme://user:pass@host` 形式的 URL 帳密會被遮蔽。

### 4.3 全形冒號不視為分隔符

```python
>>> mask_text("token：abc")
'token：abc'
>>> mask_text("token: abc")
'token: ***'

```

分隔符只認半形的 `:` 與 `=`。**中文訊息很容易出現全形冒號**（例如「密碼：xxx」「token：xxx」），這種寫法完全不會遮蔽，寫中文 `message` 時務必注意。

### 4.4 `instance`、`label`、metric 名稱不遮蔽

遮蔽只作用在 `message` 與字串型指標**值**。`HealthMonitor` 的 `service`、`instance`，lane 與節點的 `label`，以及 metric 的名稱，原樣輸出。不要把帳密放在這些欄位：

這些欄位不會經過 `mask_text`，所以不論內容是什麼都不會被遮蔽。

### 4.5 `Authorization` 只遮蔽 scheme 後的第一段

```python
>>> mask_text('Authorization: Digest username="u", response="r"')
'Authorization: Digest ***, response="r"'

```

Digest 等多參數格式，第一個參數之後的其他參數（例如 `response`）不遮蔽。

### 4.6 `Authorization` 的 scheme 與憑證之間只認同一行的空白

scheme 與憑證之間只認空格、tab、NBSP、全形空白。憑證放在下一行，或用其他 Unicode 空白（例如 EM SPACE `U+2003`）分隔時，只會遮蔽第一段（scheme），憑證**不遮蔽**：

```python
>>> mask_text("Authorization: Bearer\nabc123")
'Authorization: ***\nabc123'
>>> mask_text("Authorization: Bearer\u2003abc123")
'Authorization: ***\u2003abc123'

```

### 4.7 已修正：關鍵字比對一律使用 `re.IGNORECASE`

這條原本是限制，現已修正，保留在此供對照。Authorization 的辨識原本使用 `str.lower()`，而土耳其文帶點的 `İ` 的小寫是兩個字元，scheme 辨識失敗，憑證不會被遮蔽（舊輸出為 `AUTHORİZATİON: *** abc`）。現在 `authorization` 與 `_SENSITIVE` 一樣，以 `re.IGNORECASE` 編譯的 regex 比對，`AUTHORİZATİON` 能保留 scheme、正確遮蔽憑證：

```python
>>> mask_text("AUTHORİZATİON: Bearer abc")
'AUTHORİZATİON: Bearer ***'

```
