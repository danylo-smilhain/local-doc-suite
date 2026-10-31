"""Errors that the server tolerates are logged, not swallowed (task 5)."""
import logging

import fixtures as fx


def test_corrupt_upload_still_succeeds_and_is_logged(api, files, caplog):
    bad = files / "broken.pdf"
    bad.write_bytes(b"%PDF-1.4 this is not really a pdf")
    with caplog.at_level(logging.DEBUG):
        meta = api.upload(bad)["meta"]
    assert meta["pages"] == "N/A"
    records = [r for r in caplog.records if "metadata" in r.getMessage().lower()]
    assert records and records[0].levelno >= logging.ERROR
    assert records[0].exc_info is not None


def test_conversion_failure_is_logged_with_traceback(api, files, caplog):
    up = api.upload(fx.text_pdf(files))
    with caplog.at_level(logging.ERROR):
        res = api.convert(up, "epub")       # known-failing path (pandoc cannot read PDF)
    assert res.status_code == 500
    assert any(r.exc_info for r in caplog.records if r.levelno >= logging.ERROR)
