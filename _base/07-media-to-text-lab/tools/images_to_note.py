#!/usr/bin/env python3
"""images_to_note.py — изображения: паспорт, сжатие, и честная граница.

🔴 ПОВОД. Ревизия содержимого перевела в текст 543 документа, но изображения ей
не поддаются: у них **нет текстового слоя**. Замер 23.08.2026 по системе:

    3 427 изображений · 769 тяжелее 0.5 МБ · суммарно 1 251 МБ

Канон (`_base/00-infrastructure/06-volume-compression.md`): картинка в репе — иллюстрация
к тексту, **≤0.5 МБ**, а не фотоальбом. Скриншот интерфейса на 9 МБ нарушает это
в восемнадцать раз, ничего не добавляя к содержанию.

ЧТО ДЕЛАЕТ

  1. **Паспорт** рядом с файлом: размеры, вес, тип, где лежит, чем открыть.
  2. **Сжатие** через `sips` (системная утилита macOS) — до порога, с сохранением
     пропорций. Оригинал уходит в `~/Documents/_heavy-originals/`, **не удаляется**.
  3. Ничего не делает с тем, что **уже** укладывается в порог.

🔴 ГРАНИЦА, НАЗВАННАЯ ВСЛУХ (`71` §7г-бис). Скрипт **не описывает, что на картинке**.
Он меняет вес и пишет паспорт. Описание содержания — работа модели, которая изображение
видит; для этого нужен отдельный проход, и он в `README.md` §5 числится ненаписанным.

> **Сжать картинку и понять картинку — разные задачи.** Первая механическая и делается
> здесь. Вторая требует зрения и остаётся за вахтой.

ПОЧЕМУ СЖАТИЕ БЕЗОПАСНО — и когда нет:

| Случай | Решение |
|---|---|
| скриншот интерфейса, фото документа | сжать: текст остаётся читаемым при 2000 px |
| фотография предка, скан рукописи | 🔴 **не сжимать**: единственный экземпляр, деталь может понадобиться |
| диаграмма, схема | сжать осторожно: мелкие подписи страдают первыми |

Поэтому по умолчанию скрипт работает **только** с явно названными каталогами,
а `--all` требует подтверждения глазами: что попадает под сжатие, видно в сухом прогоне.

ЗАПУСК
    images_to_note.py --repo misc-vault                что будет сделано
    images_to_note.py --repo misc-vault --apply        сжать и описать
    images_to_note.py --repo misc-vault --note-only    только паспорта, без сжатия
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

BASE_REPO = Path(__file__).resolve().parent.parent.parent
REPOS = BASE_REPO.parent
VAULT = Path.home() / "Documents" / "_heavy-originals"
SKIP_PARTS = {"_base", ".git", "node_modules", ".venv", "__pycache__"}
IMG = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic"}

THRESHOLD = 512 * 1024          # порог канона: 0.5 МБ
MAX_SIDE = 2000                 # длинная сторона после сжатия

# 🔴 Каталоги, где сжатие ЗАПРЕЩЕНО: единственные экземпляры, деталь важна.
NO_COMPRESS = ("04-photos", "primary-sources", "03-primary-sources",
               "genetics", "02-genetics", "medical-records", "rukopis")


def dims(p: Path) -> tuple[int, int] | None:
    try:
        r = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(p)],
                           capture_output=True, text=True, timeout=30)
        w = h = None
        for line in r.stdout.splitlines():
            if "pixelWidth:" in line:
                w = int(line.split(":")[1])
            elif "pixelHeight:" in line:
                h = int(line.split(":")[1])
        return (w, h) if w and h else None
    except Exception:
        return None


def protected(p: Path) -> bool:
    return any(part in str(p) for part in NO_COMPRESS)


def note(p: Path, size: int, wh: tuple[int, int] | None,
         new_size: int | None, moved: Path | None) -> str:
    d = f"{wh[0]}×{wh[1]} px" if wh else "не измерены"
    lines = [
        f"# {p.stem} — паспорт изображения",
        "",
        "| | |",
        "|---|---|",
        f"| файл | `{p.name}` |",
        f"| размеры | {d} |",
        f"| вес | {size / 2**20:.1f} МБ |",
    ]
    if new_size is not None:
        lines.append(f"| после сжатия | **{new_size / 2**20:.2f} МБ** "
                     f"(в {size / new_size:.1f} раза меньше) |")
    if moved:
        lines.append(f"| оригинал | `{moved}` — вынесен, не удалён |")
    lines += [
        "",
        "## Что здесь НЕ написано",
        "",
        "🔴 **Содержание изображения не описано.** Этот файл — паспорт: вес, размеры, где",
        "лежит оригинал. Что именно на картинке, знает только тот, кто её видел.",
        "",
        "> **Сжать картинку и понять картинку — разные задачи.** Первая механическая",
        "> и сделана здесь. Вторая требует зрения и остаётся за вахтой.",
        "",
        "Описание появится, когда лабораторией будет пройден проход «изображение → текст»",
        "(`_base/07-media-to-text-lab/README.md` §5).",
    ]
    return "\n".join(lines) + "\n"


def process(repo: Path, apply: bool, note_only: bool) -> tuple[int, int, int, float]:
    done = skipped = prot = 0
    saved = 0.0
    for p in sorted(repo.rglob("*")):
        if not p.is_file() or any(x in p.parts for x in SKIP_PARTS):
            continue
        if p.suffix.lower() not in IMG:
            continue
        try:
            size = p.stat().st_size
            if p.stat().st_blocks == 0:       # заглушка iCloud (PIT-135)
                skipped += 1
                continue
        except OSError:
            continue
        if size <= THRESHOLD:
            continue
        out = p.with_suffix(p.suffix + ".md")
        if out.exists():
            skipped += 1
            continue

        if protected(p):
            prot += 1
            if apply:
                out.write_text(note(p, size, dims(p), None, None), encoding="utf-8")
            continue

        if not apply:
            done += 1
            saved += size / 2**20
            continue

        wh = dims(p)
        moved = None
        new_size = None
        if not note_only:
            dest = VAULT / repo.name / p.relative_to(repo)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
            moved = dest
            r = subprocess.run(["sips", "-Z", str(MAX_SIDE), str(p)],
                               capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                new_size = p.stat().st_size
                saved += (size - new_size) / 2**20
            else:
                shutil.copy2(dest, p)          # откат: оригинал вернулся на место
                moved = None
        out.write_text(note(p, size, wh, new_size, moved), encoding="utf-8")
        done += 1
    return done, skipped, prot, saved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--note-only", action="store_true")
    a = ap.parse_args()

    targets = ([REPOS / a.repo] if a.repo
               else sorted(d for d in REPOS.iterdir() if d.is_dir()) if a.all else [])
    if not targets:
        ap.error("нужен --repo ИМЯ или --all")

    td = ts = tp = 0
    tsaved = 0.0
    for t in targets:
        if not t.is_dir():
            continue
        d, s, pr, sv = process(t, a.apply, a.note_only)
        if d or pr:
            print(f"  {t.name:<26} обработано {d:>4} · защищено {pr:>3} · пропущено {s:>4}")
        td += d
        ts += s
        tp += pr
        tsaved += sv

    print(f"\n  обработано: {td} · защищено от сжатия: {tp} · пропущено: {ts}")
    print(f"  освобождено: {tsaved:.0f} МБ")
    if not a.apply:
        print("  (сухой прогон; --apply чтобы сделать)")
    else:
        print(f"  оригиналы: {VAULT}")
        print("  🔴 Содержание изображений НЕ описано — это работа модели, не скрипта.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
