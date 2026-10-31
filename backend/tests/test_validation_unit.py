"""Contract of app.validation (pure functions, no storage side effects)."""
import pytest

from app.errors import ApiError
from app.validation import (MAX_NAME_LEN, ext_from_filename, inside, parse_download_id,
                            parse_file_ids, sanitize_download_name)


@pytest.mark.parametrize("name", ["pdf", "", None, "noext"])
def test_filename_without_a_dot_has_no_extension(name):
    with pytest.raises(ApiError) as e:
        ext_from_filename(name)
    assert e.value.code.value == "UNSUPPORTED_FORMAT"
    assert e.value.status == 400


def test_extension_is_the_text_after_the_last_dot_lowercased():
    assert ext_from_filename("Archive.Tar.PDF").value == "pdf"


@pytest.mark.parametrize("name", [".", "", "a/..", "../x", "/etc/passwd"])
def test_inside_refuses_the_root_itself_and_anything_outside(tmp_path, name):
    with pytest.raises(ApiError) as e:
        inside(tmp_path, name)
    assert e.value.code.value == "INVALID_PATH"


def test_inside_accepts_a_child(tmp_path):
    assert inside(tmp_path, "x.pdf") == (tmp_path / "x.pdf").resolve()


def test_file_ids_keep_order():
    a, b = "00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"
    assert parse_file_ids(f"{b},{a}") == [b, a]


@pytest.mark.parametrize("raw", ["converted_00000000-0000-4000-8000-000000000001.exe",
                                 "merged_00000000-0000-4000-8000-00000000000Z.pdf",
                                 "converted_00000000-0000-4000-8000-000000000001.pdf.zip"])
def test_download_id_needs_known_extension_and_uuid(raw):
    with pytest.raises(ApiError):
        parse_download_id(raw)


@pytest.mark.parametrize("name", ["___", "._.", "_._", " . ", "..", "/"])
def test_names_that_are_only_filler_are_dropped(name):
    assert sanitize_download_name(name) is None


def test_a_single_underscore_name_with_letters_is_kept():
    assert sanitize_download_name("_a_") == "_a_"


def test_long_name_keeps_its_extension():
    out = sanitize_download_name("x" * 300 + ".docx")
    assert len(out) == MAX_NAME_LEN
    assert out.endswith(".docx")
    assert out == "x" * (MAX_NAME_LEN - 5) + ".docx"


def test_long_name_without_extension_is_cut():
    assert sanitize_download_name("y" * 300) == "y" * MAX_NAME_LEN


def test_long_name_with_a_huge_extension_is_cut_plainly():
    name = "a." + "b" * 300
    assert sanitize_download_name(name) == name[:MAX_NAME_LEN]


def test_name_at_the_limit_is_untouched():
    name = "z" * (MAX_NAME_LEN - 4) + ".txt"
    assert sanitize_download_name(name) == name
    one_more = "z" * (MAX_NAME_LEN - 3) + ".txt"
    assert len(sanitize_download_name(one_more)) == MAX_NAME_LEN


def test_extension_of_fifteen_chars_still_counts_as_extension():
    name = "n" * 300 + "." + "e" * 15
    out = sanitize_download_name(name)
    assert out.endswith("." + "e" * 15) and len(out) == MAX_NAME_LEN
    name16 = "n" * 300 + "." + "e" * 16
    assert sanitize_download_name(name16) == name16[:MAX_NAME_LEN]
