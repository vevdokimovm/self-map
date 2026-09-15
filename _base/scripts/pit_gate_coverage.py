#!/usr/bin/env python3
"""Охват реестра граблей машинными проверками — не блокирует релиз, только мерит.

ПОЧЕМУ ОТДЕЛЬНЫЙ СКРИПТ, НЕ ЧАСТЬ `revision_check.py` (которая FAIL-ит и блокирует
`pack_release.py`): на момент внедрения (27.08.2026) 137 из 137 карточек `pitfalls.md`
не размечены полем «Гейт» — жёсткая проверка сломала бы релиз в тот же день, когда
поле только завели. `08-systems-theory-lab/README.md` §5: антихрупкость должна расти
постепенно по мере реального разбора карточек, не одним рывком, который никто не
доведёт до конца.

ЧТО СЧИТАЕТ. Три состояния по каждой карточке `PIT-NNN`:
  - `да`   — поле «Гейт: да → ...», урок реально стал проверкой
  - `нет`  — поле «Гейт: нет — <причина>», осознанно решено не формализовывать
  - `TODO` — поля нет вообще (карточки до 27.08.2026) ИЛИ стоит «TODO»

ЗАПУСК
    pit_gate_coverage.py                отчёт в stdout
    pit_gate_coverage.py --oldest N     показать N старейших TODO-карточек (что разбирать первым)
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

BASE_REPO = Path(__file__).resolve().parent.parent
PITFALLS = BASE_REPO / "reports" / "pitfalls.md"

# Дата в заголовке — не гарантирована (найдено 27.08.2026: часть карточек её не
# несёт вовсе, часть несёт диапазон "2026-07-22 / 2026-07-23", не одну дату).
# Дата гейту не нужна для подсчёта — только сам номер карточки.
CARD_RE = re.compile(r"^### (PIT-\d+) — ", re.MULTILINE)
GATE_RE = re.compile(r"^\s*-\s*\*\*Гейт:\*\*\s*(да|нет|TODO)", re.MULTILINE | re.IGNORECASE)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--oldest", type=int, default=0)
    a = ap.parse_args()

    if not PITFALLS.is_file():
        print(f"нет файла: {PITFALLS}")
        return 2

    text = PITFALLS.read_text(encoding="utf-8", errors="replace")
    cards = list(CARD_RE.finditer(text))

    counts = {"да": 0, "нет": 0, "TODO": 0}
    todo_cards: list[tuple[str, str]] = []

    for i, m in enumerate(cards):
        card_id = m.group(1)
        start = m.end()
        end = cards[i + 1].start() if i + 1 < len(cards) else len(text)
        body = text[start:end]
        gm = GATE_RE.search(body)
        if not gm:
            counts["TODO"] += 1
            todo_cards.append(card_id)
            continue
        state = gm.group(1)
        state = "да" if state.lower() == "да" else ("нет" if state.lower() == "нет" else "TODO")
        counts[state] += 1
        if state == "TODO":
            todo_cards.append(card_id)

    total = len(cards)
    print(f"карточек всего: {total}")
    print(f"  да (есть проверка):  {counts['да']}")
    print(f"  нет (осознанно):     {counts['нет']}")
    print(f"  TODO (не оценено):   {counts['TODO']}")
    if total:
        pct = 100 * (counts["да"] + counts["нет"]) / total
        print(f"охват разбором: {pct:.0f}%")

    if a.oldest:
        print(f"\n{a.oldest} первых TODO по порядку в файле — разобрать первыми:")
        for card_id in todo_cards[:a.oldest]:
            print(f"  {card_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
