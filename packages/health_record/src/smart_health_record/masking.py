"""敏感資訊遮蔽（規格書 4.4）。只使用標準函式庫。"""
import re

MAX_TEXT_LENGTH = 200
MASK = "***"

# scheme://userinfo@host：userinfo 取到最後一個 @（密碼可能含 @），不跨越 / ? # 與空白
_URL_CREDENTIALS = re.compile(r"([A-Za-z][A-Za-z0-9+.\-]{0,31}://)[^/?#\s]*@")

# 關鍵字（可帶前後綴，如 db_password、access_token）後接 : 或 =。
# 值有三種：引號字串（支援反斜線跳脫，未收尾則遮蔽到字串結尾）、
# 或未加引號的值（遮蔽到第一個空白或 & , ; ，值內的引號不截斷）。
_KEY_VALUE = re.compile(
    r"""(?:password|passwd|pwd|secret|token|api_key|apikey)[\w\-]{0,64}
        ["']?\s*[:=]\s*
        (?:
            (?P<q>["'])(?:\\.|(?!(?P=q))[^\\])*\\?(?P<close>(?P=q))?
          | [^\s&,;"'][^\s&,;]*
        )""",
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


def _mask_value(match: "re.Match[str]") -> str:
    # 保留鍵與分隔符，只替換值；引號值保留起始引號，有收尾才補收尾引號
    value_start = match.start("q") if match.group("q") else None
    if value_start is None:
        # 未加引號：值是 match 尾端那段，起點 = 最後一個分隔符之後
        full = match.group(0)
        sep = re.search(r"[:=]\s*", full)
        return full[: sep.end()] + MASK
    prefix = match.group(0)[: value_start - match.start()]
    q = match.group("q")
    return f"{prefix}{q}{MASK}{q if match.group('close') else ''}"


def mask_text(text: str) -> str:
    """遮蔽敏感資訊後截斷到最多 200 字元（先遮蔽再截斷）。"""
    masked = _URL_CREDENTIALS.sub(lambda m: m.group(1) + MASK + "@", text)
    masked = _KEY_VALUE.sub(_mask_value, masked)
    return masked[:MAX_TEXT_LENGTH]
