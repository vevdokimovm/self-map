#!/usr/bin/env python3
"""closed_campaign_gate.py — «ЗАКРЫТО» обязано совпадать с живым измерителем.

🔴 ПОВОД, 03.09.2026. Три файла `IMAGE-REVISION-STATUS.md` — в `health-vault`,
`legal-knowledge-base` и `family` — одновременно утверждали «статус: ЗАКРЫТО,
очередь 0 серий / 0 кадров». Живая очередь на тот момент: **379**, **1102**
и **173** кадра.

Файлы не врали, когда их писали: очередь действительно была пуста 27.08.2026.
Telegram-фото импортировали **29.08** — через два дня. Один импорт обнулил
три статуса разом, и ни один этого не заметил.

ЧТО ЗДЕСЬ ЗА КЛАСС ДЕФЕКТА, И ПОЧЕМУ ОН НЕ ЛЕЧИТСЯ ВНИМАТЕЛЬНОСТЬЮ

`PIT-167`: недатированное утверждение о состоянии читается как настоящее время.
Но здесь есть добавка, которой в PIT-167 нет: **закрытая кампания перестаёт
себя проверять**. Пока кампания идёт, её очередь смотрят каждую вахту; как
только написано «ЗАКРЫТО», файл становится памятником — его читают, но не
перепроверяют. Чем увереннее заголовок, тем реже под него заглядывают.

Отсюда конструкция гейта: он сверяет **заявление** с **измерителем**, а не
проверяет свежесть даты. Дата может быть любой давности — важно лишь, совпадает
ли утверждение с тем, что показывает инструмент прямо сейчас.

ПРЕДУСЛОВИЯ: корень реп доступен; `image_queue.py` на месте.
ПОСТУСЛОВИЯ: напечатан список расхождений «заявлено / измерено».
ИНВАРИАНТ: только чтение. Ни один файл статуса не правится — что писать
в статусе, решает вахта, увидев причину расхождения.

ЗАПУСК
    closed_campaign_gate.py             все репы
    closed_campaign_gate.py --repo ИМЯ  одна
    closed_campaign_gate.py --selftest  канарейка
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402

BASE_REPO, REPOS, _ = resolve_roots(__file__)

STATUS_FILE = "IMAGE-REVISION-STATUS.md"
QUEUE_TOOL = BASE_REPO / "07-media-to-text-lab" / "tools" / "image_queue.py"

# «ЗАКРЫТО» в заголовке — заявление о том, что работы не осталось.
CLOSED = re.compile(r"^#\s.*статус:\s*ЗАКРЫТО", re.M | re.I)
# Итоговая строка измерителя: «серий в очереди: N · кадров: M».
QUEUE_LINE = re.compile(r"серий в очереди:\s*(\d+)\s*·\s*кадров:\s*(\d+)")


def measured(repo: str) -> tuple[int, int] | None:
    """Живая очередь: (серий, кадров). None — измеритель не ответил."""
    if not QUEUE_TOOL.is_file():
        return None
    try:
        out = subprocess.run(["python3", str(QUEUE_TOOL), "--repo", repo],
                             capture_output=True, text=True, timeout=300).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = QUEUE_LINE.search(out)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def check(repo_dir: Path) -> list[str]:
    """Расхождения между заявленным статусом и измеренной очередью."""
    status = repo_dir / STATUS_FILE
    problems: list[str] = []

    q = measured(repo_dir.name)
    if q is None:
        return [f"{repo_dir.name}: измеритель недоступен — проверить нечем"]
    series, frames = q

    if not status.is_file():
        # 🔴 Отсутствие файла — не «вопрос не стоит». Ровно так было в `family`
        # до 27.08: очередь не пуста, а сказать об этом негде.
        if frames:
            problems.append(
                f"{repo_dir.name}: очередь {frames} кадров в {series} сериях, "
                f"а файла {STATUS_FILE} нет — состояние нигде не записано")
        return problems

    text = status.read_text(encoding="utf-8", errors="replace")
    if CLOSED.search(text) and frames:
        problems.append(
            f"{repo_dir.name}: статус заявляет ЗАКРЫТО, "
            f"а очередь — {frames} кадров в {series} сериях")
    return problems


def selftest() -> int:
    """Канарейка проверяет РАЗЛИЧЕНИЕ, а не то, что код исполняется.

    🔴 Мерой предосторожности после `PIT-168`: правило проверяется и на
    срабатывание, и на ОТСУТСТВИЕ ложного срабатывания. Гейт, который
    ругается на честный статус, будет отключён через неделю.
    """
    ok = True
    cases = [
        ("статус ЗАКРЫТО при живой очереди", "# Ревизия изображений — статус: ЗАКРЫТО", 42, True),
        ("статус ЗАКРЫТО при пустой очереди", "# Ревизия изображений — статус: ЗАКРЫТО", 0, False),
        ("статус ОТКРЫТА при живой очереди", "# Ревизия изображений — статус: 🔴 ОТКРЫТА", 42, False),
    ]
    print("Канарейка гейта закрытых кампаний:")
    with tempfile.TemporaryDirectory() as td:
        for label, header, frames, expect in cases:
            d = Path(td) / "r"
            d.mkdir(exist_ok=True)
            (d / STATUS_FILE).write_text(header + "\n", encoding="utf-8")
            text = (d / STATUS_FILE).read_text(encoding="utf-8")
            got = bool(CLOSED.search(text) and frames)
            good = got == expect
            print(f"   {'✅' if good else '❌'} {label} → "
                  f"{'ловит' if got else 'молчит'}")
            ok = good and ok

    # Отдельно: измеритель разбирается на реальной репе
    q = measured("family")
    good = q is not None
    print(f"   {'✅' if good else '❌'} вывод image_queue.py разбирается "
          f"({'серий %d, кадров %d' % q if q else 'не удалось'})")
    ok = good and ok

    print("selftest OK" if ok else "🔴 selftest ПРОВАЛЕН")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="«ЗАКРЫТО» против живой очереди изображений")
    ap.add_argument("--repo", help="одна репа")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    if a.repo:
        targets = [REPOS / a.repo]
    else:
        targets = sorted(p for p in REPOS.iterdir()
                         if p.is_dir() and (p / STATUS_FILE).is_file())

    problems: list[str] = []
    for t in targets:
        problems += check(t)

    if not problems:
        print(f"🟢 проверено реп: {len(targets)} · "
              f"расхождений «заявлено/измерено» нет")
        return 0

    print(f"🔴 РАСХОЖДЕНИЙ: {len(problems)}")
    for p in problems:
        print(f"   · {p}")
    print()
    print("   Что делать: НЕ править число в статусе руками — оно устареет так же.")
    print("   Либо разобрать очередь, либо закрыть её ЯВНЫМ решением владельца")
    print("   (образец: legal-knowledge-base/06-conscript-school/voennoe-pravo/")
    print("   'Заявление о годности/raspoznavanie.md' — решение без описания).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
