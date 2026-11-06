/**
 * 模擬服務操作：在 compose 網路內呼叫 mock 的控制接口，
 * 以及透過 Docker Engine API（掛載的 socket）停止或恢復 compose 容器。後者只用於本機 e2e。
 */
import * as http from "node:http";
import { expect, type APIRequestContext } from "@playwright/test";

const CONTROL_URL: Record<string, string> = {
  "mock-edge-a": "http://mock-edge-a:19081",
  "mock-edge-b": "http://mock-edge-b:19081",
  "mock-api": "http://mock-api:19081",
};

/** POST /scenario 切換情境；控制接口完成切換後才回應。 */
export async function setScenario(request: APIRequestContext, service: string, name: string): Promise<void> {
  const resp = await request.post(`${CONTROL_URL[service]}/scenario`, { data: { name } });
  expect(resp.status(), `切換 ${service} 到 ${name}`).toBe(200);
  expect(await resp.json()).toEqual({ name });
}

const DOCKER_SOCKET = "/var/run/docker.sock";
const COMPOSE_PROJECT = "smart-health-dev";

function engine(method: string, path: string): Promise<{ status: number; body: string }> {
  return new Promise((resolve, reject) => {
    const req = http.request({ socketPath: DOCKER_SOCKET, method, path }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (chunk: string) => (body += chunk));
      res.on("end", () => resolve({ status: res.statusCode ?? 0, body }));
    });
    req.on("error", reject);
    req.end();
  });
}

/** 依 compose label 找出 service 的容器 id（必須剛好一個）。 */
export async function composeContainerId(service: string): Promise<string> {
  const filters = JSON.stringify({
    label: [`com.docker.compose.project=${COMPOSE_PROJECT}`, `com.docker.compose.service=${service}`],
  });
  const { status, body } = await engine("GET", `/containers/json?all=1&filters=${encodeURIComponent(filters)}`);
  if (status !== 200) throw new Error(`Docker Engine API 查詢容器失敗：HTTP ${status} ${body}`);
  const list = JSON.parse(body) as { Id: string }[];
  if (list.length !== 1) throw new Error(`預期 1 個 ${service} 容器，實際 ${list.length} 個`);
  return list[0].Id;
}

async function containerAction(id: string, action: "stop" | "start"): Promise<void> {
  const query = action === "stop" ? "?t=5" : "";
  const { status, body } = await engine("POST", `/containers/${id}/${action}${query}`);
  // 204：完成；304：本來就是目標狀態
  if (status !== 204 && status !== 304) {
    throw new Error(`Docker Engine API ${action} 失敗：HTTP ${status} ${body}`);
  }
}

export const stopContainer = (id: string) => containerAction(id, "stop");
export const startContainer = (id: string) => containerAction(id, "start");
