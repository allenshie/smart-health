import type { NodeView } from "../api/types";
import { EMPTY, formatMetric } from "../lib/format";
import { stateText } from "../lib/status";
import { formatTime } from "../lib/time";

export interface NodeDetailProps {
  id: string;
  label: string;
  /** 沒有該節點的狀態時為 undefined。 */
  node: NodeView | undefined;
}

/** 節點詳細面板。所有文字都以 JSX 文字節點呈現，不解析 HTML。 */
export function NodeDetail({ id, label, node }: NodeDetailProps) {
  const metrics = Object.entries(node?.metrics ?? {});
  const since = node?.since ?? null;
  return (
    <section className="node-detail" aria-label="節點詳細資料">
      <h2>{label === id ? label : `${label}（${id}）`}</h2>
      <dl>
        <dt>狀態</dt>
        <dd>{stateText(node)}</dd>
        <dt>原因</dt>
        <dd>{node?.reason ?? EMPTY}</dd>
        <dt>說明</dt>
        <dd>{node?.message ?? EMPTY}</dd>
        <dt>開始時間</dt>
        <dd>{since === null ? EMPTY : <time dateTime={since} title={since}>{formatTime(since)}</time>}</dd>
        <dt>指標</dt>
        <dd>
          {metrics.length === 0 ? (
            EMPTY
          ) : (
            <ul className="metrics">
              {metrics.map(([key, value]) => (
                <li key={key}>{`${key} = ${formatMetric(value)}`}</li>
              ))}
            </ul>
          )}
        </dd>
      </dl>
    </section>
  );
}
