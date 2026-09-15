#!/usr/bin/env python3
"""repo_revision.py — ревизия реп по существу: врёт ли документация о диске.

ЗАДАЧА `ROADMAP.md` §P0 п. 2: «ревизия базы и каждой репы, протокол общий + по каждой».
Машинная половина протокола.

🔴 ПОЧЕМУ ОТДЕЛЬНО ОТ `per_repo_audit.py`, А НЕ РЕЖИМОМ В НЁМ. Тот отвечает на вопрос
**«соответствует ли репа стандарту»**: есть ли обязательные файлы, какие служебки
не попали в базу. Здесь вопрос другой и на два уровня глубже:
**«не врёт ли документация репы о её собственном содержимом»**.

Разница не формальная. Репа может иметь все файлы стандарта и при этом описывать
структуру, которой нет: `health-vault` держал README с **26 мёртвыми путями** —
десять каталогов верхнего уровня и шестнадцать вложенных, — потому что каталоги
переименовали по стандарту нейминга, а README оставили. Аудит стандарта эту репу
считал образцовой: файлы-то на месте.

ЧТО ПРОВЕРЯЕТСЯ — три вопроса, на которые нельзя ответить чтением:

  1. **Мёртвые пути.** Каталог или файл, упомянутый в README как существующий,
     на диске отсутствует.
  2. **Числа в прозе против диска.** «Всего: 255 файлов» — сверяется пересчётом.
  3. **Отставший штамп базы.** `_base/BASE_VERSION` против канона.

Класс всех трёх — `PIT-091`: **утверждение, не сверенное с диском, живёт ровно
до первой попытки по нему пройти** и всё это время выглядит достоверно — тем
достовернее, чем подробнее таблица.

ГРАНИЦА (`71` §7г-бис): содержательное устаревание без структурного следа скрипт
не ловит и ловить не может. README, описывающий верную структуру неверными словами,
пройдёт проверку. Для этого остаётся чтение вахтой.

ЗАПУСК:
    repo_revision.py              все репы, сводка
    repo_revision.py --repo ИМЯ   разбор одной
    repo_revision.py --verbose    показать каждый мёртвый путь
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

# Корень определяется общим модулем: скрипт может быть запущен и из базы,
# и из копии кита в репе-наследнике (`_base/scripts/`). См. `_roots.py`.
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402
BASE_REPO, REPOS, FROM_KIT = resolve_roots(__file__)
# 🔴 БЫЛО: `Path.home() / "Documents" / "base-repo"` — путь, устаревший
# после переезда системы в `~/repos/`. Строка стояла СРАЗУ ПОСЛЕ вызова
# `resolve_roots()`, то есть отменяла правильный механизм, стоящий рядом.
# Скрипт падал `FileNotFoundError` и ронял закрытие батча любой репы.
# Найдено 04.09.2026 — тот же класс, что `recovery_kits` → `recovery-kits`
# в то же утро: переезд доехал до диска и не доехал до тех, кто ссылается.
BASE = BASE_REPO

# Путь в обратных кавычках: `01-lab-tests/`, `scripts/foo.py`, `README.md`
PATH_RE = re.compile(r"`([A-Za-zА-Яа-я0-9_.\-]+(?:/[A-Za-zА-Яа-я0-9_.\-]+)*/?)`")
COUNT_RE = re.compile(r"[Вв]сего[^.\n]{0,40}?(\d[\d\s]{1,7})\s*файл", re.M)

# Не считаем путями то, что ими не является: расширения, версии, команды.
NOT_PATH = re.compile(r"^(v?\d[\d.]*|[A-Z_]{2,}|--?\w+|\d+)$")


# Известные НЕ-пути: расширения как слово, плейсхолдеры версий, имена библиотек.
# Первая редакция считала путём всё с точкой или слэшем и выдала 183 «мёртвых пути»,
# из которых `.md`, `vX.Y.Z`, `Three.js` — не пути вовсе (найдено 22.08.2026).
# Проверка на существование не отличает «файла нет» от «это не файл»: спрашивать
# надо у формы строки, а не у диска.
BARE_EXT = re.compile(r"^\.[a-z0-9]{1,5}$")
PLACEHOLDER = re.compile(r"[XYZN]{1,3}|<[^>]+>|\{\{|\.\.\.")
KNOWN_LIBS = {"three.js", "next.js", "node.js", "vue.js", "d3.js", "chart.js"}


def looks_like_path(s: str) -> bool:
    if NOT_PATH.match(s) or BARE_EXT.match(s):
        return False
    if PLACEHOLDER.search(s) or s.lower() in KNOWN_LIBS:
        return False
    # Путь — это либо со слэшем, либо файл с осмысленным расширением
    if "/" in s:
        return True
    return bool(re.match(r"^[\w.\-]+\.(md|py|sh|json|yml|yaml|txt|csv|html|toml|cfg)$", s))


def stamp_lag(mirror: str, canon: str) -> int | None:
    """На сколько МИНОРНЫХ версий отстало зеркало. None — если не сравнить.

    🔴 ПОЧЕМУ ПОРОГ, А НЕ СТРОГОЕ РАВЕНСТВО. `ADR-004` §5 правило 1 предписывал
    краснеть «при расхождении больше N минорных версий»; первая реализация сравнивала
    строки на равенство. Следствие измерено 22.08.2026: база прошла за сессию
    12 версий, и после КАЖДОГО батча все 51 зеркало становились «отставшими».
    Метрика, которая всегда красная, не отличает норму от дефекта — и перестаёт
    читаться, как перестал читаться реестр из `PIT-116`.

    Порог 5 минорных: раздача повторяется раз в несколько батчей, а не после каждого.
    Разная МАЖОРНАЯ версия — отставание всегда, сколько бы ни было миноров.
    """
    try:
        m = [int(x) for x in mirror.split(".")[:2]]
        c = [int(x) for x in canon.split(".")[:2]]
    except ValueError:
        return None
    if m[0] != c[0]:
        return 999
    return c[1] - m[1]


LAG_THRESHOLD = 5

def dead_paths(repo: Path, doc: Path) -> list[str]:
    """Пути из документа, которых нет на диске.

    Ищем и от корня репы, и рядом с документом: README подраздела ссылается
    относительно себя, README корня — от корня.
    """
    try:
        text = doc.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    dead = []
    for raw in dict.fromkeys(PATH_RE.findall(text)):
        if not looks_like_path(raw):
            continue
        rel = raw.rstrip("/")
        # `_base/…` — зеркало, его состав проверяет base_coverage
        if rel.startswith("_base"):
            continue
        if (repo / rel).exists() or (doc.parent / rel).exists():
            continue
        # 🔴 Путь может быть ВЛОЖЕННЫМ: README пишет `invitro/`, а на диске это
        # `01-lab-tests/invitro/`. Проверка только от корня объявляла такие пути
        # мёртвыми — 21 ложное срабатывание в `health-vault` сразу после того,
        # как его README был приведён к диску (найдено 22.08.2026).
        # Ищем последний сегмент по всему дереву репы.
        tail = rel.split("/")[-1]
        if tail and any(True for _ in repo.rglob(tail)):
            continue
        # 🔴 Ссылка-указатель по НОМЕРУ файла: `01-libraries/idite-lesom/06`
        # адресует `06-obzor….md`, а не каталог `06`. В системе документы
        # нумерованы, и ссылаться на номер — штатная нотация (найдено 22.08.2026
        # в `legal-knowledge-base`: 14 таких ссылок).
        if tail.isdigit():
            parent = repo / "/".join(rel.split("/")[:-1])
            if parent.is_dir() and any(f.name.startswith(tail + "-") for f in parent.iterdir()):
                continue
        # Путь мог быть указан в чужую репу или в базу — это не дефект README
        if (REPOS / rel).exists() or (BASE / rel).exists():
            continue
        # `vevdokimovm/portrait-of-taste` — это адрес репы на GitHub, а не путь
        # на диске. Форма совпадает с относительным путём полностью, различить
        # можно только по владельцу (найдено 22.08.2026 на выборке).
        if rel.startswith("vevdokimovm/"):
            continue
        # Путь вида `base-repo/00-infrastructure/83-…` адресует КАНОН и пишется
        # от корня системы. Проверять его внутри самой базы бессмысленно —
        # получится `base-repo/base-repo/…`. Найдено 22.08.2026: документ
        # существовал, а проверка объявляла ссылку мёртвой.
        if rel.startswith("base-repo/") and (BASE.parent / rel).exists():
            continue
        dead.append(raw)
    return dead


def stated_count(doc: Path) -> int | None:
    try:
        m = COUNT_RE.search(doc.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return int(re.sub(r"\s", "", m.group(1))) if m else None


def real_count(repo: Path) -> int:
    return sum(1 for p in repo.rglob("*")
               if p.is_file() and ".git" not in p.parts and "_base" not in p.parts
               and p.name != ".DS_Store")


def check(repo: Path, canon_ver: str) -> dict:
    res = {"dead": [], "count": None, "stamp": None}
    readme = repo / "README.md"
    if readme.is_file():
        res["dead"] = dead_paths(repo, readme)
        said = stated_count(readme)
        # Уточнённое число («всего в тематических разделах») не сверяется с общим
        # пересчётом — это разные величины, и расхождение здесь не дефект.
        if said is not None and "тематическ" not in readme.read_text(
                encoding="utf-8", errors="replace")[:4000]:
            got = real_count(repo)
            # ±5 % — проза округляет; расхождение в разы это не прячет
            if abs(said - got) > max(5, got * 0.05):
                res["count"] = (said, got)
    stamp = repo / "_base" / "BASE_VERSION"
    if stamp.is_file():
        v = stamp.read_text(encoding="utf-8").strip()
        lag = stamp_lag(v, canon_ver)
        if lag is not None and lag > LAG_THRESHOLD:
            res["stamp"] = f"{v} (отстаёт на {lag} минорных)"
    return res


def check_classes() -> list[str]:
    """Все значения `.repo-class` обязаны быть описаны в `76-repo-classes.md`.

    🔴 Найдено 22.08.2026: класс `profile` **использовался** (`vevdokimovm`) и при этом
    отсутствовал в документе, объявленном единственным источником правды по классам.
    Поймано не чтением, а сверкой множеств — глазами такое не видно, потому что
    и файл, и документ выглядят исправными по отдельности.

    Класс дефекта тот же, что у реестров (`PIT-098`), но отстаёт здесь не список
    записей, а **список допустимых значений**.
    """
    doc = BASE / "00-infrastructure" / "76-repo-classes.md"
    if not doc.is_file():
        return []
    known = set(re.findall(r"^\|\s*\*\*([a-z-]+)\*\*", doc.read_text(encoding="utf-8"), re.M))
    used = {}
    for d in REPOS.iterdir():
        f = d / ".repo-class"
        if d.is_dir() and f.is_file():
            used.setdefault(f.read_text(encoding="utf-8").strip().split(":")[0], []).append(d.name)
    return [f"класс `{c}` используется ({', '.join(v[:3])}), но не описан в 76-repo-classes.md"
            for c, v in sorted(used.items()) if c and c not in known]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    canon = (BASE / "VERSION").read_text(encoding="utf-8").strip()
    targets = [REPOS / a.repo] if a.repo else sorted(d for d in REPOS.iterdir() if d.is_dir())

    bad_paths = bad_counts = bad_stamps = 0
    rows = []
    for d in targets:
        if not d.is_dir():
            continue
        r = check(d, canon)
        if not (r["dead"] or r["count"] or r["stamp"]):
            continue
        rows.append((d.name, r))
        bad_paths += len(r["dead"])
        bad_counts += 1 if r["count"] else 0
        bad_stamps += 1 if r["stamp"] else 0

    print(f"── РЕВИЗИЯ РЕП · канон базы v{canon} · проверено {len(targets)}\n")
    for name, r in rows:
        parts = []
        if r["dead"]:
            parts.append(f"мёртвых путей {len(r['dead'])}")
        if r["count"]:
            parts.append(f"число в прозе {r['count'][0]} против {r['count'][1]} на диске")
        if r["stamp"]:
            parts.append(f"зеркало v{r['stamp']}")
        print(f"  {name:<26}{' · '.join(parts)}")
        if a.verbose and r["dead"]:
            for p in r["dead"][:12]:
                print(f"      ✗ {p}")

    for line in check_classes():
        print(f"\n  🔴 {line}")

    print(f"\n  реп с расхождениями: {len(rows)} из {len(targets)}")
    print(f"  мёртвых путей всего: {bad_paths}")
    print(f"  чисел в прозе врут:  {bad_counts}")
    print(f"  отставших зеркал:    {bad_stamps}")
    if not rows:
        print("\n  ИТОГ: CLEAN")
    return 1 if rows else 0


if __name__ == "__main__":
    raise SystemExit(main())
