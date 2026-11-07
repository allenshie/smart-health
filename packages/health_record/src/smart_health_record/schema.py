"""契約層級的共用常數（規格書 4.1～4.3）：schema 版本、reason 代碼格式、message 長度上限。

函式庫內部各模組都從這裡取用，升版或調整時只改一處。
"""
import re

SCHEMA_VERSION = 1

REASON_PATTERN = "[a-z][a-z0-9_]*"
REASON_RE = re.compile(REASON_PATTERN)

MAX_MESSAGE_LENGTH = 200
