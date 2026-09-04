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

🔴 ПОВТОР НЕ ПИШЕТСЯ (03.09.2026, решение по `ROADMAP` §P0-1). Строку `batch`
теперь пишет `bump_repo.py` — тот, кто батч закрывает, — а ритуал
`close_batch.py` шагом 5 вызывает журнал следом. Без защиты это дало бы
ДВЕ строки на один батч.

Почему защита здесь, а не у вызывающих: журнал — единственный владелец
своего формата, и инвариант «одна строка на закрытый батч» принадлежит ему.
Разложенный по двум вызывающим, он разошёлся бы при первой же правке одного
из них.

Дубликат опознаётся ДОСЛОВНЫМ совпадением заметки с последней строкой `batch`
этой репы — без разбора номера версии из текста. Разбор был бы эвристикой
(`71` §7г-бис): формат заметки задаёт вахта, и «v» в начале ничем не обещана.

Цена: два РАЗНЫХ батча одной репы с дословно одинаковой заметкой сольются
в один. Это не потеря — заметка обязана называть версию, а версия не
повторяется; совпадение заметок означает, что одна из них лжёт.
Обойти: `--force`.

ЗАПУСК
    auto_log.py --repo ИМЯ --type batch --note "v3.34.0: PIT-146 закрыт"
    auto_log.py --repo ИМЯ --type batch --note "…" --force   # писать и повтор
    tail -20 06-autonomous-mode-kit/runs/auto.log
"""
import argparse
import datetime
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "runs" / "auto.log"


def last_batch_note(repo: str) -> str | None:
    """Заметка последней строки `batch` этой репы — или None, если её нет.

    Журнал читается целиком: строк тысячи, а не мегабайты. Чтение с конца
    экономило бы миллисекунды ценой разбора кодировки кусками — цена выше
    выигрыша, и такой код ошибается на границе куска.

    🔴 Битые строки пропускаются молча ТОЛЬКО здесь и только для сравнения:
    журнал дописывается конкурентно (две вахты, `PIT-175`), и оборванная
    строка не повод отказать в записи новой.
    """
    if not LOG.is_file():
        return None
    found = None
    for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) >= 4 and parts[1] == repo and parts[2] == "batch":
            found = parts[3]
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--type", required=True, choices=["batch", "skip", "stop", "wait"])
    ap.add_argument("--note", required=True)
    ap.add_argument("--force", action="store_true",
                    help="писать, даже если такая же строка batch уже последняя")
    a = ap.parse_args()

    if a.type == "batch" and not a.force and last_batch_note(a.repo) == a.note:
        print(f"уже записано: {a.repo} · {a.note}")
        return 0

    ts = datetime.datetime.now().isoformat(timespec="seconds")
    line = f"{ts}\t{a.repo}\t{a.type}\t{a.note}\n"
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line)
    print(f"записано: {LOG.relative_to(LOG.parent.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
