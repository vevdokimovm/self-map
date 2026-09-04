#!/usr/bin/env python3
"""hidden_load.py — фоновые процессы, которые грузят машину незаметно.

ЗАКАЗ ВЛАДЕЛЬЦА 02.09.2026: «чтобы она чекала и замечала все такие процессы,
которые визуально мне не видны, но которые выполняются скрытно и нагружают Mac».

Повод: `StorageManagementService` полгода жёг 20 % ядра, и это не было видно
ни в одном окне — служба системная, интерфейса у неё нет.

🔴 ГЛАВНОЕ РЕШЕНИЕ КОНСТРУКЦИИ — мерить НАКОПЛЕННОЕ время, а не мгновенное.

Мгновенный `%CPU` у фоновой службы почти всегда ноль: она работает **волнами**,
и между проходами действительно ничего не делает. Именно на этом я и ошибся
02.09.2026 — увидел 0.0 %, объявил проблему решённой, а через минуту тот же
процесс показал 32 %.

Накопленное время (`ps -o time`) обмануть нельзя: если процесс за девять часов
аптайма съел два часа процессора, он их съел, в какой бы фазе его ни застал
замер. Поэтому основа отчёта — **доля от аптайма**, а мгновенный процент идёт
справочной колонкой.

ПРЕДУСЛОВИЯ: macOS; штатные `ps`, `sysctl`.

ПОСТУСЛОВИЯ: напечатан список фоновых процессов, отсортированный по доле
съеденного времени, с порогом и вердиктом. Пустой список печатается словами.

ИНВАРИАНТ: только чтение. Ничего не останавливает и не отключает —
решение принимает владелец.
"""
from __future__ import annotations

import argparse
import platform
import re
import subprocess
import sys
import time

# 🔴 Порог в процентах ОДНОГО ядра за всё время работы системы.
# 5 % значит: процесс занимал двадцатую часть ядра непрерывно. Для фоновой
# службы, у которой нет работы, это уже много: она обязана спать.
THRESHOLD_PCT = 5.0

# Процессы, которым высокая доля НОРМАЛЬНА по их природе. Список короткий
# намеренно: чем он длиннее, тем выше шанс спрятать в нём настоящего пожирателя.
EXPECTED = {
    "WindowServer": "рисует весь интерфейс — нагрузка ожидаема",
    "kernel_task": "ядро; высокая доля часто означает борьбу с перегревом",
    "launchd": "родитель всех процессов",
    "claude": "рабочий инструмент владельца",
    "iTerm2": "терминал, в котором идёт работа",
    "Terminal": "терминал",
}


def sh(cmd: list[str], timeout: int = 30) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def uptime_seconds() -> int:
    """Аптайм системы — знаменатель для доли."""
    out = sh(["sysctl", "-n", "kern.boottime"])
    m = re.search(r"sec\s*=\s*(\d+)", out)
    return int(time.time()) - int(m.group(1)) if m else 0


def parse_time(s: str) -> int:
    """`ps` печатает время как MM:SS.ss или HH:MM:SS."""
    parts = s.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(float(parts[1]))
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
    except ValueError:
        pass
    return 0


def scan(uptime: int) -> list[dict]:
    out = sh(["ps", "-Aceo", "pid,time,%cpu,comm"], 25)
    rows = []
    for line in out.splitlines()[1:]:
        f = line.split(None, 3)
        if len(f) != 4:
            continue
        secs = parse_time(f[1])
        if not secs or not uptime:
            continue
        share = secs / uptime * 100
        if share < THRESHOLD_PCT:
            continue
        name = f[3].strip()
        rows.append({
            "pid": f[0], "имя": name,
            "время_cpu": f[1], "сейчас_проц": float(f[2]),
            "доля_ядра_проц": round(share, 1),
            "ожидаемо": EXPECTED.get(name, ""),
        })
    return sorted(rows, key=lambda r: -r["доля_ядра_проц"])


def sample_instant(names: list[str], times: int = 5, gap: float = 3.0) -> dict:
    """🔴 Серия мгновенных замеров вместо одного.

    Ровно то, на чём я ошибся: единственный замер фоновой службы попадает
    в паузу между волнами и показывает ноль. Пять замеров с паузами
    различают «спит всегда» и «спало в момент взгляда».
    """
    acc = {n: [] for n in names}
    for _ in range(times):
        out = sh(["ps", "-Aceo", "%cpu,comm"], 15)
        seen = set()
        for line in out.splitlines()[1:]:
            f = line.split(None, 1)
            if len(f) == 2:
                n = f[1].strip()
                if n in acc and n not in seen:
                    seen.add(n)
                    try:
                        acc[n].append(float(f[0]))
                    except ValueError:
                        pass
        time.sleep(gap)
    return acc


def render(rows: list[dict], uptime: int, series: dict | None) -> None:
    h, m = uptime // 3600, (uptime % 3600) // 60
    print(f"Фоновая нагрузка · аптайм {h} ч {m} мин · порог {THRESHOLD_PCT} % ядра\n")

    if not rows:
        print("🟢 Ни один процесс не превысил порог. Фоновых пожирателей нет.")
        return

    suspects = [r for r in rows if not r["ожидаемо"]]
    known = [r for r in rows if r["ожидаемо"]]

    if suspects:
        print(f"🔴 НЕЗАМЕТНЫЕ ПОЖИРАТЕЛИ: {len(suspects)}")
        print(f"   {'доля':>6} {'время CPU':>12} {'сейчас':>8}  процесс")
        for r in suspects:
            s = series.get(r["имя"], []) if series else []
            live = f" · серия: {'/'.join(f'{x:.0f}' for x in s)} %" if s else ""
            print(f"   {r['доля_ядра_проц']:>5.1f}% {r['время_cpu']:>12} "
                  f"{r['сейчас_проц']:>7.1f}%  {r['имя'][:34]}{live}")
        print()
        print("   🔴 «Сейчас 0 %» НЕ означает «не грузит».")
        print("      Фоновые службы работают волнами: между проходами они спят,")
        print("      и одиночный замер попадает именно туда. Смотреть на ДОЛЮ")
        print("      от аптайма — её обмануть нельзя.")

    if known:
        print(f"\n🟡 Ожидаемо высокие: {len(known)}")
        for r in known:
            print(f"   {r['доля_ядра_проц']:>5.1f}%  {r['имя'][:26]:<28} {r['ожидаемо']}")

    if suspects:
        print("\n   Что делать с найденным:")
        print("     · выяснить назначение: `man <имя>` или поиск по имени службы;")
        print("     · кто запускает: `launchctl list | grep -i <имя>`;")
        print("     · отключить, если не нужна:")
        print("       `launchctl disable gui/$(id -u)/<полное.имя.службы>`")
        print("     🔴 Отключение системной службы — решение владельца, не скрипта.")


def main() -> int:
    if platform.system() != "Darwin":
        print(f"🔴 Скрипт для macOS; здесь {platform.system()}.", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(description="Фоновые пожиратели процессора")
    ap.add_argument("--series", action="store_true",
                    help="добавить серию из 5 мгновенных замеров (≈15 с)")
    args = ap.parse_args()

    up = uptime_seconds()
    if not up:
        print("🔴 Не удалось узнать аптайм — доля не считается.", file=sys.stderr)
        return 2

    rows = scan(up)
    series = None
    if args.series and rows:
        names = [r["имя"] for r in rows if not r["ожидаемо"]][:5]
        if names:
            print(f"снимаю серию по {len(names)} процессам, ≈15 секунд…\n")
            series = sample_instant(names)

    render(rows, up, series)
    return 1 if any(not r["ожидаемо"] for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
