"""XLSX to XLS: an Excel 2007+ workbook saved as an Excel 97-2003 one,
every sheet with its values, formulas and look, through LibreOffice."""
import fixtures as fx
from conftest import needs_libreoffice
from test_merge_sheets import values, xls_book

pytestmark = needs_libreoffice

OLE = bytes.fromhex("D0CF11E0A1B11AE1")        # the header of a real .xls


def test_xlsx_to_xls_gives_an_xls_with_every_sheet(api, files):
    book = fx.workbook(files, "book.xlsx", {"Sales": [["Month", "Sum"], ["Jan", 10], ["Feb", 32]],
                                            "Total": [["=SUM(Sales!B2:B3)"]]})
    body, data = api.roundtrip(book, "xls")
    assert data[:8] == OLE and body["warnings"] == []
    result = xls_book(data, files)
    assert result.sheetnames == ["Sales", "Total"]
    assert values(result["Sales"]) == [["Month", "Sum"], ["Jan", 10], ["Feb", 32]]
    assert result["Total"]["A1"].value == "=SUM(Sales!B2:B3)"


def test_xlsx_to_xls_keeps_the_look(api, files):
    _, data = api.roundtrip(fx.styled_workbook(files), "xls")
    ws = xls_book(data, files)["Report"]
    assert ws["A2"].font.bold and ws["A2"].font.color.rgb == "FFFF0000"
    assert ws["A2"].fill.fgColor.rgb == "FFFFFF00"
    # LibreOffice writes the same format as #,##0.00" UAH": either shows 12.50 UAH
    assert ws["B3"].number_format.replace('"', "") == "#,##0.00 UAH" and ws["B3"].value == 12.5
    assert [str(r) for r in ws.merged_cells.ranges] == ["A1:C1"]
    assert round(ws.column_dimensions["A"].width) == 30 and ws.column_dimensions["C"].hidden   # 29.99 in XLS units
    assert ws.sheet_properties.tabColor.rgb == "FF00B050"
    assert ws["A3"].hyperlink.target == "https://example.com/tea" and ws["A3"].comment.text == "Green tea"
    assert len(ws._images) == 1 and ws.parent["Notes"].sheet_state == "hidden"


def test_frozen_panes_lost_in_xls_are_reported(api, files):
    """LibreOffice writes no frozen panes into .xls; the user is told which
    sheets had them, instead of finding the header scrolling away."""
    body, data = api.roundtrip(fx.styled_workbook(files), "xls")
    assert xls_book(data, files)["Report"].freeze_panes is None       # if this fails, LibreOffice learnt it
    assert body["warnings"] == ["Закріплені області не збережено (XLS з LibreOffice їх не містить): Report"]


def test_xlsx_to_xls_leaves_no_temporary_files(api, files, server_dir):
    before = set((server_dir / "storage" / "outputs").iterdir())
    body = api.convert_ok(api.upload(fx.workbook(files, "b.xlsx", {"S": [[1]]})), "xls")
    after = set((server_dir / "storage" / "outputs").iterdir())
    assert {p.name for p in after - before} == {body["download_id"]}
