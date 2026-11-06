import type { TargetSummary } from "../api/types";

export interface TargetSelectorProps {
  targets: TargetSummary[];
  selectedId: string;
  onChange: (id: string) => void;
}

/** 目標選單；選項為「名稱（connection 代碼）」。 */
export function TargetSelector({ targets, selectedId, onChange }: TargetSelectorProps) {
  return (
    <label className="target-selector">
      服務：
      <select value={selectedId} onChange={(e) => onChange(e.target.value)}>
        {targets.map((t) => (
          <option key={t.id} value={t.id}>
            {`${t.name}（${t.connection}）`}
          </option>
        ))}
      </select>
    </label>
  );
}
