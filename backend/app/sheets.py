"""Merging spreadsheets: every sheet of every workbook into one workbook.

Glossary
- book: one uploaded spreadsheet (an openpyxl Workbook).
- base book: the first book. The merge result is this book with the sheets
  of the others added after its own, so everything openpyxl keeps of a
  workbook (its sheets, names, charts) stays as it was.
- sheet title: a sheet's name. Excel wants titles unique without regard to
  case and at most 31 characters long.
- renames: {old title: new title} of one book's sheets whose titles were
  taken already; that book's formulas are rewritten to the new titles.
"""
from __future__ import annotations

from copy import copy

from openpyxl import Workbook, load_workbook
from openpyxl.formula.tokenizer import Token, Tokenizer
from openpyxl.worksheet.worksheet import Worksheet

MAX_TITLE = 31


def free_title(title: str, taken: set[str]) -> str:
    """title, or "title (n)" cut to 31 characters, not in taken (casefolded)."""
    n = 1
    candidate = title
    while candidate.casefold() in taken:
        n += 1
        suffix = f" ({n})"
        candidate = title[:MAX_TITLE - len(suffix)] + suffix
    return candidate


def _quoted(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def _renamed_ref(ref: str, renames: dict[str, str]) -> str:
    """A range operand ("Sheet1!A1", "'My sheet'!A1:B2") pointed at the new title."""
    sheet, bang, cells = ref.rpartition("!")
    if not bang:
        return ref
    bare = sheet[1:-1].replace("''", "'") if sheet.startswith("'") else sheet
    new = renames.get(bare.casefold())
    return f"{_quoted(new)}!{cells}" if new else ref


def renamed_formula(formula: str, renames: dict[str, str]) -> str:
    """formula with references to renamed sheets rewritten; text inside
    string literals is left alone. renames is keyed by casefolded title."""
    if not renames or not formula.startswith("="):
        return formula
    items = Tokenizer(formula).items
    for t in items:
        if t.type == Token.OPERAND and t.subtype == Token.RANGE:
            t.value = _renamed_ref(t.value, renames)
    return "=" + "".join(t.value for t in items)


_SERIES_SOURCES = ("tx", "cat", "val", "xVal", "yVal", "bubbleSize")
_REFS = ("numRef", "strRef", "multiLvlStrRef")


def _renamed_chart(chart, renames: dict[str, str]):
    """chart with every series' data reference pointed at renamed sheets."""
    for plot in chart._charts:            # a combined chart holds one per plot
        for series in plot.series:
            for source in filter(None, (getattr(series, a, None) for a in _SERIES_SOURCES)):
                for ref in filter(None, (getattr(source, r, None) for r in _REFS)):
                    if ref.f:
                        ref.f = renamed_formula("=" + ref.f, renames)[1:]
    return chart


def _copy_cells(src: Worksheet, dst: Worksheet, renames: dict[str, str]) -> None:
    for row in src.iter_rows():
        for cell in row:
            if cell.value is None and not cell.has_style:
                continue
            new = dst.cell(row=cell.row, column=cell.column)
            value = cell.value
            new.value = renamed_formula(value, renames) if isinstance(value, str) else value
            if cell.has_style:
                new.font, new.fill, new.border = copy(cell.font), copy(cell.fill), copy(cell.border)
                new.alignment, new.protection = copy(cell.alignment), copy(cell.protection)
                new.number_format = cell.number_format
            if cell.hyperlink:
                new.hyperlink = copy(cell.hyperlink)
            if cell.comment:
                new.comment = copy(cell.comment)


def _copy_drawings(src: Worksheet, dst: Worksheet, renames: dict[str, str]) -> None:
    for image in src._images:
        dst.add_image(image)
    for chart in src._charts:
        dst.add_chart(_renamed_chart(chart, renames))


def _copy_layout(src: Worksheet, dst: Worksheet) -> None:
    for key, dim in src.column_dimensions.items():
        d = dst.column_dimensions[key]
        d.width, d.hidden, d.outlineLevel = dim.width, dim.hidden, dim.outlineLevel
        d.min, d.max = dim.min, dim.max
    for key, dim in src.row_dimensions.items():
        d = dst.row_dimensions[key]
        d.height, d.hidden, d.outlineLevel = dim.height, dim.hidden, dim.outlineLevel
    for merged in src.merged_cells.ranges:
        dst.merge_cells(str(merged))
    dst.freeze_panes = src.freeze_panes
    dst.sheet_state = src.sheet_state
    dst.sheet_format = copy(src.sheet_format)
    dst.sheet_properties.tabColor = copy(src.sheet_properties.tabColor)
    dst.page_setup, dst.print_options = copy(src.page_setup), copy(src.print_options)
    dst.page_margins = copy(src.page_margins)
    dst.conditional_formatting = copy(src.conditional_formatting)
    for dv in src.data_validations.dataValidation:
        dst.add_data_validation(copy(dv))


def _add_book(base: Workbook, book: Workbook, taken: set[str]) -> None:
    renames: dict[str, str] = {}
    titles = []
    for ws in book.worksheets:
        title = free_title(ws.title, taken)
        taken.add(title.casefold())
        titles.append(title)
        if title != ws.title:
            renames[ws.title.casefold()] = title
    for ws, title in zip(book.worksheets, titles):
        dst = base.create_sheet(title)
        _copy_cells(ws, dst, renames)
        _copy_layout(ws, dst)
        _copy_drawings(ws, dst, renames)


def merge_workbooks(paths: list[str], out_path: str) -> None:
    """All sheets of the books at paths, in order, saved as one .xlsx."""
    base = load_workbook(paths[0])
    taken = {t.casefold() for t in base.sheetnames}
    for path in paths[1:]:
        _add_book(base, load_workbook(path), taken)
    base.save(out_path)
