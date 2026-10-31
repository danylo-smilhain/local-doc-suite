"""GET /api/download/{id}: serves a converted file under the requested name."""
import fixtures as fx
from conftest import needs_pandoc


@needs_pandoc
def test_download_uses_name_parameter(api, files):
    body = api.convert_ok(api.upload(fx.docx(files)), "txt")
    res = api.download(body["download_id"], name="My File.txt")
    assert res.status_code == 200
    assert "My%20File.txt" in res.headers["content-disposition"] or "My File.txt" in res.headers["content-disposition"]
    assert fx.DOCX_TEXT in res.content.decode("utf-8")


@needs_pandoc
def test_download_default_name(api, files):
    body = api.convert_ok(api.upload(fx.docx(files)), "txt")
    res = api.download(body["download_id"])
    assert f"LocalSuite_{body['download_id']}" in res.headers["content-disposition"]


def test_convert_unknown_file_id_is_404(client):
    res = client.post("/api/convert", data={
        "file_id": "00000000-0000-4000-8000-000000000000", "source_ext": "pdf", "target_format": "txt"})
    assert res.status_code == 404
