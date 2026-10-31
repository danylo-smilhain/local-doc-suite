"""Web page cleanup before text conversion: player UI, icons, inline images, original image URLs."""
import logging
import os
import re
import uuid

from app.config import OUTPUT_DIR
from app.encoding import read_text_file

logger = logging.getLogger(__name__)

# ============ Сохраненная веб-страница -> Markdown / TXT ============
# Расширения сохранения страниц (Save Page WE, SingleFile) и «Веб-страница
# полностью» встраивают картинки прямо в HTML как data:-URI (base64). Pandoc
# переносит их в markdown как есть — ![](data:image/jpeg;base64,/9j/4AAQ...) —
# и вместо текста файл забит сотнями килобайт «символов». Кроме того, pandoc
# превращает каждую inline-иконку <svg> в такую же base64-картинку, а из
# видеоплеера в текст попадают подсказки кнопок (Play, Mute, AirPlay, 0:00 / 6:08).
# Поэтому перед pandoc HTML очищается от интерфейса страницы
# (prepare_html_for_text), а после pandoc из markdown вычищаются data:-URI,
# если какие-то все же проскочили (strip_markdown_data_uris).

# Не содержание, а интерфейс страницы: скрипты, иконки, медиа, кнопки, поля форм.
_PAGE_UI_TAGS = (
    "script", "style", "template", "svg", "canvas", "video", "audio",
    "iframe", "frame", "object", "embed", "button", "input", "select", "textarea",
)
# ARIA-роли интерактивных виджетов: всплывающие подсказки, ползунки, меню.
_PAGE_UI_ROLES = frozenset((
    "tooltip", "slider", "progressbar", "switch", "toolbar", "menu", "menubar",
))
# Видеоплееры целиком: названия глав, таймеры, проценты громкости.
_MEDIA_PLAYER_XPATH = " | ".join((
    "//*[@data-media-player]",                          # Vidstack
    "//media-player", "//media-controller", "//mux-player",
    "//*[contains(concat(' ', normalize-space(@class), ' '), ' video-js ')]",
    "//*[contains(concat(' ', normalize-space(@class), ' '), ' plyr ')]",
    "//*[contains(concat(' ', normalize-space(@class), ' '), ' jwplayer ')]",
))
# Где расширения сохранения и «ленивая» загрузка хранят исходный адрес картинки.
_ORIGINAL_SRC_ATTRS = (
    "data-savepage-src", "data-src", "data-original", "data-lazy-src",
    "data-orig-src", "data-srcset", "srcset",
)


def _original_image_url(img):
    """Исходный http(s)-адрес картинки, сохраненной как data:-URI, или None."""
    for attr in _ORIGINAL_SRC_ATTRS:
        value = (img.get(attr) or "").strip()
        if not value or value.lower().startswith("data:"):
            continue
        if attr.endswith("srcset"):
            value = value.split()[0].rstrip(",")   # первый кандидат "url 1x, ..."
        if value.startswith("//"):
            value = "https:" + value
        if re.match(r"https?://", value, re.IGNORECASE):
            return value
    return None


def prepare_html_for_text(in_path: str):
    """HTML-страница -> временный UTF-8 HTML без base64-картинок, иконок
    и элементов управления. Возвращает путь к временному файлу или None,
    если HTML разобрать не удалось (тогда pandoc получает исходник как есть)."""
    try:
        import lxml.html
        text, _ = read_text_file(in_path)
        # huge_tree обязателен: без него libxml2 молча обрывает документ на
        # первой data:-картинке больше ~10 МБ, и весь текст после нее теряется.
        parser = lxml.html.HTMLParser(encoding="utf-8", huge_tree=True)
        root = lxml.html.document_fromstring(text.encode("utf-8"), parser=parser)

        # Расширения браузера вставляют <div> перед <head>, и тогда libxml2
        # переносит <title> в <body> — pandoc вывел бы его обычным текстом.
        doomed = list(root.xpath("//body//title"))
        doomed += root.xpath(_MEDIA_PLAYER_XPATH)
        doomed += root.xpath(" | ".join("//" + t for t in _PAGE_UI_TAGS))
        doomed += [el for el in root.xpath("//*[@role]")
                   if _PAGE_UI_ROLES.intersection((el.get("role") or "").lower().split())]
        for el in doomed:
            # getparent() is None — элемент уже удален вместе с предком.
            # drop_tree() сохраняет текст, идущий сразу после элемента.
            if el is not root and el.getparent() is not None:
                el.drop_tree()

        # Картинки-data:-URI: если известен исходный адрес — ставим его,
        # иначе картинку убираем (в markdown от base64 толку нет).
        for img in root.xpath("//img"):
            src = (img.get("src") or "").strip()
            if src and not src.lower().startswith("data:"):
                continue
            original = _original_image_url(img)
            if original:
                img.set("src", original)
                for attr in ("srcset", "data-srcset"):
                    img.attrib.pop(attr, None)
            else:
                img.drop_tree()

        # Ссылки на data:-URI (встроенные файлы) -> просто текст ссылки.
        for a in root.xpath("//a[starts-with(normalize-space(@href), 'data:')]"):
            a.drop_tag()

        html_out = lxml.html.tostring(root, encoding="unicode", method="html",
                                      doctype="<!DOCTYPE html>")
        tmp = os.path.join(OUTPUT_DIR, f"page_{uuid.uuid4()}.html")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(html_out)
        return tmp
    except Exception as e:
        logger.warning(f"Не удалось очистить HTML перед конвертацией: {e}")
        return None
