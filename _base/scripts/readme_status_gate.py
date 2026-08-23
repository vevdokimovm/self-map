#!/usr/bin/env python3
"""readme_status_gate.py — README не отстаёт от репы (stdlib-only).

Почему этот гейт существует. README — первое, что открывает владелец, чтобы за десять
секунд понять, что в репе происходит. Но обновляют его последним и забывают чаще всего:
версия ушла вперёд, а README описывает состояние трёхнедельной давности. Дефект тихий —
файл читается и выглядит правдой, просто правда устарела. Это тот же класс, что PIT-063
(документация называет каноном то, что каноном быть перестало) и `72-source-of-truth.md`.

ИСТОЧНИК ПРАВДЫ: файл VERSION. Блок статуса в README — производное и обязан совпадать.

Формат блока (в README.md, сразу после заголовка):

    <!-- STATUS -->
    > **Сейчас:** `v1.61.0` · 2026-08-20 · Одна строка: что происходит прямо сейчас.
    <!-- /STATUS -->

Проверки:
  1. Блок есть и разбирается.
  2. Версия в блоке == VERSION.
  3. Дата — валидный ISO и не из будущего.
  4. Описание не пустое и не плейсхолдер.
  5. Только в режиме хука (--staged): подняли VERSION → README обязан быть в том же
     коммите, и описание обязано отличаться от предыдущего. Иначе «обновление» README
     сводится к правке цифры при неизменном тексте, а это ровно то, от чего гейт.

Запуск из корня репы:
    python3 scripts/readme_status_gate.py             # проверка, exit 1 при расхождении
    python3 scripts/readme_status_gate.py --fix       # проставить версию и дату
    python3 scripts/readme_status_gate.py --staged    # режим pre-commit

--fix чинит только механическую половину — версию и дату. **Описание он не трогает
и не выдумывает:** ради описания гейт и написан, автоматически заполненная строка
вернула бы ту же несвежесть, только с правильным номером.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

README = "README.md"
VERSION_FILE = "VERSION"

OPEN_TAG = "<!-- STATUS -->"
CLOSE_TAG = "<!-- /STATUS -->"

BLOCK_RE = re.compile(
    re.escape(OPEN_TAG) + r"(?P<body>.*?)" + re.escape(CLOSE_TAG),
    re.DOTALL,
)
LINE_RE = re.compile(
    r"^>\s*\*\*Сейчас:\*\*\s*`v(?P<version>\d+\.\d+\.\d+)`"
    r"\s*·\s*(?P<date>\d{4}-\d{2}-\d{2})"
    r"\s*·\s*(?P<summary>.+?)\s*$",
    re.MULTILINE,
)
PLACEHOLDER_RE = re.compile(r"^\s*(<.*>|TODO|—|\.\.\.|…)\s*$")

# Описание обязано СООБЩАТЬ состояние, а не занимать место. Без нижней границы гейт
# проходится случайно: «.» и «ок» удовлетворяли проверке на плейсхолдер и считались
# заполненными. Проверка, которую можно пройти, не обладая защищаемым свойством,
# проверкой не является — 71-fail-loud-and-sourcing.md §7в.
MIN_SUMMARY_CHARS = 20
MIN_SUMMARY_WORDS = 3

TEMPLATE = (
    f"{OPEN_TAG}\n"
    "> **Сейчас:** `v{version}` · {date} · <одна строка: что происходит прямо сейчас>\n"
    f"{CLOSE_TAG}"
)


class Status:
    """Разобранный блок статуса README."""

    def __init__(self, version: str, date: str, summary: str):
        self.version = version
        self.date = date
        self.summary = summary


def read_text(root: Path, name: str) -> str | None:
    path = root / name
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def parse_status(readme_text: str) -> Status | None:
    block = BLOCK_RE.search(readme_text)
    if not block:
        return None
    line = LINE_RE.search(block.group("body"))
    if not line:
        return None
    return Status(line.group("version"), line.group("date"), line.group("summary"))


def staged_files() -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def summary_at_head(root: Path) -> str | None:
    """Описание из README предыдущего коммита — чтобы поймать правку одной цифры."""
    result = subprocess.run(
        ["git", "show", f"HEAD:{README}"],
        capture_output=True, text=True, cwd=root,
    )
    if result.returncode != 0:
        return None
    previous = parse_status(result.stdout)
    return previous.summary if previous else None


def check(root: Path, staged_mode: bool) -> list[str]:
    problems: list[str] = []

    version_text = read_text(root, VERSION_FILE)
    if version_text is None:
        return [f"нет {VERSION_FILE} — гейту не с чем сверять README"]
    version = version_text.strip()

    readme_text = read_text(root, README)
    if readme_text is None:
        return [f"нет {README} — заводится из templates/REPO_README_TEMPLATE.md"]

    status = parse_status(readme_text)
    if status is None:
        return [
            f"в {README} нет разбираемого блока статуса. Добавь сразу после заголовка:\n"
            + "\n".join("      " + line for line in
                        TEMPLATE.format(version=version,
                                        date=dt.date.today().isoformat()).splitlines())
        ]

    if status.version != version:
        problems.append(
            f"версия в блоке статуса ({status.version}) не совпадает с {VERSION_FILE} "
            f"({version}) — README описывает прошлое состояние"
        )

    try:
        parsed_date = dt.date.fromisoformat(status.date)
    except ValueError:
        problems.append(f"дата «{status.date}» не разбирается как ISO (ГГГГ-ММ-ДД)")
    else:
        if parsed_date > dt.date.today():
            problems.append(f"дата {status.date} из будущего")

    if PLACEHOLDER_RE.match(status.summary):
        problems.append(
            f"описание в блоке статуса — плейсхолдер («{status.summary}»). "
            "Одна живая строка: что в репе происходит прямо сейчас"
        )
    else:
        words = len(status.summary.split())
        if len(status.summary) < MIN_SUMMARY_CHARS or words < MIN_SUMMARY_WORDS:
            problems.append(
                f"описание слишком короткое, чтобы что-то сообщать "
                f"(«{status.summary}» — {len(status.summary)} симв., {words} слов; "
                f"нужно от {MIN_SUMMARY_CHARS} симв. и {MIN_SUMMARY_WORDS} слов). "
                "Это строка, по которой состояние репы понимают за десять секунд"
            )

    if staged_mode:
        touched = staged_files()
        if VERSION_FILE in touched and README not in touched:
            problems.append(
                f"{VERSION_FILE} поднят, а {README} не в коммите. "
                "Версия ушла вперёд — README обязан ехать вместе с ней"
            )
        elif VERSION_FILE in touched:
            previous = summary_at_head(root)
            if previous is not None and previous == status.summary:
                problems.append(
                    "версия поднята, но описание в блоке статуса не изменилось:\n"
                    f'      «{status.summary}»\n'
                    "      Смена цифры без смены текста оставляет README таким же "
                    "несвежим, каким он был"
                )

    return problems


def fix(root: Path) -> int:
    """Проставить версию и дату. Описание остаётся на человеке."""
    version_text = read_text(root, VERSION_FILE)
    readme_text = read_text(root, README)
    if version_text is None or readme_text is None:
        print(f"нечего чинить: нужны и {VERSION_FILE}, и {README}", file=sys.stderr)
        return 1

    version = version_text.strip()
    today = dt.date.today().isoformat()
    status = parse_status(readme_text)

    if status is None:
        print(f"в {README} нет блока статуса — вставь вручную после заголовка:\n")
        print(TEMPLATE.format(version=version, date=today))
        return 1

    if status.version == version and status.date == today:
        print(f"блок статуса уже актуален: v{version} · {today}")
        return 0

    updated = LINE_RE.sub(
        lambda m: (f"> **Сейчас:** `v{version}` · {today} · {m.group('summary')}"),
        readme_text,
        count=1,
    )
    (root / README).write_text(updated, encoding="utf-8")
    print(f"проставлено: v{status.version} · {status.date} → v{version} · {today}")
    print("описание НЕ тронуто — перечитай строку и перепиши её под текущее состояние")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true",
                        help="проставить версию и дату в блоке статуса")
    parser.add_argument("--staged", action="store_true",
                        help="режим pre-commit: сверяться с индексом git")
    parser.add_argument("--root", default=".", help="корень репы (по умолчанию текущий)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if args.fix:
        return fix(root)

    problems = check(root, staged_mode=args.staged)
    if not problems:
        return 0

    print("\n🟠 README ОТСТАЁТ ОТ РЕПЫ — остановлено\n")
    for problem in problems:
        print(f"   {problem}")
    print(f"\n   Правило: 00-infrastructure/75-readme-status-block.md")
    print(f"   Механическую часть проставит: python3 scripts/readme_status_gate.py --fix\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
