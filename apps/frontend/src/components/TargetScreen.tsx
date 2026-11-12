import { useCallback } from "react";
import { ApiError, fetchTarget } from "../api/client";
import type { TargetDetail } from "../api/types";
import { usePolling } from "../hooks/usePolling";
import { summaryColor, summaryText } from "../lib/overview";
import { formatTime } from "../lib/time";
import { BackendError } from "./BackendError";
import { TargetPanel } from "./TargetPanel";

export interface TargetScreenProps {
  /** hash 中的服務 id（已解碼）；解碼失敗時為原文。 */
  id: string;
  /** id 是否符合 SPEC §4.1 的格式；不符合時直接顯示找不到服務。 */
  valid: boolean;
  intervalS: number;
  /** 「回到總覽」的連結：這次瀏覽中最後看過的總覽頁。 */
  backHref: string;
}

/** 「回到總覽」：44px 圓形圖示連結（SPEC §7.1 視覺），沒有可見文字，名稱與提示由 aria-label、title 提供。 */
function BackLink({ href }: { href: string }) {
  return (
    <a className="back-link" href={href} aria-label="回到總覽" title="回到總覽">
      <svg
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M15 18l-6-6 6-6" />
      </svg>
    </a>
  );
}

function NotFound({ id, backHref }: { id: string; backHref: string }) {
  return (
    <>
      <header className="app-header target-header">
        <div className="target-title">
          <BackLink href={backHref} />
        </div>
      </header>
      <p className="not-found">
        找不到服務 <code>{id}</code>
      </p>
    </>
  );
}

/**
 * 服務畫面（SPEC §7.1）。不符合格式的 id 不呼叫後端，直接顯示找不到服務；
 * 這種 id 不可能出現在設定中，也避免把 `..` 之類的內容組進 API 路徑。
 */
export function TargetScreen({ id, valid, intervalS, backHref }: TargetScreenProps) {
  return (
    <section className="target-screen" data-target-id={id}>
      {valid ? (
        <PolledTarget id={id} intervalS={intervalS} backHref={backHref} />
      ) : (
        <NotFound id={id} backHref={backHref} />
      )}
    </section>
  );
}

/** 只輪詢 /api/targets/{id}。404 時顯示找不到服務並照常輪詢，目標加回後自動恢復。 */
function PolledTarget({ id, intervalS, backHref }: Omit<TargetScreenProps, "valid">) {
  const fetchDetail = useCallback(() => fetchTarget(id), [id]);
  const { data: detail, error, lastSuccessAt } = usePolling(fetchDetail, intervalS * 1000);

  if (error instanceof ApiError && error.status === 404) {
    return <NotFound id={id} backHref={backHref} />;
  }
  const backendError = error !== null;
  return (
    <>
      <TargetHeader detail={detail} backendError={backendError} intervalS={intervalS} backHref={backHref} />
      {backendError && <BackendError lastSuccessAt={lastSuccessAt} />}
      {detail === null ? (
        !backendError && <p className="loading">載入中…</p>
      ) : (
        <TargetPanel detail={detail} backendError={backendError} />
      )}
    </>
  );
}

interface TargetHeaderProps {
  detail: TargetDetail | null;
  backendError: boolean;
  intervalS: number;
  backHref: string;
}

function TargetHeader({ detail, backendError, intervalS, backHref }: TargetHeaderProps) {
  const last = detail?.last_success_at ?? null;
  const lastUpdate = last === null ? "尚未取得" : formatTime(last);
  const color = detail === null ? "gray" : summaryColor(detail, backendError);
  return (
    <header className="app-header target-header">
      <div className="target-title">
        <BackLink href={backHref} />
        {detail !== null && (
          <>
            <h1 className="target-name" title={detail.name}>
              {detail.name}
            </h1>
            <span className={`summary-lamp lamp-${color}`} data-color={color}>
              <span className="lamp-dot" aria-hidden="true" />
              <span className="summary-state">{summaryText(detail, backendError)}</span>
            </span>
          </>
        )}
      </div>
      <span className="last-update">{`最後更新 ${lastUpdate}（每 ${intervalS} 秒）`}</span>
    </header>
  );
}
