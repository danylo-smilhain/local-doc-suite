"""Merge Word: each file keeps its own look in the merged document.

docxcompose appends the body of each file to the first one. Left alone it
gives the whole result the first file's page setup and swaps every style
of a later file for the first file's style of the same name, so a file
whose Normal is Arial 11 single-spaced comes out in the first file's
Times 14 at 1.5 lines. Here each file is prepared before it is appended.

Glossary
- master: the first document; the others are appended to it.
- part: the content of one uploaded file inside the merged document.
- page setup: a part's w:sectPr (page size, orientation, margins, columns).
  Word stores it after a section: in the last paragraph of each section and
  in the body for the last one. Each part ends in a section break that
  carries its own setup.
- defaults: w:docDefaults, the formatting under every style of a file.
- root style: a style based on no other; the defaults apply beneath it.
- conflict: a style of a later file whose name or id the master has with
  another definition. It is renamed ("Normal (2)") so both definitions stay.
- story: where a file's text is: its body, headers and footers.
- Word mode: the Word version a document is laid out for (compatibility
  mode, one per document); it decides, among other things, where a table
  stands against its indent.
"""
from __future__ import annotations

from copy import deepcopy

from docx import Document
from docx.enum.text import WD_LINE_SPACING
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.shared import Pt
from docxcompose.composer import Composer

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# child order of w:rPr and w:pPr (ECMA-376 CT_RPr, CT_PPrBase); Word rejects other orders
R_ORDER = (
    "rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike", "outline",
    "shadow", "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden", "color",
    "spacing", "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect", "bdr", "shd",
    "fitText", "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout", "specVanish", "oMath"
)
P_ORDER = (
    "pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl", "numPr",
    "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap",
    "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd",
    "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc",
    "textDirection", "textAlignment", "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr",
    "sectPr", "pPrChange"
)
STYLE_AFTER = {"pPr": ("rPr", "tblPr", "trPr", "tcPr", "tblStylePr"),
               "rPr": ("tblPr", "trPr", "tcPr", "tblStylePr")}
# what Word assumes when a file's defaults say nothing (ECMA-376 17.7.2, 17.3)
SPEC = {"rFonts": {"ascii": "Times New Roman", "hAnsi": "Times New Roman",
                   "eastAsia": "Times New Roman", "cs": "Times New Roman"},
        "sz": {"val": "20"}, "szCs": {"val": "20"},
        "spacing": {"before": "0", "after": "0", "line": "240", "lineRule": "auto"},
        "ind": {"left": "0", "right": "0", "firstLine": "0", "hanging": "0"},
        "jc": {"val": "left"}, "color": {"val": "auto"}, "u": {"val": "none"},
        **{toggle: {"val": "0"} for toggle in ("b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "vanish")}}
# a font attribute and its theme twin fill one slot: either decides the font
THEME_OF = {"ascii": "asciiTheme", "hAnsi": "hAnsiTheme", "eastAsia": "eastAsiaTheme", "cs": "cstheme"}
SLOT = {**{k: k for k in THEME_OF}, **{v: k for k, v in THEME_OF.items()}}
# style children that change nothing on the page
UI_ONLY = {"rsid", "uiPriority", "semiHidden", "unhideWhenUsed", "qFormat", "locked", "autoRedefine",
           "personal", "personalCompose", "personalReply", "name", "aliases"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _place(parent, child, order) -> None:
    """child into parent before the first sibling that comes after it in order."""
    later = order[order.index(_local(child.tag)) + 1:]
    for i, sibling in enumerate(parent):
        if _local(sibling.tag) in later:
            parent.insert(i, child)
            return
    parent.append(child)


def _style_part(style, name: str):
    """The style's w:pPr or w:rPr, made where the schema wants it if missing."""
    found = style.find(W + name)
    if found is None:
        found = OxmlElement("w:" + name)
        for i, child in enumerate(style):
            if _local(child.tag) in STYLE_AFTER[name]:
                style.insert(i, found)
                break
        else:
            style.append(found)
    return found


def _canon(element) -> bytes:
    """A definition as it acts on the page: no ids, names or UI flags."""
    from lxml import etree
    if element is None:
        return b""
    copy = deepcopy(element)
    for child in list(copy):
        if _local(child.tag) in UI_ONLY:
            copy.remove(child)
    for attr in ("styleId", "default", "customStyle"):
        copy.attrib.pop(W + attr, None)
    return etree.tostring(copy, method="c14n")


# ---- defaults ---------------------------------------------------------------

def _defaults(doc, kind: str):
    """A document's w:rPrDefault/w:rPr (kind "r") or w:pPrDefault/w:pPr ("p")."""
    found = doc.styles.element.find(f"{W}docDefaults/{W}{kind}PrDefault/{W}{kind}Pr")
    return found if found is not None else OxmlElement(f"w:{kind}Pr")


def _filled_slots(element) -> set[str]:
    return {SLOT.get(_local(a), _local(a)) for a in element.attrib}


def _fill(target, source) -> None:
    """Attributes of source whose slot target leaves open."""
    taken = _filled_slots(target)
    for attr, value in source.attrib.items():
        if SLOT.get(_local(attr), _local(attr)) not in taken:
            target.set(attr, value)


def _fold(props, own_defaults, master_defaults, order) -> None:
    """Into a root style's props: what its file's defaults gave it, and the
    spec's value wherever the master's defaults would give it something."""
    for default in own_defaults:
        found = props.find(default.tag)
        if found is None:
            _place(props, deepcopy(default), order)
        else:
            _fill(found, default)
    for default in master_defaults:
        spec = SPEC.get(_local(default.tag))
        if spec is None:
            continue
        found = props.find(default.tag)
        if found is None:
            found = OxmlElement("w:" + _local(default.tag))
            _place(props, found, order)
        open_slots = (_filled_slots(default) or set(spec)) - _filled_slots(found)   # <w:b/> means val="1"
        for slot in open_slots & spec.keys():
            found.set(W + slot, spec[slot])


def _fold_defaults(master, sub) -> None:
    """sub's defaults become part of its root styles when the master's differ."""
    if all(_canon(_defaults(master, k)) == _canon(_defaults(sub, k)) for k in "rp"):
        return
    for style in sub.styles.element.findall(W + "style"):
        if style.find(W + "basedOn") is not None:
            continue
        kind = style.get(W + "type")
        _fold(_style_part(style, "rPr"), _defaults(sub, "r"), _defaults(master, "r"), R_ORDER)
        if kind in ("paragraph", "table"):
            _fold(_style_part(style, "pPr"), _defaults(sub, "p"), _defaults(master, "p"), P_ORDER)


# ---- conflicts --------------------------------------------------------------

def _conflicts(master, sub) -> set[str]:
    """Ids of sub styles the master would replace: same name or id, another definition,
    and every style of sub based on one of those that the master also has by name."""
    by_name = {s.name: s.element for s in master.styles}
    by_id = {s.style_id: s for s in master.styles}
    own = {s.style_id: s for s in sub.styles}
    found = set()
    for sid, style in own.items():
        mine = by_name.get(style.name)
        clash = by_id.get(sid)
        if (mine is not None and _canon(mine) != _canon(style.element)) or (clash is not None and clash.name != style.name):
            found.add(sid)
    grown = True
    while grown:
        grown = False
        for sid, style in own.items():
            base = style.element.find(W + "basedOn")
            if sid not in found and base is not None and base.get(W + "val") in found and style.name in by_name:
                found.add(sid)
                grown = True
    return found


def _free(value: str, taken: set[str], n: int, pattern: str) -> str:
    candidate = pattern.format(value, n)
    while candidate in taken:
        n += 1
        candidate = pattern.format(value, n)
    return candidate


def _rename(master, sub, conflicts: set[str], n: int) -> dict[str, str]:
    """New names and ids for the conflicts; returns {old id: new id}."""
    names = {s.name for s in master.styles}
    ids = {s.style_id for s in master.styles} | {s.style_id for s in sub.styles}
    renames = {}
    for style in sub.styles:
        if style.style_id not in conflicts:
            continue
        el = style.element
        if style.name in names:
            new_name = _free(style.name, names, n, "{} ({})")
            el.find(W + "name").set(W + "val", new_name)
            names.add(new_name)
        if style.style_id in {s.style_id for s in master.styles}:
            new_id = _free(style.style_id, ids, n, "{}{}")
            ids.add(new_id)
            renames[style.style_id] = new_id
            el.set(W + "styleId", new_id)
    return renames


def _point_to(roots, renames: dict[str, str]) -> None:
    tags = ("basedOn", "next", "link", "pStyle", "rStyle", "tblStyle")
    for root in roots:
        for tag in tags:
            for ref in root.iter(W + tag):
                new = renames.get(ref.get(W + "val"))
                if new:
                    ref.set(W + "val", new)


def _defaults_by_type(sub) -> dict[str, str]:
    return {s.get(W + "type"): s.get(W + "styleId")
            for s in sub.styles.element.findall(W + "style") if s.get(W + "default") in ("1", "true")}


def _stories(sub) -> list:
    """Where a file's text is: its body, headers and footers."""
    parts = [r.target_part for r in sub.part.rels.values() if r.reltype in (RT.HEADER, RT.FOOTER)]
    return [sub.element.body] + [p.element for p in parts]


def _name_unstyled(sub, defaults: dict[str, str], conflicts: set[str], renames: dict[str, str]) -> None:
    """Paragraphs and tables with no style used their file's default style;
    once that is renamed they have to say so."""
    para = defaults.get("paragraph")
    if para in conflicts:
        for p in (p for story in _stories(sub) for p in story.iter(W + "p")):
            ppr = p.get_or_add_pPr()
            if ppr.find(W + "pStyle") is None:
                ppr.style = renames.get(para, para)
    table = defaults.get("table")
    if table in conflicts:
        for tbl in (t for story in _stories(sub) for t in story.iter(W + "tbl")):
            if tbl.tblPr.find(W + "tblStyle") is None:
                tbl.tblPr.style = renames.get(table, table)
    renamed = {renames.get(c, c) for c in conflicts}
    for style in sub.styles.element.findall(W + "style"):
        if style.get(W + "styleId") in renamed:      # the master keeps its own default
            style.attrib.pop(W + "default", None)


def keep_look(master, sub, n: int) -> None:
    """Make sub's styles survive being appended to master (n: its place, 2, 3, ...)."""
    _fold_defaults(master, sub)
    conflicts = _conflicts(master, sub)
    if not conflicts:
        return
    defaults = _defaults_by_type(sub)
    renames = _rename(master, sub, conflicts, n)
    roots = [sub.styles.element, *_stories(sub)]
    try:
        roots.append(sub.part.numbering_part.element)
    except NotImplementedError:
        pass
    _point_to(roots, renames)
    _name_unstyled(sub, defaults, conflicts, renames)


def add_missing_bases(master, sub) -> None:
    """docxcompose copies the styles a part uses but not what they are based
    on; a missing base reads as none, and the style loses what it inherits."""
    while True:
        ids = {s.style_id for s in master.styles}
        names = {s.name: s.style_id for s in master.styles}
        missing = [(el, el.find(W + "basedOn").get(W + "val")) for el in master.styles.element.findall(W + "style")
                   if el.find(W + "basedOn") is not None and el.find(W + "basedOn").get(W + "val") not in ids]
        added = False
        for el, base_id in missing:
            base = sub.styles.element.get_by_id(base_id)
            if base is None:
                continue
            name = base.find(W + "name").get(W + "val") if base.find(W + "name") is not None else None
            same = next((s for s in sub.styles if s.style_id == base_id), None)
            if same is not None and same.name in names:
                el.find(W + "basedOn").set(W + "val", names[same.name])
            elif name is not None:
                copy = deepcopy(base)
                copy.attrib.pop(W + "default", None)
                master.styles.element.append(copy)
                added = True
        if not added:
            return


# ---- tables -------------------------------------------------------------------

T_ORDER = ("tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize", "tblStyleColBandSize",
           "tblW", "jc", "tblCellSpacing", "tblInd", "tblBorders", "shd", "tblLayout", "tblCellMar",
           "tblLook", "tblCaption", "tblDescription")
WORD_CELL_MARGIN = 108          # twips, a table's left cell margin when nothing says otherwise
NEW_TABLE_RULE = 15             # Word 2013: a table's border, not its text, sits at its indent


def word_mode(doc) -> int:
    """The Word version a file is laid out for (11: 2003, 15: 2013 and later);
    one per document. A file that names none is laid out the old way."""
    for setting in doc.settings.element.iter(W + "compatSetting"):
        if setting.get(W + "name") == "compatibilityMode":
            return int(setting.get(W + "val", "0"))
    return 0


def _old_table_rule(doc) -> bool:
    """Before Word 2013 a table stood out to the left by its cell margin, so
    its text lined up with the page's."""
    return word_mode(doc) < NEW_TABLE_RULE


def _cell_margin(tbl, sub) -> int:
    """The table's left cell margin: its own, its style's (or a base's), the file's default table style's."""
    def own(tblpr):
        if tblpr is None:
            return None
        for side in ("left", "start"):
            found = tblpr.find(f"{W}tblCellMar/{W}{side}")
            if found is not None and found.get(W + "type", "dxa") == "dxa":
                return int(found.get(W + "w"))
        return None
    found = own(tbl.tblPr)
    style_ref = tbl.tblPr.find(W + "tblStyle")
    sid = style_ref.get(W + "val") if style_ref is not None else _defaults_by_type(sub).get("table")
    while found is None and sid:
        style = sub.styles.element.get_by_id(sid)
        if style is None:
            break
        found = own(style.find(W + "tblPr"))
        base = style.find(W + "basedOn")
        sid = base.get(W + "val") if base is not None else None
    return WORD_CELL_MARGIN if found is None else found


def place_tables(master, sub) -> None:
    """Tables of a file saved under the other table rule than the master's
    keep their place on the page: their indent moves by their cell margin."""
    shift = _old_table_rule(master) - _old_table_rule(sub)       # +1, 0 or -1
    if not shift:
        return
    for tbl in sub.element.body.iter(W + "tbl"):      # a centred table ignores its indent anyway
        ind = tbl.tblPr.find(W + "tblInd")
        if ind is None:
            ind = OxmlElement("w:tblInd")
            ind.set(W + "w", "0")
            _place(tbl.tblPr, ind, T_ORDER)
        if ind.get(W + "type", "dxa") != "dxa":
            continue
        margin = _cell_margin(tbl, sub)
        ind.set(W + "type", "dxa")
        ind.set(W + "w", str(int(ind.get(W + "w", "0")) + shift * margin))
        _own_cell_margin(tbl, margin)


def _own_cell_margin(tbl, margin: int) -> None:
    """The margin the move was measured by, written on the table itself: a
    margin from the default table style is one LibreOffice does not apply."""
    cells = tbl.tblPr.find(W + "tblCellMar")
    if cells is None:
        cells = OxmlElement("w:tblCellMar")
        _place(tbl.tblPr, cells, T_ORDER)
    if cells.find(W + "left") is None and cells.find(W + "start") is None:
        left = OxmlElement("w:left")
        left.set(W + "w", str(margin))
        left.set(W + "type", "dxa")
        top = cells.find(W + "top")
        if top is not None:
            top.addnext(left)
        else:
            cells.insert(0, left)


# w:settings children that come after w:compat (ECMA-376 CT_Settings)
AFTER_COMPAT = ("docVars", "rsids", "mathPr", "attachedSchema", "themeFontLang", "clrSchemeMapping",
                "doNotIncludeSubdocsInStats", "doNotAutoCompressPictures", "forceUpgrade", "captions",
                "readModeInkLockDown", "smartTagType", "schemaLibrary", "shapeDefaults",
                "doNotEmbedSmartTags", "decimalSymbol", "listSeparator")


def _place_compat(settings, compat) -> None:
    for i, child in enumerate(settings):
        if _local(child.tag) in AFTER_COMPAT:
            settings.insert(i, compat)
            return
    settings.append(compat)


# ---- page setup ---------------------------------------------------------------

def _body_setup(doc):
    return doc.element.body.find(W + "sectPr")


def end_part(master) -> None:
    """The part so far ends in a section break carrying its own page setup."""
    body = master.element.body
    setup = _body_setup(master)
    last = setup.getprevious() if setup is not None else (body[-1] if len(body) else None)
    if last is None or last.tag != W + "p" or last.find(f"{W}pPr/{W}sectPr") is not None:
        last = OxmlElement("w:p")
        if setup is not None:
            setup.addprevious(last)
        else:
            body.append(last)
    ppr = last.get_or_add_pPr()
    _place(ppr, deepcopy(setup) if setup is not None else OxmlElement("w:sectPr"), P_ORDER)


R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
HEADERS_FOOTERS = ((W + "headerReference", RT.HEADER, "/word/header%d.xml"),
                   (W + "footerReference", RT.FOOTER, "/word/footer%d.xml"))


def _adopt(master, part, template: str) -> None:
    """part (with what it uses, such as pictures) gets names free in master's package."""
    taken = {p.partname for p in master.part.package.iter_parts()}
    if part.partname in taken:
        part.partname = master.part.package.next_partname(template)
    for rel in part.rels.values():
        if not rel.is_external and rel.target_part.partname in taken:
            ext = rel.target_part.partname.ext
            rel.target_part.partname = master.part.package.next_partname(
                f"{rel.target_part.partname.baseURI}/{rel.target_part.partname.filename.rstrip('0123456789.' + ext)}%d.{ext}")


def _carry_headers_footers(master, sub, own, setup) -> None:
    """The file's own headers and footers go with its page setup; where it
    has none, an empty one stops the previous part's from going on."""
    for tag, reltype, template in HEADERS_FOOTERS:
        for ref in setup.findall(tag):
            setup.remove(ref)
        for ref in own.findall(tag):
            part = sub.part.related_parts[ref.get(R + "id")]
            _adopt(master, part, template)
            _bring_styles(master, sub, part.element)
            new = deepcopy(ref)
            new.set(R + "id", master.part.relate_to(part, reltype))
            setup.insert(0, new)


def _bring_styles(master, sub, story) -> None:
    """Styles a header or footer uses that the master lacks (docxcompose
    brings those of the body only); their bases follow in add_missing_bases."""
    ids = {s.style_id for s in master.styles}
    for tag in ("pStyle", "rStyle", "tblStyle"):
        for ref in story.iter(W + tag):
            sid = ref.get(W + "val")
            style = sub.styles.element.get_by_id(sid)
            if sid not in ids and style is not None:
                copy = deepcopy(style)
                copy.attrib.pop(W + "default", None)
                master.styles.element.append(copy)
                ids.add(sid)


def _flat(header_footer) -> None:
    """An empty header takes no room: one paragraph 1 pt high."""
    for p in header_footer.paragraphs:
        p.paragraph_format.space_before = p.paragraph_format.space_after = 0
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        p.paragraph_format.line_spacing = Pt(1)
        size = OxmlElement("w:sz")
        size.set(W + "val", "2")
        rpr = p._p.get_or_add_pPr().find(W + "rPr")
        if rpr is None:
            rpr = OxmlElement("w:rPr")
            _place(p._p.pPr, rpr, P_ORDER)
        _place(rpr, size, R_ORDER)


def _no_inherited_headers_footers(master, own) -> None:
    """Where the file has no header or footer of a kind, an empty one stops
    the previous part's from going on."""
    section = master.sections[-1]
    kinds = {"default": ("header", "footer"), "first": ("first_page_header", "first_page_footer"),
             "even": ("even_page_header", "even_page_footer")}
    for kind, names in kinds.items():
        for (tag, _, _), name in zip(HEADERS_FOOTERS, names):
            header_footer = getattr(section, name)
            if own.find(f'{tag}[@{W}type="{kind}"]') is None and header_footer.is_linked_to_previous:
                header_footer.is_linked_to_previous = False
                _flat(header_footer)


def take_page_setup(master, sub) -> None:
    """The last part's page setup and headers and footers are the appended file's own."""
    own = _body_setup(sub)
    if own is None:
        return
    setup = deepcopy(own)
    _carry_headers_footers(master, sub, own, setup)
    if len(sub.sections) == 1:
        kind = setup.find(W + "type")
        if kind is not None:
            setup.remove(kind)              # a missing type is a new page
    old = _body_setup(master)
    if old is not None:
        old.addprevious(setup)
        old.getparent().remove(old)
    else:
        master.element.body.append(setup)
    _no_inherited_headers_footers(master, own)


def take_newest_mode(master, books) -> None:
    """The merged document is laid out for the newest Word among the files:
    the master takes that file's compatibility settings, and its own tables
    keep their place under the other rule. Laying newer files out the old
    way moved their lines and pages; an old file laid out the new way keeps
    them, its tables placed as in place_tables."""
    newest = max(books, key=word_mode)
    if word_mode(newest) <= word_mode(master):
        return
    place_tables(newest, master)
    settings = master.settings.element
    for old in settings.findall(W + "compat"):
        settings.remove(old)
    compat = newest.settings.element.find(W + "compat")
    if compat is not None:
        _place_compat(settings, deepcopy(compat))


def merge_docx(files, out_path) -> None:
    """Files in order into one .docx, each part with its own page setup and look."""
    books = [Document(path) for path in files]
    master = books[0]
    take_newest_mode(master, books[1:])
    composer = Composer(master)
    for n, sub in enumerate(books[1:], start=2):
        keep_look(master, sub, n)
        place_tables(master, sub)
        end_part(master)
        composer.append(sub)
        take_page_setup(master, sub)
        add_missing_bases(master, sub)
    composer.save(out_path)
