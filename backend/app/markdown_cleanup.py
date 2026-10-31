"""Markdown cleanup after pandoc: HTML tables to pipe tables, book footnotes, data: URIs."""
import logging
import re
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

# =====================================================

# ============ Очистка Markdown от сырого HTML после pandoc ============
# Pandoc не умеет класть в GFM-таблицу ячейку из нескольких абзацев или
# объединенные ячейки, поэтому вместо таблицы он отдает сырой <table> с
# <colgroup>, <thead>, <blockquote> и прочей разметкой. Ниже таблица
# разбирается вручную и переписывается обычной pipe-таблицей, а одиночные
# теги (<img>, <br>, <span>) превращаются в markdown или выбрасываются.

_MD_BLOCK_TAGS = ("p", "div", "blockquote", "li", "tr", "br")


class _TableCell:
    __slots__ = ("text", "colspan", "rowspan")

    def __init__(self, text, colspan=1, rowspan=1):
        self.text = text
        self.colspan = colspan
        self.rowspan = rowspan


class _TableParser(HTMLParser):
    """Собирает строки таблицы: список строк, каждая - список _TableCell."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []          # [(is_header, [cells])]
        self._row = None
        self._in_header = False
        self._cell = None       # накопитель текста текущей ячейки
        self._cell_attrs = None
        self._depth = 0         # вложенность таблиц

    # --- вспомогательное ---
    def _push_text(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def _break(self):
        if self._cell is not None and self._cell and self._cell[-1] != "\n":
            self._cell.append("\n")

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = dict(attrs)
        if tag == "table":
            self._depth += 1
            return
        if tag == "tr" and self._depth <= 1:
            self._row = []
        elif tag in ("td", "th") and self._depth <= 1:
            self._cell = []
            self._cell_attrs = attrs
        elif tag == "img":
            src = attrs.get("src", "")
            alt = attrs.get("alt", "")
            self._push_text("![%s](%s)" % (alt, src))
        elif tag in _MD_BLOCK_TAGS:
            self._break()

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "table":
            self._depth = max(0, self._depth - 1)
            return
        if tag == "thead":
            self._in_header = False
            return
        if tag in ("td", "th") and self._depth <= 1 and self._cell is not None:
            text = _flatten_cell("".join(self._cell))
            attrs = self._cell_attrs or {}
            try:
                colspan = max(1, int(attrs.get("colspan", 1)))
            except ValueError:
                colspan = 1
            try:
                rowspan = max(1, int(attrs.get("rowspan", 1)))
            except ValueError:
                rowspan = 1
            if self._row is not None:
                self._row.append(_TableCell(text, colspan, rowspan))
            self._cell = None
            self._cell_attrs = None
        elif tag == "tr" and self._depth <= 1 and self._row is not None:
            self.rows.append((self._in_header, self._row))
            self._row = None
        elif tag in _MD_BLOCK_TAGS:
            self._break()

    def handle_data(self, data):
        self._push_text(data)

    def unknown_decl(self, data):
        pass


def _flatten_cell(text):
    """Схлопывает содержимое ячейки в одну строку, пригодную для pipe-таблицы."""
    parts = [p.strip() for p in text.split("\n")]
    parts = [p for p in parts if p]
    out = " ".join(parts)
    out = re.sub(r"\s+", " ", out).strip()
    return out.replace("|", "\\|")


def _expand_grid(rows):
    """Разворачивает colspan/rowspan в прямоугольную сетку."""
    grid = []          # список списков строк
    header_flags = []
    pending = {}       # col -> (text_осталось_строк, text)
    for is_header, cells in rows:
        line = []
        col = 0
        it = iter(cells)
        while True:
            # сначала занятые вертикальным объединением колонки
            while col in pending:
                left, _txt = pending[col]
                line.append("")
                if left - 1 <= 0:
                    del pending[col]
                else:
                    pending[col] = (left - 1, _txt)
                col += 1
            try:
                cell = next(it)
            except StopIteration:
                break
            line.append(cell.text)
            for k in range(1, cell.colspan):
                line.append("")
            if cell.rowspan > 1:
                for k in range(cell.colspan):
                    pending[col + k] = (cell.rowspan - 1, cell.text)
            col += cell.colspan
        # хвост из вертикальных объединений
        while col in pending:
            left, _txt = pending[col]
            line.append("")
            if left - 1 <= 0:
                del pending[col]
            else:
                pending[col] = (left - 1, _txt)
            col += 1
        grid.append(line)
        header_flags.append(is_header)
    width = max((len(r) for r in grid), default=0)
    for r in grid:
        r.extend([""] * (width - len(r)))
    return grid, header_flags, width


def _render_pipe_table(grid, header_flags, width):
    if not grid or width == 0:
        return ""
    header_rows = [i for i, h in enumerate(header_flags) if h]
    if header_rows:
        head = grid[header_rows[0]]
        body = [r for i, r in enumerate(grid) if i != header_rows[0]]
    else:
        head = grid[0]
        body = grid[1:]
    lines = ["| " + " | ".join(head) + " |",
             "|" + "|".join(["---"] * width) + "|"]
    for r in body:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def _table_html_to_md(html):
    parser = _TableParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        logger.debug("Suppressed error in _table_html_to_md()", exc_info=True)
        return ""
    if not parser.rows:
        return ""
    grid, flags, width = _expand_grid(parser.rows)
    return _render_pipe_table(grid, flags, width)


_TABLE_RE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)
_IMG_RE = re.compile(r"<img\b[^>]*?>", re.IGNORECASE)
_SRC_RE = re.compile(r"""src\s*=\s*["']([^"']*)["']""", re.IGNORECASE)
_ALT_RE = re.compile(r"""alt\s*=\s*["']([^"']*)["']""", re.IGNORECASE)
_LEFTOVER_RE = re.compile(
    r"</?(?:colgroup|col|thead|tbody|tfoot|tr|td|th|div|span|blockquote|p|font|"
    r"section|article|figure|figcaption|center|u|nav|aside|header|footer|main)\b[^>]*>",
    re.IGNORECASE,
)


def _img_to_md(match):
    tag = match.group(0)
    src = _SRC_RE.search(tag)
    alt = _ALT_RE.search(tag)
    if not src:
        return ""
    return "![%s](%s)" % (alt.group(1) if alt else "", src.group(1))


# ---------------------------------------------------------------------------
# Ссылки и сноски из EPUB.
# В EPUB ссылка на сноску — это <a href="#ch2.xhtml#id52" class="a">[2]</a>.
# Атрибут class markdown выразить не может, поэтому pandoc (gfm) оставляет
# такую ссылку сырым HTML, а сама сноска остается обычным текстом в разделе
# «Примечания» в конце книги. Ниже ссылки превращаются в markdown-сноски
# [^2], а раздел «Примечания» — в их определения [^2]: текст.
# ---------------------------------------------------------------------------
_A_TAG_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_A_OPEN_CLOSE_RE = re.compile(r"</?a\b[^>]*>", re.IGNORECASE)
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']*)["']""", re.IGNORECASE)
_SVG_RE = re.compile(r"<svg\b.*?</svg>", re.IGNORECASE | re.DOTALL)
_SVG_IMAGE_HREF_RE = re.compile(r"""(?:xlink:)?href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)

# Текст ссылки-сноски: "2", "[2]", "\[2\]", "<sup>2</sup>", "^2^", "*"
_NOTE_LABEL = r"(?:<su[pb]>\s*)?\^?\\?\[?\s*(\d{1,4})\s*\\?\]?\^?(?:\s*</su[pb]>)?"
# HTML-вариант: <a href="#..." ...>[2]</a>
_NOTE_REF_HTML_RE = re.compile(
    r"<a\b[^>]*href\s*=\s*[\"']#[^\"']*[\"'][^>]*>\s*" + _NOTE_LABEL + r"\s*</a>",
    re.IGNORECASE,
)
# Markdown-вариант (если у ссылки не было class): [\[2\]](#ch2.xhtml#id52)
_NOTE_REF_MD_RE = re.compile(r"\[\s*" + _NOTE_LABEL + r"\s*\]\(#[^)\s]*\)", re.IGNORECASE)

_NOTES_HEADING_RE = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*)?[*_]*[ \t]*"
    r"(?:примечания(?:[ \t]+(?:переводчика|редактора|автора))?|сноски|комментарии|"
    r"notes|footnotes|endnotes)"
    r"[ \t]*[*_]*[ \t]*:?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
# Конец раздела примечаний: следующий markdown-заголовок или разделитель.
_SECTION_END_RE = re.compile(r"^(?:#{1,6}[ \t]+\S|-{3,}[ \t]*$|\*{3,}[ \t]*$)", re.MULTILINE)
_NOTE_NUM_ONLY_RE = re.compile(r"^\\?\[?(\d{1,4})\\?\]?\.?$")
_NOTE_NUM_TEXT_RE = re.compile(r"^\\?\[?(\d{1,4})\\?\]?[.)]?[ \t]+(\S.*)$", re.DOTALL)


def _strip_anchor_tags(text: str) -> str:
    return _A_OPEN_CLOSE_RE.sub("", text)


def _parse_notes_body(body: str):
    """Разбирает текст раздела «Примечания» в словарь {номер: [абзацы]}.

    Понимает оба типичных варианта вёрстки:
        2                         2. Текст сноски
                                  3. Текст сноски
        Текст сноски
    Возвращает None, если раздел не похож на список сносок.
    """
    notes = {}
    order = []
    cur = None
    for para in re.split(r"\n[ \t\u00a0]*\n", _strip_anchor_tags(body)):
        p = para.replace("\u00a0", " ").strip()
        if not p:
            continue
        m = _NOTE_NUM_ONLY_RE.match(p)
        if m and (cur is None or int(m.group(1)) > cur):
            cur = int(m.group(1))
            notes[cur] = []
            order.append(cur)
            continue
        m = _NOTE_NUM_TEXT_RE.match(p)
        if m and (cur is None or int(m.group(1)) == cur + 1):
            cur = int(m.group(1))
            notes[cur] = [m.group(2).strip()]
            order.append(cur)
            continue
        if cur is None:
            return None          # раздел начинается не со сноски
        notes[cur].append(p)
    notes = {n: paras for n, paras in notes.items() if paras}
    return (notes, order) if notes else None


def _format_note_definition(label: str, paras) -> str:
    first, rest = paras[0], paras[1:]
    out = ["[^%s]: %s" % (label, first.replace("\n", " "))]
    for p in rest:
        out.append("\n".join("    " + line for line in p.splitlines()))
    return "\n\n".join(out)


def convert_book_footnotes(text: str, label_prefix: str = "") -> str:
    """Превращает ссылки-сноски EPUB в markdown-сноски [^N] и раздел
    «Примечания» — в определения сносок. Если раздел не найден, ссылки
    остаются обычным текстом [N] без HTML-разметки."""
    if not text:
        return text

    # 1. Находим все разделы примечаний (у книги может быть по разделу на главу).
    sections = []   # (start, end, heading_text, notes, order)
    pos = 0
    while True:
        m = _NOTES_HEADING_RE.search(text, pos)
        if not m:
            break
        body_start = m.end()
        end_m = _SECTION_END_RE.search(text, body_start)
        next_h = _NOTES_HEADING_RE.search(text, body_start)
        end = len(text)
        if end_m:
            end = end_m.start()
        if next_h and next_h.start() < end:
            end = next_h.start()
        parsed = _parse_notes_body(text[body_start:end])
        if parsed:
            sections.append((m.start(), end, m.group(0).strip(), parsed[0], parsed[1]))
            pos = end
        else:
            pos = body_start

    multi = len(sections) > 1

    def make_label(sec_idx, num):
        return "%s%s%d" % (label_prefix, ("%d-" % (sec_idx + 1)) if multi else "", num)

    def replace_refs(segment, sec_idx):
        notes = sections[sec_idx][3] if sec_idx is not None else {}

        def repl(m):
            num = int(m.group(1))
            if num in notes:
                return "[^%s]" % make_label(sec_idx, num)
            return "[%d]" % num
        segment = _NOTE_REF_HTML_RE.sub(repl, segment)
        segment = _NOTE_REF_MD_RE.sub(repl, segment)
        return segment

    # 2. Ссылки до раздела k относятся к разделу k.
    out = []
    prev = 0
    for idx, (start, end, heading, notes, order) in enumerate(sections):
        out.append(replace_refs(text[prev:start], idx))
        defs = [_format_note_definition(make_label(idx, n), notes[n]) for n in order if n in notes]
        out.append(heading + "\n\n" + "\n\n".join(defs) + "\n\n")
        prev = end
    out.append(replace_refs(text[prev:], None))
    return "".join(out)


def _svg_to_md(match):
    """Обложка в EPUB часто обернута в <svg><image xlink:href=...></svg>."""
    href = _SVG_IMAGE_HREF_RE.search(match.group(0))
    return "![](%s)" % href.group(1) if href else ""


def _a_to_md(match):
    """Оставшиеся <a ...>текст</a>: внешние ссылки -> [текст](url),
    внутренние ссылки EPUB (#ch2.xhtml#id52) и якоря -> просто текст."""
    attrs, inner = match.group(1), match.group(2)
    inner_text = inner.strip()
    href = _HREF_RE.search(attrs)
    if href and re.match(r"(?:https?|ftp|mailto):", href.group(1), re.IGNORECASE) and inner_text:
        return "[%s](%s)" % (inner_text, href.group(1))
    return inner


def clean_markdown_html(text: str) -> str:
    """Убирает из markdown сырой HTML, оставленный pandoc."""
    if not text or "<" not in text:
        return text

    # 0. Скрытая навигация EPUB3 (landmarks, page-list) — служебная,
    #    в книге ее не видно; <cite> -> курсив.
    text = re.sub(r"<nav\b[^>]*\bhidden\b[^>]*>.*?</nav>", "", text,
                  flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<cite\b[^>]*>(.*?)</cite>", r"*\1*", text,
                  flags=re.IGNORECASE | re.DOTALL)

    # 1. Таблицы -> pipe-таблицы. Блок таблицы у pandoc может быть
    #    процитирован ("> <table>"), поэтому сначала снимаем цитирование.
    def _table_repl(m):
        block = m.group(0)
        unquoted = re.sub(r"(?m)^\s*>\s?", "", block)
        md = _table_html_to_md(unquoted)
        return "\n\n" + md + "\n\n" if md else ""

    text = _TABLE_RE.sub(_table_repl, text)

    # 2. Картинки -> markdown-синтаксис. SVG-обертка обложки -> картинка,
    #    дубль (pandoc обычно уже вывел ту же картинку строкой выше) убираем.
    text = _IMG_RE.sub(_img_to_md, text)
    text = _SVG_RE.sub(_svg_to_md, text)
    text = re.sub(r"(!\[[^\]]*\]\([^)]+\))(\s*\n\s*\1)+", r"\1", text)

    # 2a. Ссылки <a href="#ch2.xhtml#id52" class="a">[2]</a> и прочие <a>.
    text = _A_TAG_RE.sub(_a_to_md, text)
    text = _A_OPEN_CLOSE_RE.sub("", text)

    # 3. Переводы строк и оставшиеся служебные теги.
    text = re.sub(r"<br\s*/?>", "  \n", text, flags=re.IGNORECASE)
    text = _LEFTOVER_RE.sub("", text)

    # 4. Лишние пустые строки.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


# Адрес data:-URI в markdown: (data:...) или (<data:...>), с необязательным "title".
_MD_DATA_DEST = r"\(\s*(?:<data:[^>\n]*>|data:[^\s)]*)(?:\s+\"[^\"\n]*\")?\s*\)"
_MD_DATA_IMAGE_RE = re.compile(r"!\[(?:[^\]\\\n]|\\.)*\]" + _MD_DATA_DEST, re.IGNORECASE)
_MD_DATA_LINK_RE = re.compile(r"\[((?:[^\]\\\n]|\\.)*)\]" + _MD_DATA_DEST, re.IGNORECASE)
_MD_DATA_REFDEF_RE = re.compile(r"^[ ]{0,3}\[[^\]\n]+\]:[ \t]*<?data:[^\n]*(?:\n|$)",
                                re.IGNORECASE | re.MULTILINE)
# Ссылка без текста [](url) — остается от ссылок-иконок, на экране ее не видно.
_MD_EMPTY_LINK_RE = re.compile(r"(?<![!\]\\])\[\]\([^)\s]*\)")
# Код не трогаем: блок ```/~~~, строка с отступом 4 пробела (pandoc пишет
# блоки кода без языка именно так) и `код в строке`.
_MD_CODE_RE = re.compile(
    r"^[ ]{0,3}(`{3,}|~{3,})[^\n]*\n.*?^[ ]{0,3}\1[`~]*[ \t]*$"
    r"|^(?:[ ]{4}|\t)[^\n]*$"
    r"|(`+)[^\n]+?\2",
    re.MULTILINE | re.DOTALL,
)


def strip_markdown_data_uris(text: str) -> str:
    """Убирает из markdown встроенные data:-URI (base64-картинки) и пустые
    ссылки. Текст ссылок сохраняется, код не трогается."""
    if not text:
        return text

    def clean(chunk):
        chunk = _MD_DATA_IMAGE_RE.sub("", chunk)
        chunk = _MD_DATA_LINK_RE.sub(r"\1", chunk)
        chunk = _MD_DATA_REFDEF_RE.sub("", chunk)
        chunk = _MD_EMPTY_LINK_RE.sub("", chunk)
        # На месте удаленных картинок остаются пустые строки.
        return re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", chunk)

    out, pos = [], 0
    for m in _MD_CODE_RE.finditer(text):
        out.append(clean(text[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(clean(text[pos:]))
    return "".join(out).strip() + "\n"
