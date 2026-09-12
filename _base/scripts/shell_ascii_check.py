#!/usr/bin/env python3
"""Имена переменных в shell-скриптах — только ASCII.

🔴 ЗАЧЕМ МЕХАНИЧЕСКАЯ ПРОВЕРКА. Класс `PIT-202` повторился ТРИЖДЫ за три дня,
и каждый раз при живом красном предупреждении в соседнем файле:

  · `freeze_watch.sh`          — `пред=...`  → упал молча под `nohup`;
  · `collectors.sh`            — `КИТ=...`   → `No such file or directory`;
  · `test_attribution_guard.sh`— `БАЗА=...`  → то же самое.

Правило счётчика (`reports/incidents/PITFALLS.md`): дошёл до трёх — заплатки
не работают, нужна проверка. Вот она.

**Почему на это вообще наступают.** Рядом лежат питоновские инструменты, где
`ЖИВОСТЬ = 20_000` совершенно законно: Python допускает Unicode
в идентификаторах, POSIX shell — нет. Граница между языками невидима,
пока не наступишь, а предупреждение в шапке ОДНОГО файла не защищает соседний.

🔴 ЧЕГО НЕ ЛОВИТ: Unicode внутри строк, комментариев и значений — там он
законен и полезен (комментарии в этой системе по-русски намеренно). Ловится
только позиция ИМЕНИ: `имя=` в начале строки и `for имя in`.

Применение:
    shell_ascii_check.py [корень]      проверить
    shell_ascii_check.py --selftest    канарейка
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Присваивание в начале строки и переменная цикла — две позиции, где shell
# ждёт идентификатор. Отрицательный класс `[^\W\d]` без ASCII-флага пропускает
# кириллицу, поэтому ищем явно любой не-ASCII символ в начале имени.
ПРИСВАИВАНИЕ = re.compile(r"^\s*([^\s=#]*[^\x00-\x7F][^\s=]*)=", re.M)
ЦИКЛ = re.compile(r"^\s*for\s+([^\s]*[^\x00-\x7F][^\s]*)\s+in\b", re.M)
ФУНКЦИЯ = re.compile(r"^\s*([^\s()]*[^\x00-\x7F][^\s()]*)\s*\(\s*\)", re.M)


def проверить_текст(текст: str) -> list[tuple[int, str]]:
    """Номера строк и найденные не-ASCII идентификаторы."""
    найдено = []
    for шаблон in (ПРИСВАИВАНИЕ, ЦИКЛ, ФУНКЦИЯ):
        for m in шаблон.finditer(текст):
            строка = текст[:m.start()].count("\n") + 1
            найдено.append((строка, m.group(1)))
    return sorted(set(найдено))


def проверить(корень: Path) -> list[str]:
    беды = []
    for файл in sorted(корень.rglob("*.sh")):
        if any(ч in {".git", "node_modules", "__pycache__"} for ч in файл.parts):
            continue
        текст = файл.read_text(encoding="utf-8", errors="replace")
        for строка, имя in проверить_текст(текст):
            беды.append(f"{файл.relative_to(корень)}:{строка} — имя «{имя}» не ASCII")
    return беды


def selftest() -> bool:
    """Канарейка: отличает не-ASCII имя от Unicode в строках и комментариях."""
    плохо = проверить_текст('КИТ="/tmp"\nfor имя in a b; do :; done\nсостояние() { :; }')
    хорошо = проверить_текст('# комментарий по-русски\nMSG="строка по-русски"\nKIT=/tmp\n'
                             'for name in a b; do :; done\nstatus() { :; }')
    return len(плохо) == 3 and хорошо == []


def main() -> int:
    р = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    р.add_argument("корень", nargs="?", default=".", type=Path)
    р.add_argument("--selftest", action="store_true")
    a = р.parse_args()

    if a.selftest:
        ок = selftest()
        print("🟢 канарейка: различает имя и строку" if ок
              else "🔴 КАНАРЕЙКА УПАЛА")
        return 0 if ок else 1

    беды = проверить(a.корень)
    if беды:
        print(f"🔴 НЕ-ASCII ИМЕНА В SHELL: {len(беды)}\n")
        for беда in беды:
            print(f"   · {беда}")
        print("\n   POSIX shell разбирает «имя=1» как КОМАНДУ, а не присваивание.")
        print("   Под `nohup` это падает молча. Комментарии по-русски — можно.\n")
        return 1
    print("🟢 имена переменных в shell — только ASCII")
    return 0


if __name__ == "__main__":
    sys.exit(main())
