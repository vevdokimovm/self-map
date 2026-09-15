"""Заголовок и тело релиза — ровно те, что сделал бы деплойер.

🔴 ЗАЧЕМ. 08.09.2026 вахта впервые выпускала релизы сама и написала их
**отсебятиной**: свой заголовок без тезиса, своё тело вместо секции
`CHANGELOG`, ассеты не приложены. Четыре релиза из 531 выбились из строя.
Владелец: «ты сделал полное дерьмо друг. ты видел что деплой как он делает
описание? и ассеты?»

Стандарт при этом был **под рукой и прочитан**: функции `build_notes`,
`safe_title`, `ensure_release` разбирались получасом раньше — искали, откуда
деплойер берёт автора коммита. Тот же класс, что `PIT-205`: источник открыт
и не использован.

🔴 ПАРСЕР НЕ ДУБЛИРУЕТСЯ, А ИЗВЛЕКАЕТСЯ ИЗ `templates/deploy.sh`.
Он живёт там внутри heredoc `PYEOF`. Копия здесь разъехалась бы с оригиналом
при первой же правке деплойера — это `PIT-G`, 21 повтор. Один источник,
и он же канон выпуска.

Применение:
    release_notes.py <версия> [--repo ИМЯ]     печатает заголовок, тело в файл
    release_notes.py --selftest
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

БАЗА = Path(__file__).resolve().parent.parent
ДЕПЛОЙ = БАЗА / "templates" / "deploy.sh"


def извлечь_парсер() -> str:
    """Достаёт парсер CHANGELOG из heredoc деплойера — единственный источник."""
    текст = ДЕПЛОЙ.read_text(encoding="utf-8")
    метка = "cat > \"$PARSER\" <<'PYEOF'\n"
    if метка not in текст:
        raise SystemExit("🔴 в templates/deploy.sh не найден блок парсера PYEOF — "
                         "деплойер изменился, обнови метку здесь")
    начало = текст.index(метка) + len(метка)
    конец = текст.index("PYEOF", начало)
    return текст[начало:конец]


def собрать(версия: str, репа: str, куда: Path, журнал: Path | None = None) -> str:
    """Пишет тело релиза в файл, возвращает готовый заголовок.

    🔴 `журнал` — CHANGELOG ВЫПУСКАЕМОЙ репы. Первая редакция брала
    `CHANGELOG.md` базы всегда: для `base-repo` верно, для любой другой
    репы описание собралось бы из чужого журнала — или не собралось вовсе.
    Найдено чтением кода 13.09.2026, до первого выпуска чужой репы.
    """
    журнал = журнал or (БАЗА / "CHANGELOG.md")
    with tempfile.TemporaryDirectory() as tmp:
        парсер = Path(tmp) / "chlog.py"
        парсер.write_text(извлечь_парсер(), encoding="utf-8")
        res = subprocess.run(
            [sys.executable, str(парсер), str(журнал), версия, str(куда)],
            capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        raise SystemExit(f"🔴 в CHANGELOG нет секции [{версия}] — "
                         f"релиз без описания не создаётся (правило деплойера)")
    тезис = res.stdout.strip()
    return f"{репа} v{версия} — {тезис}" if тезис else f"{репа} v{версия}"


def selftest() -> bool:
    """Канарейка: парсер извлекается и строит заголовок с тезисом.

    🔴 Проверяет ИЗВЛЕЧЕНИЕ, а не только разбор: если деплойер переименует
    heredoc, инструмент обязан упасть громко, а не собрать пустой релиз.
    """
    код = извлечь_парсер()
    if "head_re" not in код or "NOTHESIS" not in код:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        п, ж, в = Path(tmp) / "p.py", Path(tmp) / "CH.md", Path(tmp) / "out.md"
        п.write_text(код, encoding="utf-8")
        ж.write_text("## [1.2.3] — 2026-01-01 — Тезис примера (MINOR)\n\nтело\n",
                     encoding="utf-8")
        r = subprocess.run([sys.executable, str(п), str(ж), "1.2.3", str(в)],
                           capture_output=True, text=True)
        return r.returncode == 0 and r.stdout.strip() == "Тезис примера" and в.exists()


def main() -> int:
    р = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    р.add_argument("версия", nargs="?")
    р.add_argument("--repo", default="base-repo")
    р.add_argument("--out", type=Path)
    р.add_argument("--changelog", type=Path, help="CHANGELOG выпускаемой репы")
    р.add_argument("--selftest", action="store_true")
    a = р.parse_args()

    if a.selftest:
        ок = selftest()
        print("🟢 канарейка: парсер извлекается и даёт тезис" if ок
              else "🔴 КАНАРЕЙКА УПАЛА — парсер не извлекается")
        return 0 if ок else 1

    if not a.версия:
        р.error("нужна версия")
    куда = a.out or Path(tempfile.gettempdir()) / f"notes-{a.версия}.md"
    заголовок = собрать(a.версия, a.repo, куда, a.changelog)
    print(заголовок)
    print(f"тело: {куда}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
