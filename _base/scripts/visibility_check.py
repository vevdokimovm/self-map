#!/usr/bin/env python3
"""visibility_check.py — три записи о публичности реп против одного GitHub.

🔴 ПОВОД, 04.09.2026. Один факт — «какие репы публичны» — записан
в системе **трижды**, и все три записи разошлись:

    repos-map.md          4 публичных
    MIRRORS в deploy.sh  10
    GitHub                8   ← единственный источник правды

Из-за расхождения вахта переспросила владельца о вопросе, решённом
и **исполненном** давно. Ответ был: «бро ты идиот этот вопрос давно решён».

ЧТО ЭТО ЗА КЛАСС. Не «кто-то поленился синхронизировать». Видимость репы
меняется **вне системы и без события в ней**: владелец нажимает кнопку
на GitHub, и ни один файл не меняется. Уровневая ревизия спрашивает диск
заново — но GitHub она не спрашивает (`21` §4а-трис).

ЧТО ПРОВЕРЯЕТСЯ:

  · каждая репа, публичная на GitHub, помечена публичной в `repos-map.md`;
  · каждая репа, помеченная публичной в карте, публична на GitHub;
  · 🔴 каждая публичная репа перечислена в `MIRRORS` деплойера — иначе
    массовый прогон сочтёт её обычной и зальёт в витрину `_base/`
    (случилось 08.08.2026 с публичной `finpilot`).

🔴 ЧЕГО НЕ ДЕЛАЕТ:

  · **не меняет видимость** — это необратимое действие вовне и решение
    владельца (`/auto` §5). Инструмент только называет расхождение;
  · **не правит `MIRRORS` сам**: список живёт в скрипте, который лежит
    в пяти копиях, и правка одной копии создала бы шестое расхождение;
  · **не работает без сети** — при недоступном `gh` честно говорит, что
    проверка не выполнена, а не «расхождений нет» (`69` §4м: молчание
    заглушки неотличимо от проверенного случая).

ЗАПУСК:
    python3 scripts/visibility_check.py
    python3 scripts/visibility_check.py --selftest
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402

BASE_REPO, REPOS, _ = resolve_roots(__file__)
OWNER = "vevdokimovm"
_LIST: list | None = None


def _repo_list() -> list | None:
    """Один запрос к GitHub на прогон — его результат нужен трижды."""
    global _LIST
    if _LIST is not None:
        return _LIST
    try:
        r = subprocess.run(
            ["gh", "repo", "list", OWNER, "--limit", "300",
             "--json", "name,visibility"],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        _LIST = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
    return _LIST


def all_on_github() -> set[str] | None:
    """Все репы аккаунта, любой видимости. None — спросить не удалось."""
    data = _repo_list()
    return None if data is None else {d["name"] for d in data}


def public_on_github() -> set[str] | None:
    """Имена публичных реп. None — спросить не удалось (сеть, авторизация)."""
    data = _repo_list()
    if data is None:
        return None
    return {d["name"] for d in data if d.get("visibility") == "PUBLIC"}


def public_in_map(text: str) -> set[str]:
    """Репы, помеченные публичными в карте: `## … \\`имя\\` · 🌐 публичная`."""
    return set(re.findall(r"^##\s+\S*\s*`([^`]+)`\s*·\s*🌐\s*публичная", text, re.M))


def mirrors_in_deploy(text: str) -> set[str]:
    """Список `MIRRORS` из тела деплойера, с учётом вложенного умолчания."""
    m = re.search(r'^MIRRORS="\$\{MIRRORS:-(.*)\}"$', text, re.M)
    if not m:
        return set()
    raw = m.group(1)
    inner = re.match(r"^\$\{CONF_MIRRORS:-(.*)\}$", raw)
    if inner:
        raw = inner.group(1)
    return set(raw.split())


def phantom_mirrors(gh: set[str], mr: set[str], all_repos: set[str]) -> list[str]:
    """Имена из `MIRRORS`, которых на GitHub нет вовсе.

    🔴 Это НЕ дефект защиты: список зеркал работает на пропуск, и лишнее имя
    в нём инертно. Более того, `mission-control::ADR-009` требует вносить зеркало **в момент
    создания**, а не после инцидента, — то есть имя вперёд репы законно.

    Но замер 04.09.2026 показал другое: **4 из 12** имён не существуют,
    и одно из них — `bron-kerbosch` — стояло в `ROADMAP` как ✅ опубликованная
    ступень витрины. Список не сверяли ни разу, и он тихо хранил
    несостоявшийся план.

    Поэтому строка **информационная, а не пороговая**: она рассказывает,
    а не краснеет.
    """
    return sorted(mr - all_repos)


def compare(gh: set[str], mp: set[str], mr: set[str]) -> list[str]:
    """Расхождения. Пусто — три записи об одном факте сходятся."""
    out = []
    for name in sorted(gh - mp):
        out.append(f"публична на GitHub, но не помечена в repos-map: {name}")
    for name in sorted(mp - gh):
        out.append(f"помечена публичной в repos-map, но на GitHub приватна: {name}")
    for name in sorted(gh - mr):
        out.append(f"🔴 публична, но НЕ в MIRRORS деплойера — массовый режим "
                   f"зальёт в неё _base/: {name}")
    return out


def selftest() -> int:
    ok = True
    cases = [
        ("карта разбирается",
         lambda: public_in_map("## 💰 `finpilot`  ·  🌐 публичная\n"
                               "## 🩺 `health-vault`\n") == {"finpilot"}),
        ("зеркала с вложенным умолчанием",
         lambda: mirrors_in_deploy(
             'MIRRORS="${MIRRORS:-${CONF_MIRRORS:-a b c}}"\n') == {"a", "b", "c"}),
        ("зеркала без вложенного умолчания",
         lambda: mirrors_in_deploy('MIRRORS="${MIRRORS:-x y}"\n') == {"x", "y"}),
        ("совпадение — тишина",
         lambda: compare({"a"}, {"a"}, {"a"}) == []),
        ("🔴 публичная вне MIRRORS — находка",
         lambda: any("НЕ в MIRRORS" in s for s in compare({"a"}, {"a"}, set()))),
        ("карта отстала от GitHub — находка",
         lambda: any("не помечена в repos-map" in s
                     for s in compare({"a", "b"}, {"a"}, {"a", "b"}))),
        ("призрачное зеркало названо",
         lambda: phantom_mirrors({"a"}, {"a", "prizrak"}, {"a"}) == ["prizrak"]),
        ("существующее зеркало призраком не считается",
         lambda: phantom_mirrors({"a"}, {"a", "b"}, {"a", "b"}) == []),
        ("карта врёт в другую сторону — находка",
         lambda: any("на GitHub приватна" in s
                     for s in compare({"a"}, {"a", "b"}, {"a", "b"}))),
    ]
    for name, fn in cases:
        got = bool(fn())
        print(f"   {'✅' if got else '🔴'} {name}")
        ok &= got
    print("selftest OK" if ok else "🔴 selftest ПРОВАЛЕН")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    gh = public_on_github()
    if gh is None:
        print("🟡 GitHub не отвечает — проверка НЕ ВЫПОЛНЕНА.")
        print("   Это не «расхождений нет»: единственный источник правды")
        print("   недоступен, и сказать нечего (`69` §4м).")
        return 0

    mp = public_in_map((BASE_REPO / "repos-map.md").read_text(
        encoding="utf-8", errors="replace"))
    mr = mirrors_in_deploy((BASE_REPO / "templates/deploy.sh").read_text(
        encoding="utf-8", errors="replace"))

    print(f"═══ Публичность реп · снято с GitHub ═══\n")
    print(f"  GitHub      : {len(gh):>3}  ← источник правды")
    print(f"  repos-map.md: {len(mp):>3}")
    print(f"  MIRRORS     : {len(mr):>3}  (шире по построению: там и будущие зеркала)\n")

    every = all_on_github()
    if every is not None:
        ghost = phantom_mirrors(gh, mr, every)
        if ghost:
            print(f"🟡 в MIRRORS, но на GitHub НЕТ — {len(ghost)}: "
                  f"{', '.join(ghost)}")
            print("   Не дефект: список работает на пропуск, лишнее имя инертно,")
            print("   и `mission-control::ADR-009` разрешает вносить зеркало ДО создания репы.")
            print("   Но замер 04.09.2026 показал, что список не сверяли ни разу:")
            print("   `bron-kerbosch` стоял в `ROADMAP` как ✅ опубликованный.\n")

    bad = compare(gh, mp, mr)
    if not bad:
        print("🟢 расхождений нет")
        return 0
    print(f"🔴 расхождений: {len(bad)}")
    for line in bad:
        print(f"   · {line}")
    print("\n🔴 Видимость меняет ВЛАДЕЛЕЦ на GitHub — инструмент только")
    print("   называет расхождение и ничего не переключает (`/auto` §5).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
