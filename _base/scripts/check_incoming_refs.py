#!/usr/bin/env python3
"""check_incoming_refs.py — есть ли конфиг-точки входа, ссылающиеся на путь, который собираются перенести.

ЗАЧЕМ. `PIT-126`: перенос `~/Documents/claude` в репу оборвал `~/.claude/CLAUDE.md`,
который подключал файл директивой `@` по абсолютному пути внутрь перенесённой папки —
регистр (`Claude` vs `claude`) маскировал совпадение, потому что на macOS ФС
регистронезависима. Проверялось только содержимое папки («что внутри, куда по
предмету»), не входящие ссылки («кто на неё ссылается снаружи»).

ЧТО ДЕЛАЕТ. Перед переносом каталога — grep по фиксированному списку конфиг-точек
входа (`~/.claude/CLAUDE.md` и всё, что оно подключает через `@`-директивы,
`~/.claude/settings.json`, `~/.zshrc`, `~/.zprofile`) на предмет абсолютных путей
**внутрь** перемещаемого каталога. Регистронезависимое сравнение — тот самый
класс, который спрятал находку в реальном случае.

ЗАПУСК
    check_incoming_refs.py ~/Documents/some-folder      # перед переносом
    check_incoming_refs.py --selftest                    # проверка без диска
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Точки входа, которые реально грузятся в каждую сессию Claude Code/интерактивный
# шелл — расширять по мере находки новых (PIT-126 сам называет ровно эти четыре).
ENTRY_POINTS = (
    Path.home() / ".claude" / "CLAUDE.md",
    Path.home() / ".claude" / "settings.json",
    Path.home() / ".zshrc",
    Path.home() / ".zprofile",
)

# `@/путь/к/файлу` — директива подключения в CLAUDE.md; голый абсолютный путь —
# во всех остальных точках входа.
PATH_RE = re.compile(r"[@]?(/[^\s\"'`]+)")


def find_referencing_lines(entry: Path, target: Path) -> list[tuple[int, str]]:
    if not entry.is_file():
        return []
    target_norm = str(target.resolve()).lower()
    hits = []
    for i, line in enumerate(entry.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        for m in PATH_RE.finditer(line):
            candidate = m.group(1)
            # Регистронезависимое сравнение с префиксом — именно то, что PIT-126
            # поймал бы: `Claude` vs `claude` совпадают на файловой системе macOS,
            # но не совпали бы при чувствительном к регистру сравнении строк.
            if candidate.lower().startswith(target_norm):
                hits.append((i, line.strip()))
    return hits


def check(target: Path) -> list[str]:
    problems = []
    target = target.expanduser().resolve()
    for entry in ENTRY_POINTS:
        for lineno, line in find_referencing_lines(entry, target):
            problems.append(f"{entry}:{lineno} ссылается внутрь {target}: {line}")
    return problems


def selftest() -> bool:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        # .resolve() здесь обязателен: macOS симлинкует /var -> /private/var,
        # и без резолва путь, записанный в тестовый конфиг-файл ниже (сырой tmp),
        # не совпал бы с тем, что вернёт target.resolve() внутри check() —
        # ложный провал теста по причине, не связанной с тем, что он проверяет.
        tmp_path = Path(tmp).resolve()
        target = tmp_path / "Old" / "Instructions"
        target.mkdir(parents=True)

        entry = tmp_path / "CLAUDE.md"
        entry.write_text(f"@{tmp_path}/old/instructions/context.md\n", encoding="utf-8")

        global ENTRY_POINTS
        original = ENTRY_POINTS
        ENTRY_POINTS = (entry,)
        try:
            problems = check(target)
            if len(problems) != 1:
                print(f"selftest FAIL: ожидался 1 конфликт (регистронезависимое совпадение), получено {len(problems)}")
                return False

            entry.write_text("ничего похожего здесь нет\n", encoding="utf-8")
            problems2 = check(target)
            if problems2:
                print(f"selftest FAIL: ложное совпадение там, где ссылки нет: {problems2}")
                return False
        finally:
            ENTRY_POINTS = original

    print("selftest OK: регистронезависимое совпадение поймано, чистый файл не даёт ложных срабатываний")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", type=Path, help="каталог, который собираются перенести")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return 0 if selftest() else 1

    if a.target is None:
        ap.error("укажи каталог (или --selftest)")

    problems = check(a.target)
    if not problems:
        print(f"[OK] конфиг-точки входа не ссылаются внутрь {a.target.expanduser().resolve()}")
        return 0

    print(f"[FAIL] {len(problems)} конфиг-точек ссылаются внутрь переносимого каталога — "
          f"перенос оборвёт их (PIT-126):")
    for p in problems:
        print(f"  · {p}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
