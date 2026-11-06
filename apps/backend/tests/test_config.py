from __future__ import annotations

from pathlib import Path

import pytest

from smart_health_backend.config import ConfigError, load_config

EXAMPLE = Path(__file__).resolve().parents[3] / "config" / "targets.example.yaml"

BASE = """
poll_interval_s: 5
request_timeout_s: 2
evaluation_stale_after_s: 10
history_limit: 200
targets:
  - id: a
    name: A
    base_url: http://a:1
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "t.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_example_config_is_valid():
    cfg = load_config(EXAMPLE)
    assert cfg.poll_interval_s == 5
    assert cfg.request_timeout_s == 2
    assert cfg.evaluation_stale_after_s == 10
    assert cfg.history_limit == 200
    assert [t.id for t in cfg.targets] == ["mock-edge-a"]
    assert cfg.targets[0].base_url == "http://mock-edge-a:18081"


@pytest.mark.parametrize("url", ["ftp://a:1", "a:1", "http://", "//a", "", "http://a:bad"])
def test_invalid_url_names_field(tmp_path, url):
    text = BASE + f"  - id: b\n    name: B\n    base_url: '{url}'\n"
    with pytest.raises(ConfigError, match=r"targets\[1\]\.base_url"):
        load_config(write(tmp_path, text))


def test_duplicate_id_rejected(tmp_path):
    text = BASE + "  - id: b\n    name: B\n    base_url: http://b:1\n"
    text += "  - id: a\n    name: A2\n    base_url: http://c:1\n"
    with pytest.raises(ConfigError, match=r"targets\[2\]\.id"):
        load_config(write(tmp_path, text))


@pytest.mark.parametrize("key", ["poll_interval_s", "request_timeout_s", "evaluation_stale_after_s"])
@pytest.mark.parametrize("value", ["0", "-1", "true", "'3'", ".nan", ".inf", "null"])
def test_non_positive_interval_rejected(tmp_path, key, value):
    text = BASE.replace(f"{key}: ", f"{key}: {value} #")
    with pytest.raises(ConfigError, match=key):
        load_config(write(tmp_path, text))


@pytest.mark.parametrize("value", ["0", "-5", "true", "1.5", "'3'"])
def test_invalid_history_limit_rejected(tmp_path, value):
    text = BASE.replace("history_limit: ", f"history_limit: {value} #")
    with pytest.raises(ConfigError, match="history_limit"):
        load_config(write(tmp_path, text))


def test_float_values_accepted(tmp_path):
    cfg = load_config(write(tmp_path, BASE.replace("poll_interval_s: 5", "poll_interval_s: 0.5")))
    assert cfg.poll_interval_s == 0.5


def test_defaults_when_top_level_numbers_missing(tmp_path):
    cfg = load_config(write(tmp_path, "targets: []\n"))
    assert (cfg.poll_interval_s, cfg.request_timeout_s) == (5, 2)
    assert (cfg.evaluation_stale_after_s, cfg.history_limit) == (10, 200)
    assert cfg.targets == []


def test_targets_required(tmp_path):
    with pytest.raises(ConfigError, match="targets"):
        load_config(write(tmp_path, "poll_interval_s: 5\n"))


@pytest.mark.parametrize("bad_id", ["A", "1a", "a b", "", "_a"])
def test_invalid_target_id(tmp_path, bad_id):
    text = BASE.replace("id: a", f"id: '{bad_id}'")
    with pytest.raises(ConfigError, match=r"targets\[0\]\.id"):
        load_config(write(tmp_path, text))


def test_empty_name_rejected(tmp_path):
    with pytest.raises(ConfigError, match=r"targets\[0\]\.name"):
        load_config(write(tmp_path, BASE.replace("name: A", "name: '  '")))


def test_unknown_fields_rejected(tmp_path):
    with pytest.raises(ConfigError, match="poll_interval"):
        load_config(write(tmp_path, BASE + "poll_interval: 3\n"))
    with pytest.raises(ConfigError, match=r"targets\[0\]\.basse_url"):
        load_config(write(tmp_path, BASE + "    basse_url: x\n"))


def test_yaml_syntax_error_and_non_mapping(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "targets: [\n"))
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "- a\n- b\n"))
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.yaml")


@pytest.mark.parametrize(
    "url", ["http://h:1?x=1", "http://h:1#frag", "http://h:1?", " http://h:1", "http://h:1 "]
)
def test_base_url_rejects_query_fragment_whitespace(tmp_path, url):
    text = BASE.replace("http://a:1", f"'{url}'")
    with pytest.raises(ConfigError, match=r"targets\[0\]\.base_url"):
        load_config(write(tmp_path, text))


def test_duplicate_yaml_key_rejected(tmp_path):
    with pytest.raises(ConfigError, match="history_limit"):
        load_config(write(tmp_path, BASE + "history_limit: 5\n"))
    with pytest.raises(ConfigError, match="name"):
        load_config(write(tmp_path, BASE + "    name: Other\n"))


def test_duplicate_key_check_does_not_change_global_yaml(tmp_path):
    import yaml

    assert yaml.safe_load("a: 1\na: 2\n") == {"a": 2}
