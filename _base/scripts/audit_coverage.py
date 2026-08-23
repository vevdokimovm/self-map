#!/usr/bin/env python3
"""Измеряет слепую зону `per_repo_audit.py`: сколько служебок он НЕ видит.

Зачем. Таблица 2 аудита считает служебным каталог, **имя которого** содержит подсказку
из списка `SERVICE_HINTS`. Вопрос «а точно ли она собирает всё» без измерения **не имеет
ответа**: пропущенное по построению невидимо. Этот скрипт повторяет логику видимости
аудита и печатает разницу между тем, что видно, и тем, что есть.

Правило и разбор — `00-infrastructure/77-system-wide-audit.md` §4.

ИМПОРТ, А НЕ КОПИЯ. Подсказки и правила видимости берутся **из самого `per_repo_audit`**.
Копия разошлась бы на первой же его правке, и измеритель начал бы честно мерить ДРУГОЙ
фильтр — врал бы тем убедительнее, чем дольше живёт (`72-source-of-truth.md`).

    python3 scripts/audit_coverage.py            # сводка
    python3 scripts/audit_coverage.py --show 40  # с именами невидимых каталогов
"""

from __future__ import annotations

import argparse
import importlib.util
import os
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_audit():
    """Забрать константы видимости у измеряемого инструмента, а не переписать их."""
    spec = importlib.util.spec_from_file_location("_audit", HERE / "per_repo_audit.py")
    module = importlib.util.module_from_spec(spec)
    # per_repo_audit печатает отчёт на импорте — глушим его вывод, нам нужны константы.
    devnull = open(os.devnull, "w")
    real_stdout, os.sys.stdout = os.sys.stdout, devnull
    try:
        spec.loader.exec_module(module)
    finally:
        os.sys.stdout = real_stdout
        devnull.close()
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", type=int, default=15,
                        help="сколько невидимых каталогов показать поимённо")
    args = parser.parse_args()

    audit = load_audit()
    # Берём САМ ПРЕДИКАТ, а не подсказки: копия логики видимости мерила бы другой
    # фильтр. Первая редакция этого скрипта повторяла обход руками — и разошлась
    # с аудитом в тот же час, когда предикат научился смотреть на предков.
    is_service = audit.is_service_dir
    skip, max_depth, root = audit.SKIP_DIRS, audit.MAX_DEPTH, audit.ROOT

    visible_md = invisible_md = 0
    invisible_dirs: Counter[str] = Counter()

    for repo in sorted(root.iterdir()):
        if not repo.is_dir() or repo.name != repo.name.strip():
            continue
        base_depth = len(repo.parts)
        for dirpath, dirnames, filenames in os.walk(repo):
            here = Path(dirpath)
            dirnames[:] = [d for d in dirnames if d not in skip]
            if len(here.parts) - base_depth > max_depth:
                dirnames[:] = []
                continue
            if here == repo:
                continue
            md = [f for f in filenames if f.lower().endswith(".md")]
            if not md:
                continue
            if is_service(here, repo):
                visible_md += len(md)
            else:
                invisible_md += len(md)
                invisible_dirs[here.relative_to(repo).as_posix()] += len(md)

    total = visible_md + invisible_md
    pct = (visible_md / total * 100) if total else 100.0

    print("Слепая зона таблицы 2 `per_repo_audit.py`")
    print(f"  подсказок: {len(audit.SERVICE_HINTS)} · глубина обхода: {max_depth}"
          f" · предикат импортирован из аудита")
    print()
    print(f"  .md в каталогах, которые аудит ВИДИТ : {visible_md}")
    print(f"  .md в каталогах, которых он НЕ ВИДИТ : {invisible_md}")
    print(f"  покрытие: {pct:.1f}%")
    print()
    if invisible_dirs:
        print(f"  невидимых каталогов (по имени): {len(invisible_dirs)}")
        for name, n in invisible_dirs.most_common(args.show):
            print(f"    {n:>5}  {name}/")
        if len(invisible_dirs) > args.show:
            print(f"    … ещё {len(invisible_dirs) - args.show} имён")
    print()
    print("  Решение по каждому имени — человеческое: расширить подсказки или")
    print("  признать содержанием. Измеритель ничего не меняет (77 §4).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
