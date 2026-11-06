// 測試用資料：直接讀 contract/fixtures 的 /topology 原文，再組出後端回應的形狀。
import apiJson from "../../../../contract/fixtures/topology_api.json";
import edgeJson from "../../../../contract/fixtures/topology_edge.json";
import type {
  NodeView,
  TargetDetail,
  TargetSummary,
  TopologyView,
} from "../api/types";

// /topology 原文多了 schema_version，後端的 TopologyView 沒有這個欄位。
function toTopology(raw: TopologyView): TopologyView {
  return {
    service: raw.service,
    instance: raw.instance,
    topology_version: raw.topology_version,
    lanes: raw.lanes,
    nodes: raw.nodes,
  };
}

export const edgeTopology: TopologyView = toTopology(edgeJson);
export const apiTopology: TopologyView = toTopology(apiJson);

export function nodeView(overrides: Partial<NodeView> = {}): NodeView {
  return {
    state: "ok",
    reason: null,
    message: null,
    since: null,
    metrics: {},
    color: "green",
    ...overrides,
  };
}

/** 依 topology 產生每個節點都是 ok 的目標詳細資料。 */
export function targetDetail(overrides: Partial<TargetDetail> = {}): TargetDetail {
  const topology = overrides.topology === undefined ? edgeTopology : overrides.topology;
  const nodes =
    overrides.nodes ??
    Object.fromEntries((topology?.nodes ?? []).map((n) => [n.id, nodeView()]));
  return {
    id: "mock-edge-a",
    name: "Mock Edge A",
    connection: "online",
    summary_color: "green",
    last_success_at: "2026-11-06T02:32:15Z",
    ...overrides,
    topology,
    nodes,
  };
}

export function summaryOf(detail: TargetDetail): TargetSummary {
  return {
    id: detail.id,
    name: detail.name,
    connection: detail.connection,
    summary_color: detail.summary_color,
    last_success_at: detail.last_success_at,
  };
}
