"""TXT -> MD: encoding detection and structure detection."""
import pytest

import fixtures as fx
from conftest import docx_text, is_docx, needs_pandoc


RUSSIAN = ("Привет, мир! Это проверка кодировки текста для конвертера.\n"
           "Он должен определить кодировку и сохранить все буквы правильно.\n")


@pytest.mark.parametrize("encoding,text,reported", [
    ("cp1251", fx.CYRILLIC_TEXT, "cp1251"),
    ("koi8-u", fx.CYRILLIC_TEXT, "koi8-u"),
    ("utf-16", fx.CYRILLIC_TEXT, "utf-16"),
    ("cp866", RUSSIAN, "cp866"),
])
def test_legacy_encodings_are_decoded_and_reported(api, files, encoding, text, reported):
    body, data = api.roundtrip(fx.txt(files, text=text, encoding=encoding), "md")
    assert body["source_encoding"] == reported
    out = data.decode("utf-8")
    first_line = text.splitlines()[0]
    assert first_line.split()[0] in out
    assert "кодир" in out or "кодув" in out


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_utf8_is_not_reported(api, files, encoding):
    body, data = api.roundtrip(fx.txt(files, encoding=encoding), "md")
    assert "source_encoding" not in body
    assert data.decode("utf-8").lstrip("﻿").startswith("Привіт")


def test_txt_to_md_detects_heading_and_list(api, files):
    _, data = api.roundtrip(fx.txt_document(files), "md")
    text = data.decode("utf-8")
    assert "# INTRODUCTION" in text or "## INTRODUCTION" in text
    assert "- first item" in text


@needs_pandoc
def test_txt_to_docx_goes_through_markdown(api, files):
    body, data = api.roundtrip(fx.txt(files, encoding="cp1251"), "docx")
    assert body["source_encoding"] == "cp1251"
    assert is_docx(data)
    assert "Привіт" in docx_text(data)


def test_txt_smart_false_keeps_lines_verbatim_but_escaped(api, files):
    _, data = api.roundtrip(fx.txt_document(files), "md", txt_smart="false")
    text = data.decode("utf-8")
    assert "# INTRODUCTION" not in text
    assert "INTRODUCTION" in text
    assert "\\- first item" in text          # list markers are escaped, not rendered
