# smart_health

通用的服務健康狀態系統：函式庫 `smart-health-record` 在各服務內記錄事實並評估狀態，Health App 後端集中拉取、前端顯示。規格見 `docs/SPEC.md`，計畫見 `docs/PLAN.md`。

## 目前結構

```text
contract/   契約文件、JSON Schema、fixtures 與契約測試
packages/   smart-health-record 函式庫
apps/       Health App 後端（FastAPI）與前端（React + Vite）
examples/   模擬服務 mock_service（edge、api）與 raw_mock（7 種不合契約的模式）
config/     targets.example.yaml（範本）、targets.dev.yaml（只含模擬服務位址）
deploy/     Dockerfile 與 compose 檔
e2e/        Playwright 端對端測試
docs/       規格書、實作計畫、驗收報告與截圖
```

完整說明待 Task 11 補上。

## 映像檔

`deploy/Dockerfile` 為多階段建置，建置 context 是 repo 根目錄：

- `frontend` 階段：`npm ci` 後 `npm run build`（含型別檢查）。
- `app` 階段（預設 target）：安裝 `apps/backend/requirements.lock`（`--require-hashes`）中鎖定的依賴，後端原始碼以 `PYTHONPATH` 載入，前端靜態檔放在 `/app/static`，由後端提供 `GET /`。以 uid 10001 的非 root 使用者執行。
- `mock` 階段：只供 dev compose 與 e2e，從原始碼載入函式庫與模擬服務。

| 環境變數 | 預設 | 說明 |
|---|---|---|
| `SMART_HEALTH_CONFIG` | `/config/targets.yaml` | 目標設定檔 |
| `SMART_HEALTH_STATIC_DIR` | `/app/static` | 前端靜態檔目錄；設定了但不存在時啟動失敗 |
| `UVICORN_HOST`、`UVICORN_PORT` | `0.0.0.0`、`8000` | 監聽位址；host 網路模式用 `UVICORN_PORT` 調整 |

`.dockerignore` 排除 `.env`、`config/targets.yaml` 等檔案，真實目標設定不會進入映像檔。

更新後端依賴時重新產生鎖定檔：

```bash
uv pip compile apps/backend/pyproject.toml --python-version 3.11 --generate-hashes \
  -o apps/backend/requirements.lock
```

**平台：** 已驗證 `docker build --platform linux/amd64 -f deploy/Dockerfile .`。`linux/arm64` **未驗證，部署到 Orin 前必須補驗**（本機沒有 buildx 與 arm64 binfmt）。

## 部署

```bash
cp config/targets.example.yaml config/targets.yaml   # 填入實際目標，此檔不進版控
docker compose -f deploy/docker-compose.yml up -d --build              # bridge 網路，SMART_HEALTH_PORT 預設 8000
UVICORN_PORT=8000 docker compose -f deploy/docker-compose.host.yml up -d --build   # host 網路（Orin 等環境）
```

`config/targets.yaml` 不存在時 compose 會直接失敗，不會自動建立同名目錄。

## 開發環境（Health App + 所有模擬服務）

```bash
docker compose -f deploy/docker-compose.dev.yml up --build --wait
# 瀏覽 http://127.0.0.1:18000
docker compose -f deploy/docker-compose.dev.yml down
```

- 專案名稱固定為 `smart-health-dev`，網路為 `smart-health-dev_default`。
- 包含 `health-app`、`mock-edge-a`、`mock-edge-b`、`mock-api` 與 7 個 `raw-*`（每個 raw_mock 模式一個）。每個 service 都有 healthcheck，`--wait` 會等到全部 healthy。
- 只有 `health-app` 發布 `127.0.0.1:18000`；模擬服務只在 compose 網路內可見。
- 目標設定為 `config/targets.dev.yaml`（只含模擬服務位址，拉取間隔 1 秒、請求逾時 3 秒）。
- 切換 edge 情境：`docker compose -f deploy/docker-compose.dev.yml exec mock-edge-b python -c "import urllib.request as u; print(u.urlopen(u.Request('http://127.0.0.1:19081/scenario', data=b'{\"name\": \"camera_down\"}', method='POST')).read())"`。
- 本機 docker 沒有 buildx 時，compose v2.24.5 仍可用 Docker Engine 內建的 BuildKit 建置；`docker build` 則會使用 legacy builder 並顯示棄用警告，兩者都能建置成功。

## 端對端測試（e2e）

e2e 在官方 Playwright Docker 映像檔內執行，對 dev compose 中的**真實後端**測試，本機不需安裝瀏覽器或系統套件：

```bash
docker compose -f deploy/docker-compose.dev.yml up --build --wait
e2e/run.sh                      # 可附加 playwright test 參數，例如 e2e/run.sh --grep starting
docker compose -f deploy/docker-compose.dev.yml down
```

`e2e/run.sh` 的做法：

- 從 `e2e/package.json` 讀出 `@playwright/test` 的確切版本，組出 `mcr.microsoft.com/playwright:v<版本>-noble`，兩者一定一致。
- 用 `docker run --rm` 加入 `smart-health-dev_default` 網路，在容器內 `npm ci && npx playwright test`，`baseURL` 為 `http://health-app:8000`。
- 以目前使用者的 uid/gid 執行，`HOME` 與 npm cache 放在容器的 `/tmp`，不產生 root 擁有的檔案。
- 掛載 `/var/run/docker.sock` 並加入 socket 的群組，讓測試透過 Docker Engine API 停止與恢復 `mock-edge-a`。**只用於本機；共用環境與 CI 不要掛載 Docker socket。** CI 怎麼跑 e2e 由 Task 11 決定。
- 只掛載 `e2e/` 與 `docs/acceptance/screenshots/`（以 `E2E_SCREENSHOT_DIR` 傳入），容器內讀不到 `.env`、`config/targets.yaml` 等其他檔案。
- 情境切換透過 mock 的控制接口（`POST /scenario`）；情境測試用 `mock-edge-b`，停止與恢復用 `mock-edge-a`。
- 截圖輸出到 `docs/acceptance/screenshots/`（`normal`、`camera_down`、`offline`、`mock-api`、`mobile`）。

測試內容：

| 檔案 | 內容 |
|---|---|
| `scenarios.spec.ts` | SPEC §8.2 的 12 個情境，驗證每個節點的狀態文字與顏色 |
| `robustness.spec.ts` | raw_mock 7 個模式、`mock-edge-a` 停止與恢復、hang 不影響其他目標 |
| `generic.spec.ts` | `mock-api` 的巢狀 lane |
| `responsive.spec.ts` | 寬度 360px 時頁面不水平捲動 |
