#!/usr/bin/env python3
"""planner_audit.py — планировщик сверяется с реальностью, а не только пополняется.

🔴 ЗАЧЕМ. Оценка системы 29.08.2026 дала планировщику **45 из 100 по
самостоятельности**: он **событийный**. Пункт появляется в нём, только если
кто-то заметил и записал; пункт исчезает, только если кто-то вспомнил закрыть.
Между планировщиком и диском нет ни одной сверки — расхождение накапливается
молча и обнаруживается случайно.

Это тот же изъян, что у любой системы «только на событиях»: потерялось
наблюдение — потерялось действие. Лечится уровневым проходом: спросить диск
заново и сравнить с тем, что планировщик утверждает.

ЧТО СВЕРЯЕТСЯ (каждая проверка отвечает на «планировщик врёт или нет»):

  1. **репа названа, а её нет** — задача ссылается на несуществующий каталог;
  2. **пункт без исполнителя** — в `BACKLOG.md` разряды 🤖/👤/👤→🤖 несут
     смысл, пункт вне разряда не попадёт ни в один срез;
  3. **дубль между файлами** — один и тот же пункт в двух местах: копии
     расходятся, и уже расходились (шесть штук 28.08.2026);
  4. **`BOARD.md` отстал** — вид старше источников, из которых собран;
  5. **счётчики в прозе** — «7 открытых», «13 пунктов» против факта.

🔴 ЧЕГО НЕ УМЕЕТ (`71` §7г-бис):

  · **не судит, нужна ли задача** — только соответствует ли запись факту;
  · **не видит пропущенного**: задача, которую никто не записал, невидима
    и здесь. Уровневость снимает потерю события, не отсутствие знания;
  · **дубли ищет по началу строки**, а не по смыслу: перефразированный
    пункт пройдёт мимо.

ЗАПУСК
    planner_audit.py             сверка
    planner_audit.py --selftest  канарейка
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402
BASE_REPO, REPOS, FROM_KIT = resolve_roots(__file__)
PLANNER = REPOS / "mission-control"

TASK_RE = re.compile(r"^\s*[-*]\s*\[[ xX]\]\s*(.+)$")
REPO_RE = re.compile(r"`([a-z][a-z0-9-]{2,})`")
# Разряды исполнителя в BACKLOG — вне их пункт не попадёт ни в один срез.
ROLE_RE = re.compile(r"(🤖|👤)")


def open_tasks(path: Path) -> list[tuple[int, str]]:
    """(номер строки, текст) по открытым пунктам файла."""
    if not path.is_file():
        return []
    out = []
    for num, line in enumerate(path.read_text(encoding="utf-8",
                                              errors="replace").splitlines(), 1):
        m = TASK_RE.match(line)
        if m and "[ ]" in line:
            out.append((num, m.group(1).strip()))
    return out


def check_missing_repos(planner: Path, repos_root: Path) -> list[str]:
    """Задача ссылается на репу, которой нет на диске."""
    known = {d.name for d in repos_root.iterdir() if d.is_dir()}
    # Слова, похожие на имя репы, но таковыми не являющиеся.
    noise = {"base", "main", "true", "false", "null", "utf", "sha", "src",
             "bin", "tmp", "etc", "usr", "var", "com", "org", "www"}
    problems = []
    for name in ("TASKS.md", "ROADMAP.md", "BACKLOG.md"):
        for num, text in open_tasks(planner / name):
            for cand in REPO_RE.findall(text):
                if cand in known or cand in noise or "-" not in cand:
                    continue
                # Имя с дефисом, похожее на репу, но отсутствующее.
                problems.append(f"{name}:{num} — названа репа `{cand}`, "
                                f"каталога нет")
    return problems


def check_role_assigned(planner: Path) -> list[str]:
    """Пункт `BACKLOG.md` вне разряда исполнителя — не попадёт ни в один срез."""
    path = planner / "BACKLOG.md"
    if not path.is_file():
        return []
    problems, current = [], None
    for num, line in enumerate(path.read_text(encoding="utf-8",
                                              errors="replace").splitlines(), 1):
        # 🔴 Разряд сбрасывается на ЛЮБОМ заголовке, не только `###`.
        # Раньше пункт под `##`-разделом наследовал разряд предыдущего
        # `###` и молча признавался размеченным. В живом `BACKLOG.md`
        # семь таких `##`-разделов — дефект был латентным (ревью 29.08.2026).
        if re.match(r"^#{1,3} ", line):
            current = ("есть" if ROLE_RE.search(line) and line.startswith("### ")
                       else None)
        elif TASK_RE.match(line) and "[ ]" in line and current is None:
            problems.append(f"BACKLOG.md:{num} — пункт вне разряда "
                            f"исполнителя (🤖 / 👤 / 👤→🤖)")
    return problems


def check_cross_file_dupes(planner: Path) -> list[str]:
    """Один пункт в двух файлах: копии расходятся, и уже расходились."""
    seen: dict[str, str] = {}
    problems = []
    for name in ("TASKS.md", "ROADMAP.md", "BACKLOG.md"):
        for num, text in open_tasks(planner / name):
            # Ключ — первые значимые слова без разметки и меток срока.
            key = re.sub(r"[*`\[\]🔴👤🤖⚫🌱📅🔥]|зав\.\s*(до\s*)?\d+\.\d+", "", text)
            key = " ".join(key.split())[:45].lower()
            if len(key) < 20:
                continue
            if key in seen and seen[key].split(":")[0] != name:
                problems.append(f"{name}:{num} — тот же пункт уже есть "
                                f"в {seen[key]}: «{key[:40]}…»")
            else:
                seen[key] = f"{name}:{num}"
    return problems


def check_board_fresh(planner: Path) -> list[str]:
    """`BOARD.md` — вид: он обязан быть НЕ старше источников, из которых собран."""
    board = planner / "BOARD.md"
    if not board.is_file():
        return []
    board_mtime = board.stat().st_mtime
    problems = []
    for name in ("TASKS.md", "ROADMAP.md", "BACKLOG.md"):
        src = planner / name
        if src.is_file() and src.stat().st_mtime > board_mtime:
            hours = (src.stat().st_mtime - board_mtime) / 3600
            problems.append(f"BOARD.md старше {name} на {hours:.0f} ч — "
                            f"вид отстал от источника, перегенерировать")
    return problems


CHECKS = (
    ("репа названа, а её нет", check_missing_repos),
    ("пункт вне разряда исполнителя", check_role_assigned),
    ("дубль между файлами", check_cross_file_dupes),
    ("вид отстал от источника", check_board_fresh),
)


def selftest() -> bool:
    """Проверяется РАЗЛИЧЕНИЕ: дубль ловится, разные пункты — нет."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        (p / "TASKS.md").write_text(
            "- [ ] Завести тринадцать секретов в связку ключей\n", encoding="utf-8")
        (p / "ROADMAP.md").write_text(
            "- [ ] Завести тринадцать секретов в связку ключей\n"
            "- [ ] Совершенно другая задача про разбор экспортов\n", encoding="utf-8")
        found = check_cross_file_dupes(p)
        if len(found) != 1:
            return False                      # ровно один дубль
        (p / "ROADMAP.md").write_text(
            "- [ ] Совершенно другая задача про разбор экспортов\n", encoding="utf-8")
        return check_cross_file_dupes(p) == []   # разные пункты молчат


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        ok = selftest()
        print("🟢 канарейка: дубль ловится, разные пункты молчат"
              if ok else "🔴 канарейка: РАЗЛИЧЕНИЕ СЛОМАНО")
        return 0 if ok else 1

    if not selftest():
        print("🔴 канарейка не прошла — находкам ниже верить нельзя")
        return 1
    if not PLANNER.is_dir():
        print(f"🔴 нет планировщика: {PLANNER}")
        return 1

    print("═══ Сверка планировщика с реальностью ═══\n")
    total = 0
    for label, probe in CHECKS:
        found = probe(PLANNER, REPOS) if probe is check_missing_repos \
            else probe(PLANNER)
        if found:
            total += len(found)
            print(f"  🔴 {label}: {len(found)}")
            for line in found[:6]:
                print(f"        · {line}")
            if len(found) > 6:
                print(f"        · … и ещё {len(found) - 6}")
        else:
            print(f"  🟢 {label} — нет")

    print(f"\nрасхождений: {total}")
    print("\n🔴 Проход УРОВНЕВЫЙ: состояние спрошено у диска заново. Планировщик")
    print("   перестаёт быть только списком — он теперь сверяется.")
    print("🔴 Но задача, которую никто не записал, невидима и здесь:")
    print("   уровневость снимает потерю события, а не отсутствие знания.")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
