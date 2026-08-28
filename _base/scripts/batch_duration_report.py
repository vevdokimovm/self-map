#!/usr/bin/env python3
"""batch_duration_report.py — сколько времени реально занимают батчи авто-режима.

ЗАЧЕМ. Прямой запрос владельца, 28.08.2026: «внести механизм замера времени,
чтобы была оценка приблизительно сколько занимает то или иное действие —
чтобы проще планировать было». Новой инфраструктуры не строим — `auto_log.py`
уже пишет ISO-таймстамп на каждый батч в `06-autonomous-mode-kit/runs/auto.log`
(закон 5 кита: «записано по ходу»). Здесь — анализ уже собранных данных, не
новый сбор: разница между соседними таймстампами и есть цена шага между двумя
точками остановки.

ЧТО СЧИТАЕТСЯ ДЛИТЕЛЬНОСТЬЮ БАТЧА. Время от предыдущей строки лога (любого
типа, любой репы) до текущей — это настенное время между двумя моментами
записи состояния, не время работы одного изолированного действия. Простои
(ожидание лимита, `wait`) и параллельная работа над несколькими репами внутри
одного отрезка размывают точность — отчёт агрегирует по медиане и разбросу,
не выдаёт число как гарантию.

ЗАПУСК
    batch_duration_report.py                       # сводка по всему auto.log
    batch_duration_report.py --repo mission-control # только одна репа
    batch_duration_report.py --top 15               # N самых долгих батчей
"""
from __future__ import annotations

import argparse
import datetime
import statistics
from collections import defaultdict
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "06-autonomous-mode-kit" / "runs" / "auto.log"


def parse_log(path: Path) -> list[tuple[datetime.datetime, str, str, str]]:
    rows = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 3)
        if len(parts) != 4:
            continue
        ts_raw, repo, kind, note = parts
        try:
            ts = datetime.datetime.fromisoformat(ts_raw)
        except ValueError:
            continue
        rows.append((ts, repo, kind, note))
    return rows


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}с"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}мин"
    hours = minutes / 60
    return f"{hours:.1f}ч"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", help="показать только батчи этой репы")
    ap.add_argument("--top", type=int, default=10, help="сколько самых долгих батчей вывести")
    ap.add_argument("--log", type=Path, default=LOG)
    a = ap.parse_args()

    rows = parse_log(a.log)
    if len(rows) < 2:
        print(f"мало данных в {a.log} — нечего анализировать (нужно ≥2 строки)")
        return 1

    # Длительность каждой строки, кроме первой (у первой нет "до неё")
    entries: list[tuple[float, datetime.datetime, str, str, str]] = []
    for i in range(1, len(rows)):
        prev_ts = rows[i - 1][0]
        ts, repo, kind, note = rows[i]
        delta = (ts - prev_ts).total_seconds()
        if delta < 0:
            continue  # часы/дата съехали (ручная правка лога, смена таймзоны) — не считаем
        entries.append((delta, ts, repo, kind, note))

    if a.repo:
        entries = [e for e in entries if e[2] == a.repo]
        if not entries:
            print(f"нет записей по репе {a.repo}")
            return 1

    durations = [e[0] for e in entries]
    print(f"=== batch_duration_report.py — {a.log.name} ===")
    print(f"строк в логе: {len(rows)} · интервалов посчитано: {len(entries)}"
          + (f" (фильтр: repo={a.repo})" if a.repo else ""))
    print()
    print(f"медиана: {format_duration(statistics.median(durations))}")
    print(f"среднее: {format_duration(statistics.mean(durations))}")
    if len(durations) > 1:
        print(f"разброс (stdev): {format_duration(statistics.stdev(durations))}")
    print(f"минимум: {format_duration(min(durations))} · максимум: {format_duration(max(durations))}")
    print()

    print("--- по типу события (медиана, штук) ---")
    by_kind: dict[str, list[float]] = defaultdict(list)
    for delta, _, _, kind, _ in entries:
        by_kind[kind].append(delta)
    for kind in sorted(by_kind, key=lambda k: -len(by_kind[k])):
        vals = by_kind[kind]
        print(f"  {kind:8s}  n={len(vals):3d}  медиана={format_duration(statistics.median(vals))}")
    print()

    print("--- по репе (медиана, штук) ---")
    by_repo: dict[str, list[float]] = defaultdict(list)
    for delta, _, repo, _, _ in entries:
        by_repo[repo].append(delta)
    for repo in sorted(by_repo, key=lambda r: -len(by_repo[r]))[:15]:
        vals = by_repo[repo]
        print(f"  {repo:22s}  n={len(vals):3d}  медиана={format_duration(statistics.median(vals))}")
    print()

    print(f"--- {a.top} самых долгих интервалов (возможные простои/сложные батчи) ---")
    for delta, ts, repo, kind, note in sorted(entries, key=lambda e: -e[0])[:a.top]:
        note_short = note if len(note) <= 70 else note[:67] + "..."
        print(f"  {format_duration(delta):>8s}  {ts.isoformat(timespec='minutes')}  "
              f"{repo:20s} {kind:6s} {note_short}")

    print()
    print("🔴 Интерпретация: это настенное время между записями, не время одного",
          "изолированного действия. Долгий интервал может быть простоем (лимит,",
          "ожидание владельца) или несколькими батчами подряд без промежуточной",
          "записи — читать вместе с note, не как чистое время работы.", sep="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
