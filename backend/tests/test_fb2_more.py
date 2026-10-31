"""FB2 -> Markdown header variants."""
import logging

import fixtures as fx
from conftest import needs_pandoc


@needs_pandoc
def test_author_without_title(api, files):
    _, data = api.roundtrip(fx.fb2(files, title=None), "md")
    assert data.decode("utf-8").startswith(f"# {fx.FB2_AUTHOR_FIRST} {fx.FB2_AUTHOR_LAST}\n\n---\n\n")


@needs_pandoc
def test_last_name_only(api, files):
    _, data = api.roundtrip(fx.fb2(files, first=None), "md")
    assert data.decode("utf-8").startswith(f"# {fx.FB2_AUTHOR_LAST}\n\n## {fx.FB2_TITLE}\n\n---\n\n")


@needs_pandoc
def test_no_author_no_title_no_header(api, files):
    _, data = api.roundtrip(fx.fb2(files, title=None, first=None, last=None), "md")
    assert not data.decode("utf-8").startswith("# ")


def test_unreadable_fb2_header_is_logged_and_empty(app, tmp_path, caplog):
    from app.convert import fb2_title_header
    with caplog.at_level(logging.WARNING):
        assert fb2_title_header(str(tmp_path)) == []          # a directory cannot be opened
    rec = [r for r in caplog.records if "FB2 header" in r.getMessage()]
    assert rec and rec[0].exc_info and issubclass(rec[0].exc_info[0], OSError)
