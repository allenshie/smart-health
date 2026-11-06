import pytest

from smart_health_record import mask_text


def test_masks_url_credentials():
    assert mask_text("rtsp://admin:secret@10.0.0.1/live") == "rtsp://***@10.0.0.1/live"


def test_masks_url_with_username_only():
    assert mask_text("rtsp://admin@10.0.0.1/live") == "rtsp://***@10.0.0.1/live"


def test_masks_url_password_containing_at_sign():
    out = mask_text("rtsp://admin:p@ss@w0rd@10.0.0.1:554/live")
    assert out == "rtsp://***@10.0.0.1:554/live"
    assert "ss" not in out and "w0rd" not in out


def test_url_without_credentials_unchanged():
    assert mask_text("http://host/path?email=a@b.c") == "http://host/path?email=a@b.c"


def test_masks_key_values():
    assert mask_text("password=secret") == "password=***"
    assert mask_text("TOKEN: abc") == "TOKEN: ***"
    assert mask_text("api_key=x") == "api_key=***"


def test_masks_all_required_keys_case_insensitive():
    for key in ["password", "passwd", "pwd", "secret", "token", "api_key", "apikey"]:
        for variant in (key, key.upper(), key.capitalize()):
            out = mask_text(f"{variant}=hunter2")
            assert "hunter2" not in out, variant
            assert out == f"{variant}=***"


def test_masks_query_string_and_keeps_rest():
    assert mask_text("http://h/p?token=abc&x=1") == "http://h/p?token=***&x=1"


def test_masks_prefixed_keys():
    assert mask_text("db_password=x") == "db_password=***"
    assert mask_text("access_token=x") == "access_token=***"


def test_masks_quoted_values_entirely():
    out = mask_text('{"password": "abc def", "user": "bob"}')
    assert "abc" not in out and "def" not in out
    assert '"user": "bob"' in out
    out = mask_text("secret='a b c' next")
    assert "a b c" not in out and out.endswith("next")


def test_combined_url_and_key_value():
    out = mask_text("open rtsp://u:p@h/x failed token=zzz")
    assert out == "open rtsp://***@h/x failed token=***"


def test_plain_text_unchanged():
    assert mask_text("connection refused") == "connection refused"
    assert mask_text("") == ""


def test_truncates_to_200_chars():
    assert len(mask_text("a" * 500)) == 200


def test_masks_before_truncating():
    # 鍵在第 200 字元前、值橫跨邊界：若先截斷會殘留部分密碼
    out = mask_text("x" * 180 + " password=hunter2hunter2hunter2")
    assert "hunt" not in out and out.endswith("password=***")
    assert len(out) <= 200


def test_masks_double_quoted_value_with_escaped_quote():
    out = mask_text(r'password = "a\"b c" tail')
    assert out == 'password = "***" tail'
    out = mask_text(r'{"password": "a\"b c", "user": "bob"}')
    assert "b c" not in out and out.endswith('"user": "bob"}')


def test_masks_single_quoted_value_with_escaped_quote():
    out = mask_text(r"secret = 'a\'b c' tail")
    assert out == "secret = '***' tail"


def test_masks_unterminated_quoted_value_to_end():
    assert mask_text('token="abc') == 'token="***'
    assert mask_text("token='abc def") == "token='***"
    assert mask_text('token="abc def ghi') == 'token="***'
    assert mask_text('pwd="abc\\') == 'pwd="***'


def test_unquoted_value_with_inner_quote_masked_to_whitespace():
    assert mask_text("Password: it's fine") == "Password: *** fine"
    assert mask_text('pwd=ab"cd ef') == 'pwd=*** ef'
    assert mask_text("token=a'b&x=1") == "token=***&x=1"


def test_quoted_value_other_text_preserved():
    assert mask_text('a password="x y" b') == 'a password="***" b'


def _elapsed(text: str) -> float:
    import time

    t0 = time.perf_counter()
    mask_text(text)
    return time.perf_counter() - t0


def test_long_plain_input_is_fast():
    assert _elapsed("x" * 200000) < 1.0


def test_long_unterminated_quoted_value_is_fast():
    assert _elapsed('password="' + "a" * 200000) < 1.0


def test_long_repeated_keyword_is_fast():
    assert _elapsed("password" * 25000) < 1.0


def test_long_scheme_like_input_is_fast_and_still_masks():
    assert _elapsed("a" * 200000 + "://") < 1.0
    out = mask_text("a" * 40 + "://user:pw@host/x")
    assert "pw" not in out and "user" not in out


def test_masking_still_works_at_end_of_long_input():
    out = mask_text("x" * 100000 + " rtsp://u:p@h/x")
    assert out == "x" * 200
    # 遮蔽發生在截斷之前，不能因輸入過長而漏遮
    tail = mask_text("rtsp://u:p@h/x " + "y" * 100000)
    assert tail.startswith("rtsp://***@h/x ")


def test_masks_key_with_very_long_suffix():
    assert mask_text("password" + "x" * 65 + "=secret") == "password" + "x" * 65 + "=***"
    out = mask_text("password" + "x" * 100000 + "=secret")
    assert "secret" not in out and out == ("password" + "x" * 100000 + "=***")[:200]


def test_masks_value_after_non_sensitive_key():
    assert mask_text("x=password=abc") == "x=password=***"
    assert mask_text("a=b&token=abc&c=d") == "a=b&token=***&c=d"


def test_long_repeated_keyword_still_masks_value():
    import time

    t0 = time.perf_counter()
    out = mask_text("password" * 25000 + "=secret")
    assert time.perf_counter() - t0 < 1.0
    # 輸出被截斷到 200 字元，所以另以較短輸入驗證值遮蔽
    assert mask_text("password" * 20 + "=secret").endswith("=***")
    assert "secret" not in out


def test_other_pathological_inputs_are_fast():
    for text in ["a " * 100000, "a=" * 100000, "a" + " " * 200000,
                 "password " * 25000, "-" * 200000]:
        assert _elapsed(text) < 1.0


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Authorization: Bearer abc.def", "Authorization: Bearer ***"),
        ("Authorization: Basic dXNlcjpwYXNz", "Authorization: Basic ***"),
        ("authorization=Bearer xyz", "authorization=Bearer ***"),
        ("AUTHORIZATION: bearer xyz", "AUTHORIZATION: bearer ***"),
        ("Proxy-Authorization: Basic abc", "Proxy-Authorization: Basic ***"),
        ("Authorization: abc", "Authorization: ***"),
        ('"Authorization": "Bearer abc"', '"Authorization": "***"'),
        ("headers: Authorization: Bearer abc, next=1", "headers: Authorization: Bearer ***, next=1"),
        ("api-key=abc", "api-key=***"),
        ("x-api-key: abc", "x-api-key: ***"),
        ("X-API-KEY=abc", "X-API-KEY=***"),
        ("X-Api-Key: abc", "X-Api-Key: ***"),
        ("api_key=abc", "api_key=***"),
    ],
)
def test_masks_authorization_and_hyphenated_keys(text, expected):
    assert mask_text(text) == expected


def test_long_authorization_and_hyphenated_inputs_are_fast_and_masked():
    for text in ["Authorization: Bearer " + "a" * 100000, "x-api-key=" * 20000,
                 "Authorization: " + "a " * 100000, "authorization" * 15000,
                 "Authorization:" + " " * 200000 + "a"]:
        assert _elapsed(text) < 1.0
    out = mask_text("Authorization: Bearer " + "a" * 100000)
    assert out == "Authorization: Bearer ***"
    assert "secret" not in mask_text("x-api-key=secret " * 20000)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("authorization: password=hunter2 next", "authorization: *** next"),
        ("missing authorization: api_key=xyz provided", "missing authorization: *** provided"),
        ("authorization: token=abc def", "authorization: *** def"),
        # 已知限制：憑證放在下一行時，第一行只有一段，整段遮蔽，下一行不處理
        ("Authorization: Bearer\nabc", "Authorization: ***\nabc"),
        ("Authorization: s3cr3tT0ken\nnext line here", "Authorization: ***\nnext line here"),
        ("Authorization: s3cr3tT0ken\r\nHost: x", "Authorization: ***\r\nHost: x"),
        ("Authorization: abcdef\n\ntraceback", "Authorization: ***\n\ntraceback"),
        ("Authorization: Bearer abc\nHost: x", "Authorization: Bearer ***\nHost: x"),
        ("Authorization: Bearer abc", "Authorization: Bearer ***"),
        ("Authorization: Bearer　abc", "Authorization: Bearer　***"),
        ("Authorization: Bearer abc", "Authorization: Bearer ***"),
        ('Authorization: Bearer "abc def"', 'Authorization: Bearer "***"'),
        ("Authorization: Bearer 'abc", "Authorization: Bearer '***"),
    ],
)
def test_authorization_scheme_is_token_only(text, expected):
    assert mask_text(text) == expected


def test_long_repeated_schemes_are_fast_and_masked():
    for text in ["Authorization: " + "Bearer " * 30000,
                 "authorization=" + "a" * 200000,
                 "authorization: " + "a=" * 100000]:
        assert _elapsed(text) < 1.0
    assert mask_text("Authorization: " + "Bearer " * 30000).startswith("Authorization: Bearer ***")
