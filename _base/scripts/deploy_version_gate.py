#!/usr/bin/env python3
"""deploy_version_gate.py — версия деплойера не расходится с документацией (stdlib-only).

Почему этот гейт существует. 2026-08-20 выяснилось, что `templates/deploy.sh` в базе
стоял на 4.3.2, пока рабочий скрипт три недели развивался до 4.16.1 в другой репе —
и документация в четырёх местах называла каноном именно базу. Любая вахта, следующая
документации, повторяла ошибку. Тот же класс дефекта случался и раньше: в 4.5.0 правили
комментарий в шапке, а не переменную, и скрипт представлялся старой версией; в 4.12.0
номер выдали редакции, которая до рабочей папки не доехала.

Вывод один: за соответствием «версия ↔ документация ↔ копии» человек не следит.
Разбор — `reports/incidents/deployer_downgrade_incident.md`, урок — PIT-063.

ИСТОЧНИК ПРАВДЫ: переменная SCRIPT_VERSION в templates/deploy.sh. Всё остальное —
производное и обязано с ней совпадать.

Проверки:
  1. Комментарий в шапке скрипта (`# deploy.sh vX.Y.Z`) == SCRIPT_VERSION.
  2. Верхняя запись в templates/deploy-CHANGELOG.md == SCRIPT_VERSION.
  3. Строка «Сверено с `deploy.sh` vX.Y.Z» в templates/deploy-SPEC.md == SCRIPT_VERSION.
  4. Известные копии скрипта на диске идентичны канону (sha256).
  5. Упоминания `deploy.sh vX.Y.Z` в живых .md не отстают от канона.
     Замороженные зоны (журналы, инциденты, ситуации) пропускаются: история
     не переписывается — 21-revision-protocol.md §1.

Запуск из корня репы:
    python3 scripts/deploy_version_gate.py            # проверка, exit 1 при расхождении
    python3 scripts/deploy_version_gate.py --fix      # починить документацию базы
    python3 scripts/deploy_version_gate.py --sync-copies   # разложить канон по копиям

--sync-copies НИКОГДА не понижает версию: копия новее канона — это сигнал, что канон
отстал, а не повод затереть рабочий инструмент. Ровно на этом и погорели.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

SCRIPT = "templates/deploy.sh"
CHANGELOG = "templates/deploy-CHANGELOG.md"
SPEC = "templates/deploy-SPEC.md"

# Копии, которые обязаны совпадать с каноном. Путь ~ разворачивается в домашний.
KNOWN_COPIES = (
    "~/Documents/mission-control/scripts/deploy.sh",
    "~/Downloads/deploy.sh",
)

# История не переписывается: в журналах и отчётах старые номера версий законны.
FROZEN_PREFIXES = (
    "reports/",
    "05-infra-synthesis-lab/runs/",
    "templates/_archive/",
    "templates/deploy-CHANGELOG.md",
    "CHANGELOG.md",
    "WATCHLOG.md",
    "repos-map-CHANGELOG.md",
)

VERSION_RE = re.compile(r"^SCRIPT_VERSION=\"([0-9]+\.[0-9]+\.[0-9]+)\"", re.M)
HEADER_RE = re.compile(r"^# deploy\.sh v([0-9]+\.[0-9]+\.[0-9]+)", re.M)
CHLOG_TOP_RE = re.compile(r"^## \[([0-9]+\.[0-9]+\.[0-9]+)\]", re.M)
SPEC_RE = re.compile(r"Сверено с `deploy\.sh` v([0-9]+\.[0-9]+\.[0-9]+)")
MENTION_RE = re.compile(r"`?deploy\.sh`? v([0-9]+\.[0-9]+\.[0-9]+)")


def as_tuple(version: str) -> tuple[int, ...]:
    """Разобрать SemVer-строку в кортеж для сравнения."""
    return tuple(int(part) for part in version.split("."))


def sha256(path: Path) -> str:
    """Посчитать sha256 файла."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_canon(root: Path) -> tuple[str, Path]:
    """Прочитать каноническую версию из SCRIPT_VERSION."""
    script = root / SCRIPT
    if not script.is_file():
        raise SystemExit(f"нет канонического скрипта: {script}")
    found = VERSION_RE.search(script.read_text(encoding="utf-8", errors="replace"))
    if not found:
        raise SystemExit(f"в {SCRIPT} не найдена переменная SCRIPT_VERSION")
    return found.group(1), script


def is_frozen(rel: str) -> bool:
    """Файл лежит в замороженной зоне, где старые номера законны."""
    return any(rel == p or rel.startswith(p) for p in FROZEN_PREFIXES)


def check_header(script: Path, canon: str) -> tuple[list[str], str | None]:
    """Шапка скрипта должна называть ту же версию, что и переменная."""
    text = script.read_text(encoding="utf-8", errors="replace")
    found = HEADER_RE.search(text)
    if not found:
        return ([f"{SCRIPT}: в шапке нет строки `# deploy.sh vX.Y.Z`"], None)
    if found.group(1) != canon:
        return (
            [
                f"{SCRIPT}: шапка говорит v{found.group(1)}, "
                f"SCRIPT_VERSION={canon} — правили комментарий, не переменную (см. 4.5.0)"
            ],
            found.group(1),
        )
    return ([], None)


def check_changelog(root: Path, canon: str) -> list[str]:
    """Верхняя запись журнала — это текущая версия."""
    path = root / CHANGELOG
    if not path.is_file():
        return [f"{CHANGELOG}: файла нет — у меняющегося инструмента журнал обязателен"]
    found = CHLOG_TOP_RE.search(path.read_text(encoding="utf-8", errors="replace"))
    if not found:
        return [f"{CHANGELOG}: не найдено ни одной записи `## [X.Y.Z]`"]
    if found.group(1) != canon:
        return [
            f"{CHANGELOG}: верхняя запись [{found.group(1)}], "
            f"а скрипт v{canon} — версия выпущена без записи в журнале"
        ]
    return []


def check_spec(root: Path, canon: str) -> list[str]:
    """Контракт помечен версией, с которой он сверялся."""
    path = root / SPEC
    if not path.is_file():
        return [f"{SPEC}: файла нет"]
    found = SPEC_RE.search(path.read_text(encoding="utf-8", errors="replace"))
    if not found:
        return [f"{SPEC}: нет пометки «Сверено с `deploy.sh` vX.Y.Z»"]
    if found.group(1) != canon:
        return [
            f"{SPEC}: контракт сверялся с v{found.group(1)}, а скрипт v{canon} — "
            f"перечитать §3–§4 и обновить пометку"
        ]
    return []


def check_copies(script: Path, canon: str) -> tuple[list[str], list[str]]:
    """Копии на диске обязаны быть тем же файлом. Копия новее — канон отстал."""
    fails: list[str] = []
    notes: list[str] = []
    canon_sum = sha256(script)
    for raw in KNOWN_COPIES:
        path = Path(raw).expanduser()
        if not path.is_file():
            notes.append(f"копии нет на диске (это нормально): {raw}")
            continue
        if sha256(path) == canon_sum:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found = VERSION_RE.search(text)
        their = found.group(1) if found else "?"
        if found and as_tuple(their) > as_tuple(canon):
            fails.append(
                f"{raw}: v{their} НОВЕЕ канона v{canon} — "
                f"отстала база, а не копия. Поднять канон, не затирать копию (PIT-063)"
            )
        else:
            fails.append(f"{raw}: v{their} != канон v{canon}, содержимое разошлось")
    return fails, notes


def check_mentions(root: Path, canon: str) -> list[str]:
    """Живая документация не должна называть устаревший номер версии."""
    stale: list[str] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".") or is_frozen(rel):
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            for found in MENTION_RE.finditer(line):
                if found.group(1) != canon:
                    stale.append(f"{rel}:{number}: назван v{found.group(1)}, канон v{canon}")
    return stale


def fix_docs(root: Path, script: Path, canon: str) -> list[str]:
    """Починить то, что чинится однозначно: шапку скрипта и пометку в контракте."""
    done: list[str] = []
    text = script.read_text(encoding="utf-8")
    patched = HEADER_RE.sub(f"# deploy.sh v{canon}", text, count=1)
    if patched != text:
        script.write_text(patched, encoding="utf-8")
        done.append(f"{SCRIPT}: шапка приведена к v{canon}")

    spec = root / SPEC
    if spec.is_file():
        text = spec.read_text(encoding="utf-8")
        patched = SPEC_RE.sub(f"Сверено с `deploy.sh` v{canon}", text, count=1)
        if patched != text:
            spec.write_text(patched, encoding="utf-8")
            done.append(f"{SPEC}: пометка сверки приведена к v{canon}")
    return done


def sync_copies(script: Path, canon: str) -> tuple[list[str], list[str]]:
    """Разложить канон по известным копиям. Понижение версии запрещено."""
    done: list[str] = []
    refused: list[str] = []
    payload = script.read_bytes()
    canon_sum = sha256(script)
    for raw in KNOWN_COPIES:
        path = Path(raw).expanduser()
        if not path.is_file() or sha256(path) == canon_sum:
            continue
        found = VERSION_RE.search(path.read_text(encoding="utf-8", errors="replace"))
        their = found.group(1) if found else None
        if their and as_tuple(their) > as_tuple(canon):
            refused.append(f"{raw}: v{their} новее канона v{canon} — НЕ ТРОНУТА")
            continue
        path.write_bytes(payload)
        path.chmod(0o755)
        done.append(f"{raw}: v{their or '?'} -> v{canon}")
    return done, refused


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="корень репы")
    parser.add_argument("--fix", action="store_true", help="починить документацию базы")
    parser.add_argument(
        "--sync-copies", action="store_true", help="разложить канон по копиям на диске"
    )
    args = parser.parse_args()
    root = Path(args.root).resolve()

    canon, script = read_canon(root)
    print(f"канон: {SCRIPT} v{canon}\n")

    if args.fix:
        for line in fix_docs(root, script, canon) or ["нечего чинить"]:
            print(f"  fix  {line}")
        print()

    if args.sync_copies:
        done, refused = sync_copies(script, canon)
        for line in done:
            print(f"  sync {line}")
        for line in refused:
            print(f"  СТОП {line}")
        print()
        if refused:
            return 1

    fails: list[str] = []
    fails += check_header(script, canon)[0]
    fails += check_changelog(root, canon)
    fails += check_spec(root, canon)
    copy_fails, notes = check_copies(script, canon)
    fails += copy_fails
    fails += check_mentions(root, canon)

    for line in notes:
        print(f"  ·    {line}")

    if not fails:
        print("CLEAN — версия деплойера, документация и копии сходятся")
        return 0

    print(f"\nDRIFT — расхождений: {len(fails)}\n")
    for line in fails:
        print(f"  FAIL {line}")
    print(
        "\nПочинить документацию базы:  python3 scripts/deploy_version_gate.py --fix"
        "\nРазложить канон по копиям:   python3 scripts/deploy_version_gate.py --sync-copies"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
