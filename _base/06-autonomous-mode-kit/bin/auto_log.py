#!/usr/bin/env python3
"""auto_log.py — журнал автономного прогона (ROADMAP P1.6, «Журнал автономного прогона»).

ЗАЧЕМ. Закон 5 кита: «записано по ходу — иначе не было». CHANGELOG/WATCHLOG фиксируют
батчи, но не ветки, которые остановились на стоп-классе, не пропущенные шаги, не
периоды простоя между батчами. Вернувшийся через неделю владелец не может из одного
CHANGELOG понять, где /auto реально топталась на месте.

ФОРМАТ. Одна строка на событие, tab-separated, дописывается в конец — никогда не
переписывается и не сортируется задним числом:

    ISO8601\tрепа\tтип\tкраткое описание

Тип — один из: batch (закрыт батч, версия в описании) · skip (шаг пропущен по §3,
причина в описании) · stop (стоп-класс, какой) · wait (простой дольше обычного,
почему).

ЗАПУСК
    auto_log.py --repo ИМЯ --type batch --note "v3.34.0: PIT-146 закрыт"
    tail -20 06-autonomous-mode-kit/runs/auto.log
"""
import argparse
import datetime
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "runs" / "auto.log"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--type", required=True, choices=["batch", "skip", "stop", "wait"])
    ap.add_argument("--note", required=True)
    a = ap.parse_args()

    ts = datetime.datetime.now().isoformat(timespec="seconds")
    line = f"{ts}\t{a.repo}\t{a.type}\t{a.note}\n"
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line)
    print(f"записано: {LOG.relative_to(LOG.parent.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
