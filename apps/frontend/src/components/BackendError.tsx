import { formatTime } from "../lib/time";

export interface BackendErrorProps {
  /** usePolling 的最後成功時間；從未成功時為 null。 */
  lastSuccessAt: Date | null;
}

/** 前端連不到後端或後端回錯誤時的錯誤區塊；畫面其他部分保留最後的資料。 */
export function BackendError({ lastSuccessAt }: BackendErrorProps) {
  const last = lastSuccessAt === null ? "尚未成功" : `最後成功 ${formatTime(lastSuccessAt)}`;
  return (
    <p className="backend-error" role="alert">
      {`無法連線到後端，將自動重試（${last}）`}
    </p>
  );
}
