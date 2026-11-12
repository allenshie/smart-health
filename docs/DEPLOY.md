# 部署說明（Health App）

Health App 由後端（FastAPI）與前端（React，建置後由後端提供）組成，以單一映像檔部署。本文說明設定檔、compose、網路與安全限制。開發環境與 e2e 見根目錄 `README.md`。

## 1. 設定檔 `config/targets.yaml`

後端從 `SMART_HEALTH_CONFIG` 指定的路徑讀取設定（容器內預設 `/config/targets.yaml`）。真實設定檔 `config/targets.yaml` **不進版控**，只追蹤範本 `config/targets.example.yaml`：

```bash
cp config/targets.example.yaml config/targets.yaml   # 填入實際目標
```

範本內容：

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

| 欄位 | 預設 | 說明 |
|---|---|---|
| `poll_interval_s` | `5` | 拉取 `/status` 的間隔（秒），前端也用同一個間隔更新；必須是正數 |
| `request_timeout_s` | `2` | 單次請求逾時（秒），涵蓋連線到讀完本文的整個請求；必須是正數 |
| `evaluation_stale_after_s` | `10` | 被監控服務的 `evaluation_age_s` 超過此值，該目標顯示 `stale`；必須是正數 |
| `history_limit` | `200` | 每個目標在記憶體中保留的狀態變化筆數上限，必須是正整數；後端重啟就會消失 |
| `max_response_bytes` | `1048576` | 單次回應本文的上限（位元組），必須是正整數。`Content-Length` 已超過上限時不讀本文；讀取中超過上限就停止讀取。兩者都判為 `invalid_response` |
| `targets[].id` | 必填 | 符合 `^[a-z][a-z0-9_-]*$`，不可重複；也是服務畫面網址 `#/targets/<id>` 的一部分 |
| `targets[].name` | 必填 | 畫面顯示名稱，非空字串；總覽卡片最多顯示兩行，超過的部分以省略號表示 |
| `targets[].base_url` | 必填 | 被監控服務的位址（`http` 或 `https`，含主機，不可含 query、fragment 或帳密）；後端會在後面加上 `/topology` 與 `/status` |

重點：

- **`base_url` 只存在後端**，不會出現在任何 API 回應，前端也看不到。錯誤也只以連線代碼（`offline`、`stale` 等）呈現，不回傳原始錯誤字串。
- **`targets` 的順序就是「服務總覽」卡片的順序**（每頁 24 個）。前端有兩個畫面：總覽 `http://<host>:<port>/#/`（第 N 頁為 `#/?page=N`）與服務畫面 `#/targets/<id>`，都可以加入書籤。修改目標的 `id` 會讓舊的服務畫面書籤顯示「找不到服務」。
- **設定錯誤時啟動會失敗**，並指出欄位路徑：格式錯誤、未知欄位、`id` 重複或格式錯誤、數值不是正數、`base_url` 不是 http 或 https，都會讓後端啟動失敗（`restart: unless-stopped` 會讓容器反覆重啟）。`docker compose -f deploy/docker-compose.yml logs health-app` 可看到 `ConfigError` 與欄位路徑。
- 每個目標獨立拉取，慢或掛掉的目標不影響其他目標；後端不跟隨重新導向。
- **`base_url` 不可含帳密**（例如 `http://user:pass@host`），否則啟動失敗。`/status` 與 `/topology` 不需要驗證，含帳密的網址也可能被 HTTP client 的 log 原樣印出。
- **後端不使用環境變數的 proxy 設定**：`HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY` 與 `.netrc` 都不套用，一律直連 `base_url`。Docker daemon 設定了 proxy 而注入這些變數時，也不會把內網主機名的拉取送往 proxy。同樣的原因，`SSL_CERT_FILE`、`SSL_CERT_DIR` 也不會生效：連到使用私有 CA 的 https 目標時，無法用這兩個環境變數指定 CA。
- **log：** 未另外設定 logging 時（例如直接以 `uvicorn` 啟動），後端輸出 INFO 以上的 log 到 stderr，格式為 `時間 level logger 名稱: 訊息`；`httpx`、`httpcore` 只輸出 WARNING 以上。以 `--log-config` 等方式已設定 root logger 時，沿用既有設定。
- 被監控服務要提供 `GET /topology` 與 `GET /status`，格式見 `contract/README.md`；使用函式庫的服務見 `docs/INTEGRATION.md`。

## 2. compose

compose 檔都在 `deploy/`，建置 context 是 repo 根目錄。

| 檔案 | 用途 |
|---|---|
| `deploy/docker-compose.yml` | 正式部署，bridge 網路 |
| `deploy/docker-compose.host.yml` | 正式部署，host 網路 |
| `deploy/docker-compose.dev.yml` | 開發與 e2e：Health App 加所有模擬服務，見根目錄 `README.md` |

### 2.1 bridge 網路（預設）

```bash
cp config/targets.example.yaml config/targets.yaml
docker compose -f deploy/docker-compose.yml up -d --build
SMART_HEALTH_PORT=9000 docker compose -f deploy/docker-compose.yml up -d --build   # 改對外 port
```

- 對外 port 由 `SMART_HEALTH_PORT` 指定，預設 `8000`；容器內固定監聽 8000。
- `config/targets.yaml` 以唯讀 bind mount 掛入。檔案不存在時 compose 會直接失敗（`bind source path does not exist`），不會自動建立同名目錄。

### 2.2 host 網路

```bash
UVICORN_PORT=8000 docker compose -f deploy/docker-compose.host.yml up -d --build
```

**原因（SPEC 第 10 節）：** 已知部分嵌入式主機的 kernel 沒有 iptables `raw` 表，Docker bridge 網路無法建立，這種主機要改用 host 網路。

host 網路沒有 port 對應，容器直接使用主機的 port，所以 port 改由 `UVICORN_PORT` 指定（預設 `8000`），注意不要和主機上其他服務衝突。

### 2.3 環境變數

| 環境變數 | 預設 | 說明 |
|---|---|---|
| `SMART_HEALTH_CONFIG` | `/config/targets.yaml` | 目標設定檔路徑 |
| `SMART_HEALTH_STATIC_DIR` | `/app/static` | 前端靜態檔目錄；設定了但不存在時啟動失敗 |
| `UVICORN_HOST`、`UVICORN_PORT` | `0.0.0.0`、`8000` | 容器內的監聽位址與 port |
| `SMART_HEALTH_PORT` | `8000` | 只用於 `docker-compose.yml` 的主機端對外 port |

## 3. 網路與安全限制

**Health App 沒有登入驗證機制。** 任何連得到它的人都能看到所有目標的名稱與狀態。因此：

- 只能放在**受信任的內網**，或放在有驗證的**反向代理**之後。畫面以網址的 hash（`#/…`）區分，hash 不會送到伺服器，反向代理不需要額外的路徑改寫規則。前端使用 inline `<style>`（光點流動的 keyframes）與 `style` 屬性；若代理加上 CSP，`style-src` 需要允許 inline（`'unsafe-inline'`）。
- **不要直接暴露到網際網路。**
- 被監控服務的 `/topology`、`/status` 同樣沒有驗證，只應開放給 Health App 所在的網路。
- 後端只驗證並轉傳被監控服務的內容，**不會重新遮蔽 `message`**；遮蔽由各服務端負責，見 `docs/INTEGRATION.md`。
- `config/targets.yaml`、`.env` 已被 `.dockerignore` 排除，不會進入映像檔。

## 4. 映像檔

`deploy/Dockerfile` 為多階段建置（`frontend` 建置前端、`app` 為正式執行階段、`mock` 只供開發與 e2e）：

- **以非 root 執行**：uid/gid 10001。
- **依賴已鎖定**：後端依賴來自 `apps/backend/requirements.lock`（以 hash 鎖定，`pip install --require-hashes`）；前端用 `package-lock.json` 與 `npm ci`；base image 使用確切的 patch 版本。
- 更新後端依賴時重新產生鎖定檔：

  ```bash
  uv pip compile apps/backend/pyproject.toml --python-version 3.11 --generate-hashes \
    -o apps/backend/requirements.lock
  ```

- **平台：** 已驗證 `linux/amd64`。`linux/arm64` **未驗證，部署到 Orin 前必須補驗**（本機沒有 buildx 與 arm64 binfmt）。

## 5. 開發與 e2e

開發環境（`docker-compose.dev.yml`）與端對端測試（`e2e/run.sh`）的用法見根目錄 `README.md`。

e2e 會掛載 Docker socket，讓測試能停止與恢復 `mock-edge-a`。**這只用於本機與用完即丟的測試環境，正式部署不需要，也不要掛載。**

## 6. 檢查 GitHub Actions workflow

`.github/workflows/` 的兩個 workflow 不發布任何東西。修改後可用固定版本的 actionlint 檢查，輸出必須為空：

```bash
docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:1.7.7 -color
```
