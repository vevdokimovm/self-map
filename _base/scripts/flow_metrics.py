#!/usr/bin/env python3
"""flow_metrics.py — поток задач: сколько приходит, сколько уходит, сколько ждёт.

ЗАВЕДЕНО 29.08.2026 по исследованию `reports/research/
task-management-and-productivity-2026-08-29.md`, кандидат ранга 2.

🔴 ЗАЧЕМ. Закон Литтла — тождество, а не эвристика: `L = λ · W`, то есть
**среднее время жизни задачи = число открытых ÷ скорость закрытия**. Из него
следует вывод, который переворачивает интуицию:

  · при 45 открытых задачах и скорости 3 в неделю задача **обязана** висеть
    в среднем 15 недель — тождественно, а не по расхлябанности;
  · закон **не зависит от дисциплины очереди** (FIFO, LIFO, приоритеты дают
    одно и то же среднее), значит **переприоритизация не уменьшает ни число
    открытых задач, ни среднее время ожидания**. Помогает ровно три вещи:
    поднять скорость закрытия, снизить приток, или явно отбрасывать.

Пока λ и μ не замерены, разговор об очереди остаётся гадательным. Этот скрипт
их считает — по тем данным, которые в системе действительно есть.

🔴 ЧЕГО ЭТОТ ЗАМЕР НЕ УМЕЕТ, И ЭТО НАДО ЗНАТЬ (`71` §7г-бис):

  · **У задач владельца нет дат.** В `TASKS.md` строка не несёт ни даты
    заведения, ни даты закрытия, а у реп нет `.git`. Значит по ним считается
    только L (число открытых) — но не λ и не μ. Честный вывод «нечем считать»
    полезнее вычисленного из воздуха.
  · **Батчи ≠ задачи.** Журнал авто-режима даёт достоверный поток ЗАКРЫТЫХ
    БАТЧЕЙ. Батч и задача — разные единицы: один батч может закрыть три
    задачи или ни одной. Поэтому скорость батчей печатается отдельно и
    подписана как другая величина, а не выдаётся за μ задач.
  · **Прогнозная сила появится позже.** Практики канбана предупреждают: закон
    Литтла нельзя использовать для ПРОГНОЗА, пока нет лимитов на число
    начатого и распределение имеет тяжёлый хвост. Как ДИАГНОСТИКА он работает
    всегда — это тождество.

ЗАПУСК
    flow_metrics.py                отчёт по планировщику и всей системе
    flow_metrics.py --weeks 8      окно замера потока батчей
    flow_metrics.py --selftest     канарейка
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

# Корень определяется общим модулем: скрипт может быть запущен и из базы,
# и из копии кита в репе-наследнике (`_base/scripts/`). См. `_roots.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402
BASE_REPO, REPOS, FROM_KIT = resolve_roots(__file__)
AUTO_LOG = BASE_REPO / "06-autonomous-mode-kit" / "runs" / "auto.log"
PLANNER = REPOS / "mission-control"

OPEN_RE = re.compile(r"^\s*[-*]\s*\[ \]")
DONE_RE = re.compile(r"^\s*[-*]\s*\[[xX]\]")
TASK_FILES = ("TASKS.md", "ROADMAP.md", "BACKLOG.md", "BOARD.md", "INBOX.md")


def count_open(path: Path) -> tuple[int, int]:
    """(открытых, закрытых-но-лежащих-в-рабочем-файле)."""
    if not path.is_file():
        return 0, 0
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return (sum(1 for l in text if OPEN_RE.match(l)),
            sum(1 for l in text if DONE_RE.match(l)))


def batches_per_week(weeks: int) -> tuple[float, Counter, int]:
    """Скорость закрытия БАТЧЕЙ по журналу авто-режима.

    Это не скорость закрытия задач — см. оговорку в шапке. Но это единственная
    величина потока, которую в системе можно замерить фактом, а не оценкой.
    """
    if not AUTO_LOG.is_file():
        return 0.0, Counter(), 0
    cutoff = date.today() - timedelta(weeks=weeks)
    by_week: Counter = Counter()
    total = 0
    for line in AUTO_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or parts[2] != "batch":
            continue
        try:
            when = datetime.fromisoformat(parts[0]).date()
        except ValueError:
            continue
        if when < cutoff:
            continue
        total += 1
        by_week[when.isocalendar()[:2]] += 1
    return (total / weeks if weeks else 0.0), by_week, total


def selftest() -> bool:
    """Проверяется РАЗЛИЧЕНИЕ: открытое от закрытого, батч от не-батча.

    Обе половины обязательны. Без первой скрипт посчитал бы закрытые пункты
    как открытые и завысил L; без второй — принял бы за батч любую строку
    журнала (там есть ещё `skip` и `note`) и завысил скорость.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "TASKS.md"
        f.write_text(
            "- [ ] открытая раз\n"
            "* [ ] открытая два\n"
            "- [x] закрытая\n"
            "- [X] закрытая с большой буквы\n"
            "обычная строка про [ ] в тексте\n",
            encoding="utf-8")
        if count_open(f) != (2, 2):
            return False

    global AUTO_LOG
    saved = AUTO_LOG
    try:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "auto.log"
            today = date.today().isoformat()
            log.write_text(
                f"{today}T10:00:00\tрепа\tbatch\tv1.0.0: раз\n"
                f"{today}T11:00:00\tрепа\tskip\tпропущено\n"
                f"{today}T12:00:00\tрепа\tbatch\tv1.0.1: два\n"
                "битая строка без табов\n",
                encoding="utf-8")
            AUTO_LOG = log
            rate, _, total = batches_per_week(1)
            # Ровно два батча: `skip` и мусор не считаются.
            return total == 2 and rate == 2.0
    finally:
        AUTO_LOG = saved


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--weeks", type=int, default=8, help="окно замера, недель")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        ok = selftest()
        print("🟢 канарейка: открытое отличается от закрытого, батч от прочего"
              if ok else "🔴 канарейка: РАЗЛИЧЕНИЕ СЛОМАНО")
        return 0 if ok else 1

    if not selftest():
        print("🔴 канарейка не прошла — числам ниже верить нельзя")
        return 1

    print("═══ L: сколько задач ждёт (планировщик) ═══\n")
    total_open = 0
    for name in TASK_FILES:
        opened, stale_done = count_open(PLANNER / name)
        if opened or stale_done:
            total_open += opened
            tail = f"  · закрытых в рабочем файле: {stale_done} (вынести в историю)" \
                if stale_done else ""
            print(f"  {name:<12} открыто: {opened:>3}{tail}")
    print(f"\n  L (всего открытого у владельца): {total_open}")

    rate, by_week, total = batches_per_week(a.weeks)
    print(f"\n═══ Скорость закрытия БАТЧЕЙ за {a.weeks} нед. ═══\n")
    if total:
        print(f"  батчей закрыто: {total}   ·   в среднем {rate:.1f} в неделю")
        for (year, week), n in sorted(by_week.items()):
            print(f"    {year}-W{week:02d}: {'█' * min(n, 40)} {n}")
    else:
        print("  журнал пуст за это окно")

    print("\n═══ Что из этого следует ═══\n")
    # 🔴 ЧИСЛО «срок жизни задачи» ЗДЕСЬ НЕ ПЕЧАТАЕТСЯ, и это решение, а не
    # недоделка. Первая редакция делила L на скорость батчей и выдала «1 неделя»
    # при задачах, висящих месяцами. Оговорка «это оценка» рядом с числом не
    # спасает: число запоминается, оговорка — нет, и завтра «1 неделя» уедет
    # в прозу как факт (`72` §4е). Батч и задача — разные единицы, делить одно
    # на другое нельзя, сколько ни подписывай.
    weeks_span = len(by_week)
    if weeks_span:
        print(f"  Журнал батчей покрывает {weeks_span} нед. — этого хватает,")
        print(f"  чтобы видеть темп работы агента, и НЕ хватает, чтобы судить")
        print(f"  о задачах владельца: это разные единицы и разные исполнители.")
    print()
    print("  🔴 Чего замерить НЕЛЬЗЯ и почему:")
    print("     · λ (приток) и μ (закрытие) ЗАДАЧ ВЛАДЕЛЬЦА — в `TASKS.md` у строки")
    print("       нет ни даты заведения, ни даты закрытия, а у реп нет `.git`.")
    print("     · Пока их нет, любое число про срок жизни задачи — арифметика")
    print("       по подставленным величинам, а не факт.")
    print()
    print("  Что это чинит: дата в строке при заведении и при закрытии.")
    print("  Через 8 недель этот же скрипт посчитает λ и μ фактом.")
    print()
    print("  🔴 И главное, что уже известно БЕЗ замера (закон Литтла — тождество):")
    print("     переприоритизация не меняет ни L, ни среднее время ожидания.")
    print("     Работают только три вещи: поднять μ, снизить λ, явно отбросить.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
