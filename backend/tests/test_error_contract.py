"""The frontend has a translation for every error code the backend can send."""
import re
from pathlib import Path

import pytest

EN = Path(__file__).resolve().parents[2] / "frontend" / "src" / "locales" / "en.ts"


@pytest.mark.skipif(not EN.exists(), reason="frontend sources not present (backend-only checkout/image)")
def test_every_error_code_has_an_english_text():
    from app.errors import ErrorCode
    block = re.search(r"errors:\s*\{(.*?)\}", EN.read_text(encoding="utf-8"), re.S).group(1)
    keys = set(re.findall(r"^\s*([A-Z_]+):", block, re.M))
    assert keys == {c.value for c in ErrorCode}
