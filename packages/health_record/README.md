# smart-health-record

在服務內記錄各節點的事實（開始、成功、錯誤、致命故障、指標），由獨立的評估執行緒推導健康狀態，並以 `GET /topology`、`GET /status` 提供給 Health App 讀取。

- 執行時只使用 Python 標準函式庫，需要 Python 3.10 以上。
- 公開 API：`HealthMonitor`、`NodeRecorder`、`StatusServer`、`mask_text`、`__version__`。
- `NodeRecorder` 由 `add_node()` 回傳；之後也可以用 `monitor.recorder(node_id)` 依節點 id 取得同一個物件，不存在時拋 `KeyError`。
- `message` 與字串型指標值會自動遮蔽密碼、token、URL 帳密等敏感資訊（有已知限制，見導入指南）。

## 安裝

```bash
pip install smart-health-record==0.1.1
```

## 最小範例

```python
from smart_health_record import HealthMonitor, StatusServer

monitor = HealthMonitor("order-service", "order-1")
monitor.add_lane("main", "主流程")
worker = monitor.add_node("worker", "訂單處理", "main", stale_after_s=10)

monitor.start()
StatusServer(monitor, port=18090).start()   # port 必填；預設只綁定 127.0.0.1

with worker.track():                        # 進入記 start，正常離開記 success，例外記 error 並往外拋
    ...                                     # 處理一筆工作
```

之後 `curl http://127.0.0.1:18090/status` 即可取得狀態。

## 文件

- 導入指南（callable 不能阻塞、port 由專案指定、遮蔽的已知限制等）：`docs/INTEGRATION.md`
- 契約：`contract/README.md`
- 規格：`docs/SPEC.md` 第 5 節
