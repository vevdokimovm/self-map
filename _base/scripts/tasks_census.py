#!/usr/bin/env python3
"""tasks_census.py — перепись всех открытых задач системы в одной картине.

ЗАКАЗ ВЛАДЕЛЬЦА 22.08.2026: «обнови роадмапы, таски, бэклоги, чтобы нахер не путалось
и не терялось ничего, почему абардак такой».

ПОЧЕМУ БАРДАК — ИЗМЕРЕНО, А НЕ ОБЪЯВЛЕНО. Задачи живут в четырёх независимых местах:

    base-repo/ROADMAP.md      работа над инфраструктурой системы
    base-repo/TASKS.md        то, что требует решения ВЛАДЕЛЬЦА
    mission-control/BOARD.md  доска планировщика, срез на репу
    <репа>/ROADMAP.md|TASKS.md  работа внутри конкретной репы

Ни одно из них не знает про остальные. Замер 22.08.2026: **719** открытых задач в 41 репе,
**94** в базе, **178** строк на доске — почти тысяча пунктов, и ни одного места, где
видно всё сразу. Задача, названная в чате, оседает в том файле, который случайно открыт,
или не оседает нигде.

ЧТО ДЕЛАЕТ ЭТОТ СКРИПТ. Не заводит пятое место — он **читает все четыре** и отвечает
на вопросы, на которые иначе нельзя ответить:

  · сколько открытого и где именно;
  · какие репы имеют задачи на доске, но не имеют своих файлов (задача не доедет);
  · какие репы имеют файлы, но отсутствуют на доске (работа невидима планировщику);
  · какие задачи выглядят дублями между уровнями (одна работа в двух списках).

🔴 ГРАНИЦА, НАЗВАННАЯ ВСЛУХ (`71` §7г-бис): скрипт **не сливает** списки и не решает,
где чему место. Слияние — суждение вахты; здесь только измерение, на которое суждение
опирается. Инструмент, притворяющийся, что решает второе, был бы хуже отсутствия.

ЗАПУСК:
    tasks_census.py            сводка
    tasks_census.py --dupes    показать похожие формулировки между уровнями
    tasks_census.py --repo ИМЯ разрез по одной репе
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

BASE = Path.home() / "Documents" / "base-repo"
REPOS = Path.home() / "Documents" / "система_репозиториев"
BOARD = REPOS / "mission-control" / "BOARD.md"

OPEN_RE = re.compile(r"^\s*[-*]\s*\[ \]\s*(.+)$")
# Приоритет бывает и прочерком: «| — | 👤 | Видео протестантизм |» — задача без
# назначенного приоритета. Первая редакция ждала строго `П\d` и такие строки не видела,
# из-за чего три репы с живыми секциями показывались как «доска не знает» (найдено 22.08).
BOARD_ROW = re.compile(r"^\|\s*(П\d|—|-)\s*\|\s*([^|]*)\|\s*(.+?)\s*\|")
SECTION = re.compile(r"^##\s+(\S+)")


def strip_md(s: str) -> str:
    s = re.sub(r"[*`_🔴🆕✅🏁📊📍🗂️⚠️]", "", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def read_open(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [m.group(1).strip()
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if (m := OPEN_RE.match(line))]


def read_board() -> dict[str, list[tuple[str, str, str]]]:
    """Доска: секция = репа, строки таблицы = задачи с приоритетом и исполнителем."""
    out: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    if not BOARD.is_file():
        return out
    current = None
    for line in BOARD.read_text(encoding="utf-8", errors="replace").splitlines():
        if m := SECTION.match(line):
            current = m.group(1).strip()
        elif current and (m := BOARD_ROW.match(line)):
            out[current].append((m.group(1), m.group(2).strip(), m.group(3).strip()))
    return out


def collect() -> tuple[dict, dict, dict]:
    base = {
        "ROADMAP.md": read_open(BASE / "ROADMAP.md"),
        "TASKS.md": read_open(BASE / "TASKS.md"),
    }
    per_repo: dict[str, dict[str, list[str]]] = {}
    if REPOS.is_dir():
        for d in sorted(REPOS.iterdir()):
            if not d.is_dir():
                continue
            found = {f: read_open(d / f) for f in ("ROADMAP.md", "TASKS.md")}
            if any(found.values()) or (d / "ROADMAP.md").is_file():
                per_repo[d.name] = found
    return base, per_repo, read_board()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dupes", action="store_true", help="похожие формулировки между уровнями")
    p.add_argument("--repo", metavar="ИМЯ", help="разрез по одной репе")
    a = p.parse_args()

    base, per_repo, board = collect()

    if a.repo:
        r = a.repo
        print(f"── {r}")
        for f, items in per_repo.get(r, {}).items():
            print(f"  {f}: {len(items)} открытых")
            for it in items[:10]:
                print(f"    · {it[:96]}")
        print(f"  доска: {len(board.get(r, []))} задач")
        for pr, who, txt in board.get(r, []):
            print(f"    [{pr}] {who} {txt[:88]}")
        return 0

    nb = sum(len(v) for v in base.values())
    nr = sum(len(x) for v in per_repo.values() for x in v.values())
    nbo = sum(len(v) for v in board.values())
    print("── ПЕРЕПИСЬ ОТКРЫТЫХ ЗАДАЧ\n")
    print(f"  base-repo/ROADMAP.md      {len(base['ROADMAP.md']):>5}")
    print(f"  base-repo/TASKS.md        {len(base['TASKS.md']):>5}   (ждут владельца)")
    print(f"  по репам (файлы)          {nr:>5}   в {len(per_repo)} репах")
    print(f"  доска BOARD.md            {nbo:>5}   в {len(board)} секциях")
    print(f"  {'ВСЕГО':<24}{nb + nr + nbo:>5}\n")

    print("── ТОП-10 РЕП ПО ОБЪЁМУ ОТКРЫТОГО")
    tops = sorted(((sum(len(x) for x in v.values()), k) for k, v in per_repo.items()),
                  reverse=True)[:10]
    for n, k in tops:
        print(f"  {k:<26}{n:>5}")

    # 🔴 Два разрыва между доской и репами — каждый означает потерянную работу
    on_board = set(board)
    with_files = {k for k, v in per_repo.items() if any(v.values())}
    all_repos = {d.name for d in REPOS.iterdir() if d.is_dir()} if REPOS.is_dir() else set()

    orphan_board = sorted(on_board - all_repos)
    no_files = sorted(on_board & all_repos - with_files)
    invisible = sorted(with_files - on_board)

    print(f"\n── РАЗРЫВЫ")
    print(f"  секций доски без репы на диске:      {len(orphan_board):>4}"
          + (f"  ({', '.join(orphan_board[:6])})" if orphan_board else ""))
    print(f"  на доске есть, своих файлов нет:     {len(no_files):>4}"
          + (f"  ({', '.join(no_files[:6])})" if no_files else ""))
    print(f"  работа идёт, но доска не знает:      {len(invisible):>4}"
          + (f"  ({', '.join(invisible[:6])})" if invisible else ""))
    print(f"  реп без ROADMAP и TASKS вовсе:       {len(all_repos - set(per_repo)):>4}")

    if a.dupes:
        print("\n── ПОХОЖИЕ ФОРМУЛИРОВКИ МЕЖДУ УРОВНЯМИ (порог 0.72)")
        base_all = [(f"base/{f}", t) for f, items in base.items() for t in items]
        board_all = [(f"board/{r}", t) for r, rows in board.items() for _, _, t in rows]
        shown = 0
        for src, t1 in base_all:
            n1 = strip_md(t1)
            if len(n1) < 25:
                continue
            for dst, t2 in board_all:
                n2 = strip_md(t2)
                if len(n2) < 25:
                    continue
                if SequenceMatcher(None, n1[:120], n2[:120]).ratio() >= 0.72:
                    print(f"  {src} ↔ {dst}\n    · {t1[:88]}\n    · {t2[:88]}")
                    shown += 1
                    if shown >= 15:
                        print("  … показаны первые 15")
                        return 0
        if not shown:
            print("  совпадений выше порога нет")
    else:
        print("\n  Похожие формулировки между уровнями:  --dupes")
        print("  Разрез по одной репе:                 --repo ИМЯ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
