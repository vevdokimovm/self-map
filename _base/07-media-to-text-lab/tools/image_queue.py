#!/usr/bin/env python3
"""image_queue.py — очередь на описание изображений: по СЕРИЯМ, а не по файлам.

🔴 ПОВОД. 23.08.2026 задача «перевести изображения в служебные заметки» была подменена
сжатием: скрипт менял вес файлов и писал паспорта с мегабайтами, ни слова не говоря
о содержании. Метод — `../METHOD_IMAGES.md`.

ЧТО ДЕЛАЕТ. Не описывает — **готовит работу**: находит серии, отбрасывает то, что знания
не несёт, отмечает уже описанное и печатает очередь. Смотрит и пишет заметку **вахта**:
у изображения нет текстового слоя, доставать нечего, нужен взгляд.

ЕДИНИЦА — СЕРИЯ (`METHOD_IMAGES.md` §3). Билет снят восемью кадрами, вопрос виден
на двух частями. Пофайловая заметка не может сказать, что на билете: первая попытка
дала «8 заданий», при том что их 15.

ОТБОР (§8). Иконки, логотипы, ассеты вёрстки и дубликаты кадров выбывают: описать
3 400 изображений, из которых 2 000 — элементы интерфейса, значит повторить подмену,
только дороже.

ЗАПУСК
    image_queue.py                       очередь по всей системе
    image_queue.py --repo family         по одной репе
    image_queue.py --repo family -v      с перечнем файлов серии
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path

BASE_REPO = Path(__file__).resolve().parent.parent.parent
REPOS = BASE_REPO.parent
SKIP_PARTS = {"_base", ".git", "node_modules", ".venv", "__pycache__",
              "build", "dist", "assets", "static", "public", ".next"}
IMG = {".jpg", ".jpeg", ".png", ".heic", ".tiff", ".tif", ".webp"}

# Заметки, которые описывают СЕРИЮ целиком — их наличие снимает серию с очереди.
SERIES_NOTES = ("raspoznavanie.md", "razbor.md", "notes.md", "recognition_report.md",
                "ORIGINALS.md", "opisanie.md")

# Знания не несут: элементы интерфейса и вёрстки (§8).
JUNK_NAME = re.compile(r"(icon|logo|favicon|sprite|badge|avatar-default|placeholder|"
                       r"bg-|button|arrow|chevron|spinner|thumb_)", re.I)
JUNK_SMALL = 30 * 1024          # меньше 30 КБ — почти наверняка элемент интерфейса

# Дубликаты кадров серии: описан оригинал, производные не описываются.
DERIVED = re.compile(r"^(crop|thumb|small|preview|copy|resized)[-_]", re.I)


def described(series: Path) -> str | None:
    """Есть ли заметка на серию — рядом или уровнем выше."""
    for d in (series, series.parent):
        for name in SERIES_NOTES:
            if (d / name).exists():
                return str((d / name).relative_to(REPOS))
    return None


def collect(repo: Path) -> dict[Path, list[Path]]:
    series: dict[Path, list[Path]] = defaultdict(list)
    for p in repo.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in IMG:
            continue
        if any(x in p.parts for x in SKIP_PARTS):
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_blocks == 0:                 # заглушка iCloud (PIT-135)
            continue
        if JUNK_NAME.search(p.name) or st.st_size < JUNK_SMALL:
            continue
        if DERIVED.match(p.name):
            continue
        series[p.parent].append(p)
    return series


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    targets = ([REPOS / a.repo] if a.repo
               else sorted(d for d in REPOS.iterdir() if d.is_dir() and not (d / ".git").exists()))

    tq = tf = dq = df = 0
    rows = []
    for repo in targets:
        if not repo.is_dir():
            continue
        for folder, files in sorted(collect(repo).items()):
            note = described(folder)
            rel = folder.relative_to(REPOS)
            mb = sum(f.stat().st_size for f in files) / 2**20
            if note:
                dq += 1
                df += len(files)
                continue
            tq += 1
            tf += len(files)
            rows.append((len(files), mb, rel, files))

    rows.sort(reverse=True, key=lambda r: r[0])
    for n, mb, rel, files in rows:
        print(f"  {n:>4} кадр · {mb:>7.1f} МБ · {rel}")
        if a.verbose:
            for f in files[:12]:
                print(f"         {f.name}")
            if len(files) > 12:
                print(f"         … ещё {len(files) - 12}")

    print(f"\n  серий в очереди: {tq} · кадров: {tf}")
    print(f"  уже описано: {df} кадров в {dq} сериях")
    print("  🔴 Очередь — не описание. Смотрит и пишет вахта: у картинки нет текстового слоя.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
