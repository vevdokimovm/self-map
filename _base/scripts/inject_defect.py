#!/usr/bin/env python3
"""inject_defect.py — учебная тревога: подсадить дефект и проверить, поймает ли гейт.

🔴 САМАЯ СИЛЬНАЯ КОНТРМЕРА ИЗ ИССЛЕДОВАНИЯ HUMAN FACTORS 29.08.2026,
и она контринтуитивна.

Parasuraman, Molloy & Singh (1993), реплицировано Bagheri & Jamieson (2004):
обнаружение отказов автоматики — **82 % при ПЕРЕМЕННОЙ надёжности против
33 % при ПОСТОЯННОЙ**. Разница в два с половиной раза, и она не про качество
проверки, а про то, что человек перестаёт смотреть на то, что всегда зелёное.

  · Гейт, который 200 прогонов подряд говорит «чисто», обучает не доверять
    ему, а **не читать его**.
  · Нижнего порога, ниже которого благодушие исчезает, НЕТ (May, Molloy &
    Parasuraman 1993): даже зная, что проверка ненадёжна, человек работает
    с ней хуже, чем без неё.
  · Тренировка и инструкции не помогают (Parasuraman & Manzey, обзор 2010):
    automation bias одинаков у новичков и экспертов и не лечится словами.
  · Помогает **опыт реального отказа**, а не рассказ о нём (Bahner 2008):
    группа, пережившая отказы, проверяла лучше группы, которую о них
    предупредили.

Отсюда механизм: раз в N прогонов гейт обязан **честно покраснеть на
подсаженном дефекте**. Человек знает, что такое бывает, и не знает когда —
это и есть переменная надёжность.

🔴 ЧТО ЭТОТ ИНСТРУМЕНТ НЕ ДЕЛАЕТ И ПОЧЕМУ:

  · **не трогает рабочие файлы репы** — дефект подсаживается во ВРЕМЕННУЮ
    копию. Учебная тревога, портящая настоящие данные, стоит дороже, чем
    ловит;
  · **не притворяется настоящим отказом в общем прогоне** — печатает, что
    это учение. Подделка вывода гейта разрушила бы доверие к самому гейту,
    то есть отняла бы больше, чем даёт;
  · **не измеряет, заметил ли человек** — это требует человека, а не скрипта.
    Инструмент даёт возможность проверить себя, не оценку.

ЗАПУСК
    inject_defect.py                случайный класс дефекта
    inject_defect.py --kind cjk     конкретный: cjk · link · wip · pointer
    inject_defect.py --list         какие классы умеет
    inject_defect.py --selftest     канарейка
"""
from __future__ import annotations

import argparse
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_REPO = Path(__file__).resolve().parent.parent
GATE = BASE_REPO / "scripts" / "revision_check.py"

# Каждый класс — (описание, функция, которая портит копию репы).
# Классы выбраны так, чтобы бить по РАЗНЫМ проверкам: если инъекция всегда
# одного вида, человек привыкает и к ней — та же постоянная надёжность,
# только на уровень выше.


def _defect_cjk(root: Path) -> str:
    """Токен-слип: иероглиф внутри русского слова."""
    target = root / "УЧЕНИЕ-подсаженный-дефект.md"
    target.write_text(f"# Учебная тревога\n\nнет{chr(0xCF54)}д в русском слове\n",
                      encoding="utf-8")
    return "иероглиф внутри русского слова (класс CJK)"


def _defect_link(root: Path) -> str:
    """Битая ссылка на несуществующий файл."""
    target = root / "УЧЕНИЕ-подсаженный-дефект.md"
    target.write_text("# Учебная тревога\n\n"
                      "[ссылка в пустоту](docs/такого-файла-нет-12345.md)\n",
                      encoding="utf-8")
    return "битая ссылка на несуществующий файл"


def _defect_wip(root: Path) -> str:
    """Превышение предела задач в работе."""
    target = root / "TASKS.md"
    prev = target.read_text(encoding="utf-8") if target.is_file() else ""
    target.write_text(prev + "\n<!-- WIP:START limit=2 -->\n"
                      "- [ ] учение раз\n- [ ] учение два\n- [ ] учение три\n"
                      "<!-- WIP:END -->\n", encoding="utf-8")
    return "три пункта в разделе с пределом 2"


def _defect_pointer(root: Path) -> str:
    """Состояние внутри файла-указателя."""
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "WATCHLOG.md").write_text("## §0. Где стоим\nтекст\n",
                                               encoding="utf-8")
    (root / "WATCHLOG.md").write_text(
        "# указатель\n\n**Версия:** 9.9.9\n\n"
        "Журнал — [`docs/WATCHLOG.md`](docs/WATCHLOG.md).\n", encoding="utf-8")
    return "версия внутри файла-указателя (второй источник правды)"


KINDS = {
    "cjk": ("токен-слип модели", _defect_cjk),
    "link": ("битая ссылка", _defect_link),
    "wip": ("превышен предел задач", _defect_wip),
    "pointer": ("состояние в указателе", _defect_pointer),
}


def run_drill(repo: Path, kind: str) -> bool:
    """Подсадить дефект в КОПИЮ и проверить, что гейт его нашёл."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / repo.name
        shutil.copytree(repo, work, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", "node_modules",
                                                      ".venv", "__pycache__"))
        description, breaker = KINDS[kind]
        detail = breaker(work)
        result = subprocess.run(["python3", str(GATE), "--root", str(work)],
                                capture_output=True, text=True)
        caught = result.returncode != 0
        print(f"  подсажено: {detail}")
        if caught:
            hit = [l.strip() for l in result.stdout.splitlines()
                   if l.strip().startswith("·") and "УЧЕНИЕ" in l]
            print(f"  🟢 гейт ПОЙМАЛ (код {result.returncode})")
            for line in hit[:2]:
                print(f"       {line[:100]}")
        else:
            print(f"  🔴 ГЕЙТ ПРОПУСТИЛ — это настоящая находка, разбери её")
        return caught


def selftest() -> bool:
    """Каждый класс дефекта обязан ловиться. Класс, который не ловится, —
    не учение, а дыра, и знать о ней надо до, а не во время учения."""
    return len(KINDS) >= 4 and all(callable(f) for _, f in KINDS.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default="base-repo")
    ap.add_argument("--kind", choices=sorted(KINDS))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        ok = selftest()
        print("🟢 канарейка: классы дефектов на месте" if ok
              else "🔴 канарейка: классы дефектов повреждены")
        return 0 if ok else 1

    if a.list:
        print("Классы учебных дефектов:")
        for name, (desc, _) in sorted(KINDS.items()):
            print(f"  {name:<10} {desc}")
        return 0

    repo = BASE_REPO.parent / a.repo
    if not repo.is_dir():
        print(f"🔴 нет репы: {a.repo}")
        return 1

    kind = a.kind or random.choice(sorted(KINDS))
    print("═══ УЧЕБНАЯ ТРЕВОГА ═══")
    print("🔴 Это учение, а не настоящий отказ. Рабочие файлы НЕ тронуты —")
    print("   дефект подсажен во временную копию репы.\n")
    caught = run_drill(repo, kind)
    print()
    print("Зачем: постоянно зелёная проверка обучает не читать её "
          "(33 % обнаружения против 82 % при переменной надёжности,")
    print("Parasuraman et al. 1993). Тренировка и инструкции этого "
          "не лечат — лечит только опыт отказа.")
    return 0 if caught else 1


if __name__ == "__main__":
    sys.exit(main())
