import type { Connection } from "../api/types";
import { formatTime } from "../lib/time";

const MESSAGES: Record<Exclude<Connection, "online">, string> = {
  offline: "無法連線到此服務",
  stale: "此服務的評估已停止更新",
  incompatible: "此服務的契約版本不相容",
  invalid_response: "此服務回傳的資料無效",
  unknown: "尚未取得此服務的狀態",
};

export interface ConnectionBannerProps {
  connection: Connection;
  lastSuccessAt: string | null;
}

/** 目標不是 online 時的橫幅：說明、連線代碼與最後成功時間。 */
export function ConnectionBanner({ connection, lastSuccessAt }: ConnectionBannerProps) {
  if (connection === "online") return null;
  const message = MESSAGES[connection] ?? "此服務的連線狀態異常";
  const last = lastSuccessAt === null ? "尚未成功取得" : `最後更新 ${formatTime(lastSuccessAt)}`;
  return (
    <p className="banner" role="status" data-connection={connection}>
      {`${message}（${connection}），${last}`}
    </p>
  );
}
