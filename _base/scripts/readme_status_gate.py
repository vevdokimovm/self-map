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
    # 🔴 Время ОПЦИОНАЛЬНО: с 03.09.2026 система пишет `ГГГГ-ММ-ДД ЧЧ:ММ`,
    # но записи, сделанные до этого, законны и нарушением не становятся
    # (тот же принцип, что «легаси принимается целиком» в стандарте `43`).
    r"\s*·\s*(?P<date>\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)"
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


def repo_class(root: Path) -> str:
    """Класс репы из `.repo-class`; пусто, если файла нет."""
    path = root / ".repo-class"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def check(root: Path, staged_mode: bool) -> list[str]:
    problems: list[str] = []

    # 🔴 02.09.2026. Гейт не знал про классы вовсе и требовал служебный блок
    # «Сейчас: v1.1.2 · Пересборка: архив содержал устаревший канон» в README
    # спецрепы профиля — то есть на публичной странице найма, которую читает
    # рекрутёр. Владелец увидел это в браузере раньше, чем любая проверка.
    # STATUS существует, чтобы ВЛАДЕЛЕЦ за десять секунд понял состояние репы;
    # у витрины человека читатель другой, и внутренняя версия ему не адресована.
    if repo_class(root) == "profile":
        return []

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


def changelog_summary(root: Path) -> str | None:
    """Тезис верхней секции CHANGELOG — заготовка описания для нового блока.

    Формат секции: `## [1.2.3] — 2026-08-28 — Тезис (MINOR)`. Берём тезис,
    отрезая версию, дату и хвост `(MAJOR|MINOR|PATCH)`. Это НЕ окончательный
    текст — вахта обязана его перечитать; но пустой плейсхолдер, который никто
    не заполняет, хуже честной заготовки из соседнего файла.
    """
    text = read_text(root, "CHANGELOG.md")
    if not text:
        return None
    for line in text.splitlines():
        # Время опционально — см. `LINE_RE`. Без `(?:...)?` заголовок со
        # временем не распознавался бы вовсе, и гейт молча брал бы заголовок
        # СЛЕДУЮЩЕЙ секции: ложь тем опаснее, что выглядит успехом.
        m = re.match(r"^##\s*\[[^\]]+\]\s*[—-]\s*\d{4}-\d{2}-\d{2}"
                     r"(?:\s+\d{2}:\d{2})?\s*[—-]\s*(.+?)\s*$", line)
        if m:
            return re.sub(r"\s*\((?:MAJOR|MINOR|PATCH)\)\s*$", "", m.group(1)).strip()
    return None


def insert_status_block(root: Path, version: str, today: str) -> int:
    """Создать блок статуса в README, которого его нет.

    🔴 Заведено 28.08.2026: замер по диску показал **58 реп из 63 без блока**.
    Прежняя редакция `--fix` в этом случае печатала «вставь вручную» и выходила
    с кодом 1 — то есть для 92 % системы инструмент не работал вовсе, а гейт
    исправно жаловался на каждую. Автоматизировать было нечего только на бумаге:
    и версия, и дата, и заготовка описания берутся из файлов самой репы.
    """
    readme_text = read_text(root, README) or ""
    lines = readme_text.split("\n")
    # Вставляем сразу после H1; если H1 нет — в самое начало.
    idx = 0
    for i, ln in enumerate(lines[:10]):
        if ln.startswith("# "):
            idx = i + 1
            break
    summary = changelog_summary(root) or "<одна строка: что происходит прямо сейчас>"
    # 🔴 Ссылаемся ТОЛЬКО на файлы, которые существуют. Первая редакция вписывала
    # все три ссылки безусловно — и завела 23 битые ссылки на `TASKS.md` в репах,
    # где такого файла нет (поймано тем же гейтом в тот же заход, 28.08.2026).
    # Массовый инструмент обязан проверять предпосылку в КАЖДОЙ репе, а не
    # исходить из того, что все устроены как та, на которой его писали.
    nav = [
        (f"Открытое — [`{n}`]({n})" if kind == "roadmap" else
         f"на владельце — [`{n}`]({n})" if kind == "tasks" else
         f"где стоим — [`{n}`]({n}) §0")
        for kind, n in (("roadmap", "ROADMAP.md"), ("tasks", "TASKS.md"),
                        ("watchlog", "WATCHLOG.md"))
        if (root / n).is_file()
    ]
    block = [
        "",
        OPEN_TAG,
        f"> **Сейчас:** `v{version}` · {today} · {summary}",
    ]
    if nav:
        block.append("> " + " · ".join(nav) + ".")
    block.append(CLOSE_TAG)
    lines[idx:idx] = block
    (root / README).write_text("\n".join(lines), encoding="utf-8")
    src = "из CHANGELOG" if changelog_summary(root) else "ПЛЕЙСХОЛДЕР — переписать"
    print(f"создан блок статуса: v{version} · {today} · описание {src}")
    return 0


def fix(root: Path, create: bool = False) -> int:
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
        if create:
            return insert_status_block(root, version, today)
        print(f"в {README} нет блока статуса — вставь вручную "
              f"(или прогони с --create):\n")
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


def selftest() -> int:
    """Канарейка `--create`: блок реально появляется и реально разбирается.

    Проверяется ВЫВОД (файл после правки парсится обратно `parse_status()`),
    а не факт, что функция не упала (`PIT-016`). Работает на временной репе,
    настоящие файлы не трогает.
    """
    import tempfile

    bad = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td).resolve()

        # сценарий 1: есть CHANGELOG канонического формата — описание берётся оттуда
        (root / "VERSION").write_text("2.3.4\n", encoding="utf-8")
        (root / "README.md").write_text("# demo\n\nтекст репы\n", encoding="utf-8")
        (root / "CHANGELOG.md").write_text(
            "# CHANGELOG\n\n## [2.3.4] — 2026-08-28 — Живой тезис релиза (MINOR)\n\nтело\n",
            encoding="utf-8")
        fix(root, create=True)
        text = (root / "README.md").read_text(encoding="utf-8")
        st = parse_status(text)
        if st is None:
            bad.append("блок создан, но обратно не разбирается parse_status()")
        else:
            if st.version != "2.3.4":
                bad.append(f"версия в блоке {st.version!r}, ожидалась '2.3.4'")
            if "Живой тезис релиза" not in text:
                bad.append("описание не подхватилось из CHANGELOG")
            if "(MINOR)" in text:
                bad.append("хвост (MINOR) не отрезан от тезиса")
        if text.index(OPEN_TAG) < text.index("# demo"):
            bad.append("блок вставлен ДО заголовка H1, а не после")
        # ссылка только на существующие файлы: здесь нет ни ROADMAP, ни TASKS,
        # ни WATCHLOG — значит навигационной строки быть не должно вовсе
        for absent in ("ROADMAP.md", "TASKS.md", "WATCHLOG.md"):
            if f"]({absent})" in text:
                bad.append(f"ссылка на несуществующий {absent} — битая ссылка в README")

        # сценарий 2: CHANGELOG в чужом формате — честный плейсхолдер, не выдумка
        root2 = root / "other"
        root2.mkdir()
        (root2 / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        (root2 / "README.md").write_text("# other\n", encoding="utf-8")
        (root2 / "CHANGELOG.md").write_text(
            "# CHANGELOG\n\n## v1.0.0 — 2026-08-26\n\nтело без тезиса\n", encoding="utf-8")
        fix(root2, create=True)
        t2 = (root2 / "README.md").read_text(encoding="utf-8")
        if "одна строка" not in t2:
            bad.append("чужой формат CHANGELOG: ожидался плейсхолдер, а не выдуманный тезис")

        # сценарий 3: блок уже есть — --create не должен его дублировать
        before = t2.count(OPEN_TAG)
        fix(root2, create=True)
        after = (root2 / "README.md").read_text(encoding="utf-8").count(OPEN_TAG)
        if after != before:
            bad.append(f"повторный --create задублировал блок: {before} → {after}")

    if bad:
        print("selftest FAIL:")
        for b in bad:
            print("  ·", b)
        return 1
    print("selftest OK: блок создаётся и разбирается, описание берётся из CHANGELOG, "
          "чужой формат даёт честный плейсхолдер, повтор не дублирует")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true",
                        help="проставить версию и дату в блоке статуса")
    parser.add_argument("--staged", action="store_true",
                        help="режим pre-commit: сверяться с индексом git")
    parser.add_argument("--root", default=".", help="корень репы (по умолчанию текущий)")
    parser.add_argument("--create", action="store_true",
                        help="создать блок статуса, если его нет "
                             "(описание — заготовка из верхней секции CHANGELOG)")
    parser.add_argument("--selftest", action="store_true",
                        help="канарейка режима --create на временной репе")
    args = parser.parse_args()

    if args.selftest:
        return selftest()

    root = Path(args.root).resolve()
    if args.fix or args.create:
        return fix(root, create=args.create)

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
