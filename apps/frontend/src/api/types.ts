// 與後端 models.py / contract.py 對齊；後端已驗證，前端不做執行期驗證。

export type Connection =
  | "unknown"
  | "online"
  | "offline"
  | "stale"
  | "incompatible"
  | "invalid_response";

export type Color = "green" | "yellow" | "red" | "gray";

export interface ConfigResponse {
  poll_interval_s: number;
}

export interface TargetSummary {
  id: string;
  name: string;
  connection: Connection;
  summary_color: Color;
  last_success_at: string | null;
}

export interface Lane {
  id: string;
  label: string;
  parent: string | null;
  sequential: boolean;
  nodes: string[];
}

export interface TopologyNode {
  id: string;
  label: string;
  upstream: string[];
  dependencies: string[];
}

export interface TopologyView {
  service: string;
  instance: string;
  topology_version: string;
  lanes: Lane[];
  nodes: TopologyNode[];
}

export type MetricValue = number | string | boolean | null;

export interface NodeView {
  state: string | null;
  reason: string | null;
  message: string | null;
  since: string | null;
  metrics: Record<string, MetricValue>;
  color: Color;
}

export interface TargetDetail extends TargetSummary {
  topology: TopologyView | null;
  nodes: Record<string, NodeView>;
}

export interface Transition {
  node: string;
  from: string | null;
  to: string;
  reason: string | null;
  at: string;
}
