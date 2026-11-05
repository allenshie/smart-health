"""敏感資訊遮蔽（規格書 4.4）。只使用標準函式庫。"""
import re

MAX_TEXT_LENGTH = 200
MASK = "***"

# scheme://userinfo@host：userinfo 取到最後一個 @（密碼可能含 @），不跨越 / ? # 與空白
_URL_CREDENTIALS = re.compile(r"([A-Za-z][A-Za-z0-9+.\-]*://)[^/?#\s]*@")

# 關鍵字（可帶前後綴，如 db_password、access_token）後接 : 或 =，值可帶引號
_KEY_VALUE = re.compile(
    r"""(?:password|passwd|pwd|secret|token|api_key|apikey)[\w\-]*  # 鍵
        (["']?\s*[:=]\s*)                                            # 分隔
        ("[^"]*"|'[^']*'|[^\s&,;"']+)                                # 值""",
    re.IGNORECASE | re.VERBOSE,
)


def _mask_value(match: "re.Match[str]") -> str:
    full = match.group(0)
    value = match.group(2)
    prefix = full[: len(full) - len(value)]
    if value[0] in "\"'" and len(value) >= 2 and value[-1] == value[0]:
        return f"{prefix}{value[0]}{MASK}{value[0]}"
    return prefix + MASK


def mask_text(text: str) -> str:
    """遮蔽敏感資訊後截斷到最多 200 字元（先遮蔽再截斷）。"""
    masked = _URL_CREDENTIALS.sub(lambda m: m.group(1) + MASK + "@", text)
    masked = _KEY_VALUE.sub(_mask_value, masked)
    return masked[:MAX_TEXT_LENGTH]
