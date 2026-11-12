import type { TargetSummary } from "../api/types";
import { summaryColor, summaryText } from "../lib/overview";
import { targetHash } from "../lib/route";
import { formatTime } from "../lib/time";

export interface TargetCardProps {
  target: TargetSummary;
  /** 後端請求失敗：燈號轉灰、狀態文字「未知」，其他內容保留最後的值。 */
  backendError: boolean;
}

/** online 顯示最後更新，其他顯示最後成功；從未成功時為「尚未取得」。 */
function timeText(target: TargetSummary): string {
  if (target.last_success_at === null) return "尚未取得";
  const time = formatTime(target.last_success_at);
  return target.connection === "online" ? `最後更新 ${time}` : `最後成功 ${time}`;
}

/** 總覽上的一個服務：整張卡片是連到服務畫面的連結。所有文字以純文字呈現。 */
export function TargetCard({ target, backendError }: TargetCardProps) {
  const color = summaryColor(target, backendError);
  return (
    <a
      className={`target-card lamp-${color}`}
      href={targetHash(target.id)}
      data-target-id={target.id}
      data-color={color}
    >
      <span className="card-head">
        <span className="lamp-dot" aria-hidden="true" />
        <span className="card-name" title={target.name}>
          {target.name}
        </span>
      </span>
      <span className="card-state">{summaryText(target, backendError)}</span>
      <span className="card-meta">
        <span className="card-connection">{target.connection}</span>{" "}
        <span className="card-time">{timeText(target)}</span>
      </span>
    </a>
  );
}
