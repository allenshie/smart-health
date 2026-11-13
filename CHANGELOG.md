# 變更紀錄

依元件分開列出各版本對使用者與整合者有意義的改變，新版在上。函式庫與 Health App 的版本各自獨立。括號內是 [docs/SPEC.md](docs/SPEC.md) 的章節。目前沒有 git tag，日期是該版本內容定案的日期。

## 函式庫 `smart-health-record`

### 0.1.1（2026-11-11）

只新增 API，和 0.1.0 相容。

**新增**

- `HealthMonitor.recorder(node_id)`：依節點 id 取得 `add_node()` 回傳的同一個 `NodeRecorder`（§5.1、§5.2）。整合框架只知道節點 id 時，不必自行保存回傳值，也不必依賴私有屬性。
  - 節點不存在時拋 `KeyError`。
  - 傳入的不是字串時（包括無法雜湊的值）同樣拋 `KeyError`，不是 `TypeError`。

**變更**

- 採用 MIT 授權：套件附上 `LICENSE`，metadata 以 PEP 639 的寫法標示 `license` 與 `license-files`，並加上 `authors` 與 classifiers（§5）。
- sdist 不再包含測試與 benchmark，只放建置需要的檔案（§5）。

### 0.1.0（2026-11-10）

第一個發布到 PyPI 的版本。只使用 Python 標準函式庫，支援 Python 3.10 以上。

- **記錄事實**（§5.1、§5.2）：
  - `NodeRecorder` 提供 `record_start()`、`record_success()`、`record_error()`、`set_fatal()`、`clear_fatal()`、`set_metric()`、`track()`。
  - 這些方法不會讓例外跑進業務執行緒。
- **跳過**：`record_skip()` 用於沒有新資料等情況。它只清除進行中的狀態、不算成功，所以節點不會被誤判成卡住（§5.2）。
- **評估狀態**（§2.2、§3）：
  - 獨立的評估執行緒推導每個節點的狀態（`ok`、`degraded`、`unavailable`、`waiting`、`disabled`）與顏色。
  - 判斷依據包括：啟動寬限、太久沒有成功（`stale_after_s`）、進行中太久（`stuck_after_s`）、錯誤時間窗、依賴檢查、上游、sequential lane 的阻塞、致命故障、停用。
- **等待就緒**（§3.1）：`wait_for_ready=True` 時：
  - 呼叫 `mark_ready()` 之前只判定致命故障；
  - 時間相關的判斷從就緒時刻起算。
  - `wait_for_ready=False`（預設）時不受影響。
- **接口**（§4）：`StatusServer` 提供 `GET /topology` 與 `GET /status`（通用契約 `schema_version: 1`）。
  - `/status` 包含最近的狀態變化，以及非必要欄位 `ready_at`。
  - 第一輪評估前與 `start()` 之前的回應都有固定的內容。
- **遮蔽敏感資訊**（§4.4）：
  - 記錄時遮蔽 `message` 中的敏感內容，例如 `Authorization` 標頭保留 scheme、只遮蔽憑證；關鍵字中的 `-` 和 `_` 視為相同。
  - `mask_text()` 也可以單獨使用。已知限制見 [docs/INTEGRATION.md](docs/INTEGRATION.md)。
- **通用契約**（`contract/`）：兩個接口的 JSON Schema 與 fixtures。不使用函式庫的服務只要符合契約，也能被監控。

## Health App

後端的版本一直是 0.1.0，以下依前端的版本列出。

### 前端 0.3.0（2026-11-13）

**新增**

- **映像檔發布到 Docker Hub**（§10、[docs/DEPLOY.md](docs/DEPLOY.md)）：CI 的測試全部通過後才推送。每個 tag 都同時含 `linux/amd64` 與 `linux/arm64`；`linux/arm64` 由 CI 建置並以 QEMU smoke test，實機（例如 Orin）尚未驗證。
  - push 到 `main`：`sha-<commit 前 7 碼>`。
  - push `app-vX.Y.Z` tag：`X.Y.Z`，必須等於前端 `package.json` 的版本，和同一個 commit 的 `sha-` tag 指向同一個 digest。
  - 不推送 `latest`；已存在的 tag 不覆寫。

**變更**（只改外觀，判斷規則與狀態文字不變；§7.1「視覺」）

- **發光燈號：** 節點燈號、總覽卡片、服務畫面頂端的總體燈號、統計列都改成發光的號誌風格：綠、黃、紅亮燈有高光與光暈，灰色是沒亮的燈。
- **總覽卡片：** 依總體狀態使用淡色底與邊框，文字對比維持 4.5:1 以上。
- **回到總覽：** 改成 44px 的圓形圖示連結，放在服務名稱左側，`aria-label` 與 `title` 是「回到總覽」。
- **主迴圈的光點流動：** `sequential` 且有 2 個以上節點的 lane 全綠時，光點沿箭頭流動、經過的節點短暫變亮。
  - 速度固定，不代表實際的處理量。
  - 系統設定減少動態效果，或視窗寬度 640px 以下時不流動。
  - lane 元素有 `data-flowing` 屬性。

**部署注意**

- `deploy/Dockerfile` 的前端階段改在建置主機的原生平台執行。沒有 buildx 時的 `docker build`（legacy builder）會用 `linux/amd64`，所以 arm64 主機請拉 Docker Hub 的映像檔，或用 buildx 建置。
- 前端使用 inline `<style>` 與 `style` 屬性。反向代理若加上 CSP，`style-src` 需要允許 inline（[docs/DEPLOY.md](docs/DEPLOY.md)）。

### 前端 0.2.0（2026-11-12）

**新增**

- **兩層畫面：** 「服務總覽」與「服務畫面」以網址的 hash 區分（`#/`、`#/?page=N`、`#/targets/<id>`），上一頁、下一頁、重新整理和書籤都能用（§7.1）。
- **服務總覽：**
  - 統計列依全部目標的總體狀態計數；
  - 每個目標一張卡片，卡片本身是連結；
  - 每頁 24 個，超過時分頁；
  - 只輪詢 `/api/targets`。
- **服務畫面：**
  - 「回到總覽」回到最後看過的總覽頁；
  - 找不到服務時顯示訊息並繼續輪詢，目標加回設定後自動恢復；
  - 只輪詢 `/api/targets/{id}`。
- **每秒次數：** 節點的 `rate_per_s` 指標顯示在燈號下方，一律小數 2 位，單位 `/s`。服務不是 `online` 或後端請求失敗時不顯示。

**變更**

- 指標值統一格式：整數照原樣顯示，非整數顯示小數 2 位（不顯示 `-0.00`），`null` 顯示「—」（§7.1「數值格式」）。
- 移除目標下拉選單，以及「預設顯示第一個目標」和「目標消失時改選第一個」的行為。

### 前端 0.1.0、後端 0.1.0（2026-11-11）

第一個版本。

**後端**（§6）

- **設定：**
  - 監控目標寫在 `targets.yaml`，路徑由 `SMART_HEALTH_CONFIG` 指定；
  - 包含拉取間隔、逾時、評估過舊的門檻、狀態變化的保留筆數與回應大小上限；
  - 設定無效時啟動失敗，並指出是哪個欄位。
- **拉取：**
  - 每個目標各自拉取，慢或掛掉的目標不影響其他目標；
  - `topology_version` 或 `started_at` 改變時重新取架構；
  - 不跟隨重新導向（§6.1）。
- **連線狀態：** `unknown`、`online`、`offline`、`stale`、`incompatible`、`invalid_response`。不是 `online` 時，所有節點一律回傳灰色，不保留舊狀態（§6.1）。
- **回應大小上限：** 回應本文超過 `max_response_bytes`（預設 1 MiB）時停止讀取，判為 `invalid_response`（§6.1）。
- **API：** `/api/config`、`/api/targets`、`/api/targets/{id}`、`/api/targets/{id}/transitions`、`/healthz`。回應不包含 `base_url` 和原始錯誤字串（§6.2）。

**前端**（§7）

- 由 `/topology` 動態產生架構圖，支援任意數量的 lane 與巢狀 lane，不寫死節點名稱。
- 燈號加上狀態文字。點擊節點顯示狀態、原因、說明、開始時間與指標。
- 服務不是 `online` 時，顯示橫幅與最後成功的時間；後端連線失敗時顯示錯誤並自動重試。
- 寬度 360px 時頁面不水平捲動。

**部署與開發**（§8、§10、[docs/DEPLOY.md](docs/DEPLOY.md)）

- **映像檔：** `linux/amd64` 已驗證，`linux/arm64` 尚未驗證。
- **compose 檔：** `docker-compose.yml`，以及給無法使用 bridge 網路的主機用的 `docker-compose.host.yml`。
- **開發用的 compose（`docker-compose.dev.yml`）：** Health App 加上模擬服務：
  - 使用函式庫的 `mock_service`，有 `edge` 與 `api` 兩種架構；情境以角色命名，例如 `messaging_down`、`stream_sink_down`，另有 `loading`、`loading_fatal`。
  - `raw_mock`：7 種不符合契約的模式。
