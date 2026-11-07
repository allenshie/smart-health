# smart_health Health App 映像檔（多階段）。建置 context 為 repo 根目錄：
#   docker build -f deploy/Dockerfile -t smart-health-app:local .
# 預設 target 為最後一個階段 app；mock 階段只供 dev compose 與 e2e 使用。
# base image 一律使用確切 patch 版本的 tag。

# ---- 前端建置：npm ci 依 package-lock.json 安裝，npm run build 含型別檢查 ----
FROM node:22.22.0-bookworm-slim AS frontend
WORKDIR /src/apps/frontend
COPY apps/frontend/package.json apps/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/frontend/ ./
RUN npm run build

# ---- 模擬服務（只供 dev compose 與 e2e）：函式庫與 mock 皆從原始碼載入 ----
FROM python:3.11.15-slim-bookworm AS mock
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/mock/lib:/opt/mock/examples/mock_service
# uid/gid 10001 超出系統帳號範圍，不加 --system（否則 useradd 會警告）
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --no-log-init --shell /usr/sbin/nologin app
# 函式庫沒有依賴，從 src 載入就是真實的 smart-health-record（SPEC §8）
COPY packages/health_record/src /opt/mock/lib
COPY examples/mock_service /opt/mock/examples/mock_service
COPY examples/raw_mock /opt/mock/examples/raw_mock
WORKDIR /opt/mock
USER 10001:10001

# ---- 正式執行階段（預設 target）----
FROM python:3.11.15-slim-bookworm AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore
WORKDIR /app
# 只安裝鎖定版本且驗證 hash 的 runtime 依賴；後端程式本身不經 pip 建置，避免抓取未鎖定的建置工具
# 以 root 安裝到系統 site-packages 是刻意的（映像檔內沒有 venv，執行時改用非 root），所以關閉 pip 的 root 警告
COPY apps/backend/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock \
    && rm /tmp/requirements.lock
# uid/gid 10001 超出系統帳號範圍，不加 --system（否則 useradd 會警告）
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --no-log-init --shell /usr/sbin/nologin app
COPY apps/backend/src/smart_health_backend /app/smart_health_backend
COPY --from=frontend /src/apps/frontend/dist /app/static
ENV PYTHONPATH=/app \
    SMART_HEALTH_CONFIG=/config/targets.yaml \
    SMART_HEALTH_STATIC_DIR=/app/static \
    UVICORN_HOST=0.0.0.0 \
    UVICORN_PORT=8000
USER 10001:10001
EXPOSE 8000
# 只用標準函式庫檢查 /healthz，不額外安裝 curl；port 跟著 UVICORN_PORT（host 網路模式可覆寫）
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('UVICORN_PORT', '8000'), timeout=2)"]
# uvicorn 從 UVICORN_HOST、UVICORN_PORT 讀取綁定位址
CMD ["uvicorn", "smart_health_backend.app:app"]
