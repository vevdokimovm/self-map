#!/usr/bin/env python3
"""Структура репы по требованию — не снимок, который хранится и гниёт.

ПОЧЕМУ СКРИПТ, А НЕ ФАЙЛ В БАЗЕ (`76-repo-classes.md` §8 — та же ООП-логика,
что уже дважды подтвердилась 27.08.2026 на `repos-map.md` и `.repo-meta`):
сохранённый снимок структуры устареет в день, когда в любой репе появится
новая папка, и ничего не заметит расхождения. Читать с диска заново каждый
раз — единственный способ не соврать.

ЧТО ДЕЛАЕТ. Верхнеуровневые папки репы (глубина 1, без служебных) + число
файлов в каждой рекурсивно — таблица вида README-паттерна «Структура»,
уже используемого в `health-vault`/других репах. Столбец «Что внутри» —
не заполняется машиной (это синтез, не подсчёт) — оставляется TODO при
первой генерации, дальше правится руками и остаётся стабильным, пока сам
скрипт перезапускают только для чисел.

ЗАПУСК
    gen_repo_structure.py <репа>              таблица в stdout
    gen_repo_structure.py <репа> --update-readme   вписать/обновить блок в README.md
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

SKIP_DIRS = {
    ".git", "_base", "__MACOSX", "node_modules", ".idea", "__pycache__",
    ".venv", "venv", ".pytest_cache", "dist", "build", "web",
}
SKIP_PREFIX = ("_", ".")

MARKER_START = "<!-- STRUCTURE:AUTO:START -->"
MARKER_END = "<!-- STRUCTURE:AUTO:END -->"


def count_files(d: Path) -> int:
    n = 0
    for p in d.rglob("*"):
        if p.is_dir():
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(d).parts[:-1]):
            continue
        n += 1
    return n


def build_table(repo: Path, existing_notes: dict[str, str]) -> str:
    rows = []
    for child in sorted(repo.iterdir()):
        if not child.is_dir():
            continue
        if child.name in SKIP_DIRS or child.name.startswith(SKIP_PREFIX):
            continue
        n = count_files(child)
        if n == 0:
            continue
        note = existing_notes.get(child.name, "TODO — заполнить вручную")
        rows.append(f"| `{child.name}/` | {n} | {note} |")

    if not rows:
        return "_репа пуста или всё содержимое в служебных папках_\n"

    header = "| Папка | Файлов | Что внутри |\n|---|---|---|\n"
    return header + "\n".join(rows) + "\n"


def parse_existing_notes(readme_text: str) -> dict[str, str]:
    """Не затирать уже написанные вручную описания при перегенерации чисел."""
    notes: dict[str, str] = {}
    for line in readme_text.splitlines():
        m = re.match(r"\|\s*`([^`]+)/`\s*\|\s*\d+\s*\|\s*(.+?)\s*\|\s*$", line)
        if m:
            notes[m.group(1)] = m.group(2)
    return notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--update-readme", action="store_true")
    ap.add_argument("--force", action="store_true", help="вписать блок даже в product/profile-репу")
    a = ap.parse_args()

    repo = Path(a.repo).expanduser().resolve()
    if not repo.is_dir():
        print(f"нет такой репы: {repo}")
        return 2

    # PIT-156-родня, найдено 28.08.2026: блок «Структура» — служебная
    # навигация для личных репов, но был вписан и в публичные продукты
    # (`vevdokimovm.github.io`, `finpilot`, `algorithms-site`, `vk-graph`,
    # `salvation`, `game-analytics-engine`, `claude-usage`) — «TODO —
    # заполнить вручную» на живой странице выглядит как незаконченный
    # продукт перед работодателем/рекрутером. `.repo-class` — `product`
    # или `profile` — блокирует --update-readme без явного --force.
    if a.update_readme:
        class_file = repo / ".repo-class"
        repo_class = class_file.read_text(encoding="utf-8").strip() if class_file.is_file() else ""
        if repo_class in {"product", "profile"} and not a.force:
            print(
                f"{repo.name}: .repo-class = {repo_class} — публичный/витринный класс. "
                f"«Структура» — служебный блок для личных репов, на публичной странице "
                f"выглядит незаконченным. Добавь --force, если действительно нужно."
            )
            return 2

    readme = repo / "README.md"
    existing_notes: dict[str, str] = {}
    if readme.is_file():
        existing_notes = parse_existing_notes(readme.read_text(encoding="utf-8", errors="replace"))

    table = build_table(repo, existing_notes)

    if not a.update_readme:
        print(table)
        return 0

    if not readme.is_file():
        print(f"нет README.md в {repo} — не во что вписывать, запусти без --update-readme")
        return 2

    text = readme.read_text(encoding="utf-8", errors="replace")
    block = f"{MARKER_START}\n{table}{MARKER_END}"

    if MARKER_START in text and MARKER_END in text:
        # Уже маркирован нашим прошлым проходом — заменить только блок.
        text = re.sub(
            rf"{re.escape(MARKER_START)}.*?{re.escape(MARKER_END)}",
            block, text, flags=re.DOTALL,
        )
    else:
        # Найден ли уже заголовок "## Структура" (ручной, без маркеров)? Замена
        # ЕГО содержимого, а не добавление второго — баг 27.08.2026: 8 репо
        # получили дублированный заголовок именно из-за пропуска этой ветки.
        heading_re = re.compile(r"^## Структура\s*$", re.MULTILINE)
        m = heading_re.search(text)
        if m:
            start = m.end()
            next_heading = re.search(r"^## ", text[start:], re.MULTILINE)
            end = start + next_heading.start() if next_heading else len(text)
            text = text[:start] + "\n\n" + block + "\n" + text[end:]
        else:
            text = text.rstrip("\n") + "\n\n## Структура\n\n" + block + "\n"

    readme.write_text(text, encoding="utf-8")
    print(f"обновлено: {readme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
