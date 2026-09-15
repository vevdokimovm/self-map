#!/usr/bin/env python3
"""Пофактовый аудит КАЖДОЙ репы: что реально лежит на диске, а не что написано в доках.

Две таблицы сплошной ревизии (`00-infrastructure/77-system-wide-audit.md` §3):

  Таблица 1 — соответствие стандарту: обязательные файлы, `_base/`, BASE_VERSION.
  Таблица 2 — кандидаты в базу: служебки, которых в базе нет, с числом реп и проверкой
              совпадения копий по хешу.

Ничего не меняет — читает и составляет. Решение по каждому кандидату человеческое (§3).
"""
import hashlib
import os
from collections import defaultdict
from pathlib import Path

# 🔴 Путь к базе — одной строкой и через окружение (`ROADMAP.md` §P0 п. 6).
# Замер 22.08.2026: `/Users/vasyaevdokimov/Documents/base-repo` был вписан строкой
# в 15 файлов, и это единственное, что мешало перенести базу в каталог системы:
# перенос обрывал собственный инструмент исполнения, включая сессию, которая его делает.
# Падение на путь скрипта, а не на константу: скрипт лежит В базе и знает, где он.
BASE_ENV = os.environ.get("BASE_REPO")
CANON = Path(BASE_ENV).expanduser() if BASE_ENV else Path(__file__).resolve().parent.parent
ROOT = CANON.parent

MARKERS = ["README.md", "VERSION", ".repo-id", ".repo-class", ".repo-meta",
           "CHANGELOG.md", "WATCHLOG.md", "ROADMAP.md", "TASKS.md",
           "START-HERE.md", "00-CLAUDE-STOP.md", ".gitignore"]

# Каталоги служебок ищутся ПО ФАКТУ, а не по списку: зашитый перечень из четырёх папок
# однажды не увидел ничего в четырёх репах, где служебки лежали в reports/ и protocols/
# (77 §4). Подсказка расширяет охват, а не сужает: её промах даёт лишний каталог
# на проверку, а не потерянный.
SERVICE_HINTS = ("infrastructure", "standards", "protocols", "reports", "decisions",
                 "docs", "guides", "methodology", "templates", "kb")
SKIP_DIRS = {".git", "_base", "__MACOSX", "node_modules", ".idea", "__pycache__",
             ".venv", "venv", ".pytest_cache"}
MAX_DEPTH = 3


def sha1(p):
    try:
        return hashlib.sha1(p.read_bytes()).hexdigest()
    except OSError:
        return None


def dirfiles(d):
    if not d.is_dir():
        return {}
    out = {}
    for dp, dn, fns in os.walk(d):
        dn[:] = [x for x in dn if x not in {".git", "__MACOSX"}]
        for fn in fns:
            if fn == ".DS_Store":
                continue
            p = Path(dp) / fn
            out[str(p.relative_to(d))] = sha1(p)
    return out


def _main_body() -> None:
    canon_infra = dirfiles(CANON / "00-infrastructure")

    rows = []
    for repo in sorted(ROOT.iterdir()):
        if not repo.is_dir():
            continue
        own = dirfiles(repo / "00-infrastructure")
        base = dirfiles(repo / "_base" / "00-infrastructure")
        bv = (repo / "_base" / "BASE_VERSION")
        bv = bv.read_text().strip() if bv.exists() else "—"

        # сколько файлов своей 00-infrastructure БАЙТ-В-БАЙТ совпадают с _base-копией
        dup = sum(1 for k, v in own.items() if k in base and base[k] == v)
        # сколько совпадают с КАНОНОМ (актуальной базой)
        dupcanon = sum(1 for k, v in own.items() if k in canon_infra and canon_infra[k] == v)
        # действительно своё = ни в _base, ни в каноне
        truly_own = [k for k, v in own.items()
                     if not (k in base and base[k] == v)
                     and not (k in canon_infra and canon_infra[k] == v)]

        present = [m for m in MARKERS if (repo / m).exists()]
        missing = [m for m in MARKERS if not (repo / m).exists()]

        rows.append({
            "repo": repo.name, "own": len(own), "base": len(base), "bv": bv,
            "dup_base": dup, "dup_canon": dupcanon, "truly_own": truly_own,
            "present": present, "missing": missing,
            "has_base": (repo / "_base").is_dir(),
        })

    print(f"{'репа':<24}{'_base':>7}{'BASEV':>9}{'своя':>6}{'дубль':>7}{'реально своё':>14}")
    print("-" * 70)
    for r in rows:
        print(f"{r['repo']:<24}{('да' if r['has_base'] else 'НЕТ'):>7}{r['bv']:>9}"
              f"{r['own']:>6}{r['dup_base']:>7}{len(r['truly_own']):>14}")

    print("\n\n=== РЕАЛЬНО СВОИ файлы (не копия базы) по репам ===")
    for r in rows:
        if r["truly_own"]:
            print(f"\n--- {r['repo']} ({len(r['truly_own'])})")
            for f in sorted(r["truly_own"])[:30]:
                print("   ", f)
            if len(r["truly_own"]) > 30:
                print(f"    … ещё {len(r['truly_own'])-30}")

    print("\n\n=== ЧЕГО НЕ ХВАТАЕТ в корне (обязательный минимум) ===")
    for r in rows:
        if r["missing"]:
            print(f"{r['repo']:<24} нет: {', '.join(r['missing'])}")


    # ============================================================================
    # Таблица 2 — кандидаты в базу (77 §4)
    # ============================================================================

    def is_service_dir(here: Path, repo: Path) -> bool:
        """Служебный ли каталог. ЕДИНСТВЕННОЕ место, где живёт это решение.

        Проверяются ВСЕ сегменты пути внутри репы, а не только имя самого каталога:
        `reports/incidents/` служебный, потому что служебен `reports/`, хотя слова
        «incidents» в подсказках нет. Первая редакция смотрела только на `here.name`
        и теряла `incidents/`, `situations/`, `merges/`, `adr/` — найдено измерителем
        слепой зоны (`audit_coverage.py`) в первом же прогоне.

        Импортируется измерителем — дублировать эту логику там запрещено:
        измеритель, повторяющий логику измеряемого, начинает мерить другой фильтр
        (77-system-wide-audit.md §4).
        """
        rel = here.relative_to(repo)
        return any(
            any(h in part.lower() for h in SERVICE_HINTS)
            for part in rel.parts
        )


    def service_md(repo: Path) -> dict[str, str]:
        """Служебные .md репы: имя файла -> sha1. Обход до MAX_DEPTH, каталоги по подсказке."""
        found: dict[str, str] = {}
        base_depth = len(repo.parts)
        for dp, dn, fns in os.walk(repo):
            here = Path(dp)
            dn[:] = [x for x in dn if x not in SKIP_DIRS]
            if len(here.parts) - base_depth > MAX_DEPTH:
                dn[:] = []
                continue
            if here == repo:
                continue
            if not is_service_dir(here, repo):
                continue
            for fn in fns:
                if fn.lower().endswith(".md"):
                    found[fn] = sha1(here / fn)
        return found


    canon_names = {p.name for p in CANON.rglob("*.md") if ".git" not in p.parts}

    # имя -> {репа: sha1}
    seen: dict[str, dict[str, str]] = defaultdict(dict)
    for repo in sorted(ROOT.iterdir()):
        if not repo.is_dir() or repo.name != repo.name.strip():
            continue
        for name, h in service_md(repo).items():
            seen[name][repo.name] = h

    print("\n\n=== ТАБЛИЦА 2. Кандидаты в базу (77 §4) ===")
    print("Два условия переноса: встречается в N репах И все копии совпадают по хешу.")
    print("Разное содержимое под одним именем — КОНФЛИКТ, а не кандидат: автоперенос")
    print("выбрал бы одну редакцию и молча затёр чужую.\n")
    print(f"{'реп':>4}{'редакций':>10}  имя")
    print("-" * 62)

    cands = []
    for name, per_repo in seen.items():
        if name in canon_names:
            continue
        n = len(per_repo)
        if n < 2:
            continue
        cands.append((n, len(set(per_repo.values())), name, per_repo))

    for n, variants, name, per_repo in sorted(cands, key=lambda c: (-c[0], c[2])):
        mark = "" if variants == 1 else "  ← КОНФЛИКТ"
        print(f"{n:>4}{variants:>10}  {name}{mark}")

    agree = [c for c in cands if c[1] == 1 and c[0] >= 3]
    conflict = [c for c in cands if c[1] > 1]
    print(f"\nвсего кандидатов: {len(cands)} · согласованных (3+ реп, один хеш): {len(agree)}"
          f" · конфликтов: {len(conflict)}")
    print("\nРешение по каждому — человеческое (77 §3): поднять / оставить местным / удалить.")
    print("""
    ГРАНИЦЫ ЭТОЙ ТАБЛИЦЫ — читать до того, как на неё опереться:

      1. Показывает только имена, КОТОРЫХ В БАЗЕ НЕТ. Файл, который в базе есть, а в репах
         разошёлся, сюда не попадёт — это отдельный вопрос, его считает drift_versions.py.
      2. Сверка по ИМЕНИ. Переименование прячет файл: `CHANGELOG.md` ≠ `changelog.md`,
         а перенумерация при синтезе (`34-…` → `54-…`) делает старую копию «новым» именем.
         Оба случая тут видны как кандидаты, хотя это протечка базы (PIT-090).
      3. Плоские legacy-копии базы считает кандидатами. Полную картину по ним даёт
         legacy_delta.py — запускать его ПЕРЕД разбором этой таблицы.""")

# 🔴 ГВАРД ДОБАВЛЕН 04.09.2026. Тело лежало на верхнем уровне: импорт ради
# одной функции запускал всю программу. У `scan_lessons.py` это перезаписало
# артефакт при попытке прочитать код — чтение изменило состояние.
# Правило и проверка — `00-infrastructure/102-debugging-discipline.md` §3а.
if __name__ == "__main__":
    _main_body()
