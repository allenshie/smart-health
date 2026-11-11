"""__version__ 與 pyproject.toml 的版本一致（規格書第 5 節）。"""
import re
from pathlib import Path

import smart_health_record

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_version_matches_pyproject():
    # 3.10 沒有 tomllib，用 regex 讀 [project] 的 version
    match = re.search(r'^version = "([^"]+)"$', PYPROJECT.read_text(encoding="utf-8"), re.MULTILINE)
    assert match is not None
    assert smart_health_record.__version__ == match.group(1) == "0.1.1"
