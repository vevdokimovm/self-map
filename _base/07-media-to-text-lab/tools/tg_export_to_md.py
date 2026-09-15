#!/usr/bin/env python3
"""Выгрузка Telegram → .md: знание вынимается, медиа остаётся снаружи.

Правило (`06-volume-compression.md` §Жёсткие правила, `00-CLAUDE-STOP.md` §3):
непереносимый тяжёлый файл сворачивается в служебку — что это, откуда, что внутри,
как воспроизвести, — а оригинал удаляется. Текст канала и есть знание; 1808 фото,
87 стикеров и 8 видео — оболочка.

Парсер идёт по структуре экспорта Telegram (div.message → div.body → div.text/date),
а не плоским вырезанием тегов: иначе автор, дата и границы сообщений схлопываются
в одну простыню, и восстановить их потом нельзя.
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

SRC = Path(sys.argv[1])
OUT = Path(sys.argv[2])

MSG = re.compile(r'<div class="message[^"]*"(.*?)(?=<div class="message |\Z)', re.S)
DATE = re.compile(r'<div class="pull_right date details" title="([^"]*)"')
FROM = re.compile(r'<div class="from_name">(.*?)</div>', re.S)
TEXT = re.compile(r'<div class="text">(.*?)</div>', re.S)
MEDIA = re.compile(r'<div class="media_wrap[^"]*">(.*?)</div>\s*</div>', re.S)
PHOTO = re.compile(r'<img class="photo"|photo_wrap|video_file_wrap|sticker_wrap')


def clean(fragment: str) -> str:
    t = re.sub(r"<br\s*/?>", "\n", fragment)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    return re.sub(r"[ \t]+", " ", t).strip()


def main() -> None:
    total = with_text = with_media = 0
    chunks: list[str] = []
    last_author = ""

    for path in sorted(SRC.glob("messages*.html"),
                       key=lambda p: (len(p.stem), p.stem)):
        raw = path.read_text(encoding="utf-8", errors="replace")
        for body in MSG.findall(raw):
            total += 1
            date = DATE.search(body)
            author = FROM.search(body)
            text = TEXT.search(body)
            if author:
                last_author = clean(author.group(1))
            has_media = bool(PHOTO.search(body))
            if has_media:
                with_media += 1
            if not text:
                continue
            content = clean(text.group(1))
            if not content:
                continue
            with_text += 1
            stamp = date.group(1).split()[0] if date else "—"
            head = f"**{stamp}**" + (f" · {last_author}" if last_author else "")
            if has_media:
                head += " · _[в оригинале было вложение]_"
            chunks.append(f"{head}\n\n{content}\n")

    OUT.write_text("\n---\n\n".join(chunks), encoding="utf-8")
    print(f"сообщений всего:      {total}")
    print(f"из них с текстом:     {with_text}   → извлечено")
    print(f"из них с вложением:   {with_media}  → отмечено пометкой, файл не переносится")
    print(f"знаков в результате:  {len(OUT.read_text(encoding='utf-8')):,}")


if __name__ == "__main__":
    main()
