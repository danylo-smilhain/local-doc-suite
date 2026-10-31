"""Plain text -> Markdown: escaping, heading/list/code detection, unwrapping hard-wrapped lines."""
import logging
import re
import statistics
import unicodedata

from app.encoding import read_text_file

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"(?:https?://|ftp://|www\.)[^\s<>\)\]]+[^\s<>\)\]\.,;:!?»\"']", re.I)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
ENTITY_RE = re.compile(r"&(?:#\d+|#x[0-9a-f]+|\w+);", re.I)

_ALWAYS = str.maketrans(
    {
        "\\": "\\\\",
        "`": "\\`",
        "*": "\\*",
        "[": "\\[",
        "]": "\\]",
        "<": "\\<",
        ">": "\\>",
        "|": "\\|",
    }
)

_UNDERSCORE = re.compile(r"(?<![^\W_])_|_(?![^\W_])")
_LINE_START = re.compile(r"^(\s*)([#>+=~]|\d+(?=[.)])|[-*](?=\s))")


def escape_inline(text: str) -> str:
    out, pos = [], 0
    for m in _find_links(text):
        out.append(_escape_chunk(text[pos:m.start()]))
        out.append(f"<{m.group(0)}>")
        pos = m.end()
    out.append(_escape_chunk(text[pos:]))
    return "".join(out)


def _find_links(text: str):
    spans = sorted(
        list(URL_RE.finditer(text)) + list(EMAIL_RE.finditer(text)),
        key=lambda m: m.start(),
    )
    last_end = -1
    for m in spans:
        if m.start() >= last_end:
            last_end = m.end()
            yield m


def _escape_chunk(chunk: str) -> str:
    if not chunk:
        return ""
    chunk = ENTITY_RE.sub(lambda m: "&amp;" + m.group(0)[1:], chunk)
    chunk = chunk.translate(_ALWAYS)
    chunk = _UNDERSCORE.sub(r"\_", chunk)
    return chunk


def escape_line(line: str) -> str:
    escaped = escape_inline(line)
    return _LINE_START.sub(lambda m: m.group(1) + "\\" + m.group(2), escaped)


SETEXT_RE = re.compile(r"^\s*([=\-~_*#+])\1{2,}\s*$")
HR_RE = re.compile(r"^\s*([-=_*~#])(?:\s?\1){2,}\s*$")
BULLET_RE = re.compile(r"^(\s*)([-*+•·‣◦▪–—])\s+(\S.*)$")
ORDERED_RE = re.compile(r"^(\s*)(\d{1,3})[.)]\s+(\S.*)$")
LETTERED_RE = re.compile(r"^(\s*)([a-zа-яіїєґ])[.)]\s+(\S.*)$", re.I)
NUMBERED_HEAD_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+(\S.*?)\s*$")
QUOTE_RE = re.compile(r"^\s*[>|]\s?(.*)$")


def _is_all_caps(line: str) -> bool:
    cased = [c for c in line if c.isalpha()]
    if len(cased) < 2:
        return False
    upper = sum(1 for c in cased if c.isupper())
    return upper / len(cased) >= 0.85


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 90:
        return False
    if stripped.endswith((".", ",", ";", ":")):
        return False
    return _is_all_caps(stripped)


def _numbered_heading_level(line: str):
    m = NUMBERED_HEAD_RE.match(line)
    if not m:
        return None
    number, title = m.group(1), m.group(2)
    if len(title) > 90 or title.endswith((".", ",", ";")):
        return None
    depth = number.count(".") + 1
    if depth == 1 and not _is_all_caps(title) and len(title.split()) > 8:
        return None
    return min(depth + 1, 6), f"{number}. {title}"


def _is_indented_block(lines) -> bool:
    body = [l for l in lines if l.strip()]
    if len(body) < 2:
        return False
    return all(l.startswith(("    ", "\t")) for l in body)


def _is_hard_wrapped(lines) -> bool:
    if len(lines) < 3:
        return False
    lengths = [len(l.rstrip()) for l in lines[:-1]]
    if not lengths:
        return False
    mx, mn = max(lengths), min(lengths)
    if mx > 110 or mx < 40:
        return False
    if statistics.pstdev(lengths) > mx * 0.12:
        return False
    return mn >= mx * 0.7


def _split_blocks(lines):
    blocks, current = [], []
    for line in lines:
        if line.strip():
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def _render_list(lines, out):
    indents = []
    for line in lines:
        m = BULLET_RE.match(line) or ORDERED_RE.match(line) or LETTERED_RE.match(line)
        if m:
            indents.append(len(m.group(1).expandtabs(4)))
    base = min(indents) if indents else 0

    def _pad(raw: str) -> str:
        return " " * (max(0, len(raw.expandtabs(4)) - base) // 2 * 2)

    for line in lines:
        m = BULLET_RE.match(line)
        if m:
            out.append(f"{_pad(m.group(1))}- {escape_inline(m.group(3))}")
            continue
        m = ORDERED_RE.match(line)
        if m:
            out.append(f"{_pad(m.group(1))}{m.group(2)}. {escape_inline(m.group(3))}")
            continue
        m = LETTERED_RE.match(line)
        if m:
            out.append(f"{_pad(m.group(1))}- {m.group(2)}\\) {escape_inline(m.group(3))}")
            continue
        out.append(f"  {escape_inline(line.strip())}")


def _render_paragraph(lines, out, unwrap: bool):
    if unwrap and _is_hard_wrapped(lines):
        out.append(escape_inline(" ".join(l.strip() for l in lines)))
        return
    escaped = [escape_line(l.rstrip()) for l in lines]
    for i, line in enumerate(escaped):
        out.append(line + ("\\" if i < len(escaped) - 1 else ""))


def _render_block(block, out, opts, state):
    lines = block
    if len(lines) == 1 and HR_RE.match(lines[0]):
        out.append("---")
        return

    if len(lines) == 2 and SETEXT_RE.match(lines[1]) and lines[0].strip():
        char = lines[1].strip()[0]
        level = 1 if char in "=#" else 2
        if state["first_heading"]:
            level, state["first_heading"] = 1, False
        out.append(f"{'#' * level} {escape_inline(lines[0].strip())}")
        return

    if len(lines) > 2 and SETEXT_RE.match(lines[1]):
        _render_block(lines[:2], out, opts, state)
        out.append("")
        _render_block(lines[2:], out, opts, state)
        return

    if opts["detect_code"] and _is_indented_block(lines):
        out.append("```")
        for line in lines:
            out.append(line.expandtabs(4)[4:] if line.startswith(("    ", "\t")) else line)
        out.append("```")
        return

    if all(QUOTE_RE.match(l) for l in lines):
        for line in lines:
            out.append(f"> {escape_inline(QUOTE_RE.match(line).group(1).strip())}")
        return

    if opts["detect_headings"] and len(lines) == 1:
        line = lines[0].strip()
        if _looks_like_heading(line):
            level = 1 if state["first_heading"] else 2
            state["first_heading"] = False
            out.append(f"{'#' * level} {escape_inline(line)}")
            return
        numbered = _numbered_heading_level(line)
        if numbered:
            level, title = numbered
            if state["first_heading"]:
                level, state["first_heading"] = 1, False
            out.append(f"{'#' * level} {escape_inline(title)}")
            return

    if opts["detect_lists"]:
        markers = sum(
            1 for l in lines if BULLET_RE.match(l) or ORDERED_RE.match(l) or LETTERED_RE.match(l)
        )
        if markers and markers >= len(lines) * 0.6:
            _render_list(lines, out)
            return

    if opts["detect_headings"] and len(lines) > 1:
        head = lines[0].strip()
        if _looks_like_heading(head) or _numbered_heading_level(head):
            _render_block([lines[0]], out, opts, state)
            out.append("")
            _render_block(lines[1:], out, opts, state)
            return

    state["first_heading"] = False
    _render_paragraph(lines, out, opts["unwrap"])


def convert_txt_to_md(
    text: str,
    *,
    smart: bool = True,
    unwrap: bool = True,
    detect_headings: bool = True,
    detect_lists: bool = True,
    detect_code: bool = True,
    title: str = None,
) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    text = "".join(
        c for c in text if c == "\n" or c == "\t" or unicodedata.category(c)[0] != "C"
    )
    lines = [l.rstrip() for l in text.split("\n")]

    out = []
    if title:
        out.append(f"# {escape_inline(title)}")
        out.append("")

    if not smart:
        for line in lines:
            out.append(escape_line(line) if line.strip() else "")
        return _finalize(out)

    opts = {
        "unwrap": unwrap,
        "detect_headings": detect_headings,
        "detect_lists": detect_lists,
        "detect_code": detect_code,
    }
    state = {"first_heading": title is None}

    for block in _split_blocks(lines):
        _render_block(block, out, opts, state)
        out.append("")

    return _finalize(out)


def _finalize(lines) -> str:
    result, blank = [], False
    for line in lines:
        if not line.strip():
            if blank or not result:
                continue
            blank = True
            result.append("")
        else:
            blank = False
            result.append(line)
    while result and not result[-1].strip():
        result.pop()
    return "\n".join(result) + "\n"


def txt_file_to_md(in_path: str, out_path: str, **kwargs) -> str:
    text, encoding = read_text_file(in_path)
    markdown = convert_txt_to_md(text, **kwargs)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(markdown)
    return encoding
