#!/usr/bin/env python3
"""journal_audit.py — исполнитель стандарта журналов (`00-infrastructure/94`).

🔴 ЗАКАЗ ВЛАДЕЛЬЦА 03.09.2026: механизм хранения истории изменений «формально
официально не введён как стандарт», хотя используется везде. Замер подтвердил:
**16 журналов, пять несовместимых форматов**, общего ответа нет ни на один
вопрос — что записано, кто пишет, можно ли править.

ЧТО ПРОВЕРЯЕТСЯ — три разных утверждения, не одно:

  1. МОНОТОННОСТЬ журнала событий: время не убывает сверху вниз.
     Единственная проверка целостности, не требующая хранить состояние:
     ни эталона, ни снимка, ни счётчика строк. Вставка в середину,
     сортировка, склейка двух журналов — нарушают её немедленно.

  2. СВЕЖЕСТЬ журнала изменений: версия верхней секции равна `VERSION`
     сущности. Отставший журнал означает, что версия поднята мимо ритуала.

  3. НАЛИЧИЕ: сущность с собственной версией обязана иметь журнал.

🔴 ЧЕГО НЕ ЛОВИТ (`71` §7г-бис) — названо здесь, а не оставлено читателю:
  · **удаление строки**: остаток остаётся монотонным. Ловится только ревью;
  · **правку значения** при верной дате — подделка показания невидима;
  · **дописывание выдуманного события** в конец: монотонность сохраняется;
  · **содержательность**: строка-заглушка пройдёт.
Проверяется ПЕРЕСТАНОВКА, а не ПРАВДИВОСТЬ. Правдивость обеспечивается тем,
что журнал событий пишет инструмент, а не человек (`ADR-007`).

ЖУРНАЛЫ НЕ ПЕРЕЧИСЛЯЮТСЯ СПИСКОМ. Журналы событий берутся из объявлений
`.runtime-writes` — того же механизма, что исключает их из отпечатка канона.
Второй список разошёлся бы с первым на первой же правке (`PIT-178`).

ЗАПУСК
    journal_audit.py              перепись и проверки
    journal_audit.py --selftest   канарейка
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runtime_writes  # noqa: E402
from _roots import resolve_roots  # noqa: E402

BASE_REPO, REPOS, FROM_KIT = resolve_roots(__file__)

# Время первым полем строки. Дата без времени считается полуночью:
# в `LEDGER.tsv` время не пишется, и требовать его задним числом значило бы
# объявить нарушением формат, который был законным.
STAMP = re.compile(r'^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}:\d{2}))?')

# Секция журнала изменений — тот же разбор, что у `bump_repo`/`revision_check`.
SECTION = re.compile(r'^##\s+\[(\d+\.\d+\.\d+)\]', re.M)

# Расширения, в которых журнал событий строчный. `.md` сюда не входит:
# `HISTORY.md` и `decisions.md` — свободный текст с датами, монотонность
# в них не обещана и требовать её значило бы выдумать правило.
EVENT_SUFFIXES = {".log", ".tsv", ".csv"}


# Каталоги вне содержания базы (копии кита, кэш) и данные, где строчного
# журнала быть не обязано.
SKIP_DIRS = {"_base", "__pycache__", ".git", ".pytest_cache", "node_modules"}


def _distribute() -> tuple[str, ...]:
    """Раздаваемый набор — спрашивается у раздачи, не дублируется здесь."""
    from sync_base_local import _distribute as d
    return d()


def declared_journals() -> list[Path]:
    """Журналы событий, ОБЪЯВЛЕННЫЕ в `.runtime-writes`.

    Шаблоны (`snapshots/*.json`) раскрываются по диску: объявление описывает
    класс файлов, а проверять надо существующие.
    """
    out: list[Path] = []
    for pat in sorted(runtime_writes.declared(BASE_REPO, _distribute())):
        found = sorted(BASE_REPO.glob(pat)) if any(c in pat for c in "*?") \
            else [BASE_REPO / pat]
        out += [p for p in found if p.is_file() and p.suffix in EVENT_SUFFIXES]
    return out


def found_journals() -> list[Path]:
    """Всё, что ПОХОЖЕ на журнал событий, по диску.

    🔴 ЗАЧЕМ ОТДЕЛЬНО ОТ ОБЪЯВЛЕННЫХ. Проверять только объявленное значит
    не видеть неучтённое — ровно `PIT-176`: каталог без разметки не стал
    красным, он перестал существовать для проверок. Журнал, о котором никто
    не объявил, точно так же не проверяется на монотонность и молча теряет
    порядок.

    Признак «похоже на журнал»: строчный суффикс И первая строка с данными
    начинается с даты ISO. Второе условие отсекает конфиги и выгрузки
    (`scan.csv` — перепись файлов, а не журнал: дат в начале строк нет).
    """
    out = []
    for p in BASE_REPO.rglob("*"):
        if p.suffix not in EVENT_SUFFIXES or not p.is_file():
            continue
        if any(s in p.parts for s in SKIP_DIRS):
            continue
        try:
            lines = [l for l in p.read_text(encoding="utf-8", errors="replace")
                     .splitlines() if l.strip()][:3]
        except OSError:
            continue
        if any(STAMP.match(l.strip()) for l in lines):
            out.append(p)
    return sorted(out)


def event_journals() -> list[Path]:
    """Объединение: объявленные плюс найденные на диске."""
    seen, out = set(), []
    for p in declared_journals() + found_journals():
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def monotonic(path: Path) -> tuple[int, list[str]]:
    """(строк с датой, нарушения монотонности). Пустой список — журнал цел."""
    stamps: list[tuple[int, dt.datetime]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return 0, [f"не читается: {exc}"]
    for i, line in enumerate(lines, 1):
        m = STAMP.match(line.strip())
        if not m:
            continue
        stamp = m.group(1) + "T" + (m.group(2) or "00:00:00")
        try:
            stamps.append((i, dt.datetime.fromisoformat(stamp)))
        except ValueError:
            continue
    bad = [f"строка {b[0]} старше строки {a[0]} ({b[1]:%d.%m %H:%M} < {a[1]:%d.%m %H:%M})"
           for a, b in zip(stamps, stamps[1:]) if b[1] < a[1]]
    return len(stamps), bad


def change_journal_fresh(entity_dir: Path, journal: Path) -> str | None:
    """Отстал ли журнал изменений от версии сущности. None — свеж."""
    vf = entity_dir / "VERSION"
    if not (vf.is_file() and journal.is_file()):
        return None
    version = vf.read_text(encoding="utf-8").strip()
    head = journal.read_text(encoding="utf-8", errors="replace")[:4000]
    m = SECTION.search(head)
    if not m:
        return f"{journal.name}: верхней секции [X.Y.Z] нет вовсе"
    if m.group(1) != version:
        return f"{journal.name}: верхняя секция [{m.group(1)}], а VERSION {version}"
    return None


def audit() -> list[str]:
    """Все три проверки. Пустой список — стандарт исполняется."""
    problems: list[str] = []

    for j in event_journals():
        n, bad = monotonic(j)
        rel = j.relative_to(BASE_REPO)
        if bad:
            problems.append(f"{rel}: 🔴 порядок нарушен — {bad[0]}"
                            + (f" (и ещё {len(bad) - 1})" if len(bad) > 1 else ""))

    for jr in (BASE_REPO / "CHANGELOG.md",):
        bad = change_journal_fresh(BASE_REPO, jr)
        if bad:
            problems.append(bad)

    # 🔴 Журнал, найденный на диске, но не объявленный. Не нарушение порядка —
    # нарушение видимости: он не попадёт ни в исключения отпечатка, ни в этот
    # аудит на следующем прогоне, если признак «похоже на журнал» изменится.
    declared = {p.resolve() for p in declared_journals()}
    for p in found_journals():
        if p.resolve() not in declared:
            problems.append(f"{p.relative_to(BASE_REPO)}: журнал не объявлен "
                            f"в `.runtime-writes` — невидим для отпечатка и учёта")

    return problems


def selftest() -> bool:
    """Канарейка: проверяется РАЗЛИЧЕНИЕ обоих исходов на подсаженном дефекте.

    🔴 Проверка, которую нельзя провалить, — не проверка (`71` §7в). Поэтому
    сначала подтверждается, что целый журнал признан целым, и только потом —
    что переставленные строки ловятся. Одного второго мало: проверка,
    объявляющая нарушением всё, тоже «ловит».
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        good = Path(tmp) / "ok.log"
        good.write_text("2026-09-01T10:00:00\tA\n2026-09-02T10:00:00\tB\n"
                        "2026-09-03T10:00:00\tC\n", encoding="utf-8")
        n, bad = monotonic(good)
        if n != 3 or bad:
            print("🔴 канарейка: целый журнал объявлен нарушенным", file=sys.stderr)
            return False

        broken = Path(tmp) / "bad.log"
        broken.write_text("2026-09-03T10:00:00\tC\n2026-09-01T10:00:00\tA\n",
                          encoding="utf-8")
        if not monotonic(broken)[1]:
            print("🔴 канарейка: перестановка НЕ поймана", file=sys.stderr)
            return False

        # дата без времени законна — иначе `LEDGER.tsv` стал бы нарушителем
        dated = Path(tmp) / "dates.tsv"
        dated.write_text("2026-09-01\tx\n2026-09-02\ty\n", encoding="utf-8")
        if monotonic(dated) != (2, []):
            print("🔴 канарейка: дата без времени не принята", file=sys.stderr)
            return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="аудит журналов системы")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        ok = selftest()
        print("канарейка: " + ("🟢 зелёная" if ok else "🔴 красная"))
        return 0 if ok else 1

    js = event_journals()
    print(f"журналов событий (по объявлениям `.runtime-writes`): {len(js)}")
    for j in js:
        n, bad = monotonic(j)
        mark = "🔴" if bad else "✓"
        print(f"  {mark} {j.relative_to(BASE_REPO)} — строк с датой {n}")

    problems = audit()
    print(f"\nнарушений: {len(problems)}")
    for p in problems:
        print(f"  🔴 {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
