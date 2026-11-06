"""敏感資訊遮蔽（規格書 4.4）。只使用標準函式庫。"""
import re

MAX_TEXT_LENGTH = 200
MASK = "***"

# scheme://userinfo@host：userinfo 取到最後一個 @（密碼可能含 @），不跨越 / ? # 與空白
_URL_CREDENTIALS = re.compile(r"([A-Za-z][A-Za-z0-9+.\-]{0,31}://)[^/?#\s]*@")

# 鍵值遮蔽採分段掃描，鍵長度沒有上限且維持線性時間（不使用 atomic group，相容 3.10）：
# 1. _KEY_TOKEN 找出完整的鍵 token 與分隔符；lookbehind 讓比對只從 token 起點開始。
# 2. _SENSITIVE 判斷鍵是否含敏感字樣（前後綴都算，如 db_password、access_token）。
# 3. 比對前先把鍵名的 - 換成 _（api-key 等同 api_key）；敏感的鍵才用 _VALUE 比對值並替換；不敏感的鍵只跳過分隔符，不吃掉值。
_KEY_TOKEN = re.compile(r"""(?<![\w\-])[\w\-]+["']?\s*[:=]\s*""")
_KEY_ONLY = re.compile(r"[\w\-]+")
_SENSITIVE = re.compile(
    r"password|passwd|pwd|secret|token|api_key|apikey|authorization", re.IGNORECASE
)
# Authorization 的 scheme：英文字母開頭的 token 字元（不含 = : 引號），後接空白。
# 不符合時退回一般規則整段遮蔽，避免 scheme 位置吞掉內層敏感鍵值。
# scheme 與空白字元集互斥，不會回溯成二次成長。
_AUTH_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9._~+\-]*\s+")
# 值：引號字串（支援反斜線跳脫，未收尾則遮蔽到字串結尾），
# 或未加引號的值（遮蔽到第一個空白或 & , ; ，值內的引號不截斷）。
_VALUE = re.compile(
    r"""(?:(?P<q>["'])(?:\\.|(?!(?P=q))[^\\])*\\?(?P<close>(?P=q))?
        |[^\s&,;"'][^\s&,;]*)""",
    re.VERBOSE | re.DOTALL,
)


def _mask_key_values(text: str) -> str:
    parts = []
    pos = 0  # 已輸出到的位置
    scan = 0  # 掃描位置
    while True:
        key = _KEY_TOKEN.search(text, scan)
        if key is None:
            break
        scan = key.end()
        name = _KEY_ONLY.match(text, key.start()).group(0)
        name = name.replace("-", "_")
        if not _SENSITIVE.search(name):
            continue  # 不敏感：只越過分隔符，值仍可能是下一個鍵（x=password=abc）
        prefix_end = scan
        if "authorization" in name.lower():
            scheme = _AUTH_SCHEME.match(text, scan)
            if scheme is not None and _VALUE.match(text, scheme.end()) is not None:
                prefix_end = scheme.end()  # 保留 scheme 與空白，只遮蔽憑證
        value = _VALUE.match(text, prefix_end)
        if value is None:
            continue
        q = value.group("q")
        if q:
            masked = f"{q}{MASK}{q if value.group('close') else ''}"
        else:
            masked = MASK
        parts.append(text[pos:prefix_end])
        parts.append(masked)
        pos = scan = value.end()
    parts.append(text[pos:])
    return "".join(parts)


def mask_text(text: str) -> str:
    """遮蔽敏感資訊後截斷到最多 200 字元（先遮蔽再截斷）。"""
    masked = _URL_CREDENTIALS.sub(lambda m: m.group(1) + MASK + "@", text)
    masked = _mask_key_values(masked)
    return masked[:MAX_TEXT_LENGTH]
