#!/usr/bin/env python3
"""gate_monitor.py — мета-гейт: проверяет, что сами проверки живы.

ЗАВЕДЕНО 29.08.2026 по исследованию `reports/research/
system-building-and-analysis-2026-08-29.md` (кандидат ранга 1). Внешнее имя
метода — **способность Monitor** из Resilience Assessment Grid (Hollnagel):
устойчивая система обязана знать не только своё состояние, но и состояние
**собственных средств наблюдения**.

🔴 СИМПТОМ, РАДИ КОТОРОГО ЭТО ПИШЕТСЯ, УЖЕ ИЗМЕРЕН В ЭТОЙ СИСТЕМЕ.
`00-infrastructure/69-agents-hooks-and-gates.md` §4г: блокирующий гейт был
красным **41 день подряд**, за это время выпущено **65 тегированных версий**,
и никто не смотрел. Правило «не отдавать до зелёного» формально соблюдалось —
не работал расчёт на вторую, независимую проверку. Молча.

ЧЕТЫРЕ КЛАССА МЁРТВОЙ ПРОВЕРКИ, каждый невидим по-своему:

  1. **Канарейка не вызывается.** Функция `selftest_*` определена, но её никто
     не зовёт в `main()`. Проверка работает, а способность ловить — нет.
  2. **Канарейка не различает.** Возвращает True всегда — в том числе на
     подсаженном дефекте. Такая канарейка неотличима от сломанной.
  3. **Проверка не вызывается.** `check_*` определена и не зовётся: мёртвый код,
     который читается как действующая защита.
  4. **Хук не исполняем.** Файл на месте, `+x` потерян — Claude Code молча
     пропускает такой хук, и об этом нигде не сообщается.

ЧЕГО ЭТОТ ИНСТРУМЕНТ НЕ УМЕЕТ (и это надо знать, `71` §7г-бис):
  · **не судит, ПРАВИЛЬНУЮ ли вещь проверяет гейт** — это validation, а мета-гейт,
    как и обычный, умеет только verification. Потолок структурный, не временный;
  · не ловит проверку, которая вызывается, различает, но покрывает не тот класс
    дефектов, что нужен, — для этого нужен читающий человек.

ЗАПУСК
    gate_monitor.py              отчёт по base-repo
    gate_monitor.py --strict     ненулевой код возврата при любой находке
    gate_monitor.py --selftest   канарейка самого мета-гейта
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from pathlib import Path

BASE_REPO = Path(__file__).resolve().parent.parent
GATE = BASE_REPO / "scripts" / "revision_check.py"
HOOK_DIRS = (".claude/hooks", ".githooks")


def defined_and_called(source: str, prefix: str) -> tuple[set[str], set[str]]:
    """Какие функции с префиксом ОПРЕДЕЛЕНЫ и какие из них где-то ВЫЗЫВАЮТСЯ.

    Разбор через `ast`, а не регуляркой: имя в комментарии или в строке
    документации вызовом не является, и грубый `grep` посчитал бы его живым —
    ровно та ошибка, против которой инструмент и заводится.
    """
    tree = ast.parse(source)
    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name.startswith(prefix)}
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id.startswith(prefix):
                called.add(node.func.id)
    return defined, called


def check_canaries_wired() -> list[str]:
    """Класс 1 и 3: определена, но не вызывается ни из одного места."""
    source = GATE.read_text(encoding="utf-8")
    problems = []
    for prefix, label in (("selftest_", "канарейка"), ("check_", "проверка")):
        defined, called = defined_and_called(source, prefix)
        for name in sorted(defined - called):
            problems.append(f"{label} определена, но НЕ вызывается: {name}()")
    return problems


def check_canaries_discriminate() -> list[str]:
    """Класс 2: канарейка, возвращающая True всегда.

    Признак — тело без единой ветки, которая может вернуть False. Такая
    функция синтаксически канарейка, а по смыслу — заглушка.
    """
    tree = ast.parse(GATE.read_text(encoding="utf-8"))
    problems = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef)
                and node.name.startswith("selftest_")):
            continue
        returns = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
        if not returns:
            problems.append(f"канарейка ничего не возвращает: {node.name}()")
            continue
        # Единственный `return True` без сравнений — заглушка.
        only_true = all(isinstance(r.value, ast.Constant) and r.value.value is True
                        for r in returns if r.value is not None)
        if only_true:
            problems.append(f"канарейка возвращает True всегда — не различает: "
                            f"{node.name}()")
    return problems


def check_hooks_executable(root: Path) -> list[str]:
    """Класс 4: хук на месте, бит `+x` потерян — Claude Code молча пропустит."""
    problems = []
    for rel in HOOK_DIRS:
        folder = root / rel
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix in {".sh", ""} and not path.name.startswith("."):
                if not os.access(path, os.X_OK):
                    problems.append(f"хук не исполняем (потерян +x): "
                                    f"{path.relative_to(root)}")
    return problems


def check_hooks_registered(root: Path) -> list[str]:
    """Хук лежит в каталоге, но не объявлен в `settings.json` — он мёртв.

    Обратное тоже дефект: объявлен, а файла нет — тогда Claude Code при каждом
    событии зовёт несуществующее.
    """
    settings = root / ".claude" / "settings.json"
    folder = root / ".claude" / "hooks"
    if not settings.is_file() or not folder.is_dir():
        return []
    text = settings.read_text(encoding="utf-8", errors="replace")
    problems = []
    for path in sorted(folder.glob("*.sh")):
        if path.name not in text:
            problems.append(f"хук не объявлен в settings.json: "
                            f"{path.relative_to(root)}")
    for name in re.findall(r"hooks/([A-Za-z0-9_.-]+\.sh)", text):
        if not (folder / name).is_file():
            problems.append(f"в settings.json объявлен несуществующий хук: {name}")
    return problems


def selftest() -> bool:
    """Мета-гейт обязан ловить подсаженную мёртвую проверку.

    🔴 Канарейка мета-гейта — не роскошь: инструмент, который проверяет
    работоспособность других проверок, при поломке даёт самый опасный вид
    отказа — уверенное «всё живо».
    """
    src = (
        "def selftest_живая():\n"
        "    return 1 == 1 and 2 != 1\n"
        "def selftest_заглушка():\n"
        "    return True\n"
        "def check_вызывается():\n"
        "    return []\n"
        "def check_мёртвая():\n"
        "    return []\n"
        "def main():\n"
        "    selftest_живая()\n"
        "    selftest_заглушка()\n"
        "    check_вызывается()\n"
    )
    defined, called = defined_and_called(src, "check_")
    dead = defined - called
    tree = ast.parse(src)
    stubs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("selftest_"):
            returns = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
            if returns and all(isinstance(r.value, ast.Constant)
                               and r.value.value is True for r in returns):
                stubs.append(node.name)
    # Ловит ровно мёртвую и ровно заглушку, живые не трогает.
    return dead == {"check_мёртвая"} and stubs == ["selftest_заглушка"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(BASE_REPO))
    ap.add_argument("--strict", action="store_true",
                    help="ненулевой код возврата при любой находке")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        ok = selftest()
        print("🟢 канарейка мета-гейта: ловит мёртвую проверку и заглушку" if ok
              else "🔴 канарейка мета-гейта: РАЗЛИЧЕНИЕ СЛОМАНО")
        return 0 if ok else 1

    root = Path(a.root).resolve()
    if not selftest():
        print("🔴 канарейка мета-гейта не прошла — результатам ниже верить нельзя")
        return 1

    blocks = [
        ("Проверки и канарейки, определённые но не вызываемые", check_canaries_wired()),
        ("Канарейки, не умеющие различать", check_canaries_discriminate()),
        ("Хуки без бита +x", check_hooks_executable(root)),
        ("Хуки, разошедшиеся с settings.json", check_hooks_registered(root)),
    ]

    total = 0
    for title, problems in blocks:
        if problems:
            total += len(problems)
            print(f"[FAIL] {title}: {len(problems)}")
            for line in problems:
                print(f"    · {line}")
        else:
            print(f"[OK] {title} — нет")

    source = GATE.read_text(encoding="utf-8")
    checks, _ = defined_and_called(source, "check_")
    canaries, _ = defined_and_called(source, "selftest_")
    print(f"\nЖивых проверок: {len(checks)} · канареек: {len(canaries)}")
    print("🔴 Мета-гейт умеет только verification: он проверяет, что проверки")
    print("   РАБОТАЮТ, а не что они проверяют ПРАВИЛЬНУЮ вещь (69 §4г).")

    if total:
        print(f"\nИТОГ: найдено {total}")
        return 1 if a.strict else 0
    print("\nИТОГ: все проверки живы")
    return 0


if __name__ == "__main__":
    sys.exit(main())
