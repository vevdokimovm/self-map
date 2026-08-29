#!/usr/bin/env python3
"""owner_blockers.py — свод открытых блокировок владельца по всем репам системы.

ЗАЧЕМ (ROADMAP.md: «Свести блокировки владельца по всей системе в одно место»).
Найдено 22.08.2026: `money`, `productivity`, `career` — три репы класса `core` —
18 дней стояли на одной и той же строке `TASKS.md` («прислать исходные материалы»).
Каждая репа знает про свою блокировку; «N реп ждут одного действия» не видел никто —
блокировки живут по репам, а решение о них принимает один человек в одном месте.

ЧТО ДЕЛАЕТ. Сканирует `TASKS.md` каждой репы (`- [ ]` пункты, с абзацем-продолжением
до следующего пункта/пустой строки), группирует по нормализованному тексту первой
строки пункта (case-insensitive, схлопнутые пробелы) — одинаковая формулировка из
разных реп попадает в одну группу с числом реп и списком.

ЗАПУСК
    python3 scripts/owner_blockers.py            репорт по убыванию размера группы
    python3 scripts/owner_blockers.py --csv       машинный вывод
"""
from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path

# Корень определяется общим модулем: скрипт может быть запущен и из базы,
# и из копии кита в репе-наследнике (`_base/scripts/`). См. `_roots.py`.
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402
BASE_REPO, REPOS, FROM_KIT = resolve_roots(__file__)

ITEM_RE = re.compile(r"^- \[ \]\s*(.+)$")


def normalize(text: str) -> str:
    text = re.sub(r"\*\*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.lower()


def extract_items(tasks_file: Path) -> list[str]:
    items = []
    for line in tasks_file.read_text(encoding="utf-8", errors="replace").splitlines():
        m = ITEM_RE.match(line)
        if m:
            items.append(m.group(1).strip())
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", action="store_true")
    a = ap.parse_args()

    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    repos_scanned = 0
    repos_with_tasks = 0

    for d in sorted(REPOS.iterdir()):
        if not d.is_dir():
            continue
        repos_scanned += 1
        tasks_file = d / "TASKS.md"
        if not tasks_file.is_file():
            continue
        repos_with_tasks += 1
        for item in extract_items(tasks_file):
            key = normalize(item)
            groups[key].append((d.name, item))

    ranked = sorted(groups.items(), key=lambda kv: -len(kv[1]))

    if a.csv:
        print("group_size,repos,sample_text")
        for key, entries in ranked:
            repos_list = ";".join(r for r, _ in entries)
            sample = entries[0][1].replace(",", ";")
            print(f"{len(entries)},{repos_list},{sample}")
        return 0

    print(f"репов просканировано: {repos_scanned} · с TASKS.md: {repos_with_tasks}")
    print(f"уникальных формулировок: {len(groups)} · пунктов всего: "
          f"{sum(len(v) for v in groups.values())}\n")

    multi = [(k, v) for k, v in ranked if len(v) > 1]
    print(f"=== Повторяющиеся блокировки — {len(multi)} групп ===\n")
    for key, entries in multi:
        repos_list = ", ".join(r for r, _ in entries)
        print(f"  [{len(entries)} репов] {entries[0][1]}")
        print(f"    → {repos_list}\n")

    if not a.csv:
        biggest = len(multi[0][1]) if multi else 0
        _record_liveness(f"{biggest} реп в крупнейшей группе, {len(multi)} групп")
    return 0


def _record_liveness(summary: str) -> None:
    """Признак живости (`08-automation-triggers.md`) — не тихая автоматизация."""
    import datetime
    import re

    path = BASE_REPO / "reports" / "infra-liveness.md"
    if not path.is_file():
        return
    today = datetime.date.today().isoformat()
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(\| `scripts/owner_blockers\.py` \| )[^|]+( \| )[^|]+( \|)"
    )
    new_text, n = pattern.subn(rf"\g<1>{today}\g<2>{summary}\g<3>", text)
    if n:
        path.write_text(new_text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
