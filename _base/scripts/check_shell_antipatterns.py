#!/usr/bin/env python3
"""check_shell_antipatterns.py — грамматические грабли shell/python-кода САМОЙ репы.

ПОЧЕМУ ОТДЕЛЬНЫЙ СКРИПТ, НЕ ЧАСТЬ `revision_check.py`. Тот гейт проверяет СОСТОЯНИЕ
дерева (файлы, версии, реестры) — вопрос «репа корректна прямо сейчас». Этот скрипт
проверяет КАЧЕСТВО КОДА самих `.sh`/`.py`-файлов репы — вопрос «не наступит ли этот
код на уже известные грабли». Разные оси, разные последствия у находки: там DRIFT
чинится правкой файла, здесь — правкой скрипта.

ЧТО ЭТО (и чем не является). Это ГРЕП по конкретным регэксп-сигнатурам граблей,
уже описанных в `reports/pitfalls.md` — не полноценный shellcheck и не статический
анализатор семантики. Сигнатуры узкие и намеренно консервативные (лучше пропустить
редкий случай, чем завалить отчёт ложными срабатываниями на легитимном коде) —
см. докстринг каждого паттерна. Инструмент РЕПОРТИТ, не блокирует релиз: как и
`pit_gate_coverage.py`, он не встроен в `revision_check.py`/`pack_release.py`, чтобы
найденное не роняло гейт релиза в день, когда паттерн только заведён.

ЗАПУСК
    python3 scripts/check_shell_antipatterns.py            отчёт по всей репе
    python3 scripts/check_shell_antipatterns.py --root DIR  по произвольному дереву
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

BASE_REPO = Path(__file__).resolve().parent.parent

SKIP_DIR_NAMES = {"_base", "_archive", "node_modules", ".venv", "venv", ".git", "__pycache__"}
SCAN_SUFFIXES = {".sh", ".py"}


class Pattern:
    def __init__(self, pit: str, name: str, regex: str, why: str):
        self.pit = pit
        self.name = name
        self.rx = re.compile(regex)
        self.why = why


PATTERNS = [
    Pattern(
        "PIT-001", "find … && echo лжёт про существование",
        r"find\s+.*&&\s*echo",
        "`find` выходит с кодом 0 даже без единой находки — `&&` смотрит на код "
        "выхода, не на вывод. Проверять надо `test -f`/`[ -f … ]` или непустой вывод.",
    ),
    Pattern(
        "PIT-002", "grep -c … && обрывает цепочку при нуле совпадений",
        r"grep\s+-c\b[^)\n]*&&",
        "`grep` с нулём совпадений возвращает 1 → `&&` рвёт остаток цепочки молча. "
        "`-c` почти всегда используется для ПОДСЧЁТА (информационно), а не как "
        "условие, поэтому его прямое участие в `&&`-цепочке — почти всегда грабли, "
        "не осознанный gate. Узкий шаблон: не ловит `grep -q X && Y` — тот идиоматичен.",
    ),
    Pattern(
        "PIT-017", "for X in $VAR — в zsh не делает word splitting",
        r"for\s+\w+\s+in\s+\$\{?[A-Za-z_][A-Za-z0-9_]*\}?\s*;?\s*do\b",
        "`VAR=\"a b c\"; for x in $VAR` даёт N итераций в bash и РОВНО ОДНУ в zsh "
        "(вся строка целиком) — и в этой системе скрипты периодически запускают "
        "именно `zsh script.sh`, а не через шебанг. Чинится через файл + "
        "`while IFS= read -r`, ЛИБО глобальным `setopt sh_word_split` на входе "
        "скрипта (см. SHWORDSPLIT_GUARD_RE ниже — эта защита распознаётся, "
        "находки после неё не репортятся).",
    ),
    Pattern(
        "PIT-038", "cd X && job & — фонит ВЕСЬ пайплайн вместе с cd",
        r"cd\s+\S+\s*&&[^&\n]*&\s*$",
        "`&` имеет меньший приоритет, чем `&&`, поэтому `cd X && job &` фонит "
        "`(cd X && job)` целиком — CWD foreground-шелла не меняется, хотя выглядит, "
        "что должен. `cd` держать отдельным оператором в foreground.",
    ),
    Pattern(
        "PIT-049", "head -n -N — не работает в BSD head (macOS)",
        r"head\s+-n\s*-\d+",
        "GNU coreutils понимает отрицательный `-n`, BSD `head` (macOS) — нет, падает "
        "`illegal line count`. Переносимая замена — `sed '$d'` (для одной строки).",
    ),
    Pattern(
        "PIT-095", "sed/awk парсит CHANGELOG.md в обход канонического парсера",
        r"sed\s+-n\b[^\n]*CHANGELOG",
        "Формат секции CHANGELOG уже разбирается каноническим инструментом "
        "(`build_notes` в `templates/deploy.sh`). Собственный `sed`-диапазон — "
        "вторая реализация одного знания о формате, которая расходится при первом "
        "же изменении формата, о котором не узнает.",
    ),
]


SELF_PATH = Path(__file__).resolve()

# Найдено 28.08.2026: `templates/deploy.sh` уже несёт правильную защиту от
# PIT-017 — `setopt sh_word_split`/`setopt shwordsplit` на входе, под guard'ом
# `[ -n "${ZSH_VERSION:-}" ]`, — и 13 находок оказались ложными срабатываниями:
# for-циклы после этой строки ведут себя как в bash, потому что опция включена
# для всего оставшегося скрипта. PIT-017 не репортится для строк ПОСЛЕ такой
# защиты в том же файле.
SHWORDSPLIT_GUARD_RE = re.compile(r"setopt\s+sh_?word_?split")


def iter_scan_files(root: Path):
    # Анти-самореференция (тот же приём, что канарейка CJK в revision_check.py):
    # этот файл несёт сигнатуры граблей и синтетические образцы селфтеста как
    # СТРОКИ ПИТОНА — без исключения он ловит сам себя на каждом прогоне.
    for path in root.rglob("*"):
        if path.suffix not in SCAN_SUFFIXES or not path.is_file():
            continue
        if path.resolve() == SELF_PATH:
            continue
        if any(part in SKIP_DIR_NAMES for part in path.relative_to(root).parts):
            continue
        yield path


def scan(root: Path) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {p.pit: [] for p in PATTERNS}
    for path in iter_scan_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(root)
        lines = text.splitlines()
        shwordsplit_at = next(
            (i for i, line in enumerate(lines, 1) if SHWORDSPLIT_GUARD_RE.search(line)),
            None,
        )
        for i, line in enumerate(lines, 1):
            for pat in PATTERNS:
                if pat.pit == "PIT-017" and shwordsplit_at is not None and i > shwordsplit_at:
                    continue
                if pat.rx.search(line):
                    hits[pat.pit].append(f"{rel}:{i}: {line.strip()[:110]}")
    return hits


def selftest() -> bool:
    """Канарейка (71 §7в): каждый паттерн обязан ловить свой синтетический образец
    и не ловить безобидную соседнюю строку."""
    import tempfile

    samples = {
        "PIT-001": ("find . -name x && echo ЕСТЬ\n", "test -f x && echo ЕСТЬ\n"),
        "PIT-002": ("grep -c X file && next\n", "grep -q X file && next\n"),
        "PIT-017": ("for v in $VERSIONS; do\n", 'for v in "${arr[@]}"; do\n'),
        "PIT-038": ("cd /tmp && long_job &\n", "cd /tmp && long_job\n"),
        "PIT-049": ("head -n -1 file\n", "sed '$d' file\n"),
        "PIT-095": ("sed -n '/^## /,/^$/p' CHANGELOG.md\n", "python3 build_notes.py CHANGELOG.md\n"),
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ok = True
        for pit, (bad, good) in samples.items():
            (root / "bad.sh").write_text(bad, encoding="utf-8")
            (root / "good.sh").write_text(good, encoding="utf-8")
            hits = scan(root)
            if not hits[pit]:
                print(f"[selftest FAIL] {pit}: не поймал синтетический образец")
                ok = False
            if any("good.sh" in h for h in hits[pit]):
                print(f"[selftest FAIL] {pit}: ложное срабатывание на безобидной строке")
                ok = False

        # Канарейка на guard 28.08.2026: for-цикл ПОСЛЕ setopt sh_word_split —
        # не находка (deploy.sh-случай); ДО неё в том же файле — по-прежнему находка.
        (root / "guarded.sh").write_text(
            "echo before\n"
            "setopt sh_word_split 2>/dev/null || true\n"
            "for v in $VERSIONS; do echo \"$v\"; done\n",
            encoding="utf-8",
        )
        (root / "bad.sh").write_text(
            "for v in $VERSIONS; do echo \"$v\"; done\n"
            "setopt sh_word_split 2>/dev/null || true\n",
            encoding="utf-8",
        )
        (root / "good.sh").write_text("", encoding="utf-8")
        hits = scan(root)
        if any("guarded.sh" in h for h in hits["PIT-017"]):
            print("[selftest FAIL] PIT-017: guard setopt sh_word_split не подавил находку после себя")
            ok = False
        if not any("bad.sh" in h for h in hits["PIT-017"]):
            print("[selftest FAIL] PIT-017: находка ДО guard'а в том же файле пропущена ошибочно")
            ok = False
        return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(BASE_REPO))
    a = ap.parse_args()
    root = Path(a.root).resolve()

    if not selftest():
        print("[FAIL] канарейка сломана — паттерны не проверены, отчёту не доверять")
        return 1

    hits = scan(root)
    total = sum(len(v) for v in hits.values())
    for pat in PATTERNS:
        found = hits[pat.pit]
        if found:
            print(f"[FAIL] {pat.pit} — {pat.name}: {len(found)}")
            for line in found[:20]:
                print(f"    · {line}")
            if len(found) > 20:
                print(f"    · … ещё {len(found) - 20}")
        else:
            print(f"[OK] {pat.pit} — {pat.name}: не найдено")

    print()
    print(f"ИТОГ: найдено срабатываний {total} по {len(PATTERNS)} паттернам "
          f"(инструмент репортит, не блокирует релиз)")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
