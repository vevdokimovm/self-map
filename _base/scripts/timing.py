#!/usr/bin/env python3
"""timing.py — сколько на самом деле занимают действия, по журналам, а не по памяти.

🔴 ЗАДАЧА ВЛАДЕЛЬЦА 28.08.2026 дословно: «внести в репу механизм замера
времени, чтобы была оценка приблизительно, сколько занимает то или иное
действие. Чтобы проще планировать было».

🔴 ПОЧЕМУ ЭТО ВАЖНЕЕ, ЧЕМ КАЖЕТСЯ. Ошибка планирования измерена и велика:
Buehler, Griffin & Ross (1994) — студенты оценивали работу в 33,9 дня,
фактически уходило **55,5**; в собственный прогноз уложились ~30 %. Даже те,
кто говорил «закончу с вероятностью 99 %», успевали в 45 % случаев. Значит
оценка «по ощущению» систематически занижена, и лечится это не старанием,
а **записью фактических длительностей**.

ЧТО ЭТО МЕРЯЕТ: расстояние между соседними записями в `auto.log`, то есть
**календарное время между закрытиями батчей**.

🔴 ЧЕГО ЭТО ЧИСЛО НЕ ЗНАЧИТ, И ЭТО ГЛАВНОЕ ПРЕДУПРЕЖДЕНИЕ (`71` §7г-бис):

  · **это НЕ «сколько занял батч работы».** В промежуток попадает всё:
    ожидание владельца, вопросы в чате, упор в лимит, сон машины, обрыв
    сети, время между сессиями. Батч, закрытый через 14 часов после
    предыдущего, не длился 14 часов;
  · поэтому разумно смотреть **медиану и нижние доли**, а не среднее:
    среднее здесь измеряет длину пауз, а не длину работы;
  · **интервал длиннее шести часов отбрасывается** как заведомая пауза между
    сессиями — граница выбрана по данным, но остаётся допущением, и потому
    названа явно и вынесена в `--gap`;
  · **первый батч сессии не измеряется вовсе** — не с чем сравнивать;
  · инструмент **не знает, что именно делалось** внутри батча: батч из одной
    правки и батч из тридцати неразличимы.

Что бы измерялось честно и чего пока НЕТ: отметка старта и финиша у самого
действия. Пока её нет, это оценка сверху, и пользоваться ей надо как оценкой
сверху — для планирования это как раз безопасная сторона ошибки.

ЗАПУСК
    timing.py                     сводка по всем репам
    timing.py --repo base-repo    по одной
    timing.py --gap 3             своя граница паузы, часов
    timing.py --selftest          канарейка
"""
from __future__ import annotations

import argparse
import datetime as dt
import statistics
import sys
from collections import defaultdict
from pathlib import Path

BASE_REPO = Path(__file__).resolve().parent.parent
LOG = BASE_REPO / "06-autonomous-mode-kit" / "runs" / "auto.log"
# Замеры конкретных действий — то, чего в `auto.log` нет по построению.
DURATIONS = BASE_REPO / "reports" / "durations.tsv"


def read_events(path: Path) -> list[tuple[dt.datetime, str, str]]:
    """(момент, репа, тип) по каждой строке журнала."""
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        try:
            when = dt.datetime.fromisoformat(parts[0])
        except ValueError:
            continue
        out.append((when, parts[1], parts[2]))
    return sorted(out)


def intervals(events, gap_hours: float, repo: str | None = None) -> list[float]:
    """Минуты между соседними батчами; паузы длиннее `gap_hours` отброшены."""
    by_repo = defaultdict(list)
    for when, name, kind in events:
        if kind != "batch":
            continue
        if repo and name != repo:
            continue
        by_repo[name].append(when)
    out = []
    for moments in by_repo.values():
        for a, b in zip(moments, moments[1:]):
            minutes = (b - a).total_seconds() / 60
            if 0 < minutes <= gap_hours * 60:
                out.append(minutes)
    return sorted(out)


def summary(values: list[float]) -> str:
    if not values:
        return "  данных нет"
    def q(p: float) -> float:
        return values[min(int(len(values) * p), len(values) - 1)]
    return (f"  замеров: {len(values)}\n"
            f"    четверть быстрее : {q(0.25):5.0f} мин\n"
            f"    МЕДИАНА          : {statistics.median(values):5.0f} мин\n"
            f"    три четверти до  : {q(0.75):5.0f} мин\n"
            f"    девять из десяти : {q(0.90):5.0f} мин\n"
            f"    самый долгий     : {values[-1]:5.0f} мин")


def selftest() -> bool:
    """Проверяется РАЗЛИЧЕНИЕ: паузу между сессиями нельзя считать работой."""
    base = dt.datetime(2026, 8, 29, 10, 0)
    events = [
        (base, "r", "batch"),
        (base + dt.timedelta(minutes=20), "r", "batch"),      # 20 мин — работа
        (base + dt.timedelta(hours=14), "r", "batch"),        # 14 ч — пауза
        (base + dt.timedelta(hours=14, minutes=30), "r", "batch"),  # 30 мин
        (base + dt.timedelta(hours=15), "r", "skip"),         # не батч
    ]
    got = intervals(events, gap_hours=6)
    # Ровно два интервала: 20 и 30. Ночная пауза и запись «skip» не в счёт.
    return got == [20.0, 30.0]


def measure(label: str, command: list[str]) -> int:
    """Выполнить команду, записав фактическую длительность.

    🔴 Это вторая половина инструмента, и она честнее первой. Промежуток
    между батчами — оценка СВЕРХУ: в него попадает всё постороннее. Здесь
    же меряется ровно то, что выполнялось, от запуска до возврата.

    Записывается и **код возврата**: длительность упавшей команды и успешной
    смешивать нельзя — упасть можно быстро, и такая запись занизила бы оценку.
    """
    import subprocess, time
    started = dt.datetime.now()
    t0 = time.monotonic()
    result = subprocess.run(command)
    seconds = time.monotonic() - t0
    DURATIONS.parent.mkdir(parents=True, exist_ok=True)
    new = not DURATIONS.exists()
    with DURATIONS.open("a", encoding="utf-8") as fh:
        if new:
            fh.write("# начало\tсекунд\tкод\tчто\tкоманда\n")
        fh.write(f"{started.isoformat(timespec='seconds')}\t{seconds:.1f}\t"
                 f"{result.returncode}\t{label}\t{' '.join(command)}\n")
    mark = "🟢" if result.returncode == 0 else "🔴"
    print(f"\n{mark} «{label}»: {seconds:.1f} с (код {result.returncode}) "
          f"→ {DURATIONS.relative_to(BASE_REPO)}")
    return result.returncode


def report_durations(gap_unused: float = 0) -> None:
    """Сводка по замеренным действиям — только успешные, по названию."""
    if not DURATIONS.is_file():
        print("  замеров действий пока нет — заводятся через `--measure`")
        return
    by_label = defaultdict(list)
    for line in DURATIONS.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 4 or parts[2] != "0":
            continue          # упавшие не смешиваем с успешными
        by_label[parts[3]].append(float(parts[1]))
    if not by_label:
        print("  успешных замеров пока нет")
        return
    for label, vals in sorted(by_label.items(), key=lambda kv: -statistics.median(kv[1])):
        med = statistics.median(vals)
        unit = f"{med:.0f} с" if med < 120 else f"{med / 60:.1f} мин"
        print(f"  {label:<34} медиана {unit:>9}  ({len(vals)} замеров)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo")
    ap.add_argument("--gap", type=float, default=6.0,
                    help="интервал длиннее этого числа часов считается паузой")
    ap.add_argument("--measure", metavar="ЧТО",
                    help="замерить команду: --measure «имя» -- команда")
    ap.add_argument("command", nargs="*", help="команда после --")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.measure:
        if not a.command:
            print("🔴 нужна команда после --")
            return 1
        return measure(a.measure, a.command)

    if a.selftest:
        ok = selftest()
        print("🟢 канарейка: пауза между сессиями не считается работой"
              if ok else "🔴 канарейка: РАЗЛИЧЕНИЕ СЛОМАНО")
        return 0 if ok else 1

    if not selftest():
        print("🔴 канарейка не прошла — числам ниже верить нельзя")
        return 1
    if not LOG.is_file():
        print(f"🔴 нет журнала: {LOG}")
        return 1

    events = read_events(LOG)
    batches = [e for e in events if e[2] == "batch"]
    print(f"Журнал: {len(events)} записей, из них батчей {len(batches)}, "
          f"с {batches[0][0].date()} по {batches[-1][0].date()}\n")

    print(f"═══ Время между закрытиями батчей "
          f"(паузы длиннее {a.gap:g} ч отброшены) ═══")
    print(summary(intervals(events, a.gap, a.repo)))

    if not a.repo:
        print("\n═══ По репам, где замеров хватает ═══")
        names = {e[1] for e in batches}
        rows = []
        for name in sorted(names):
            vals = intervals(events, a.gap, name)
            if len(vals) >= 3:
                rows.append((statistics.median(vals), name, len(vals)))
        for med, name, count in sorted(rows):
            print(f"  {name:<26} медиана {med:5.0f} мин  ({count} замеров)")

    print("\n═══ Замеренные действия (только успешные) ═══")
    report_durations()

    print("\n🔴 ЭТО НЕ «сколько занял батч работы». В промежуток попадает всё:")
    print("   ожидание владельца, вопросы в чате, упор в лимит, сон машины.")
    print("   Пользоваться как ОЦЕНКОЙ СВЕРХУ — для планирования это безопасная")
    print("   сторона ошибки (ошибка планирования занижает: 33,9 дня оценка")
    print("   против 55,5 факта, Buehler et al. 1994).")
    print("🔴 Раздел «замеренные действия» — честный: там ровно время команды.")
    print("   Заводится так: timing.py --measure «прогон гейта» -- python3 …")
    return 0


if __name__ == "__main__":
    sys.exit(main())
