#!/usr/bin/env python3
"""rename_user_paths.py — заменить старое имя пользователя в путях по всем репам.

ЗАКАЗ ВЛАДЕЛЬЦА 02.09.2026: «поменял имя с vasyaevdokimov на vasiliievdokimov,
и заодно все пути в документации где они указаны аккуратно».

🔴 СКРИПТ НЕ МЕНЯЕТ ИМЯ УЧЁТНОЙ ЗАПИСИ. Переименование пользователя macOS —
необратимое системное действие: оно меняет `/Users/<имя>`, права доступа,
привязки связки ключей и путей приложений. Его делает владелец вручную,
по инструкции `it-base/05-tech-guides/macos-username-change.md`.

Здесь — только текст в файлах, и только после того, как имя уже сменено.

ПРЕДУСЛОВИЯ (проверяются до первой записи):
  · старое и новое имя заданы и различаются;
  · корень с репами существует;
  · 🔴 без `--force` скрипт ОТКАЗЫВАЕТСЯ работать, если имя ещё не сменено:
    правка путей раньше переименования сделает документацию неверной
    относительно живой системы, а не после неё.

ПОСТУСЛОВИЯ:
  · в изменённых файлах старого пути не осталось;
  · напечатан отчёт: сколько файлов, сколько вхождений, что пропущено и почему.

ИНВАРИАНТ: файлы истории (`CHANGELOG`, `WATCHLOG`, `reports/`, `*_HISTORY`)
НЕ правятся никогда. Там путь — свидетельство о прошлом состоянии, а не
инструкция. Переписать его значило бы задним числом изменить показания.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# 🔴 История не правится. Запись «22.08.2026 путь был /Users/старое» остаётся
# верной после переименования: тогда он таким и был. Правка превратила бы
# журнал в реконструкцию (`71` §5д — опровержение пишется поверх, не вместо).
HISTORY_MARKERS = ("CHANGELOG", "WATCHLOG", "_HISTORY", "/reports/",
                   "ROADMAP_HISTORY", "TASKS_HISTORY")

# Раздаваемая копия канона: правится в источнике, а не в наследниках.
SKIP_DIRS = ("_base", ".git", "node_modules", "__pycache__", ".venv")

TEXT_SUFFIXES = (".md", ".py", ".sh", ".txt", ".json", ".toml", ".yml", ".yaml",
                 ".cfg", ".ini", ".html", ".js", ".css")


def is_history(path: Path) -> bool:
    p = str(path)
    return any(m in p for m in HISTORY_MARKERS)


def scan(root: Path, old: str) -> tuple[list[Path], list[Path], int]:
    """Возвращает (что править, что пропустить как историю, всего вхождений)."""
    to_fix, history, total = [], [], 0
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix not in TEXT_SUFFIXES:
            continue
        if any(f"/{d}/" in str(p) or str(p).endswith(f"/{d}") for d in SKIP_DIRS):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        n = text.count(old)
        if not n:
            continue
        total += n
        (history if is_history(p) else to_fix).append(p)
    return to_fix, history, total


def main() -> int:
    ap = argparse.ArgumentParser(description="Замена имени пользователя в путях")
    ap.add_argument("--old", default="vasyaevdokimov", help="прежнее короткое имя")
    ap.add_argument("--new", default="vasiliievdokimov", help="новое короткое имя")
    ap.add_argument("--root", default=str(Path.home() / "repos"), help="корень с репами")
    ap.add_argument("--apply", action="store_true",
                    help="записать изменения (по умолчанию — только показать)")
    ap.add_argument("--force", action="store_true",
                    help="работать, даже если имя ещё не сменено в системе")
    args = ap.parse_args()

    # ── предусловия, все до единой записи
    if args.old == args.new:
        print("🔴 Старое и новое имя совпадают — менять нечего.", file=sys.stderr)
        return 2
    root = Path(args.root)
    if not root.is_dir():
        print(f"🔴 Нет каталога: {root}", file=sys.stderr)
        return 2

    current = os.environ.get("USER") or Path.home().name
    if current != args.new and not args.force:
        print(f"🔴 ОСТАНОВЛЕНО: имя учётной записи всё ещё «{current}», "
              f"а не «{args.new}».\n"
              f"   Правка путей ДО переименования сделает документацию неверной\n"
              f"   относительно живой системы. Сначала смените имя\n"
              f"   (it-base/05-tech-guides/macos-username-change.md), потом запустите это.\n"
              f"   Если так и задумано — повторите с --force.", file=sys.stderr)
        return 1

    to_fix, history, total = scan(root, args.old)

    print(f"Замена «{args.old}» → «{args.new}» в {root}\n")
    print(f"  всего вхождений:      {total}")
    print(f"  файлов под правку:    {len(to_fix)}")
    print(f"  файлов истории:       {len(history)} — 🔴 НЕ правятся")

    if history:
        print("\n  История (путь остаётся как свидетельство о прошлом):")
        for p in history[:8]:
            print(f"      {p.relative_to(root)}")
        if len(history) > 8:
            print(f"      … и ещё {len(history) - 8}")

    if not args.apply:
        print("\n🟡 Это осмотр. Записать: тот же вызов с --apply")
        return 0

    changed = 0
    for p in to_fix:
        try:
            text = p.read_text(encoding="utf-8")
            p.write_text(text.replace(args.old, args.new), encoding="utf-8")
            changed += 1
        except (OSError, UnicodeDecodeError) as exc:
            print(f"  🔴 не записан {p}: {exc}", file=sys.stderr)

    # ── постусловие: старого пути в поправленных файлах не осталось
    left = sum(1 for p in to_fix if args.old in p.read_text(encoding="utf-8", errors="ignore"))
    print(f"\n  изменено файлов: {changed} из {len(to_fix)}")
    if left:
        print(f"  🔴 в {left} файлах старое имя осталось — проверить вручную")
        return 1
    print("  🟢 старого имени в поправленных файлах не осталось")
    return 0


if __name__ == "__main__":
    sys.exit(main())
