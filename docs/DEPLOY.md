# 部署說明（Health App）

Health App 由後端（FastAPI）與前端（React，建置後由後端提供）組成，以單一映像檔部署。本文說明設定檔、compose、網路與安全限制、映像檔與版本發布。開發環境、e2e 與從原始碼建置見 `docs/DEVELOPMENT.md`。

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

正式部署從追蹤的範本 `deploy/docker-compose.example.yml` 出發：直接使用 Docker Hub 的映像檔（第 4 節），部署主機不需要建置。

| 檔案 | 用途 |
|---|---|
| `deploy/docker-compose.example.yml` | 正式部署的範本：Docker Hub 的映像檔、bridge 網路，host 網路的寫法以註解提供。複製成 `deploy/docker-compose.yml` 後修改 |
| `deploy/docker-compose.dev.yml` | 開發與 e2e：從原始碼建置 Health App，加上所有模擬服務，見 `docs/DEVELOPMENT.md` |

### 2.1 bridge 網路（預設）

從 repo 根目錄複製 example 與設定檔，修改後啟動：

```bash
cp deploy/docker-compose.example.yml deploy/docker-compose.yml
cp config/targets.example.yaml config/targets.yaml   # 填入實際目標
docker compose -f deploy/docker-compose.yml up -d
SMART_HEALTH_PORT=9000 docker compose -f deploy/docker-compose.yml up -d   # 改對外 port
```

- 複製出來的 `deploy/docker-compose.yml` 含本機設定，**不進版控**（已列在 `.gitignore`），可以直接修改。
- 映像檔是 `image` 指定的正式版本（目前 `0.3.0`）。升版時把 tag 改成新版本，可用的版本見 `CHANGELOG.md`；不提供 `latest`。
- 對外 port 由 `SMART_HEALTH_PORT` 指定，預設 `8000`；容器內固定監聽 8000。
- `config/targets.yaml` 以唯讀 bind mount 掛入。檔案不存在時 compose 會直接失敗（`bind source path does not exist`），不會自動建立同名目錄。
- bind mount 的相對路徑（`../config/targets.yaml`）以 compose 檔所在的目錄為基準；把 compose 檔複製到 `deploy/` 以外的位置時，要修改 `source` 的路徑。

### 2.2 host 網路

依 `deploy/docker-compose.yml`（由 example 複製）中的註解修改：刪掉 `ports`，取消 `network_mode: host` 與 `environment` 的註解，然後啟動：

```bash
UVICORN_PORT=8000 docker compose -f deploy/docker-compose.yml up -d
```

**原因（SPEC 第 10 節）：** 已知部分嵌入式主機的 kernel 沒有 iptables `raw` 表，Docker bridge 網路無法建立，這種主機要改用 host 網路。

host 網路沒有 port 對應，容器直接使用主機的 port，所以 port 改由 `UVICORN_PORT` 指定（預設 `8000`），注意不要和主機上其他服務衝突。

### 2.3 環境變數

| 環境變數 | 預設 | 說明 |
|---|---|---|
| `SMART_HEALTH_CONFIG` | `/config/targets.yaml` | 目標設定檔路徑 |
| `SMART_HEALTH_STATIC_DIR` | `/app/static` | 前端靜態檔目錄；設定了但不存在時啟動失敗 |
| `UVICORN_HOST`、`UVICORN_PORT` | `0.0.0.0`、`8000` | 容器內的監聽位址與 port |
| `SMART_HEALTH_PORT` | `8000` | 只用於由 example 複製的 compose 檔（bridge 網路），主機端的對外 port |

## 3. 網路與安全限制

**Health App 沒有登入驗證機制。** 任何連得到它的人都能看到所有目標的名稱與狀態。因此：

- 只能放在**受信任的內網**，或放在有驗證的**反向代理**之後。畫面以網址的 hash（`#/…`）區分，hash 不會送到伺服器，反向代理不需要額外的路徑改寫規則。前端使用 inline `<style>`（光點流動的 keyframes）與 `style` 屬性；若代理加上 CSP，`style-src` 需要允許 inline（`'unsafe-inline'`）。
- **不要直接暴露到網際網路。**
- 被監控服務的 `/topology`、`/status` 同樣沒有驗證，只應開放給 Health App 所在的網路。
- 後端只驗證並轉傳被監控服務的內容，**不會重新遮蔽 `message`**；遮蔽由各服務端負責，見 `docs/INTEGRATION.md`。
- `config/targets.yaml`、`.env` 已被 `.dockerignore` 排除，不會進入映像檔。

## 4. 映像檔

### 4.1 從 Docker Hub 拉取

`ci.yml` 的測試全部通過後，呼叫 `docker.yml`（GitHub 上的 job 名稱是 `docker / image`）把映像檔推到 Docker Hub 的 `<DOCKERHUB_REPO>`（GitHub repository variable，格式 `namespace/repository`）。每個 tag 都是同時含 `linux/amd64` 與 `linux/arm64` 的 manifest list，`docker pull` 會自動選主機的平台。

| tag | 來源 | 說明 |
|---|---|---|
| `X.Y.Z` | push `app-vX.Y.Z` tag | 正式版本，等於 `apps/frontend/package.json` 的 `version` |
| `sha-<commit 前 7 碼>` | push 到 `main`、手動執行 | 每個 commit 一個 |

- 不推送 `latest`。tag 不可變：已存在的 tag 不重新建置、不覆寫。
- 同一個 commit 的 `X.Y.Z` 與 `sha-` 指向同一個 digest。

```bash
docker pull <DOCKERHUB_REPO>:0.3.0                  # 依版本
docker pull <DOCKERHUB_REPO>@sha256:<digest>        # 依 digest 固定（digest 列在 workflow 的 job summary）
```

`deploy/docker-compose.example.yml` 已指向 Docker Hub 的正式版（`image: <DOCKERHUB_REPO>:X.Y.Z`），`docker compose up -d` 會直接拉取，部署主機不需要建置（第 2 節）。要測試尚未發布的修改、從原始碼建置正式映像檔時，見 `docs/DEVELOPMENT.md` 第 6 節。

Docker Hub repository 是 private 時，部署主機要先 `docker login`。

**平台：** `linux/amd64` 已驗證。`linux/arm64` 由 CI 建置並以 QEMU smoke test，**實機（例如 Orin）尚未驗證，部署到 arm64 主機前必須驗證。**

### 4.2 Dockerfile

`deploy/Dockerfile` 為多階段建置（`frontend` 建置前端、`app` 為正式執行階段、`mock` 只供開發與 e2e）：

- **以非 root 執行**：uid/gid 10001。
- **依賴已鎖定**：後端依賴來自 `apps/backend/requirements.lock`（以 hash 鎖定，`pip install --require-hashes`）；前端用 `package-lock.json` 與 `npm ci`；base image 使用確切的 patch 版本。
- 更新後端依賴時重新產生鎖定檔：

  ```bash
  uv pip compile apps/backend/pyproject.toml --python-version 3.11 --generate-hashes \
    -o apps/backend/requirements.lock
  ```

- **前端只建置一次：** 前端的產物是平台無關的靜態檔，`frontend` 階段寫成 `FROM --platform=${BUILDPLATFORM:-linux/amd64}`，在建置主機的原生平台執行，多平台建置時不經過 QEMU。
- **已知限制：** legacy builder（沒有 buildx 時的 `docker build`）沒有 `BUILDPLATFORM`，前端階段會退回 `linux/amd64` 的 node，**在 arm64 主機上建置會失敗**。arm64 主機請直接拉 Docker Hub 的映像檔（4.1），或用 buildx 建置，BuildKit 會填入主機的實際平台。

### 4.3 推送映像檔需要的 GitHub 設定

在 GitHub repo 的 Settings → Secrets and variables → Actions 設定：

| 種類 | 名稱 | 內容 |
|---|---|---|
| Variable | `DOCKERHUB_USERNAME` | Docker Hub 帳號 |
| Variable | `DOCKERHUB_REPO` | `namespace/repository`，例如 `<帳號>/smart-health-app`；只能用小寫英數字與 `_`、`.`、`-` |
| Secret | `DOCKERHUB_TOKEN` | 具 Read & Write 權限的 Docker Hub access token |

- 缺少任何一項或格式不符時，push 到 `main`、手動執行與 push tag 會在「檢查 Docker Hub 設定」步驟失敗並列出缺少的項目。pull request 不使用這些設定，不受影響。
- token 只用在登入步驟，不會印到 log。

## 5. 發布 Health App 版本

Health App 的版本是 `apps/frontend/package.json` 的 `version`（後端版本另計，見 `CHANGELOG.md`）。

1. 改版本號（同時更新 `package-lock.json`）：

   ```bash
   cd apps/frontend && npm version X.Y.Z --no-git-tag-version
   ```

   並把 `deploy/docker-compose.example.yml` 的 `image` 改成新版本（`<DOCKERHUB_REPO>:X.Y.Z`）。

2. 更新 `CHANGELOG.md`：把 Health App 的「未發布」改成這個版本與日期。
3. 以 pull request 合併到 `main`。建議等 `main` 上 `ci` 的 `docker / image` 完成，確認它推送了這個 commit 的 `sha-<7 碼>`，再推 tag。同一個 commit 的執行會排隊（concurrency 以 commit 分組），所以提早推 tag 也不會互相覆寫：tag 那次會在 `main` 推出 `sha-` 後，只為同一個 digest 加上版本 tag。
4. 在同一個 commit 打 tag 並 push：

   ```bash
   git tag app-vX.Y.Z <commit>
   git push origin app-vX.Y.Z
   ```

5. 確認 tag 觸發的 `ci` 通過（測試會重跑，通過後才執行 `docker / image`），job summary 中 `X.Y.Z` 與 `sha-<7 碼>` 的 digest 相同。

tag 那次執行的規則：

- tag 必須是 `app-vX.Y.Z`（X、Y、Z 是不含前導 0 的整數），而且 `X.Y.Z` 必須等於該 commit 的 `package.json` 版本，否則失敗、不推送。要修正時先刪除遠端的 tag（`git push origin :refs/tags/app-vX.Y.Z`），改好再重新打 tag。
- `deploy/docker-compose.example.yml` 中的 `image:`（註解行不計入）必須剛好一行，而且等於 `<DOCKERHUB_REPO>:X.Y.Z`；找不到、超過一行、不一致，或沒有設定 `DOCKERHUB_REPO` 時失敗、不推送，修正方式同上。push 到 `main`、手動執行與 pull request 不檢查：兩次發布之間，example 指向上一個正式版是正確的。
- `sha-<7 碼>` 已存在時不重新建置，只為同一個 digest 加上 `X.Y.Z`。不存在時（例如這個 commit 沒有在 `main` 上建置過）才建置、smoke test，再推送兩個 tag。
- `X.Y.Z` 已存在且指向不同的 digest 時失敗，不覆寫。

## 6. 開發與 e2e

開發環境（`docker-compose.dev.yml`）、端對端測試（`e2e/run.sh`）、本機測試與 CI 見 `docs/DEVELOPMENT.md`。

e2e 會掛載 Docker socket，讓測試能停止與恢復 `mock-edge-a`。**這只用於本機與用完即丟的測試環境，正式部署不需要，也不要掛載。**
