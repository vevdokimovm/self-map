#!/usr/bin/env python3
"""dedup.py — удаляет ПОБАЙТОВЫЕ дубли документов, оставляя один эталон.

🔴 ПОВОД. 05.09.2026 владелец: «удали плохие дубликаты… оставь только
оригиналы эталоны мед доков лучшие… остальное удали, и только заметки
к каждому должны быть».

ЧТО СЧИТАЕТСЯ ДУБЛЕМ. Только совпадение **md5 всего файла**. Похожие имена,
близкий размер, «тот же документ в другом качестве» — НЕ дубли: у них разное
содержание, и решает их сравнение читаемости, а не эта программа (`65` §6.1б-3).

КАКОЙ ЭКЗЕМПЛЯР ОСТАЁТСЯ ЭТАЛОНОМ. Порядок предпочтения:
  1. вне `reports/imports/` — тематический раздел важнее папки импорта;
  2. вне `sergastokh/` — общий импорт важнее личного подкаталога;
  3. более короткий путь.
Импорт — это входящий поток; после раскладки по разделам копия в нём
избыточна, а оригинал живёт там, где ему место по смыслу.

🔴 ПУСТЫЕ ФАЙЛЫ ПРОПУСКАЮТСЯ. Два пустых файла имеют одинаковый md5,
но это не дубли: `ecg-*.csv` и `heartratenotifications-*.csv` называют
разные выгрузки Apple Health, обе пустые. Удалить один как «дубль»
значило бы стереть след того, что выгрузка вообще запрашивалась.

ЗАПУСК
    dedup.py            показать план, ничего не трогая
    dedup.py --apply    удалить
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".docx", ".xlsx", ".heic",
              ".ogg", ".vcf", ".mp4", ".mov"}
SKIP_PARTS = {"_base", ".git", "node_modules", "web"}


def file_hash(path: Path) -> str:
    """Посчитать md5 файла блоками, не поднимая его целиком в память."""
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rank(path: Path) -> tuple:
    """Ключ сортировки: чем меньше, тем вероятнее эталон."""
    s = str(path)
    return ("reports/imports" in s, "sergastokh" in s, len(s))


def collect() -> dict[str, list[Path]]:
    """Сгруппировать файлы репы по md5, пропустив пустые и служебные."""
    groups: dict[str, list[Path]] = {}
    for path in sorted(REPO.rglob("*")):
        if not path.is_file():
            continue
        if SKIP_PARTS & set(path.parts):
            continue
        if path.suffix.lower() not in EXTENSIONS:
            continue
        if path.stat().st_size == 0:
            continue
        groups.setdefault(file_hash(path), []).append(path)
    return {h: v for h, v in groups.items() if len(v) > 1}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="удалить (без флага — только показать план)")
    args = ap.parse_args()

    groups = collect()
    if not groups:
        print("побайтовых дублей нет")
        return 0

    freed = 0
    removed = 0
    for _, paths in sorted(groups.items(), key=lambda kv: -kv[1][0].stat().st_size):
        keep = sorted(paths, key=rank)[0]
        print(f"\nЭТАЛОН  {keep.relative_to(REPO)}")
        for path in paths:
            if path == keep:
                continue
            size = path.stat().st_size
            print(f"  {'удалён' if args.apply else 'удалить'}: {path.relative_to(REPO)}")
            if args.apply:
                path.unlink()
            freed += size
            removed += 1

    verb = "освобождено" if args.apply else "освободится"
    print(f"\n  файлов: {removed} · {verb}: {freed / 1024 / 1024:.2f} МБ")
    if not args.apply:
        print("  это план. Удалить: dedup.py --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
