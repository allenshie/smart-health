"""後端 log 設定：由 create_app 呼叫，import 時不產生副作用。"""

from __future__ import annotations

import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
# httpx 的 INFO log 以 str(url) 印出請求網址，不遮蔽帳密，所以只保留 WARNING 以上
_QUIET_LOGGERS = ("httpx", "httpcore")


def configure_logging() -> None:
    """root logger 沒有 handler 時才設定為 INFO 並輸出時間、level、logger 名稱。

    uvicorn 預設只設定 uvicorn* 的 logger；已有 handler（例如以 --log-config
    自行設定、或測試框架）時尊重既有設定，不覆寫。
    """
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
