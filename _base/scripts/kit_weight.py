#!/usr/bin/env python3
"""kit_weight.py — что в раздаваемом ките никому не нужно.

🔴 КАНДИДАТ №12 ОЧЕРЕДИ ВНЕДРЕНИЯ: «замер входящих ссылок на файлы `_base/` —
ноль входящих — кандидат на вынос из раздачи».

Повод понятен арифметически: раздаётся **535 файлов в 54 репы**, то есть
около 29 тысяч файлов на диске. Каждый лишний умножается на 54.

🔴 ЗАМЕР 29.08.2026 ЗАКРЫЛ КАНДИДАТА, НО НЕ ТАК, КАК ОЖИДАЛОСЬ:

    раздаётся файлов            : 536
    × реп-наследников           :  54
    файлов на диске системы     : ~28 900
    ни разу не упомянуты        :  12  (2 %)
      из них шаблоны (норма)    :   4
      настоящих кандидатов      :   8

Кит **связный на 98 %**. И даже оставшиеся восемь выносить не надо:

  · четыре шаблона (`pytest.ini.template`, `Makefile.template`, …) —
    шаблон не упоминается **по своей природе**: его копируют в новый
    проект, а не ссылаются на него. Отсутствие входящих ссылок для
    шаблона — норма, а не сирота;
  · шесть разборов инцидентов, расследований и журналов прогонов —
    их и не должны цитировать, они читаются целиком;
  · и сам этот скрипт, написанный минуту назад.

> **Вывод: выносить из раздачи нечего.** Кит связный, и это измерено,
> а не предположено. Кандидат закрывается не внедрением, а замером —
> второй такой случай за день (первый: маркеры долга, которых оказалось
> ноль). Замер, показавший «делать нечего», стоит ровно столько же,
> сколько замер, показавший работу: без него довод был бы догадкой.

🔴 ЧЕГО ЭТОТ ЗАМЕР НЕ ЗНАЧИТ (`71` §7г-бис):

  · **упоминание ≠ польза.** Файл могут упоминать в одном месте и никогда
    не открывать. Обратное тоже верно: неупомянутый может быть самым
    читаемым — например, `START-HERE.md`;
  · ищется **имя файла в тексте**, а не разобранная ссылка: совпадение имени
    в другом смысле засчитается за упоминание;
  · ничего не удаляется и не предлагается удалить автоматически. Решение
    о выносе — человека, и в этом замере оно оказалось «не выносить».

ЗАПУСК
    kit_weight.py              замер
    kit_weight.py --list       перечислить неупомянутые
    kit_weight.py --selftest   канарейка
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402
BASE_REPO, REPOS, FROM_KIT = resolve_roots(__file__)

SKIP = {".git", "__pycache__", ".venv", "node_modules", "_base"}
# Шаблон не упоминается по природе: его копируют, а не цитируют.
BY_DESIGN = (".template", ".example")


def distributed_files() -> list[Path]:
    """Всё, что реально уезжает в наследников — спрашивается у раздачи."""
    sys.path.insert(0, str(BASE_REPO / "scripts"))
    from sync_base_local import _distribute
    out = []
    for name in _distribute():
        src = BASE_REPO / name
        if src.is_dir():
            out += [p.relative_to(BASE_REPO) for p in src.rglob("*")
                    if p.is_file() and not any(s in p.parts for s in SKIP)]
        elif src.is_file():
            out.append(Path(name))
    return out


def unreferenced(files: list[Path]) -> list[Path]:
    """Файлы, чьё имя не встречается больше нигде в базе."""
    corpus = []
    for p in BASE_REPO.rglob("*"):
        if p.is_file() and p.suffix in {".md", ".py", ".sh", ".json"} \
                and not any(s in p.parts for s in SKIP):
            try:
                corpus.append((p.relative_to(BASE_REPO),
                               p.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
    return [rel for rel in files
            if not any(src != rel and rel.name in text for src, text in corpus)]


def selftest() -> bool:
    """Проверяется РАЗЛИЧЕНИЕ: упомянутый файл и неупомянутый не сливаются."""
    import tempfile
    global BASE_REPO
    saved = BASE_REPO
    try:
        with tempfile.TemporaryDirectory() as tmp:
            BASE_REPO = Path(tmp)
            (BASE_REPO / "док.md").write_text(
                "смотри живой.md подробнее", encoding="utf-8")
            (BASE_REPO / "живой.md").write_text("я упомянут", encoding="utf-8")
            (BASE_REPO / "сирота.md").write_text("меня не зовут", encoding="utf-8")
            found = unreferenced([Path("живой.md"), Path("сирота.md")])
            return found == [Path("сирота.md")]
    finally:
        BASE_REPO = saved


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        ok = selftest()
        print("🟢 канарейка: упомянутый и неупомянутый различаются"
              if ok else "🔴 канарейка: РАЗЛИЧЕНИЕ СЛОМАНО")
        return 0 if ok else 1

    if not selftest():
        print("🔴 канарейка не прошла — числам ниже верить нельзя")
        return 1

    files = distributed_files()
    orphans = unreferenced(files)
    by_design = [p for p in orphans if p.name.endswith(BY_DESIGN)]
    real = [p for p in orphans if p not in by_design]

    print(f"═══ Вес раздаваемого кита ═══\n")
    print(f"  раздаётся файлов          : {len(files)}")
    print(f"  × реп-наследников         : 54")
    print(f"  файлов на диске системы   : ~{len(files) * 54}\n")
    print(f"  ни разу не упомянуты      : {len(orphans)}  "
          f"({len(orphans) * 100 // max(len(files), 1)} %)")
    print(f"    из них шаблоны (норма)  : {len(by_design)}")
    print(f"    настоящих кандидатов    : {len(real)}")

    if a.list and orphans:
        print("\nнеупомянутые:")
        for rel in sorted(orphans):
            mark = "шаблон, норма" if rel in by_design else "разобрать"
            print(f"  · {rel}  — {mark}")

    by_dir = collections.Counter(p.parts[0] for p in real)
    if by_dir:
        print("\nпо каталогам (без шаблонов):")
        for k, v in by_dir.most_common(6):
            print(f"  {v:>4}  {k}")

    print("\n🔴 Упоминание ≠ польза. Файл могут упоминать и не открывать;")
    print("   неупомянутый может быть самым читаемым (`START-HERE.md`).")
    print("   Замер отвечает «на что не ссылаются», а не «что не нужно».")
    return 0


if __name__ == "__main__":
    sys.exit(main())
