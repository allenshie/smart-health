# smart-health

通用的服務健康狀態系統：各服務以函式庫或通用契約提供狀態，Health App 集中拉取並以架構圖與燈號顯示。

## 三大部分

| 部分 | 說明 | 文件 |
|---|---|---|
| **函式庫 `smart-health-record`**（`packages/health_record`） | 在各服務內記錄事實（開始、成功、錯誤、致命故障、指標），由獨立的評估執行緒推導節點狀態，並以 `GET /topology`、`GET /status` 提供。只使用 Python 標準函式庫。 | [`packages/health_record/README.md`](packages/health_record/README.md)、[`docs/INTEGRATION.md`](docs/INTEGRATION.md) |
| **Health App**（`apps/`） | 後端（FastAPI）定期拉取各服務的 `/topology` 與 `/status`；前端（React + Vite）以「服務總覽」卡片列出所有服務的總體狀態，點進「服務畫面」查看架構圖、燈號與節點詳細資料。 | [`docs/DEPLOY.md`](docs/DEPLOY.md)（畫面規格見 [`docs/SPEC.md`](docs/SPEC.md) §7.1） |
| **通用契約**（`contract/`） | 兩個接口的 JSON Schema 與 fixtures；不使用函式庫的服務只要符合契約也能被監控。 | [`contract/README.md`](contract/README.md) |

## 畫面

| 服務總覽 | 服務畫面（正常） |
|---|---|
| ![服務總覽](docs/screenshots/overview.png) | ![服務畫面](docs/screenshots/normal.png) |

## 快速開始

以 Docker Hub 的映像檔部署 Health App，從 repo 根目錄執行：

```bash
cp deploy/docker-compose.example.yml deploy/docker-compose.yml
cp config/targets.example.yaml config/targets.yaml   # 填入實際目標
docker compose -f deploy/docker-compose.yml up -d
```

瀏覽 `http://<主機>:8000`（服務總覽）。對外 port、host 網路、設定檔欄位與網路安全限制見 [`docs/DEPLOY.md`](docs/DEPLOY.md)。

## 文件

| 文件 | 內容 |
|---|---|
| [`docs/SPEC.md`](docs/SPEC.md) | 規格書 |
| [`CHANGELOG.md`](CHANGELOG.md) | 函式庫與 Health App 各版本的變更 |
| [`contract/README.md`](contract/README.md) | 契約與 `topology_version` 算法 |
| [`docs/INTEGRATION.md`](docs/INTEGRATION.md) | 函式庫導入指南：範例、callable 不能阻塞、port、`message` 遮蔽與已知限制 |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | 部署說明：設定檔、compose、host 網路、網路安全限制、映像檔與版本發布 |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | 開發說明：本機測試、函式庫打包、CI、開發環境、e2e、從原始碼建置映像檔 |
| [`packages/health_record/README.md`](packages/health_record/README.md) | 函式庫簡介與最小範例 |

## 目錄結構

```text
contract/           契約文件、JSON Schema、fixtures 與契約測試
packages/           smart-health-record 函式庫（原始碼、測試、benchmarks）
apps/backend/       Health App 後端（FastAPI），requirements.lock 鎖定執行時依賴
apps/frontend/      Health App 前端（React + Vite）
examples/           模擬服務 mock_service（edge、api）與 raw_mock（7 種不合契約的模式）
config/             targets.example.yaml（範本）、targets.dev.yaml（只含模擬服務位址）
deploy/             Dockerfile、正式部署的 compose 範本 docker-compose.example.yml、開發與 e2e 用的 docker-compose.dev.yml
e2e/                Playwright 端對端測試
docs/               規格書、導入指南、部署說明、開發說明與截圖
.github/workflows/  ci.yml（唯一的入口：ruff、單元測試，通過後呼叫 docker.yml）與 docker.yml（Health App 映像檔推到 Docker Hub）
```
