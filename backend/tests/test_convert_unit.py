"""Small helpers of app.convert."""


def test_remove_tolerates_missing_and_none(app, tmp_path):
    from app.convert import _remove
    _remove(None)
    _remove(str(tmp_path / "missing.txt"))
    f = tmp_path / "x.txt"
    f.write_text("x")
    _remove(str(f))
    assert not f.exists()
