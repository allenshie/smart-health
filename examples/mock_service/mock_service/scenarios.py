"""情境名稱與模擬用常數（只含常數，測試也會 import）。"""

# 假帳密：帶進錯誤訊息，模擬真實的錯誤字串；任何輸出都不應出現 FAKE_SECRET。
FAKE_SECRET = "mock-s3cret"
FAKE_RTSP_URL = f"rtsp://admin:{FAKE_SECRET}@10.0.0.1/live"
FAKE_PASSWORD_TEXT = f"password={FAKE_SECRET}"

STARTING = "starting"

# 規格書 8.2 的 12 個情境
EDGE_SCENARIOS = (
    "normal", "starting", "camera_down", "messaging_down", "stream_sink_down",
    "infer_stuck", "infer_exception", "camera_and_messaging_down", "read_errors",
    "publish_errors", "worker_fatal", "stream_disabled",
)

# 無畫面（相機中斷或 worker 失效）的情境
EDGE_NO_FRAME = frozenset({"starting", "camera_down", "camera_and_messaging_down", "worker_fatal"})
EDGE_MESSAGING_DOWN = frozenset({"messaging_down", "camera_and_messaging_down"})

# api 情境：依賴失效，以及讓單一上游失效的 fatal
API_SCENARIOS = (
    "normal", "database_down", "cache_down",
    "gateway_fatal", "cache_warmer_fatal", "job_runner_fatal",
)
API_FATAL_NODE = {
    "gateway_fatal": "gateway",
    "cache_warmer_fatal": "cache-warmer",
    "job_runner_fatal": "job-runner",
}
API_DEPENDENCY_DOWN = {"database_down": "database", "cache_down": "cache"}
