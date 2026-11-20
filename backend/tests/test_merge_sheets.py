"""Merge XLSX / Merge XLS: every sheet of every spreadsheet ends up in one
file, in the order the files were given, each sheet as it was."""
import io

import fixtures as fx
from conftest import needs_libreoffice
from openpyxl import load_workbook
from test_merge import merged


def book_of(data: bytes):
    return load_workbook(io.BytesIO(data))


def values(ws) -> list[list]:
    return [list(r) for r in ws.iter_rows(values_only=True)]


def test_merge_xlsx_keeps_every_sheet_in_order(api, files):
    first = fx.workbook(files, "a.xlsx", {"Sales": [["Month", "Sum"], ["Jan", 10]], "Costs": [["Rent", 5]]})
    second = fx.workbook(files, "b.xlsx", {"Staff": [["Name"], ["Olena"]]})
    body, data = merged(api, [api.upload(first), api.upload(second)], "xlsx")
    book = book_of(data)
    assert book.sheetnames == ["Sales", "Costs", "Staff"]
    assert values(book["Sales"]) == [["Month", "Sum"], ["Jan", 10]]
    assert values(book["Costs"]) == [["Rent", 5]]
    assert values(book["Staff"]) == [["Name"], ["Olena"]]
    assert body["warnings"] == []


def test_sheets_with_the_same_name_both_stay_and_formulas_follow_theirs(api, files):
    """Excel needs unique sheet names (case does not count): the later sheet
    is renamed, and a formula of its own file still reads its own sheet."""
    first = fx.workbook(files, "a.xlsx", {"Sheet1": [[1]], "Total": [["=Sheet1!A1*2"]]})
    second = fx.workbook(files, "b.xlsx", {"SHEET1": [[7]], "Total": [["=SHEET1!A1+'SHEET1'!A1"]]})
    _, data = merged(api, [api.upload(first), api.upload(second)], "xlsx")
    book = book_of(data)
    assert book.sheetnames == ["Sheet1", "Total", "SHEET1 (2)", "Total (2)"]
    assert book["Total"]["A1"].value == "=Sheet1!A1*2"
    assert book["Total (2)"]["A1"].value == "='SHEET1 (2)'!A1+'SHEET1 (2)'!A1"
    assert book["SHEET1 (2)"]["A1"].value == 7


def test_a_renamed_sheet_fits_excels_31_characters(api, files):
    long = "Quarterly revenue by region 2026"[:31]
    first = fx.workbook(files, "a.xlsx", {long: [[1]]})
    second = fx.workbook(files, "b.xlsx", {long: [[2]]})
    _, data = merged(api, [api.upload(first), api.upload(second)], "xlsx")
    names = book_of(data).sheetnames
    assert names[0] == long and len(names[1]) <= 31 and names[1].endswith(" (2)")


def test_a_merged_sheet_keeps_its_look(api, files):
    """The sheet from the second file, copied into the first, keeps its fonts,
    fills, number formats, widths, heights, merged cells and frozen panes."""
    first = fx.workbook(files, "a.xlsx", {"Intro": [["hello"]]})
    _, data = merged(api, [api.upload(first), api.upload(fx.styled_workbook(files))], "xlsx")
    ws = book_of(data)["Report"]
    head = ws["A2"]
    assert head.font.bold and head.font.color.rgb == "FFFF0000"
    assert head.fill.fgColor.rgb == "FFFFFF00"
    assert ws["B3"].number_format == '#,##0.00 "UAH"' and ws["B3"].value == 12.5
    assert ws.column_dimensions["A"].width == 30
    assert ws.column_dimensions["C"].hidden
    assert ws.row_dimensions[2].height == 40
    assert [str(r) for r in ws.merged_cells.ranges] == ["A1:C1"]
    assert ws.freeze_panes == "A3"
    assert ws.sheet_properties.tabColor.rgb == "FF00B050"


def test_a_chart_comes_along_and_still_draws_its_own_sheet(api, files):
    first = fx.workbook(files, "a.xlsx", {"Sheet1": [[100], [200], [300]]})
    _, data = merged(api, [api.upload(first), api.upload(fx.chart_workbook(files))], "xlsx")
    book = book_of(data)
    charts = book["Sheet1 (2)"]._charts
    assert len(charts) == 1 and book["Sheet1"]._charts == []
    assert charts[0].series[0].val.numRef.f == "'Sheet1 (2)'!$A$1:$A$3"


def as_xls(path):
    """The same workbook saved by LibreOffice as Excel 97-2003 (.xls)."""
    from app.engines import engine_libreoffice
    return type(path)(engine_libreoffice(str(path), str(path.parent), "xls"))


def xls_book(data: bytes, files):
    from app.engines import engine_libreoffice
    xls = files / "result.xls"
    xls.write_bytes(data)
    return load_workbook(engine_libreoffice(str(xls), str(files), "xlsx"))


@needs_libreoffice
def test_merge_xls_gives_one_xls_with_every_sheet(api, files):
    first = as_xls(fx.workbook(files, "a.xlsx", {"Sales": [["Jan", 10]], "Data": [[1]]}))
    second = as_xls(fx.workbook(files, "b.xlsx", {"Data": [[2]], "Sum": [["=Data!A1*3"]]}))
    _, data = merged(api, [api.upload(first), api.upload(second)], "xls")
    assert data[:8] == bytes.fromhex("D0CF11E0A1B11AE1")        # Excel 97-2003, not xlsx renamed
    book = xls_book(data, files)
    assert book.sheetnames == ["Sales", "Data", "Data (2)", "Sum"]
    assert values(book["Sales"]) == [["Jan", 10]]
    assert book["Data (2)"]["A1"].value == 2
    assert book["Sum"]["A1"].value == "='Data (2)'!A1*3"
