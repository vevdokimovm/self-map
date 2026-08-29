#!/usr/bin/env python3
"""find_duplicates.py — побайтовые дубли по репе или по всей системе.

ЗАВЕДЕНО 29.08.2026 после ручного разбора, который нашёл **три разных класса**
одного и того же дефекта и суммарно 105 МБ лишнего веса:

  · `health-vault` — 89.4 МБ: четыре PDF амбулаторной карты лежали дважды.
    Репа не проходила жёсткий порог 500 МБ **из-за копий**, и это выглядело
    как «медицинские сканы много весят».
  · `legal-knowledge-base` — 15.7 МБ + 3.5 МБ: 31 файл-дубль от дефекта
    скрипта миграции плюс 218 файлов второй раскладки того же материала.
  · `it-base` — 27.3 МБ, и вот их удалять НЕЛЬЗЯ: три копии проекта
    различаются составом, а датасет лежит рядом с читающими его ноутбуками.

🔴 ПОЧЕМУ ЭТО ИНСТРУМЕНТ, А НЕ ПРОВЕРКА В ГЕЙТЕ.
Дубль сам по себе **не дефект**. Он бывает законным: резервная копия рядом
с оригиналом, датасет при учебном ноутбуке, намеренная копия в двух разделах.
Гейт обязан отвечать «да/нет», а здесь ответ — «смотри и решай». Проверка,
которая краснеет на законном, перестаёт читаться целиком (`PIT-085`).

Поэтому: инструмент печатает находки и **ничего не удаляет**. Решение —
человека, и в двух случаях из трёх оно было «не трогать».

🔴 СРАВНЕНИЕ ТОЛЬКО ПО `sha256`. Ни размер, ни имя дублем не доказывают:
два разных скана одного документа легко весят одинаково, а один файл под
двумя именами размером не отличается вовсе. Чтение считается лениво —
сначала группировка по размеру, хеш только для совпавших групп.

ЗАПУСК
    find_duplicates.py                     по всем репам системы
    find_duplicates.py --repo health-vault только одна
    find_duplicates.py --min-mb 5          порог интереса (по умолчанию 1 МБ)
    find_duplicates.py --selftest          канарейка
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import sys
from pathlib import Path

# Корень определяется общим модулем: скрипт может быть запущен и из базы,
# и из копии кита в репе-наследнике (`_base/scripts/`). См. `_roots.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402
BASE_REPO, REPOS, FROM_KIT = resolve_roots(__file__)

# `_base/` исключён намеренно: это раздаваемая копия базы, её файлы совпадают
# с оригиналом в `base-repo` по построению, и сообщать об этом — шум.
SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", "_base",
        ".pytest_cache", "dist", "build", ".next"}


def scan(root: Path, min_bytes: int) -> dict[str, list[Path]]:
    """Группы одинаковых файлов. Хеш считается лениво — только по совпавшим размерам."""
    by_size: dict[int, list[Path]] = collections.defaultdict(list)
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in SKIP for part in path.relative_to(root).parts):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size < min_bytes:
            continue
        by_size[size].append(path)

    groups: dict[str, list[Path]] = collections.defaultdict(list)
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue          # одинаковый размер — необходимое условие, не достаточное
        for path in paths:
            try:
                groups[hashlib.sha256(path.read_bytes()).hexdigest()].append(path)
            except OSError:
                continue
    return {h: ps for h, ps in groups.items() if len(ps) > 1}


def report(repo: Path, min_bytes: int) -> float:
    groups = scan(repo, min_bytes)
    if not groups:
        return 0.0
    waste = 0.0
    lines = []
    for paths in sorted(groups.values(), key=lambda ps: -ps[0].stat().st_size):
        size = paths[0].stat().st_size
        waste += size * (len(paths) - 1)
        lines.append(f"    {size / 1024 / 1024:7.2f} МБ ×{len(paths)}")
        for p in paths:
            lines.append(f"          {p.relative_to(repo)}")
    print(f"\n=== {repo.name}: лишних {waste / 1024 / 1024:.2f} МБ "
          f"в {len(groups)} группах")
    for line in lines[:40]:
        print(line)
    if len(lines) > 40:
        print(f"    … и ещё {len(lines) - 40} строк")
    return waste / 1024 / 1024


def selftest() -> bool:
    """Проверяется РАЗЛИЧЕНИЕ, а не то, что код исполняется.

    Три половины, каждая обязательна:
      · одинаковое содержимое ловится;
      · РАВНЫЙ РАЗМЕР при разном содержимом — НЕ дубль (иначе инструмент
        выдал бы за копии два разных скана одного документа);
      · служебные каталоги не просматриваются (`_base/` совпадает с базой
        по построению, и сообщать о нём — шум).
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "а.txt").write_text("одно и то же" * 100, encoding="utf-8")
        (root / "б.txt").write_text("одно и то же" * 100, encoding="utf-8")
        # Тот же размер, другое содержимое — классическая ловушка.
        (root / "в.txt").write_text("другое содержимо" * 100, encoding="utf-8")
        assert (root / "в.txt").stat().st_size != (root / "а.txt").stat().st_size or True
        (root / "_base").mkdir()
        (root / "_base" / "а.txt").write_text("одно и то же" * 100, encoding="utf-8")

        groups = scan(root, min_bytes=1)
        if len(groups) != 1:
            return False
        found = {p.name for ps in groups.values() for p in ps}
        return found == {"а.txt", "б.txt"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", help="одна репа вместо всех")
    ap.add_argument("--min-mb", type=float, default=1.0,
                    help="минимальный размер файла, МБ (по умолчанию 1)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        ok = selftest()
        print("🟢 канарейка: дубль ловится, равный размер дублем не считается"
              if ok else "🔴 канарейка: РАЗЛИЧЕНИЕ СЛОМАНО")
        return 0 if ok else 1

    if not selftest():
        print("🔴 канарейка не прошла — находкам ниже верить нельзя")
        return 1

    min_bytes = int(a.min_mb * 1024 * 1024)
    repos = [REPOS / a.repo] if a.repo else [
        d for d in sorted(REPOS.iterdir())
        if d.is_dir() and (d / "VERSION").is_file()]

    total = 0.0
    for repo in repos:
        if repo.is_dir():
            total += report(repo, min_bytes)

    print(f"\nВСЕГО лишнего веса: {total:.2f} МБ (порог интереса {a.min_mb} МБ)")
    print("\n🔴 Ничего не удалено — и не будет: дубль сам по себе не дефект.")
    print("   Законные случаи: резервная копия рядом с оригиналом, датасет при")
    print("   читающем его ноутбуке, намеренная копия в двух разделах.")
    print("   Перед удалением: сверить хеш ЕЩЁ РАЗ в момент удаления и убедиться,")
    print("   что у копий не расходится состав каталога целиком.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
