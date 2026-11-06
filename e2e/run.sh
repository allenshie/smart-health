#!/usr/bin/env bash
# 在官方 Playwright 映像檔內執行 e2e（只用於本機）。先啟動 dev compose：
#   docker compose -f deploy/docker-compose.dev.yml up --build --wait
#   e2e/run.sh [playwright test 的參數...]
#
# - 映像檔 tag 由 e2e/package.json 的 @playwright/test 確切版本組出，兩者一定一致。
# - 容器加入 dev compose 網路，對真實後端 http://health-app:8000 測試。
# - 以目前使用者的 uid/gid 執行，避免產生 root 擁有的檔案；HOME 與 npm cache 放在 /tmp。
# - 掛載 Docker socket 並加入 socket 的群組，只為了停止與恢復 mock-edge-a。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(sed -n 's/^ *"@playwright\/test": *"\([0-9][0-9.]*\)".*/\1/p' "$ROOT/e2e/package.json")"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "無法從 e2e/package.json 讀出 @playwright/test 的確切版本（讀到：'$VERSION'）" >&2
  exit 1
fi
IMAGE="mcr.microsoft.com/playwright:v${VERSION}-noble"
NETWORK="${SMART_HEALTH_E2E_NETWORK:-smart-health-dev_default}"
SOCKET=/var/run/docker.sock

if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
  echo "找不到 Docker 網路 $NETWORK，請先執行：docker compose -f deploy/docker-compose.dev.yml up --build --wait" >&2
  exit 1
fi

mkdir -p "$ROOT/docs/acceptance/screenshots"
echo "使用映像檔 $IMAGE，網路 $NETWORK"
exec docker run --rm --init --ipc=host \
  --network "$NETWORK" \
  --user "$(id -u):$(id -g)" \
  --group-add "$(stat -c %g "$SOCKET")" \
  -v "$SOCKET:$SOCKET" \
  -v "$ROOT:/work" \
  -w /work/e2e \
  -e HOME=/tmp/e2e-home \
  -e npm_config_cache=/tmp/e2e-home/.npm \
  -e CI=1 \
  "$IMAGE" \
  bash -c 'npm ci --no-audit --no-fund && npx playwright test "$@"' playwright "$@"
