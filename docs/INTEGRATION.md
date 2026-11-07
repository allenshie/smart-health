# 函式庫導入指南（`smart-health-record`）

本文說明如何讓一個服務使用 `smart-health-record`，輸出 Health App 能讀取的 `GET /topology` 與 `GET /status`。契約定義見 `contract/README.md` 與 `docs/SPEC.md` 第 4 節。

## 1. 安裝

函式庫只使用 Python 標準函式庫，需要 Python 3.10 以上，沒有任何第三方依賴。

本階段**尚未發布到 PyPI**（發布由使用者操作），目前從原始碼建置 wheel 後安裝：

```bash
python -m pip install build
python -m build packages/health_record          # 產生 packages/health_record/dist/*.whl
python -m pip install packages/health_record/dist/smart_health_record-0.1.0-py3-none-any.whl
```

發布後，套件名稱為 `smart-health-record`，可以直接安裝：

```bash
pip install smart-health-record==0.1.0          # 發布後才可用
```

匯入名稱是 `smart_health_record`，只公開 `HealthMonitor`、`StatusServer`、`mask_text` 與 `__version__`（`NodeRecorder` 由 `HealthMonitor.add_node` 回傳）。

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
| `record_error(reason, message=None)` | 一次錯誤；`error_window_s`（預設 30 秒）內節點為 `degraded` |
| `set_fatal(reason, message=None)`、`clear_fatal()` | 致命故障；節點為 `unavailable`，直到清除 |
| `set_metric(name, value)` | 指標，值只接受數字、字串、布林或 `None` |
| `track()` | context manager：進入記 `record_start`，正常結束記 `record_success`，例外記 `record_error("exception", ...)` 並原樣往外拋。被取消（`asyncio.CancelledError`）或 `KeyboardInterrupt` 等非 `Exception` 的 `BaseException` 中斷時，只清除進行中狀態，不記 success 也不記 error，例外同樣原樣往外拋 |

`reason` 必須符合 `^[a-z][a-z0-9_]*$`，格式錯誤時會改用 `invalid_reason` 並記一次警告。這些方法不會讓例外進入業務執行緒。

### 啟動階段的設定錯誤

id 重複或格式錯誤、lane 或 upstream 指向不存在的項目、upstream 或 `parent` 形成循環、`start()` 之後再新增 lane 或節點、數值參數為負，都會立即拋 `ValueError`。請在服務啟動時就讓它失敗，不要吞掉。

## 3. 使用上的規則

### 3.1 callable 不能阻塞

`dependencies` 與 `enabled` 可以是 callable，它們在**評估執行緒**中呼叫：

- 專案必須提供立即回傳的 callable，例如讀取另一個執行緒維護的旗標。不要在裡面做網路請求、磁碟 I/O 或等待鎖。
- 阻塞時評估執行緒停住，`/status` 的 `evaluation_age_s` 會持續增加；Health App 在超過 `evaluation_stale_after_s`（預設 10 秒）後把該目標顯示為 `stale`，所有節點變灰色。
- callable 拋例外時，dependency 視為 `None`（無法判斷，視同通過），`enabled` 視為 `True`；同一個 callable 連續失敗只記一次警告。

### 3.2 port 由專案指定

`StatusServer` 的 `port` 為必填，沒有預設值，因為同一台主機可能有多個實體。傳入 `0` 時由系統分配，可從 `server.port` 讀取實際值。

預設只綁定 `127.0.0.1`。要讓其他主機或容器連到，必須明確指定 `host`，例如 `StatusServer(monitor, port=18090, host="0.0.0.0")`。這兩個接口**沒有驗證**，請只開放在受信任的內網。

綁定失敗時 `start()` 拋 `OSError`，由專案決定如何處理。

### 3.3 沒有 `stale_after_s` 的閒置節點

`stale_after_s`、`stuck_after_s` 為 `None`（預設）時會跳過對應檢查，讓閒置也正常的節點（例如 API server）不會誤報。但要留意啟動初期的行為（SPEC 第 3 節規則 3、8、11）：

1. 從未成功、且還在 `startup_grace_s`（預設 30 秒，從 `HealthMonitor.start()` 起算）內：`waiting`，reason 為 `starting`，畫面上是「啟動中」。
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

### 4.7 關鍵字比對使用 Python 的不分大小寫比對

關鍵字以 Python `re` 的 `IGNORECASE` 與 `str.lower()` 比對，土耳其文帶點的 `İ` 等特殊大小寫字元可能比對不到。例如 `Authorization` 的 scheme 辨識使用 `str.lower()`，而 `İ` 的小寫是兩個字元，所以辨識失敗，只遮蔽第一段，憑證不遮蔽：

```python
>>> mask_text("AUTHORİZATİON: Bearer abc")
'AUTHORİZATİON: *** abc'

```
