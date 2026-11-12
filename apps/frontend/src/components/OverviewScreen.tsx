import { useEffect } from "react";
import { fetchTargets } from "../api/client";
import type { Color } from "../api/types";
import { usePolling } from "../hooks/usePolling";
import { EMPTY } from "../lib/format";
import { colorCounts, paginate } from "../lib/overview";
import { overviewHash } from "../lib/route";
import { formatTime } from "../lib/time";
import { BackendError } from "./BackendError";
import { TargetCard } from "./TargetCard";

const STATS: ReadonlyArray<[Color, string]> = [
  ["green", "正常"],
  ["yellow", "注意"],
  ["red", "異常"],
  ["gray", "離線或等待"],
];

export interface OverviewScreenProps {
  intervalS: number;
  /** hash 中的頁碼（已確認是正整數）。 */
  page: number;
  /** 以 replace 改寫 hash。 */
  replace: (hash: string) => void;
}

/**
 * 服務總覽（SPEC §7.1）：只輪詢 /api/targets。統計列以全部目標計數；卡片每頁 PAGE_SIZE 個。
 * 頁碼超過最後一頁時顯示最後一頁，並在取得清單且後端沒有錯誤時以 replace 改寫 hash。
 */
export function OverviewScreen({ intervalS, page, replace }: OverviewScreenProps) {
  const { data: targets, error, lastSuccessAt } = usePolling(fetchTargets, intervalS * 1000);
  const backendError = error !== null;
  const paged = paginate(targets ?? [], page);
  const known = targets !== null && !backendError;
  const counts = known ? colorCounts(targets) : null;
  const lastUpdate = lastSuccessAt === null ? "尚未取得" : formatTime(lastSuccessAt);

  const mustClamp = known && paged.page !== page;
  useEffect(() => {
    if (mustClamp) replace(overviewHash(paged.page));
  }, [mustClamp, paged.page, replace]);

  return (
    <>
      <header className="app-header overview-header">
        <h1 className="screen-title">服務總覽</h1>
        <span className="last-update">{`最後更新 ${lastUpdate}（每 ${intervalS} 秒）`}</span>
      </header>
      <ul className="overview-stats" aria-label="統計">
        {STATS.map(([color, label]) => (
          <li key={color} className={`stat lamp-${color}`} data-color={color}>
            {`${label} ${counts === null ? EMPTY : counts[color]}`}
          </li>
        ))}
      </ul>
      {backendError && <BackendError lastSuccessAt={lastSuccessAt} />}
      {targets === null && !backendError && <p className="loading">載入中…</p>}
      {targets !== null && targets.length === 0 && <p className="empty">尚未設定任何服務</p>}
      {paged.items.length > 0 && (
        <ul className="target-cards">
          {paged.items.map((t) => (
            <li key={t.id}>
              <TargetCard target={t} backendError={backendError} />
            </li>
          ))}
        </ul>
      )}
      {paged.pageCount > 1 && targets !== null && (
        <nav className="pager" aria-label="分頁">
          <PagerLink page={paged.page - 1} enabled={paged.page > 1} label="上一頁" />
          <span className="pager-status">{`第 ${paged.page} / ${paged.pageCount} 頁（共 ${targets.length} 個服務）`}</span>
          <PagerLink page={paged.page + 1} enabled={paged.page < paged.pageCount} label="下一頁" />
        </nav>
      )}
    </>
  );
}

function PagerLink({ page, enabled, label }: { page: number; enabled: boolean; label: string }) {
  if (!enabled) {
    return (
      <span className="pager-link" aria-disabled="true">
        {label}
      </span>
    );
  }
  return (
    <a className="pager-link" href={overviewHash(page)}>
      {label}
    </a>
  );
}
