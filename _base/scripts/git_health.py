"""Здоровье git-реп: пять настроек, каждая из которых молчит, пока не укусит.

🔴 ЗАЧЕМ. Вопрос владельца 09.09.2026: «как-то можно автоматизировать
проверки на эту тему или это опасность/риск этого выбора?»

Ответ — автоматизируется, и вот чем. За один день нашлось ПЯТЬ настроек,
которых не было, и все пять вели себя одинаково: `git_adopt.py` отрабатывал
с кодом 0, печатал «🟢 заведён», ни одна команда не падала. Симптом
не наступал, пока не понадобится — а тогда выглядел как порча репозитория.

| настройка | если её нет |
|---|---|
| `extensions.partialClone` | git считает репу **повреждённой**: `unable to read sha1 file` |
| `core.autocrlf=false` | `git status` уходит в сеть **по запросу на файл** |
| upstream ветки | `push` без аргументов падает; счётчик «опередил на N» врёт |
| `core.hooksPath` | репа **без защиты от секретов и подписи** |
| `maintenance.auto` не должен быть `false` | репа **никогда не делает авто-gc** (остаётся навсегда после `unregister`) |

🔴 ПОЧЕМУ ПРОВЕРКА, А НЕ ВНИМАТЕЛЬНОСТЬ. Первую нашёл независимый ресёрч,
остальные четыре — только когда вахта пошла перебирать список руками.
Правило, которое надо помнить, не работает — это в системе доказано трижды
(`PIT-202`, `PIT-G`, `PIT-211`).

🔴 ЧЕГО НЕ ПРОВЕРЯЕТ: содержимое реп, целостность объектов (`git fsck`),
живость remote. Только конфигурацию, и только ту, чьё отсутствие уже
кусало. Список растёт по мере находок, а не по догадкам.

Применение:
    git_health.py            все репы с .git
    git_health.py --fix      починить найденное
    git_health.py --selftest
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402


def _cfg(корень: Path, ключ: str) -> str:
    res = subprocess.run(["git", "-C", str(корень), "config", "--get", ключ],
                         capture_output=True, text=True)
    return res.stdout.strip()


def _есть_upstream(корень: Path) -> bool:
    return subprocess.run(["git", "-C", str(корень), "rev-parse",
                           "--abbrev-ref", "@{u}"],
                          capture_output=True).returncode == 0


def _путь_хуков(корень: Path) -> str | None:
    for к in (".githooks", "_base/.githooks"):
        if (корень / к).is_dir():
            return к
    return None


def проверить(корень: Path) -> list[tuple[str, str, str | None]]:
    """Список (что не так, почему опасно, чем чинить). Пусто — здорова."""
    беды = []

    if not _cfg(корень, "extensions.partialClone"):
        # Только если репа действительно частичная — у полного клона
        # этого флага быть и не должно, и требовать его было бы ложной
        # тревогой (`PIT-159`: правку прозы под ложное срабатывание).
        if _cfg(корень, "remote.origin.promisor") == "true":
            беды.append((
                "extensions.partialClone не задан",
                "git считает репу ПОВРЕЖДЁННОЙ: unable to read sha1 file",
                "config extensions.partialClone origin"))

    if _cfg(корень, "core.autocrlf") != "false":
        беды.append((
            f"core.autocrlf = {_cfg(корень, 'core.autocrlf') or 'из глобального'}",
            "git status уходит в сеть по одному запросу НА ФАЙЛ",
            "config core.autocrlf false"))

    if not _есть_upstream(корень):
        беды.append((
            "у ветки нет upstream",
            "push без аргументов падает; счётчик незапушенного врёт",
            None))

    путь = _путь_хуков(корень)
    # Репа без своих хуков — это ПУБЛИЧНОЕ ЗЕРКАЛО, и так задумано:
    # проверки проходятся, когда копия делается из приватной репы в зеркало,
    # а не в самом зеркале (владелец, 13.09.2026). Поэтому здесь не требуется.
    if путь and _cfg(корень, "core.hooksPath") != путь:
        беды.append((
            f"core.hooksPath не указывает на {путь}",
            "репа БЕЗ защиты от секретов и от подписи ассистента",
            f"config core.hooksPath {путь}"))

    if _cfg(корень, "maintenance.auto") == "false":
        беды.append((
            "maintenance.auto = false",
            "репа НИКОГДА не делает авто-gc; остаётся после unregister",
            "config --unset maintenance.auto"))

    if _cfg(корень, "remote.origin.promisor") == "true":
        for ключ in ("diff.renames", "status.renames"):
            if _cfg(корень, ключ) != "false":
                беды.append((
                    f"{ключ} не выключен",
                    "поиск переименований тянет старые блобы из сети: "
                    "замер — 1151 запрос на один коммит",
                    f"config {ключ} false"))

    return беды


def selftest() -> bool:
    """Канарейка: различает здоровую репу и репу с недостачей."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        к = Path(td)
        subprocess.run(["git", "init", "-q", str(к)], capture_output=True)
        # Свежая репа: нет upstream и нет autocrlf=false — минимум две беды.
        плохо = проверить(к)
        subprocess.run(["git", "-C", str(к), "config", "core.autocrlf", "false"],
                       capture_output=True)
        лучше = проверить(к)
        # 🔴 Канарейка проверяет и то, что проверка РЕАГИРУЕТ на починку:
        # инструмент, который ругается всегда, проходит тест «умеет находить»
        # и бесполезен.
        return len(плохо) >= 2 and len(лучше) == len(плохо) - 1


def main() -> int:
    р = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    р.add_argument("--fix", action="store_true")
    р.add_argument("--selftest", action="store_true")
    a = р.parse_args()

    if a.selftest:
        ок = selftest()
        print("🟢 канарейка: находит недостачу и видит починку" if ок
              else "🔴 КАНАРЕЙКА УПАЛА")
        return 0 if ок else 1

    _, корень_реп, _ = resolve_roots(__file__)
    репы = sorted(d for d in корень_реп.iterdir()
                  if d.is_dir() and (d / ".git").exists())
    if not репы:
        print("реп с .git нет")
        return 0

    всего = 0
    for репа in репы:
        беды = проверить(репа)
        if not беды:
            print(f"  🟢 {репа.name}")
            continue
        всего += len(беды)
        print(f"  🔴 {репа.name}")
        for что, почему, чинить in беды:
            print(f"       {что}")
            print(f"         → {почему}")
            if a.fix and чинить:
                subprocess.run(["git", "-C", str(репа)] + чинить.split(),
                               capture_output=True)
                print("         🟢 починено")

    if всего:
        print(f"\n  недостач: {всего}")
        if not a.fix:
            print("  починить: python3 scripts/git_health.py --fix")
            print("  🔴 upstream автоматически не ставится — нужен fetch "
                  "ветки, а он сетевой")
        return 1
    print(f"\n  🟢 все {len(репы)} реп здоровы")
    return 0


if __name__ == "__main__":
    sys.exit(main())
