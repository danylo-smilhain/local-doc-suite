"""Telegram chat export (HTML) -> Markdown, with authors, dates, replies and media labels."""
import logging
import re
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

class _Node:
    __slots__ = ("tag", "cls", "attrs", "children", "parent")

    def __init__(self, tag="", attrs=None, parent=None):
        self.tag = tag
        self.attrs = dict(attrs or [])
        self.cls = set((self.attrs.get("class") or "").split())
        self.children = []
        self.parent = parent


_VOID = {"br", "img", "hr", "meta", "link", "input", "source"}


class _DomBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        if tag in _VOID:
            if tag == "br":
                self.cur.children.append("\n")
            elif tag == "img":
                pass
            return
        node = _Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        self.cur = node

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        node = self.cur
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.cur = node.parent

    def handle_data(self, data):
        if data.strip() or "\n" in data:
            self.cur.children.append(data)


def _find_all(node, cls=None, tag=None, out=None):
    out = [] if out is None else out
    for ch in node.children:
        if isinstance(ch, _Node):
            if (cls is None or cls in ch.cls) and (tag is None or ch.tag == tag):
                out.append(ch)
            _find_all(ch, cls, tag, out)
    return out


def _find(node, cls):
    res = _find_all(node, cls)
    return res[0] if res else None


# Экранируем только то, что реально ломает разметку внутри строки.
# Точки, дефисы и восклицательные знаки не трогаем — иначе текст
# превращается в частокол из "\\.".
_MD_ESCAPE = re.compile(r"([\\`*\[\]])")
_MD_UNDERSCORE = re.compile(r"(?<![^\W_])_|_(?![^\W_])")
_LINE_PREFIX = re.compile(r"^(\s*)([#>|]|[-+*](?=\s)|\d+[.)](?=\s))", re.M)


def _escape_inline(text):
    text = _MD_ESCAPE.sub(r"\\\1", text)
    return _MD_UNDERSCORE.sub(r"\\_", text)


def _fix_multiline_emphasis(text):
    """Telegram допускает жирный текст через перенос строки, Markdown — нет."""
    def repl(m):
        inner = m.group(1)
        if "\n" not in inner:
            return m.group(0)
        return "\n".join(f"**{p.strip()}**" if p.strip() else "" for p in inner.split("\n"))
    return re.sub(r"\*\*(.+?)\*\*", repl, text, flags=re.S)


def _wrap(text, marker):
    """Пробелы вокруг выделения выносим наружу: '**1. **x' ломает разметку."""
    stripped = text.strip()
    if not stripped:
        return text
    lead = text[:len(text) - len(text.lstrip())]
    tail = text[len(text.rstrip()):]
    return f"{lead}{marker}{stripped}{marker}{tail}"


def _inline(node, escape=True):
    """Текст узла с сохранением b/i/code/ссылок."""
    parts = []
    for ch in node.children:
        if isinstance(ch, str):
            t = ch.replace("\r", "")
            parts.append(_escape_inline(t) if escape else t)
        elif ch.tag in ("b", "strong"):
            parts.append(_wrap(_inline(ch, escape), "**"))
        elif ch.tag in ("i", "em"):
            parts.append(_wrap(_inline(ch, escape), "*"))
        elif ch.tag in ("code", "pre"):
            parts.append(f"`{_inline(ch, False).strip()}`")
        elif ch.tag in ("s", "strike", "del"):
            parts.append(f"~~{_inline(ch, escape).strip()}~~")
        elif ch.tag == "a":
            href = ch.attrs.get("href", "")
            label = _inline(ch, escape).strip()
            parts.append(f"[{label}]({href})" if href and href != label else label)
        else:
            parts.append(_inline(ch, escape))
    return "".join(parts)


def _clean(text):
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_MEDIA_TITLES = {
    "Photo": "Фото",
    "Video file": "Видео",
    "Voice message": "Голосовое сообщение",
    "Video message": "Видеосообщение",
    "Sticker": "Стикер",
    "Animation": "GIF",
    "File": "Файл",
}


def is_telegram_export(html_text: str) -> bool:
    head = html_text[:200000]
    return ('class="page_body chat_page"' in head or 'class="history"' in head) \
        and 'class="message' in head


def telegram_html_to_md(html_text: str, with_title: bool = True) -> str:
    builder = _DomBuilder()
    builder.feed(html_text)
    root = builder.root

    lines = []
    if with_title:
        header = _find(root, "page_header")
        if header:
            title = _find(header, "text")
            if title:
                name = _clean(_inline(title))
                if name:
                    lines.append(f"# {name}\n")

    last_author = None
    for msg in _find_all(root, "message"):
        # служебные сообщения: даты, «вошёл в группу» и т.п.
        if "service" in msg.cls:
            body = _find(msg, "body")
            text = _clean(_inline(body)) if body else ""
            if not text:
                continue
            if re.fullmatch(r"\d{1,2} \w+ \d{4}", text.replace("\\", "")):
                lines.append(f"\n## {text.replace(chr(92), '')}\n")
                last_author = None
            else:
                lines.append(f"*{text}*\n")
            continue

        body = _find(msg, "body")
        if body is None:
            continue

        from_node = _find(body, "from_name")
        author = _clean(_inline(from_node)) if from_node else None
        if author:
            last_author = author
        date_node = _find(body, "date")
        time_str = ""
        if date_node is not None:
            time_str = _clean(_inline(date_node))

        chunks = []

        fwd = _find(body, "forwarded")
        if fwd is not None:
            fwd_from = _find(fwd, "from_name")
            if fwd_from:
                chunks.append(f"> Переслано от {_clean(_inline(fwd_from))}\n")

        reply = _find(body, "reply_to")
        if reply is not None:
            quoted = _clean(_inline(reply))
            quoted = re.sub(r"\[(.+?)\]\(#go_to_message\d+\)", r"\1", quoted)
            if quoted:
                chunks.append("\n".join(f"> {ln}" for ln in quoted.split("\n")) + "\n")

        media = _find(body, "media_wrap")
        if media is not None:
            title = _find(media, "title")
            status = _find(media, "status")
            label = _clean(_inline(title)) if title else "Вложение"
            label = _MEDIA_TITLES.get(label.replace("\\", ""), label)
            detail = _clean(_inline(status)) if status else ""
            chunks.append(f"*[{label}]*" + (f" — {detail}" if detail else ""))

        for text_node in _find_all(body, "text"):
            if text_node.parent is not None and "reply_to" in text_node.parent.cls:
                continue
            t = _clean(_inline(text_node))
            if t:
                chunks.append(t)

        if not chunks:
            continue

        head = ""
        if author:
            head = f"**{author}**" + (f" · {time_str}" if time_str else "")
        elif last_author and time_str:
            head = f"**{last_author}** · {time_str}"
        if head:
            lines.append(f"\n{head}\n")
        lines.append("\n".join(chunks) + "\n")

    text = _clean("\n".join(lines))
    text = _fix_multiline_emphasis(text)
    return text + "\n"
