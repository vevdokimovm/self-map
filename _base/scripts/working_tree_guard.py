"""Сторож эталона: не дать git-командам уничтожить оригинал.

🔴 ЗАЧЕМ. Владелец 09.09.2026, дословно: «САМОЕ ГЛАВНОЕ ТО ЧТО У МЕНЯ
НА МАКЕ — ЭТО И ЕСТЬ ЭТАЛОН. не копия. не частично. ОРИГИНАЛ».

Это переворачивает обычную логику git. В нормальном репозитории рабочее
дерево — копия истории: испортил → `git checkout` вернул. Здесь наоборот:
**история отстаёт от диска**, и команда «восстановить файлы из истории»
на деле откатывает эталон к устаревшему состоянию.

Замер 09.09.2026: `it-base` — 211 файлов расходятся с GitHub,
`exam-kit` — 214, из них **102 неотслеживаемых**. В обычном проекте
неотслеживаемое — мусор сборки; здесь это новые документы, которых
в истории ещё нет. `git clean -fd` уничтожил бы их без следа.

ЧТО ДЕЛАЕТ: считает, сколько работы потеряется от опасной команды,
и показывает это ДО того, как команда выполнена.

🔴 ЧЕГО НЕ ДЕЛАЕТ — И ЭТО ГЛАВНАЯ ГРАНИЦА: не перехватывает git.
Запретить `git reset --hard` из терминала нельзя ничем, кроме обёртки
над самим бинарником, а обёртка ломается первым же вызовом из IDE или
скрипта. Этот инструмент — **измеритель цены**, а не запрет. Он отвечает
на вопрос «что я потеряю», а решает человек.

Применение:
    guard.py <репа>          что потеряется от опасных команд
    guard.py --all           по всем репам с .git
    guard.py --selftest
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402

ОПАСНЫЕ = {
    "git reset --hard": "затрёт рабочее дерево версией из истории",
    "git checkout . / restore .": "перезапишет все изменённые файлы",
    "git clean -fd": "УДАЛИТ все неотслеживаемые файлы",
    "git stash": "спрячет правки в .git (обратимо, но неочевидно)",
}


def _git(корень: Path, *арг: str) -> str:
    res = subprocess.run(["git", "-C", str(корень), *арг],
                         capture_output=True, text=True, encoding="utf-8")
    return res.stdout if res.returncode == 0 else ""


def срез(корень: Path) -> dict:
    """Сколько и чего потеряется от каждой опасной команды."""
    строки = [s for s in _git(корень, "status", "--porcelain").splitlines() if s]
    изменено = sum(1 for s in строки if s[:2].strip() in {"M", "MM", "AM", "D"})
    новых = sum(1 for s in строки if s.startswith("??"))
    # 🔴 Размер СЧИТАЕТСЯ, а не оценивается: «102 файла» звучит абстрактно,
    # «14 МБ документов» — нет. Владелец решает по цене, а не по числу.
    байт = 0
    for s in строки:
        if s.startswith("??"):
            п = корень / s[3:].strip().strip('"')
            if п.is_file():
                байт += п.stat().st_size
            elif п.is_dir():
                байт += sum(f.stat().st_size for f in п.rglob("*") if f.is_file())
    незапушено = len([x for x in _git(корень, "log", "--oneline",
                                      "@{u}..HEAD").splitlines() if x]) \
        if _git(корень, "rev-parse", "--abbrev-ref", "@{u}") else 0
    return {"изменено": изменено, "новых": новых, "байт": байт,
            "незапушено": незапушено, "всего": len(строки)}


def печать(имя: str, д: dict) -> bool:
    """Печатает срез, возвращает True если есть что терять."""
    опасно = д["всего"] > 0 or д["незапушено"] > 0
    if not опасно:
        print(f"  🟢 {имя:<14} чисто — терять нечего")
        return False
    мб = д["байт"] / 1048576
    print(f"  🔴 {имя}")
    if д["изменено"]:
        print(f"       {д['изменено']:>4} изменённых файлов — потеряет `reset --hard`")
    if д["новых"]:
        print(f"       {д['новых']:>4} НОВЫХ файлов ({мб:.1f} МБ) — УДАЛИТ `clean -fd`")
    if д["незапушено"]:
        print(f"       {д['незапушено']:>4} коммитов не запушено — есть только здесь")
    return True


def selftest() -> bool:
    """Канарейка: срез различает чистую репу и репу с потерями."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        к = Path(td)
        subprocess.run(["git", "init", "-q", str(к)], capture_output=True)
        subprocess.run(["git", "-C", str(к), "config", "user.email", "t@t"],
                       capture_output=True)
        subprocess.run(["git", "-C", str(к), "config", "user.name", "t"],
                       capture_output=True)
        (к / "a.txt").write_text("x")
        subprocess.run(["git", "-C", str(к), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(к), "commit", "-qm", "1"], capture_output=True)
        чисто = срез(к)
        (к / "new.txt").write_text("y" * 100)
        (к / "a.txt").write_text("changed")
        грязно = срез(к)
        return (чисто["всего"] == 0 and грязно["новых"] == 1
                and грязно["изменено"] == 1 and грязно["байт"] == 100)


def main() -> int:
    р = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    р.add_argument("репа", nargs="?")
    р.add_argument("--all", action="store_true")
    р.add_argument("--selftest", action="store_true")
    a = р.parse_args()

    if a.selftest:
        ок = selftest()
        print("🟢 канарейка: срез различает чистое и опасное" if ок
              else "🔴 КАНАРЕЙКА УПАЛА")
        return 0 if ок else 1

    _, корень_реп, _ = resolve_roots(__file__)
    if a.all:
        цели = sorted(d for d in корень_реп.iterdir()
                      if d.is_dir() and (d / ".git").exists())
    elif a.репа:
        цели = [корень_реп / a.репа]
    else:
        р.error("нужно имя репы или --all")

    print("🔴 НА ЭТОЙ МАШИНЕ РАБОЧЕЕ ДЕРЕВО — ЭТАЛОН, А НЕ КОПИЯ.")
    print("   История на GitHub ОТСТАЁТ от диска. Команды ниже\n"
          "   не восстанавливают, а откатывают:\n")
    for имя, что in ОПАСНЫЕ.items():
        print(f"     {имя:<28} {что}")
    print("\n   Что потеряется прямо сейчас:\n")

    есть_потери = False
    for ц in цели:
        if not (ц / ".git").exists():
            continue
        есть_потери |= печать(ц.name, срез(ц))

    if есть_потери:
        print("\n   🔴 Прежде чем звать любую из этих команд — выпустить работу:")
        print("      python3 scripts/publish.py <репа>")
    print("\n   🔴 Это ИЗМЕРИТЕЛЬ, а не запрет. Перехватить git он не может:")
    print("      обёртка над бинарником ломается первым вызовом из IDE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
