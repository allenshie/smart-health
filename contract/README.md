# smart_health 通用契約（schema_version: 1）

完整定義見 `docs/SPEC.md` 第 4 節。函式庫和後端都必須用這裡的 schema 與 fixtures 做測試。

## 內容

| 檔案 | 說明 |
|---|---|
| `topology.schema.json` | `GET /topology` 的 JSON Schema（draft 2020-12） |
| `status.schema.json` | `GET /status` 的 JSON Schema（draft 2020-12） |
| `fixtures/topology_edge.json` | `edge` 架構，6 個節點（SPEC 8.1） |
| `fixtures/status_edge_camera_down.json` | `edge` 在 `camera_down` 情境的狀態（SPEC 8.2） |
| `fixtures/status_before_first_evaluation.json` | 第一輪評估完成前的狀態 |
| `fixtures/topology_api.json` | `api` 架構：非 Edge 命名、2 個依賴、多上游、巢狀 lane（SPEC 8.3） |
| `tests/test_contract.py` | 契約測試 |

## 規則摘要

- 所有物件接受未知欄位，解析端應忽略。
- `schema_version` 目前固定為 `1`。
- `service`、lane、node、dependency 的 id：`^[a-z][a-z0-9_-]*$`；`instance` 只要求非空字串。
- `reason`：`^[a-z][a-z0-9_]*$`；`message` 最長 200 字元，可為 `null`。
- 時間字串為含時區的 ISO 8601。
- `evaluated_at` 為 `null` 時，`nodes` 必須為 `{}`、`recent_transitions` 必須為 `[]`。
- `recent_transitions` 最多 50 筆，`from` 可為 `null`。

## topology_version 算法

`lanes` 與 `nodes` 的正規化 JSON 取 UTF-8 SHA-256，取前 16 個十六進位字元：

```python
import hashlib, json

def topology_version(lanes, nodes):
    text = json.dumps({"lanes": lanes, "nodes": nodes},
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
```

fixtures 內的版本值是依此算出的真實值，並由測試驗證。

## 執行測試

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r contract/requirements-dev.txt
.venv/bin/python -m pytest contract/tests -v --import-mode=importlib
```
