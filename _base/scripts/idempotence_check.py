#!/usr/bin/env python3
"""idempotence_check.py — прогнать скрипт-ритуал дважды и сравнить состояние.

ЗАКАЗ ВЛАДЕЛЬЦА, 29.08.2026, дословно: *«идемпотентность — что значит „запустить
`bump_repo.py` дважды и получить то же“? У нас скрипты-ритуалы, это буквально
их свойство, и оно нигде не сформулировано»*.

Он прав дважды. Свойство **не сформулировано** (объявлено одной строкой И7
в `templates/deploy-SPEC.md` — и только для деплойера) и **нигде не проверено**.
Строка в спецификации без проверки — обещание, а не гарантия.

🔴 ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ, А ЧТО НЕТ. Идемпотентность в строгом смысле —
`f(f(x)) = f(x)` — нашим ритуалам **не свойственна и не должна быть**:
`bump_repo.py` обязан при втором прогоне поднять версию ещё раз, это его работа.
Различать надо два класса:

  · **сходящиеся** (`sync_base_local.py`, `readme_status_gate.py --fix`,
    `gen_repo_structure.py`) — приводят состояние к каноническому. Второй
    прогон обязан **ничего не менять**: канон уже достигнут. Это и есть
    идемпотентность, и она проверяема механически.
  · **продвигающие** (`bump_repo.py`, `close_batch.py`, `auto_log.py`) —
    двигают состояние вперёд по замыслу. От них требуется другое: **второй
    прогон не должен ломать то, что сделал первый** (не дублировать секцию
    CHANGELOG, не удваивать строку журнала, не терять запись).

Смешивать их — распространённая ошибка: «скрипт не идемпотентен» звучит как
дефект, хотя для продвигающего это норма.

ЗАПУСК
    idempotence_check.py                 все сходящиеся скрипты, по всем репам
    idempotence_check.py --repo sport    только на одной репе
    idempotence_check.py --selftest      канарейка

🔴 РАБОТАЕТ НА КОПИИ. Скрипт копирует репу во временный каталог и гоняет
проверяемое там. Проверка, способная испортить проверяемое, стоит дороже
того, что находит.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Корень определяется общим модулем: скрипт может быть запущен и из базы,
# и из копии кита в репе-наследнике (`_base/scripts/`). См. `_roots.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402
BASE_REPO, REPOS, FROM_KIT = resolve_roots(__file__)

# Сходящиеся скрипты: аргумент — путь к репе, второй прогон обязан быть пустым.
# Каждая строка — (имя, как позвать, что считать «изменилось»).
CONVERGING = (
    ("gen_repo_structure.py",
     lambda repo: ["python3", str(BASE_REPO / "scripts/gen_repo_structure.py"),
                   str(repo), "--update-readme"]),
    ("readme_status_gate.py",
     lambda repo: ["python3", str(BASE_REPO / "scripts/readme_status_gate.py"),
                   "--root", str(repo), "--fix"]),
)

# Каталоги, которые в слепок не входят: их содержимое меняется от прогона
# к прогону по причинам, к идемпотентности отношения не имеющим.
SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache",
        "dist", "build", ".DS_Store"}


def snapshot(root: Path) -> dict[str, str]:
    """Слепок состояния: путь → sha256 содержимого."""
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root)
        if any(part in SKIP for part in rel.parts) or path.name in SKIP:
            continue
        try:
            out[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
    return out


def diff(before: dict[str, str], after: dict[str, str]) -> list[str]:
    changed = [f"изменён: {k}" for k in before if k in after and before[k] != after[k]]
    added = [f"появился: {k}" for k in after if k not in before]
    gone = [f"исчез: {k}" for k in before if k not in after]
    return sorted(changed + added + gone)


def check_one(repo: Path, name: str, build_cmd) -> tuple[bool, list[str]]:
    """Два прогона на копии; изменения второго — и есть нарушение."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / repo.name
        shutil.copytree(repo, work, symlinks=True,
                        ignore=shutil.ignore_patterns(*SKIP))
        first = subprocess.run(build_cmd(work), capture_output=True, text=True)
        if first.returncode not in (0, 2):
            # 2 — штатный отказ («публичная репа», «нечего делать»), не сбой.
            return True, [f"первый прогон вернул {first.returncode}, пропуск"]
        mid = snapshot(work)
        second = subprocess.run(build_cmd(work), capture_output=True, text=True)
        if second.returncode not in (0, 2):
            return False, [f"второй прогон упал с кодом {second.returncode}"]
        after = snapshot(work)
        return (not diff(mid, after)), diff(mid, after)


def selftest() -> bool:
    """Различение: сходящийся скрипт проходит, продвигающий — нет.

    🔴 Обе половины обязательны. Без второй проверка неотличима от «всегда
    зелено»: она бы не заметила скрипт, который дописывает строку при каждом
    запуске — то есть ровно тот дефект, ради которого написана.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "файл.txt"
        target.write_text("канон\n", encoding="utf-8")

        converging = root / "conv.py"
        converging.write_text(
            "import sys, pathlib\n"
            "p = pathlib.Path(sys.argv[1]) / 'файл.txt'\n"
            "p.write_text('канон\\n', encoding='utf-8')\n",
            encoding="utf-8")
        advancing = root / "adv.py"
        advancing.write_text(
            "import sys, pathlib\n"
            "p = pathlib.Path(sys.argv[1]) / 'файл.txt'\n"
            "p.write_text(p.read_text(encoding='utf-8') + 'ещё\\n', encoding='utf-8')\n",
            encoding="utf-8")

        repo = root / "репа"
        repo.mkdir()
        (repo / "файл.txt").write_text("канон\n", encoding="utf-8")

        ok_conv, _ = check_one(repo, "conv",
                               lambda r: ["python3", str(converging), str(r)])
        ok_adv, changes = check_one(repo, "adv",
                                    lambda r: ["python3", str(advancing), str(r)])
        return ok_conv and not ok_adv and any("изменён" in c for c in changes)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", help="проверить на одной репе (по умолчанию — на трёх разных)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        ok = selftest()
        print("🟢 канарейка: сходящийся проходит, продвигающий ловится" if ok
              else "🔴 канарейка: РАЗЛИЧЕНИЕ СЛОМАНО")
        return 0 if ok else 1

    if not selftest():
        print("🔴 канарейка не прошла — результатам ниже верить нельзя")
        return 1

    if a.repo:
        repos = [REPOS / a.repo]
    else:
        # Три разные по устройству репы: база, крупная предметная, мелкая.
        # Проверять все 63 незачем — нарушение идемпотентности лежит в скрипте,
        # а не в репе, и проявляется на первой же подходящей.
        repos = [REPOS / n for n in ("base-repo", "science", "sport")
                 if (REPOS / n).is_dir()]

    failures = 0
    for repo in repos:
        if not repo.is_dir():
            print(f"⏭  нет репы: {repo.name}")
            continue
        print(f"\n=== {repo.name}")
        for name, build in CONVERGING:
            ok, changes = check_one(repo, name, build)
            if ok:
                print(f"  🟢 {name}: второй прогон ничего не изменил")
            else:
                failures += 1
                print(f"  🔴 {name}: второй прогон изменил состояние ({len(changes)})")
                for c in changes[:5]:
                    print(f"       · {c}")

    print("\n🔴 Проверяются только СХОДЯЩИЕСЯ скрипты. Продвигающие "
          "(`bump_repo.py`, `close_batch.py`) обязаны менять состояние —")
    print("   от них требуется другое: не ломать сделанное первым прогоном.")
    if failures:
        print(f"\nИТОГ: нарушений — {failures}")
        return 1
    print("\nИТОГ: сходящиеся скрипты идемпотентны")
    return 0


if __name__ == "__main__":
    sys.exit(main())
