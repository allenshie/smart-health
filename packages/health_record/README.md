# smart-health-record

記錄服務內各節點的事實（開始、成功、錯誤、致命故障、指標），供獨立的評估執行緒推導健康狀態。
執行時只使用 Python 標準函式庫。

目前已提供（Task 2）：

- `NodeRecorder`：執行緒安全的事實記錄器，所有方法都不會讓例外進入業務執行緒。
- `mask_text`：敏感資訊遮蔽（URL 帳密、`password`／`token` 等鍵值），輸出最多 200 字元。

規格見專案 `docs/SPEC.md` 第 5 節。
