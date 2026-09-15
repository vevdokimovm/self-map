#!/usr/bin/env python3
"""import_safety_check.py — импорт скрипта ничего не запускает?

🔴 ПОВОД, ЗАМЕРЕН 04.09.2026. Попытка переиспользовать ОДНУ функцию
из `05-infra-synthesis-lab/tools/scan_lessons.py` запустила полный обход
**11 935 файлов** и перезаписала `scan.csv`. Тело скрипта лежало
на верхнем уровне, без `if __name__ == "__main__"`.

**Чтение кода изменило состояние.** Для отладки это хуже, чем кажется:
она начинается с чтения — импортировать, вызвать функцию, посмотреть вывод.
Если чтение меняет состояние, следующий замер уже неверен, и причина ищется
в предмете, которого не касались (`102-debugging-discipline.md` §3а).

ЧТО ПРОВЕРЯЕТСЯ. У файла, который **что-то делает** на верхнем уровне,
обязан быть гвард. Разбор идёт по `ast`, а не по отступам:

  · импорты, `def`, `class`, докстроки, КОНСТАНТЫ — не тело;
  · всё остальное на верхнем уровне — тело, и оно требует гварда.

🔴 ЧЕГО НЕ ДЕЛАЕТ:

  · **не импортирует проверяемое** — это и был бы тот самый побочный
    эффект. Разбирается исходник, программа не выполняется;
  · **не судит о вреде в общем виде.** `print()` безобиден, обход 12 тысяч
    файлов — нет; статически это не различить. Но РАБОТУ от КОНФИГУРАЦИИ
    инструмент различает — см. отдельный блок ниже;
  · **не трогает `__init__.py`** и модули-библиотеки без тела — им гвард
    не нужен, и требовать его было бы шумом.

🔴 РАБОТА ПРОТИВ КОНФИГУРАЦИИ. Граница предложена второй вахтой
(`finpilot-02`, 04.09.2026) после двух ложных срабатываний в её репе:

  · `tools/timewarp/warp.py` — pytest-плагин: подменяет время НА ИМПОРТЕ,
    и это его назначение. Гвард его сломает — подмена обязана случиться
    ДО импорта модулей приложения;
  · `tools/survey_analysis/visualization.py` — `matplotlib.use("Agg")`
    обязан стоять ДО `import pyplot`. Требование библиотеки, а не оплошность.

Её формулировка принята дословно: **«присваивание, `matplotlib.use`,
регистрация в реестре — конфигурация; открытие файлов, сеть, запуск расчёта,
`print` — работа»**. Иначе инструмент даёт красное на плагинах и на matplotlib
ВСЕГДА, а красное, которое всегда, перестают читать (`69` §4з).

Решает при этом не место и не имя, а **вызов**: `CFG = os.getcwd()` остаётся
находкой, хотя это присваивание с именем константы.

ЗАПУСК:
    python3 scripts/import_safety_check.py            # база
    python3 scripts/import_safety_check.py --all      # все репы
    python3 scripts/import_safety_check.py --selftest
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402

# 🔴 ЧУЖОЙ КОД ИСКЛЮЧЁН — замер 04.09.2026. Первый прогон дал **2877**
# срабатываний по 65 репам, из них **1797 в `.venv`**: это установленные
# библиотеки, и правило не про них. Требовать гвард у стороннего пакета
# бессмысленно — его никто не правит, а вердикт «2877 нарушений» ничего
# не сообщает и учит не читать проверку (`69` §4з: всегда красная проверка
# так же бесполезна, как всегда зелёная).
#
# Исключается ПО СВОЙСТВУ «этот код не наш и не правится нами», а не
# по списку имён: окружения, зависимости, сборка, архивы.
SKIP_PARTS = (".git", "__pycache__", "_base", "_archive", "node_modules",
              ".venv", "venv", "site-packages", "dist-packages", ".tox",
              "build", "dist", ".eggs", "vendor", "third_party",
              "02-code-archive")


# 🔴 РАБОТА — вызовы, обращающиеся к миру за пределами процесса. Список
# короткий намеренно: он не обязан быть полным, потому что НЕИЗВЕСТНЫЙ вызов
# и так считается работой (см. `call_kind`). Он нужен для другого — чтобы
# работа, спрятанная ВНУТРИ дешёвой обёртки, не проехала: `X = Path(open(...))`
# снаружи выглядит как построение пути.
WORK_CALLS = frozenset((
    "open", "print", "input", "read_text", "read_bytes", "write_text",
    "write_bytes", "glob", "rglob", "iterdir", "walk", "listdir", "mkdir",
    "remove", "unlink", "rmtree", "copy", "move", "rename",
    "run", "check_output", "check_call", "call", "popen", "system", "Popen",
    "urlopen", "request", "connect", "socket", "sendall", "recv",
    "main", "sleep", "execute", "executemany", "commit",
))

# 🔴 КОНФИГУРАЦИЯ — вызовы, которые ставят значение и ничего не делают.
# Они законны на верхнем уровне и часто ОБЯЗАНЫ там быть: `matplotlib.use`
# работает только до импорта `pyplot`, регистрация плагина — только до того,
# как реестр прочитают.
CONFIG_CALLS = frozenset((
    "use", "register", "register_dialect", "filterwarnings", "simplefilter",
    "basicConfig", "setLevel", "addHandler", "setFormatter", "disable",
    "set_start_method", "setrecursionlimit", "set_loglevel", "seed",
    "set_option", "setdefaulttimeout", "signal", "setattr",
))

# Дешёвые фабрики: строят значение из готовых частей, мира не касаются.
CHEAP_CALLS = frozenset((
    "Path", "compile", "set", "dict", "list", "tuple", "frozenset",
    "namedtuple", "getLogger", "timedelta", "datetime", "date", "time",
    "Decimal", "Fraction", "defaultdict", "deque", "Counter", "OrderedDict",
    "str", "int", "float", "bool", "bytes", "len", "sorted", "range",
))


def call_name(node: ast.AST) -> str:
    """Имя вызываемого — `f()` и `mod.f()` дают одинаковое `f`."""
    fn = node.func if isinstance(node, ast.Call) else None
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return ""


def call_kind(value: ast.AST) -> str:
    """`work` · `config` · `none` — что произойдёт при импорте.

    🔴 Порядок проверок — не косметика. Работа ищется ПО ВСЕМУ поддереву,
    и только потом смотрится внешний вызов: обёртка не должна прикрывать
    то, что внутри неё. Неизвестный вызов считается работой — ошибиться
    в эту сторону дешевле (`/auto` §1.4).
    """
    calls = [n for n in ast.walk(value) if isinstance(n, ast.Call)]
    if not calls:
        return "none"
    names = {call_name(c) for c in calls}
    if names & WORK_CALLS:
        return "work"
    outer = call_name(value) if isinstance(value, ast.Call) else ""
    if outer in CONFIG_CALLS or outer in CHEAP_CALLS:
        return "config"
    return "work"


def body_lineno(src: str) -> int | None:
    """Строка первого исполняемого узла верхнего уровня, или None."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue                                    # докстрока
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            tgt = node.targets[0] if isinstance(node, ast.Assign) else node.target
            # 🔴 ВЫЗОВ ПРОВЕРЯЕТСЯ РАНЬШЕ ИМЕНИ. Первая редакция сначала
            # пропускала всё в ВЕРХНЕМ РЕГИСТРЕ как «константу» — и
            # `CFG = os.getcwd()` проскакивал. Имя говорит о намерении
            # автора, вызов — о том, что произойдёт при импорте.
            # Поймано собственной канарейкой до первого прогона.
            if isinstance(node.value, ast.Await):
                return node.lineno
            if call_kind(node.value) == "work":
                return node.lineno
            continue
            # Константа-литерал верхнего уровня — объявление, не действие.
            if isinstance(tgt, ast.Name) and tgt.id.isupper():
                continue
            continue
        if isinstance(node, ast.Expr):
            # Голый вызов: `matplotlib.use("Agg")` — конфигурация,
            # `print(...)` и `main()` — работа.
            if call_kind(node.value) == "config":
                continue
            return node.lineno
        if isinstance(node, ast.If):
            # `if __name__ == "__main__":` — это и есть гвард.
            if "__main__" in ast.dump(node.test):
                continue
            return node.lineno
        return node.lineno
    return None


# 🔴 ПРАВИЛО ПРО ИНСТРУМЕНТЫ, А НЕ ПРО ВЕСЬ PYTHON НА ДИСКЕ.
# Замер 04.09.2026, второй заход: после отсева `.venv` осталось **533**
# срабатывания, из них **320 в `04-study-guides`** — учебные примеры
# и конспекты. Скрипт из методички по алгоритмам ДОЛЖЕН печатать при запуске;
# требовать у него гвард — шум, который учит не читать проверку.
#
# Инструмент узнаётся по МЕСТУ: его кладут туда, откуда запускают и
# переиспользуют. Учебный код лежит в материалах и живёт один раз.
TOOL_DIRS = ("scripts", "bin", "tools", "templates", "hooks")


def is_tool(rel: Path) -> bool:
    return any(part in TOOL_DIRS for part in rel.parts)


def check(root: Path, tools_only: bool = True) -> list[tuple[str, int, str]]:
    bad: list[tuple[str, int, str]] = []
    for f in sorted(root.rglob("*.py")):
        if any(p in SKIP_PARTS for p in f.parts) or f.name == "__init__.py":
            continue
        if tools_only and not is_tool(f.relative_to(root)):
            continue
        try:
            src = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "__main__" in src:
            continue
        n = body_lineno(src)
        if n is not None:
            line = src.splitlines()[n - 1].strip()[:60]
            bad.append((f.relative_to(root).as_posix(), n, line))
    return bad


def selftest() -> int:
    import tempfile
    ok = True
    cases = [
        ("тело без гварда", '"""док"""\nimport os\nprint("работаю")\n', True),
        ("тело под гвардом", 'import os\n\n\ndef m():\n    print(1)\n\n\n'
                             'if __name__ == "__main__":\n    m()\n', False),
        ("только определения", 'import os\n\n\ndef f():\n    return 1\n', False),
        ("константы не тело", 'X = 1\nPATH = "/tmp"\n\n\ndef f():\n    pass\n', False),
        ("🔴 вызов в присваивании", 'import os\nCFG = os.getcwd()\n', True),
        ("конфигурация: matplotlib.use",
         'import matplotlib\nmatplotlib.use("Agg")\nimport matplotlib.pyplot\n',
         False),
        ("конфигурация: подмена в плагине",
         'import os\nfrom datetime import timedelta\n'
         '_off = timedelta(days=int(os.environ.get("WARP_DAYS", "90")))\n', False),
        ("🔴 работа под дешёвой обёрткой",
         'from pathlib import Path\nDATA = Path(open("x").read())\n', True),
        ("🔴 голый вызов-работа", 'import shutil\nshutil.rmtree("/tmp/x")\n', True),
    ]
    with tempfile.TemporaryDirectory() as d:
        for name, src, expect in cases:
            p = Path(d) / "probe.py"
            p.write_text(src, encoding="utf-8")
            got = bool(check(Path(d), tools_only=False))
            mark = "✅" if got == expect else "🔴"
            print(f"   {mark} {name}: {'ловится' if got else 'молчит'}")
            ok &= got == expect
    print("selftest OK" if ok else "🔴 selftest ПРОВАЛЕН")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", nargs="?", help="имя репы; без него — база")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--everything", action="store_true",
                    help="🔴 весь Python, включая учебный код и примеры — шумно, "
                         "по умолчанию проверяются только каталоги инструментов")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    base, root, _ = resolve_roots(__file__)
    if a.all:
        repos = [d for d in sorted(root.iterdir())
                 if d.is_dir() and (d / "VERSION").exists()]
    elif a.repo:
        repos = [root / a.repo]
    else:
        repos = [base]

    total = 0
    for repo in repos:
        if not repo.exists():
            print(f"🔴 нет репы: {repo.name}")
            return 2
        bad = check(repo, tools_only=not a.everything)
        total += len(bad)
        if bad:
            print(f"\n🔴 {repo.name} — импорт запустит работу ({len(bad)}):")
            for rel, n, line in bad:
                print(f"   {rel}:{n}  {line}")

    scope = f"{len(repos)} реп" if a.all else repos[0].name
    if total:
        print(f"\nИТОГ: {scope} · 🔴 {total} файл(ов) без гварда.")
        print("Чтение такого кода меняет состояние (102 §3а).")
        return 1
    print(f"ИТОГ: {scope} · 🟢 импорт ничего не запускает")
    return 0


if __name__ == "__main__":
    sys.exit(main())
