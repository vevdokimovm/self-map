#!/usr/bin/env python3
"""examples_check.py — команды в документах существуют или только написаны?

🔴 КАНДИДАТ №9 ОЧЕРЕДИ ВНЕДРЕНИЯ: «команды в ритуалах должны запускаться,
а не только читаться» (`08-systems-theory-lab/INDUSTRY_VS_US.md`).

ПОВОД ИЗМЕРЕН В ЭТОТ ЖЕ ДЕНЬ, ТРИЖДЫ:

  · `close_batch.py .` — пример подразумевал путь, скрипт ждал имя репы;
  · `sync_base_local.py --check` — в докстроке без имени репы, а скрипт
    требовал его и отказывал;
  · `--force` был объявлен ПОСЛЕ `parse_args()` — то есть существовал
    в коде и не существовал для разбора, а в докстроке уже упоминался.

Во всех трёх случаях документ описывал команду, которой нет. Читающий верит
документу — он для того и написан.

ЧТО ПРОВЕРЯЕТСЯ (и почему не запуск):

  1. **скрипт существует** — путь из команды `python3 scripts/X.py` ведёт
     к файлу;
  2. **флаг объявлен** — каждый `--флаг` в примере есть в `add_argument`
     этого скрипта.

🔴 ПОЧЕМУ НЕ ЗАПУСКАТЬ КОМАНДЫ ПО-НАСТОЯЩЕМУ. Примеры в этой системе меняют
состояние: поднимают версию, собирают архив, раздают канон по шестидесяти
репам. Проверка, исполняющая документацию, была бы разрушительнее любого
дефекта, который она ищет. Проверяется **существование**, не поведение —
это меньше, чем хотелось бы, и это честная граница.

🔴 ЧЕГО НЕ ЛОВИТ (`71` §7г-бис):

  · **семантику аргумента** — флаг может существовать и значить не то;
  · команды не на Python (`bash`, `git`, `gh`) — у них нет объявленных
    флагов, которые можно сверить из файла;
  · пример, верный на момент написания и устаревший по смыслу: «сначала A,
    потом B» проверке недоступно.

ЗАПУСК
    examples_check.py              по base-repo
    examples_check.py --repo ИМЯ   другая репа
    examples_check.py --selftest   канарейка
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402
BASE_REPO, REPOS, FROM_KIT = resolve_roots(__file__)

# Команда вида `python3 scripts/имя.py --флаг ...` внутри строки документа.
CMD_RE = re.compile(r"python3?\s+(?P<path>[\w./-]*scripts/[\w_-]+\.py)"
                    r"(?P<args>[^\n`]*)")
FLAG_RE = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]+)")
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "_base"}

# 🔴 Явное исключение для ИСТОРИЧЕСКИХ команд. Карточка `PIT-NNN`
# свидетельствует о том, что было, а не о том, как звать скрипт сегодня;
# переписать её значило бы подделать свидетельство. Но и краснеть вечно
# проверка не должна — постоянно красная проверка обучает не читать себя.
# Поэтому исключение ставится СТРОКОЙ РЯДОМ, а не списком в коде: причина
# живёт там же, где предмет, и не отстаёт от него.
#
#     <!-- examples-check: историческая команда -->
#
# Маркер действует на 10 строк ниже себя — ровно на одну карточку.
HISTORIC_RE = re.compile(r"<!--\s*examples-check:\s*[^>]*-->")
HISTORIC_SPAN = 10


def declared_flags(script: Path) -> set[str] | None:
    """Флаги, известные скрипту. None — файл не разбирается.

    🔴 Собираются ВСЕ строковые литералы вида `--имя`, а не только аргументы
    `add_argument`. Причина найдена ложной тревогой 29.08.2026:
    `base_coverage.py` разбирает аргументы вручную — `if "--adr004" in
    sys.argv` — и проверка, знавшая только `argparse`, объявила рабочий флаг
    несуществующим. Инструмент, признающий один способ из двух, уверенно
    врёт про второй.

    🔴 Цена этого решения названа честно: проверка теперь ловит **«флаг нигде
    не упомянут в скрипте»** — это всегда дефект. Она НЕ ловит «упомянут,
    но не работает» (объявлен после `parse_args`, лежит в мёртвой ветке).
    Слабее, чем хотелось, но без ложных тревог, а ложная тревога в проверке
    документации особенно дорога: она толкает править верный документ.
    """
    try:
        tree = ast.parse(script.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return None
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value.startswith("--")}


def check_repo(repo: Path) -> list[str]:
    """Найденные расхождения между документами и скриптами."""
    problems = []
    cache: dict[Path, set[str] | None] = {}
    for doc in sorted(repo.rglob("*.md")):
        if any(p in SKIP_DIRS for p in doc.relative_to(repo).parts):
            continue
        try:
            text = doc.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Строки, накрытые маркером исторической команды.
        excused = set()
        for line_no, line in enumerate(text.splitlines()):
            if HISTORIC_RE.search(line):
                excused.update(range(line_no, line_no + HISTORIC_SPAN + 1))

        for m in CMD_RE.finditer(text):
            if text[:m.start()].count("\n") in excused:
                continue
            rel = m.group("path").lstrip("./")
            where = doc.relative_to(repo)
            # 🔴 Путь может указывать в ТРИ разных места, и все три законны.
            # Первая редакция знала одно — «внутри этой репы» — и объявила
            # четыре живых скрипта отсутствующими: команды в планировщике
            # зовут `base-repo/scripts/…`, то есть соседнюю репу. Проверка,
            # знающая один способ адресации из трёх, уверенно врёт про два.
            candidates = [
                repo / rel,                 # путь от корня репы
                REPOS / rel,                # путь от корня всех реп
                repo / rel[rel.index("scripts/"):],   # только хвост
            ]
            script = next((c for c in candidates if c.is_file()), None)
            if script is None:
                script = candidates[0]
            if not script.is_file():
                problems.append(f"{where}: команда зовёт {rel} — файла нет")
                continue
            if script not in cache:
                cache[script] = declared_flags(script)
            flags = cache[script]
            if flags is None:
                continue
            for flag in FLAG_RE.findall(m.group("args")):
                if flag not in flags:
                    problems.append(
                        f"{where}: {script.name} {flag} — флаг не объявлен")
    return problems


def selftest() -> bool:
    """Проверяется РАЗЛИЧЕНИЕ: объявленный флаг и выдуманный не должны
    сливаться, а несуществующий скрипт обязан находиться.

    🔴 Данные канарейки — РЕАЛИСТИЧНЫЕ, и это не мелочь. Первая редакция
    брала флаги кириллицей (`--настоящий`, `--выдуманный`), и канарейка
    честно упала: регулярка ищет латинские флаги, как их и пишут в argparse.
    Проверка была исправна, **нереалистичны были данные проверки** — то есть
    канарейка проверяла случай, которого в жизни не бывает, и объявляла
    поломку там, где её нет.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "scripts").mkdir()
        (repo / "scripts" / "alive.py").write_text(
            "import argparse\n"
            "ap = argparse.ArgumentParser()\n"
            "ap.add_argument('--check', action='store_true')\n",
            encoding="utf-8")
        (repo / "doc.md").write_text(
            "# Док\n\n"
            "```\npython3 scripts/alive.py --check\n```\n"        # верно
            "```\npython3 scripts/alive.py --invented\n```\n"     # флага нет
            "```\npython3 scripts/dead.py\n```\n",                # файла нет
            encoding="utf-8")
        found = check_repo(repo)
        # Ровно два: выдуманный флаг и отсутствующий файл. Верная команда молчит.
        return (len(found) == 2
                and any("флаг не объявлен" in f for f in found)
                and any("файла нет" in f for f in found))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default="base-repo")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        ok = selftest()
        print("🟢 канарейка: выдуманный флаг и мёртвый скрипт ловятся, верное молчит"
              if ok else "🔴 канарейка: РАЗЛИЧЕНИЕ СЛОМАНО")
        return 0 if ok else 1

    if not selftest():
        print("🔴 канарейка не прошла — находкам ниже верить нельзя")
        return 1

    repo = REPOS / a.repo
    if not repo.is_dir():
        print(f"🔴 нет репы: {a.repo}")
        return 1

    problems = check_repo(repo)
    print(f"═══ Команды в документах · {a.repo} ═══\n")
    if not problems:
        print("  🟢 все упомянутые скрипты существуют, все флаги объявлены")
    else:
        print(f"  🔴 расхождений: {len(problems)}\n")
        for line in problems[:30]:
            print(f"    · {line}")
        if len(problems) > 30:
            print(f"    · … и ещё {len(problems) - 30}")

    print("\n🔴 Проверяется СУЩЕСТВОВАНИЕ, а не поведение: примеры в этой")
    print("   системе поднимают версии, собирают архивы и раздают канон по")
    print("   60 репам — проверка, исполняющая документацию, была бы")
    print("   разрушительнее дефекта, который она ищет.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
