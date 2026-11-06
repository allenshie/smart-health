function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** 以瀏覽器本地時間顯示 HH:MM:SS（24 小時制）；無效日期回傳原字串。 */
export function formatTime(value: string | Date): string {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}
