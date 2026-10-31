"""EPUB -> DOCX laid out from the book's own CSS, and EPUB -> PDF."""
import io
import logging
import os
import re
import shutil
import uuid
import zipfile

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from PIL import Image

from app.config import OUTPUT_DIR
from app.ebooks.book_format import _set_style_font, format_book_docx
from app.engines import engine_libreoffice, engine_pandoc

logger = logging.getLogger(__name__)

# =====================================================

# ============== EPUB -> DOCX С СОХРАНЕНИЕМ ВЕРСТКИ ==============
# Pandoc при чтении EPUB выбрасывает CSS: классы абзацев (.title, .title2,
# .p1, .empty-line, .epigraph ...) теряются, заголовки превращаются в обычный
# текст 14 pt, а разрывы страниц между главами (каждый XHTML-файл spine в
# читалке начинается с новой страницы) пропадают. Отсюда «съехавший»
# титульный лист, заголовки без жирного и меньшее число страниц.
# Ниже EPUB разбирается напрямую: spine по порядку, CSS книги применяется к
# каждому элементу (размер, жирность, курсив, выравнивание, отступы, поля,
# page-break-*), и из этого собирается DOCX для LibreOffice.

EPUB_PAGE = (21.0, 29.7)               # A4, см
EPUB_MARGINS = (2.0, 1.75, 2.5, 2.5)   # top, bottom, left, right, см
EPUB_FONT = "Times New Roman"
EPUB_BASE_PT = 14.0                    # 1em
EPUB_LINE_HEIGHT = 1.2                 # line-height: normal
EPUB_SPINE_PAGE_BREAKS = True          # каждый файл spine с новой страницы
EPUB_FRONT_TITLE_PAGE = True           # титульный лист из метаданных OPF
EPUB_FRONT_ANNOTATION = True           # аннотация (dc:description) отдельной страницей
EPUB_HEADING_BREAK_LEVEL = 9           # заголовки до этого уровня — с новой страницы

_OPF_NS = {"opf": "http://www.idpf.org/2007/opf",
           "dc": "http://purl.org/dc/elements/1.1/",
           "c": "urn:oasis:names:tc:opendocument:xmlns:container"}

_BLOCK_TAGS = {
    "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "section",
    "article", "aside", "header", "footer", "nav", "main", "figure",
    "figcaption", "ul", "ol", "li", "dl", "dt", "dd", "pre", "center",
    "address", "table", "tr", "td", "th", "tbody", "thead", "tfoot",
    "caption", "hr", "body", "html", "poem", "stanza", "v",
}
_SKIP_TAGS = {"head", "script", "style", "title", "meta", "link", "noscript"}

# Встроенные стили браузера (то, что читалка применяет без CSS книги)
_UA_CSS = """
h1 { font-size: 2em; font-weight: bold; margin: 0.67em 0; page-break-after: avoid; }
h2 { font-size: 1.5em; font-weight: bold; margin: 0.83em 0; page-break-after: avoid; }
h3 { font-size: 1.17em; font-weight: bold; margin: 1em 0; page-break-after: avoid; }
h4 { font-size: 1em; font-weight: bold; margin: 1.33em 0; page-break-after: avoid; }
h5 { font-size: 0.83em; font-weight: bold; margin: 1.67em 0; page-break-after: avoid; }
h6 { font-size: 0.67em; font-weight: bold; margin: 2.33em 0; page-break-after: avoid; }
p { margin: 1em 0; }
blockquote { margin: 1em 40px; }
figure { margin: 1em 40px; }
ul, ol { margin: 1em 0; padding-left: 40px; }
dd { margin-left: 40px; }
pre { margin: 1em 0; white-space: pre; }
center { text-align: center; }
b, strong, th { font-weight: bold; }
i, em, cite, var, dfn { font-style: italic; }
u, ins { text-decoration: underline; }
s, strike, del { text-decoration: line-through; }
sup { vertical-align: super; font-size: smaller; }
sub { vertical-align: sub; font-size: smaller; }
small { font-size: smaller; }
big { font-size: larger; }
code, kbd, samp, tt { font-family: monospace; }
"""

_CSS_INHERITED = {"font-size", "font-weight", "font-style", "text-align",
                  "text-indent", "line-height", "font-variant",
                  "text-transform", "white-space", "font-family"}

_FONT_KEYWORDS = {"xx-small": 0.6, "x-small": 0.75, "small": 0.89,
                  "medium": 1.0, "large": 1.2, "x-large": 1.5,
                  "xx-large": 2.0, "xxx-large": 3.0}


def _local(tag):
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def _parse_css(text, order_base=0):
    """Простой разбор CSS: правила верхнего уровня, @media/@font-face
    пропускаются. Возвращает [(selector_parts, specificity, order, decls)]."""
    text = re.sub(r"/\*.*?\*/", "", text or "", flags=re.S)
    rules = []
    i, n, order = 0, len(text), order_base
    while i < n:
        brace = text.find("{", i)
        if brace < 0:
            break
        head = text[i:brace].strip()
        depth, j = 1, brace + 1
        while j < n and depth:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        body = text[brace + 1:j - 1]
        i = j
        if not head or head.startswith("@"):
            continue
        decls = {}
        for decl in body.split(";"):
            if ":" not in decl:
                continue
            k, v = decl.split(":", 1)
            v = v.replace("!important", "").strip()
            decls[k.strip().lower()] = v
        decls = _expand_shorthands(decls)
        for sel in head.split(","):
            sel = sel.strip()
            if not sel or re.search(r"::?[a-z-]+", sel):
                continue  # псевдоклассы/псевдоэлементы не поддерживаем
            parts = [p for p in re.split(r"\s*>\s*|\s+", sel) if p]
            spec = 0
            for p in parts:
                spec += 100 * p.count("#") + 10 * (p.count(".") + p.count("["))
                if re.match(r"^[a-zA-Z]", p):
                    spec += 1
            order += 1
            rules.append((parts, spec, order, decls))
    return rules


def _expand_shorthands(decls):
    out = dict(decls)
    for prop in ("margin", "padding"):
        if prop in decls:
            vals = decls[prop].split()
            if len(vals) == 1:
                vals = vals * 4
            elif len(vals) == 2:
                vals = [vals[0], vals[1], vals[0], vals[1]]
            elif len(vals) == 3:
                vals = [vals[0], vals[1], vals[2], vals[1]]
            for side, v in zip(("top", "right", "bottom", "left"), vals[:4]):
                out.setdefault(f"{prop}-{side}", v)
                out[f"{prop}-{side}"] = v
    if "font" in decls:
        v = decls["font"]
        if "bold" in v:
            out.setdefault("font-weight", "bold")
        if "italic" in v:
            out.setdefault("font-style", "italic")
        m = re.search(r"([\d.]+(?:em|pt|px|%|rem))", v)
        if m:
            out.setdefault("font-size", m.group(1))
    for k in ("break-before", "break-after"):
        if k in decls:
            out.setdefault("page-" + k, "always" if decls[k] in ("page", "always", "left", "right") else decls[k])
    if "text-decoration-line" in decls:
        out.setdefault("text-decoration", decls["text-decoration-line"])
    return out


def _simple_match(el, part):
    if part == "*":
        return True
    m = re.match(r"^([a-zA-Z][\w-]*|\*)?((?:[.#][\w-]+|\[[^\]]*\])*)$", part)
    if not m:
        return False
    tag, rest = m.group(1), m.group(2) or ""
    if tag and tag != "*" and _local(el.tag) != tag.lower():
        return False
    classes = (el.get("class") or "").split()
    for kind, name in re.findall(r"([.#])([\w-]+)", rest):
        if kind == "." and name not in classes:
            return False
        if kind == "#" and el.get("id") != name:
            return False
    for attr in re.findall(r"\[([^\]=~|^$*]+)", rest):
        if el.get(attr.strip()) is None:
            return False
    return True


def _selector_match(el, parts):
    if not _simple_match(el, parts[-1]):
        return False
    anc = el.getparent()
    for part in reversed(parts[:-1]):
        while anc is not None and not _simple_match(anc, part):
            anc = anc.getparent()
        if anc is None:
            return False
        anc = anc.getparent()
    return True


def _css_len(value, font_pt, base_pt=EPUB_BASE_PT, percent_of=None):
    """CSS-длина -> pt. em/% считаются от font_pt (или percent_of)."""
    if value is None:
        return None
    v = str(value).strip().lower()
    if v in ("0", "auto", "none", "normal", "inherit", "initial", ""):
        return 0.0
    m = re.match(r"^(-?[\d.]+)\s*([a-z%]*)$", v)
    if not m:
        return 0.0
    try:
        num = float(m.group(1))
    except ValueError:
        return 0.0
    unit = m.group(2)
    if unit == "em":
        return num * font_pt
    if unit == "rem":
        return num * base_pt
    if unit == "ex":
        return num * font_pt * 0.5
    if unit == "%":
        return num / 100.0 * (percent_of if percent_of is not None else font_pt)
    if unit == "px":
        return num * 0.75
    if unit == "pt":
        return num
    if unit == "pc":
        return num * 12
    if unit == "cm":
        return num * 28.3465
    if unit == "mm":
        return num * 2.83465
    if unit == "in":
        return num * 72
    if unit == "":
        return num * 0.75 if num else 0.0
    return 0.0


class _EpubStyler:
    """Вычисляет стили элементов: UA-стили < CSS книги < style=''."""

    def __init__(self, css_texts, content_width_pt):
        self.rules = _parse_css(_UA_CSS, 0)
        self.ua_count = len(self.rules)
        order = 10000
        for t in css_texts:
            r = _parse_css(t, order)
            order += len(r) + 1
            self.rules.extend(r)
        self.content_width = content_width_pt
        self.cache = {}

    def declared(self, el):
        matched = []
        for idx, (parts, spec, order, decls) in enumerate(self.rules):
            if _selector_match(el, parts):
                author = 1 if idx >= self.ua_count else 0
                matched.append(((author, spec, order), decls))
        matched.sort(key=lambda x: x[0])
        out = {}
        for _, decls in matched:
            out.update(decls)
        inline = el.get("style")
        if inline:
            d = {}
            for decl in inline.split(";"):
                if ":" in decl:
                    k, v = decl.split(":", 1)
                    d[k.strip().lower()] = v.replace("!important", "").strip()
            out.update(_expand_shorthands(d))
        # Атрибуты старого HTML
        if el.get("align") and "text-align" not in out:
            out["text-align"] = el.get("align").lower()
        return out

    def computed(self, el, parent_cs):
        key = el  # не id(el): lxml переиспользует прокси-объекты и их id
        if key in self.cache:
            return self.cache[key]
        decl = self.declared(el)
        cs = {k: parent_cs[k] for k in _CSS_INHERITED if k in parent_cs}
        parent_fs = parent_cs.get("font-size", EPUB_BASE_PT)
        fs = parent_fs
        if "font-size" in decl:
            v = decl["font-size"].strip().lower()
            if v in _FONT_KEYWORDS:
                fs = EPUB_BASE_PT * _FONT_KEYWORDS[v]
            elif v == "smaller":
                fs = parent_fs * 0.83
            elif v == "larger":
                fs = parent_fs * 1.2
            else:
                val = _css_len(v, parent_fs, percent_of=parent_fs)
                if val and val > 0:
                    fs = val
        cs["font-size"] = fs
        for k, v in decl.items():
            if k == "font-size":
                continue
            val = v.strip().lower() if k != "font-family" else v
            if val == "inherit":
                # text-align: inherit и т.п. — берем значение родителя
                if k in parent_cs:
                    cs[k] = parent_cs[k]
                else:
                    cs.pop(k, None)
                continue
            if val in ("initial", "unset"):
                cs.pop(k, None)
                continue
            cs[k] = val
        # Ненаследуемые свойства, которых нет в объявлении, сбрасываем
        for k in ("vertical-align", "text-decoration"):
            if k not in decl and k in cs:
                del cs[k]
        self.cache[key] = cs
        return cs


def _epub_open(path):
    """Читает EPUB: метаданные, spine, CSS, обложку."""
    from lxml import etree
    zf = zipfile.ZipFile(path)
    names = set(zf.namelist())

    def read(name):
        return zf.read(name) if name in names else None

    container = read("META-INF/container.xml")
    opf_path = None
    if container:
        croot = etree.fromstring(container)
        rf = croot.find(".//c:rootfile", _OPF_NS)
        if rf is not None:
            opf_path = rf.get("full-path")
    if not opf_path:
        opf_path = next((n for n in names if n.lower().endswith(".opf")), None)
    if not opf_path:
        raise RuntimeError("EPUB: OPF file not found")
    base = os.path.dirname(opf_path)
    opf = etree.fromstring(zf.read(opf_path))

    def full(href):
        from urllib.parse import unquote
        href = unquote(href.split("#", 1)[0])
        return os.path.normpath(os.path.join(base, href)).replace("\\", "/") if base else os.path.normpath(href).replace("\\", "/")

    meta = {}
    md = opf.find("opf:metadata", _OPF_NS)
    if md is None:
        md = opf.find(".//{*}metadata")
    if md is not None:
        for key in ("title", "creator", "publisher", "date", "description", "language"):
            vals = [(e.text or "").strip() for e in md.findall(f"dc:{key}", _OPF_NS) if (e.text or "").strip()]
            if vals:
                meta[key] = vals

    manifest = {}
    cover_href = None
    cover_id = None
    if md is not None:
        for m in md.findall("opf:meta", _OPF_NS) + md.findall("{*}meta"):
            if m.get("name") == "cover":
                cover_id = m.get("content")
    for item in opf.iter("{*}item"):
        manifest[item.get("id")] = (full(item.get("href", "")), item.get("media-type", ""))
        if "cover-image" in (item.get("properties") or ""):
            cover_href = full(item.get("href", ""))
    if not cover_href and cover_id in manifest:
        cover_href = manifest[cover_id][0]
    if cover_href and not cover_href.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")):
        cover_href = None

    spine = []
    for ref in opf.iter("{*}itemref"):
        if (ref.get("linear") or "yes").lower() == "no":
            continue
        it = manifest.get(ref.get("idref"))
        if it and ("html" in it[1] or it[0].lower().endswith((".xhtml", ".html", ".htm"))):
            spine.append(it[0])
    return zf, names, meta, spine, cover_href


def _parse_xhtml(data):
    import html.entities as ents

    from lxml import etree
    from lxml import html as lhtml

    def ent(m):
        name = m.group(1)
        if name in ("amp", "lt", "gt", "quot", "apos"):
            return m.group(0)
        cp = ents.name2codepoint.get(name)
        return chr(cp) if cp else m.group(0)

    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    text = re.sub(r"^﻿", "", text)
    text = re.sub(r"&([a-zA-Z][a-zA-Z0-9]*);", ent, text)
    try:
        parser = etree.XMLParser(recover=True, resolve_entities=False, huge_tree=True)
        root = etree.fromstring(text.encode("utf-8"), parser)
        if root is not None and _local(root.tag) == "html":
            return root
    except (etree.LxmlError, ValueError, TypeError):
        logger.debug("XHTML is not well-formed, falling back to the HTML parser", exc_info=True)
    return lhtml.fromstring(text.encode("utf-8"))


def _image_size_px(blob):
    try:
        with Image.open(io.BytesIO(blob)) as im:
            return im.size
    except Exception:
        logger.debug("Suppressed error in _image_size_px()", exc_info=True)
        return None


class _EpubDocxBuilder:
    def __init__(self, doc, styler, content_w, content_h, lang):
        self.doc = doc
        self.styler = styler
        self.cw = content_w
        self.ch = content_h
        self.lang = lang
        self.para = None
        self.para_cs = None
        self.pending_space = 0.0
        self.pending_break = False
        self.last_space = True
        self.first_body = True
        self.keep_next = False
        self.para_count = 0
        self.last_heading = False   # последний абзац — заголовок
        self.at_doc_start = True    # в текущем файле spine еще нет текста

    # ---- абзацы ----
    def _new_para(self, cs, indent_l, indent_r):
        p = self.doc.add_paragraph()
        pf = p.paragraph_format
        fs = cs.get("font-size", EPUB_BASE_PT)
        align = cs.get("text-align", "left")
        pf.alignment = {
            "center": WD_ALIGN_PARAGRAPH.CENTER,
            "right": WD_ALIGN_PARAGRAPH.RIGHT,
            "end": WD_ALIGN_PARAGRAPH.RIGHT,
            "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        }.get(align, WD_ALIGN_PARAGRAPH.LEFT)
        indent = _css_len(cs.get("text-indent"), fs, percent_of=self.cw) or 0.0
        pf.first_line_indent = Pt(indent)
        pf.left_indent = Pt(max(indent_l, 0))
        pf.right_indent = Pt(max(indent_r, 0))
        pf.space_before = Pt(self.pending_space)
        pf.space_after = Pt(0)
        lh = cs.get("line-height", "normal")
        mult = EPUB_LINE_HEIGHT
        if lh not in ("normal", "inherit", "initial"):
            m = re.match(r"^([\d.]+)\s*([a-z%]*)$", lh)
            if m:
                num, unit = float(m.group(1)), m.group(2)
                if unit == "":
                    mult = num
                elif unit == "%":
                    mult = num / 100.0
                elif unit == "em":
                    mult = num
                else:
                    mult = (_css_len(lh, fs) or fs * EPUB_LINE_HEIGHT) / fs
        mult = max(mult, 1.0)
        pf.line_spacing_rule = WD_LINE_SPACING.AT_LEAST
        pf.line_spacing = Pt(round(fs * mult, 1))
        pf.widow_control = True
        if self.pending_break:
            pf.page_break_before = True
            self.pending_break = False
        self.pending_space = 0.0
        self.para = p
        self.para_cs = cs
        self.last_space = True
        self.para_count += 1
        return p

    def _flush(self):
        if self.para is not None:
            # хвостовые пробелы
            runs = self.para.runs
            if runs and runs[-1].text.endswith(" "):
                runs[-1].text = runs[-1].text.rstrip(" ")
        self.para = None
        self.para_cs = None

    # ---- текст ----
    def _add_text(self, text, cs, ctx):
        pre = cs.get("white-space", "normal") in ("pre", "pre-wrap", "pre-line")
        if not pre:
            text = re.sub(r"[ \t\r\n\f​]+", " ", text)
            if self.para is None and not text.strip():
                return
        if not text:
            return
        if self.para is None:
            self._new_para(ctx["block_cs"], ctx["il"], ctx["ir"])
            self._apply_block_flags(ctx)
        if not pre:
            if self.last_space and text.startswith(" "):
                text = text[1:]
            if not text:
                return
            self.last_space = text.endswith(" ")
        tt = cs.get("text-transform")
        if tt == "uppercase":
            text = text.upper()
        elif tt == "lowercase":
            text = text.lower()
        if pre and "\n" in text:
            lines = text.split("\n")
            for k, line in enumerate(lines):
                if k:
                    self.para.add_run().add_break()
                if line:
                    self._run(line, cs)
            return
        self._run(text, cs)

    def _run(self, text, cs):
        r = self.para.add_run(text)
        fs = cs.get("font-size", EPUB_BASE_PT)
        va = cs.get("vertical-align", "")
        if abs(fs - EPUB_BASE_PT) > 0.05:
            r.font.size = Pt(round(fs * 2) / 2)
        fw = cs.get("font-weight", "normal")
        if fw in ("bold", "bolder") or (fw.isdigit() and int(fw) >= 600):
            r.font.bold = True
        if cs.get("font-style") in ("italic", "oblique"):
            r.font.italic = True
        td = cs.get("text-decoration", "")
        if "underline" in td:
            r.font.underline = True
        if "line-through" in td:
            r.font.strike = True
        if va in ("super", "top", "text-top"):
            r.font.superscript = True
            # vertical-align:super уже уменьшает кегль в Word, не уменьшаем дважды
            if abs(fs - EPUB_BASE_PT) > 0.05:
                r.font.size = Pt(round(self.para_cs.get("font-size", EPUB_BASE_PT) * 2) / 2) \
                    if self.para_cs else None
        elif va in ("sub", "bottom", "text-bottom"):
            r.font.subscript = True
            if abs(fs - EPUB_BASE_PT) > 0.05:
                r.font.size = Pt(round(self.para_cs.get("font-size", EPUB_BASE_PT) * 2) / 2) \
                    if self.para_cs else None
        if cs.get("font-variant") == "small-caps":
            r.font.small_caps = True
        fam = (cs.get("font-family") or "").lower()
        if "monospace" in fam or "courier" in fam:
            r.font.name = "Liberation Mono"

    def _apply_block_flags(self, ctx):
        pf = self.para.paragraph_format
        # Эпиграф/посвящение после заголовка не «разрывает» группу заголовков:
        # подраздел, идущий сразу за ними, остается на той же странице.
        if ctx.get("outline") is not None:
            self.last_heading = True
        elif not ctx.get("epigraph"):
            self.last_heading = False
        self.at_doc_start = False
        if ctx.get("keep_next"):
            pf.keep_with_next = True
        if ctx.get("keep_together"):
            pf.keep_together = True
        lvl = ctx.get("outline")
        if lvl is not None:
            ppr = self.para._p.get_or_add_pPr()
            el = OxmlElement("w:outlineLvl")
            el.set(qn("w:val"), str(min(max(lvl, 0), 8)))
            ppr.append(el)

    # ---- картинки ----
    def _add_image(self, blob, ctx, w_attr=None, h_attr=None, fit_page=False):
        size = _image_size_px(blob)
        if not size:
            return
        wpx, hpx = size
        if w_attr and h_attr:
            try:
                wpx, hpx = float(w_attr), float(h_attr)
            except ValueError:
                pass
        w_pt, h_pt = wpx * 0.75, hpx * 0.75
        max_w = self.cw - ctx["il"] - ctx["ir"]
        max_h = self.ch - 2
        if fit_page:
            k = min(max_w / w_pt, max_h / h_pt)
        else:
            k = min(1.0, max_w / w_pt, max_h / h_pt)
        w_pt, h_pt = w_pt * k, h_pt * k
        inline_ok = self.para is not None and h_pt <= 2.5 * EPUB_BASE_PT
        if not inline_ok:
            self._flush()
            cs = dict(ctx["block_cs"])
            if fit_page or cs.get("text-align", "left") == "left":
                cs["text-align"] = "center"
            cs["text-indent"] = "0"
            cs["line-height"] = "1"
            self._new_para(cs, ctx["il"], ctx["ir"])
        try:
            self.para.add_run().add_picture(io.BytesIO(blob), width=Pt(w_pt), height=Pt(h_pt))
        except Exception as e:
            logger.warning(f"EPUB: картинка не вставлена: {e}")
        if not inline_ok:
            self._flush()

    # ---- обход дерева ----
    def render_document(self, root, zf, names, doc_path, cs_root):
        self._zf, self._names, self._doc_dir = zf, names, os.path.dirname(doc_path)
        body = None
        for el in root.iter():
            if _local(el.tag) == "body":
                body = el
                break
        if body is None:
            body = root
        html_cs = self.styler.computed(root, cs_root) if body is not root else cs_root
        ctx = {"block_cs": html_cs, "il": 0.0, "ir": 0.0}
        # Обложка: документ, в котором только картинка
        texts = "".join(body.itertext()).strip()
        imgs = [e for e in body.iter() if _local(e.tag) in ("img", "image")]
        self._cover_doc = (not texts and len(imgs) == 1)
        self.at_doc_start = True
        self.last_heading = False
        self._block(body, html_cs, ctx)
        self._flush()

    def _resolve(self, href):
        from urllib.parse import unquote
        if not href or href.startswith("data:"):
            return None
        p = os.path.normpath(os.path.join(self._doc_dir, unquote(href.split("#", 1)[0]))).replace("\\", "/")
        return p if p in self._names else None

    def _block(self, el, parent_cs, ctx):
        cs = self.styler.computed(el, parent_cs)
        if cs.get("display") == "none" or cs.get("visibility") == "hidden":
            return
        tag = _local(el.tag)
        fs = cs.get("font-size", EPUB_BASE_PT)
        avail = self.cw - ctx["il"] - ctx["ir"]
        mt = _css_len(cs.get("margin-top"), fs, percent_of=avail) or 0.0
        mb = _css_len(cs.get("margin-bottom"), fs, percent_of=avail) or 0.0
        ml = (_css_len(cs.get("margin-left"), fs, percent_of=avail) or 0.0) + \
             (_css_len(cs.get("padding-left"), fs, percent_of=avail) or 0.0)
        mr = (_css_len(cs.get("margin-right"), fs, percent_of=avail) or 0.0) + \
             (_css_len(cs.get("padding-right"), fs, percent_of=avail) or 0.0)
        pt_ = _css_len(cs.get("padding-top"), fs, percent_of=avail) or 0.0
        pb_ = _css_len(cs.get("padding-bottom"), fs, percent_of=avail) or 0.0
        if tag in ("body", "html"):
            # Верх/низ задают поля страницы DOCX; боковые поля body из CSS
            # книги (например .z { margin-right: 8pt }) сужают колонку текста.
            mt = mb = pt_ = pb_ = 0.0

        self._flush()
        if cs.get("page-break-before") in ("always", "left", "right", "page"):
            self.pending_break = True
        self.pending_space = max(self.pending_space, mt) + pt_

        cls = (el.get("class") or "").split()
        sub = dict(ctx)
        sub["block_cs"] = cs
        sub["il"] = ctx["il"] + ml
        sub["ir"] = ctx["ir"] + mr
        if cs.get("page-break-after") == "avoid":
            sub["keep_next"] = True
        if cs.get("page-break-inside") == "avoid":
            sub["keep_together"] = True
        if any(re.search(r"epigraph|annotation|dedication|text-author|subtitle", c, re.I) for c in cls):
            sub["epigraph"] = True
        if re.match(r"^h[1-6]$", tag):
            sub["outline"] = int(tag[1]) - 1
        else:
            for c in cls:
                m = re.match(r"^(?:title|chapter|heading)(\d*)$", c, re.I)
                if m:
                    sub["outline"] = int(m.group(1) or 0)
                    break

        # Заголовок главы — с новой страницы (как в эталоне), если перед ним
        # был текст. Подряд идущие заголовки (глава + первый подраздел)
        # остаются на одной странице.
        if "outline" in sub and "outline" not in ctx:
            if sub["outline"] <= EPUB_HEADING_BREAK_LEVEL and not self.last_heading \
                    and not self.at_doc_start:
                self.pending_break = True
                self.pending_space = mt + pt_
            sub["heading_root"] = True

        para_before = self.para_count
        if tag == "hr":
            self.pending_space = max(self.pending_space, fs * 0.5)
        elif tag == "li":
            self._li(el, cs, sub)
        elif tag == "table":
            self._table(el, cs, sub)
        else:
            self._children(el, cs, sub)
        self._flush()

        produced = self.para_count != para_before
        h = cs.get("height")
        if not produced and h and h not in ("auto", "0", "100%"):
            # пустые «строки-разделители» (.empty-line { height: 1em })
            self.pending_space += _css_len(h, fs) or 0.0
        self.pending_space += pb_
        self.pending_space = max(self.pending_space, mb)
        if cs.get("page-break-after") in ("always", "left", "right", "page"):
            self.pending_break = True
            self.pending_space = 0.0

    def _children(self, el, cs, ctx):
        if el.text:
            self._add_text(el.text, cs, ctx)
        for child in el:
            tag = _local(child.tag)
            if not isinstance(child.tag, str) or tag in _SKIP_TAGS:
                pass
            else:
                self._node(child, cs, ctx)
            if child.tail:
                self._add_text(child.tail, cs, ctx)

    def _has_block_child(self, el):
        for d in el.iter():
            if d is not el and _local(d.tag) in _BLOCK_TAGS:
                return True
        return False

    def _node(self, el, parent_cs, ctx):
        tag = _local(el.tag)
        # hidden="" (EPUB3: landmarks, page-list в nav.xhtml) читалка не показывает
        if el.get("hidden") is not None:
            return
        if tag == "br":
            if self.para is None:
                self._new_para(ctx["block_cs"], ctx["il"], ctx["ir"])
                self._apply_block_flags(ctx)
            self.para.add_run().add_break()
            self.last_space = True
            return
        if tag in ("img", "image"):
            href = el.get("src") or el.get("{http://www.w3.org/1999/xlink}href") or el.get("href")
            path = self._resolve(href)
            if path:
                self._add_image(self._zf.read(path), ctx, el.get("width"), el.get("height"),
                                fit_page=self._cover_doc)
            return
        if tag == "svg":
            for d in el.iter():
                if _local(d.tag) == "image":
                    self._node(d, parent_cs, ctx)
            return
        if tag in _BLOCK_TAGS or self._has_block_child(el):
            if tag in _BLOCK_TAGS:
                self._block(el, parent_cs, ctx)
            else:
                # <span> вокруг абзацев: прозрачный контейнер
                cs = self.styler.computed(el, parent_cs)
                self._children(el, cs, ctx)
            return
        cs = self.styler.computed(el, parent_cs)
        if cs.get("display") == "none":
            return
        if cs.get("display") == "block":
            self._block(el, parent_cs, ctx)
            return
        self._children(el, cs, ctx)

    def _li(self, el, cs, ctx):
        parent = el.getparent()
        ordered = parent is not None and _local(parent.tag) == "ol"
        marker = "•"
        if ordered:
            idx = [c for c in parent if _local(c.tag) == "li"].index(el) + 1
            marker = f"{idx}."
        lst = (cs.get("list-style-type") or cs.get("list-style") or "")
        self._new_para(cs, ctx["il"], ctx["ir"])
        self._apply_block_flags(ctx)
        pf = self.para.paragraph_format
        il = max(ctx["il"], 18)
        pf.left_indent = Pt(il)
        pf.first_line_indent = Pt(-18)
        pf.tab_stops.add_tab_stop(Pt(il))
        if "none" not in lst:
            self._run(marker + "\t", cs)
        self.last_space = True
        self._children(el, cs, ctx)

    def _table(self, el, cs, ctx):
        rows = [r for r in el.iter() if _local(r.tag) == "tr"]
        if not rows:
            return
        grid = [[c for c in r if _local(c.tag) in ("td", "th")] for r in rows]
        ncols = max((sum(int(c.get("colspan", 1) or 1) for c in r) for r in grid), default=0)
        if not ncols:
            return
        self._flush()
        table = self.doc.add_table(rows=len(grid), cols=ncols)
        try:
            table.style = "Table Grid"
        except (KeyError, ValueError):
            logger.debug("Style 'Table Grid' is not available in this document")
        for ri, r in enumerate(grid):
            ci = 0
            for c in r:
                if ci >= ncols:
                    break
                span = int(c.get("colspan", 1) or 1)
                cell = table.cell(ri, ci)
                if span > 1 and ci + span - 1 < ncols:
                    cell = cell.merge(table.cell(ri, ci + span - 1))
                text = re.sub(r"\s+", " ", "".join(c.itertext())).strip()
                cell.text = text
                if _local(c.tag) == "th":
                    for run in cell.paragraphs[0].runs:
                        run.font.bold = True
                ci += span
        self.pending_space = max(self.pending_space, 6)


def _epub_front_page(builder, lines, center_v=False):
    """Служебная страница из метаданных (титул/аннотация)."""
    first = True
    for text, size, bold, italic, align, space in lines:
        if not text:
            continue
        cs = {"font-size": size, "text-align": align, "text-indent": "0"}
        builder.pending_space = space
        p = builder._new_para(cs, 0.0, 0.0)
        r = p.add_run(text)
        if abs(size - EPUB_BASE_PT) > 0.05:
            r.font.size = Pt(size)
        r.font.bold = bold or None
        r.font.italic = italic or None
        first = False
        builder._flush()
    builder.pending_break = True


def epub_to_book_docx(epub_path: str, out_path: str):
    """EPUB -> DOCX, по верстке совпадающий с тем, как книгу показывает
    читалка: обложка, титульный лист и аннотация из метаданных, затем
    файлы spine — каждый с новой страницы, оформление из CSS книги."""
    zf, names, meta, spine, cover_href = _epub_open(epub_path)
    try:
        doc = Document()
        sec = doc.sections[0]
        sec.page_width, sec.page_height = Cm(EPUB_PAGE[0]), Cm(EPUB_PAGE[1])
        sec.top_margin, sec.bottom_margin = Cm(EPUB_MARGINS[0]), Cm(EPUB_MARGINS[1])
        sec.left_margin, sec.right_margin = Cm(EPUB_MARGINS[2]), Cm(EPUB_MARGINS[3])
        sec.header_distance = sec.footer_distance = Cm(0.5)
        content_w = (EPUB_PAGE[0] - EPUB_MARGINS[2] - EPUB_MARGINS[3]) * 28.3465
        content_h = (EPUB_PAGE[1] - EPUB_MARGINS[0] - EPUB_MARGINS[1]) * 28.3465

        lang = (meta.get("language") or ["ru"])[0]
        lang = {"ru": "ru-RU", "uk": "uk-UA", "en": "en-US"}.get(lang.split("-")[0].lower(), lang)
        normal = doc.styles["Normal"]
        _set_style_font(normal, EPUB_FONT, EPUB_BASE_PT, lang)
        normal.paragraph_format.space_before = Pt(0)
        normal.paragraph_format.space_after = Pt(0)
        normal.paragraph_format.widow_control = True
        # Автоперенос выключен: читалка (и эталонный PDF) слов не переносит
        settings = doc.settings.element
        el = settings.find(qn("w:autoHyphenation"))
        if el is not None:
            el.set(qn("w:val"), "false")

        # python-docx создает документ с одним пустым абзацем — убираем его
        body = doc.element.body
        for p in list(body.iterchildren(qn("w:p"))):
            body.remove(p)

        styler_cache = {}

        def styler_for(css_hrefs, inline_css):
            key = (tuple(css_hrefs), inline_css)
            if key not in styler_cache:
                texts = []
                for h in css_hrefs:
                    if h in names:
                        texts.append(zf.read(h).decode("utf-8", errors="replace"))
                texts.append(inline_css)
                styler_cache[key] = _EpubStyler(texts, content_w)
            return styler_cache[key]

        builder = _EpubDocxBuilder(doc, None, content_w, content_h, lang)

        # Разбор spine
        docs = []
        for path in spine:
            data = zf.read(path) if path in names else None
            if data is None:
                continue
            root = _parse_xhtml(data)
            if root is None:
                continue
            css_hrefs, inline_css = [], ""
            for e in root.iter():
                t = _local(e.tag)
                if t == "link" and "stylesheet" in (e.get("rel") or "").lower():
                    h = os.path.normpath(os.path.join(os.path.dirname(path), e.get("href", ""))).replace("\\", "/")
                    if h not in css_hrefs:
                        css_hrefs.append(h)
                elif t == "style":
                    inline_css += "\n" + "".join(e.itertext())
            docs.append((path, root, css_hrefs, inline_css))

        def is_cover(root):
            body_el = next((e for e in root.iter() if _local(e.tag) == "body"), root)
            txt = "".join(body_el.itertext()).strip()
            imgs = [e for e in body_el.iter() if _local(e.tag) in ("img", "image")]
            return not txt and len(imgs) == 1

        # 1. Обложка
        cover_in_spine = bool(docs) and is_cover(docs[0][1])
        started = False
        if cover_in_spine:
            path, root, css, icss = docs.pop(0)
            builder.styler = styler_for(css, icss)
            builder.render_document(root, zf, names, path, {"font-size": EPUB_BASE_PT})
            started = True
        elif cover_href and cover_href in names:
            builder._zf, builder._names, builder._doc_dir = zf, names, ""
            builder._cover_doc = True
            builder._add_image(zf.read(cover_href),
                               {"block_cs": {"font-size": EPUB_BASE_PT}, "il": 0.0, "ir": 0.0},
                               fit_page=True)
            started = True

        # 2. Титульный лист из метаданных
        if EPUB_FRONT_TITLE_PAGE and (meta.get("title") or meta.get("creator")):
            if started:
                builder.pending_break = True
            info = []
            if meta.get("publisher"):
                info.append(meta["publisher"][0])
            if meta.get("date"):
                info.append(meta["date"][0][:4])
            _epub_front_page(builder, [
                (", ".join(meta.get("creator", [])), EPUB_BASE_PT * 1.3, False, False, "center", 120),
                ((meta.get("title") or [""])[0], EPUB_BASE_PT * 1.8, True, False, "center", 24),
                (" · ".join(info), EPUB_BASE_PT, False, False, "center", 48),
            ])
            started = True

        # 3. Аннотация
        if EPUB_FRONT_ANNOTATION and meta.get("description"):
            desc = re.sub(r"<[^>]+>", " ", meta["description"][0])
            desc = re.sub(r"\s+", " ", desc).strip()
            if desc:
                if started:
                    builder.pending_break = True
                cs = {"font-size": EPUB_BASE_PT, "text-align": "justify", "text-indent": "1.5em"}
                builder.pending_space = 0
                p = builder._new_para(cs, 0.0, 0.0)
                p.add_run(desc).font.italic = True
                builder._flush()
                started = True

        # 4. Текст книги: каждый файл spine с новой страницы
        for path, root, css, icss in docs:
            builder.styler = styler_for(css, icss)
            if started and EPUB_SPINE_PAGE_BREAKS:
                builder.pending_break = True
            builder.pending_space = 0.0
            builder.render_document(root, zf, names, path, {"font-size": EPUB_BASE_PT})
            started = True

        # Метаданные PDF
        cp = doc.core_properties
        if meta.get("title"):
            cp.title = meta["title"][0]
        if meta.get("creator"):
            cp.author = ", ".join(meta["creator"])
        if meta.get("language"):
            cp.language = meta["language"][0]
        doc.save(out_path)
    finally:
        zf.close()

def epub_to_pdf(in_path: str, out_path: str):
    """EPUB -> PDF через собственную верстку DOCX (epub_to_book_docx) и
    LibreOffice. Возвращает текст предупреждения, если пришлось откатиться
    на старый путь pandoc (сломанный/нестандартный EPUB), иначе None."""
    tmp_docx = os.path.join(OUTPUT_DIR, f"tmp_epub_{uuid.uuid4()}.docx")
    warning = None
    try:
        try:
            epub_to_book_docx(in_path, tmp_docx)
        except Exception as e:
            warning = f"Верстку EPUB не удалось сохранить ({type(e).__name__}: {e}), использован pandoc"
            logger.exception("%s", warning)
            engine_pandoc(in_path, tmp_docx, 'docx', 'epub')
            format_book_docx(tmp_docx)
        pdf_res = engine_libreoffice(tmp_docx, OUTPUT_DIR, 'pdf')
        shutil.move(pdf_res, out_path)
    finally:
        if os.path.exists(tmp_docx):
            os.remove(tmp_docx)
    return warning
