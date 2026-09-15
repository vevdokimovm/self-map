#!/usr/bin/env python3
"""acceptance_audit.py — сходится ли записанная приёмка репы с диском СЕГОДНЯ.

🔴 ПОВОД — `ROADMAP` §P1.6, дословно: *«доверие к „репа закрыта“. Сейчас это
утверждение проверяется только чтением журнала, то есть не проверяется»*.

Приёмка (`PROCEDURE.md` §6) записывается строкой вида:

    self-map: всего 629 = база(v2.18.0) 77 + character-a-analysis 148 + С 371
                          + прочитано и решено 33

Строка — **утверждение о состоянии на день записи**. Диск с тех пор менялся:
файлы добавлялись, репа росла, база уезжала вперёд. Через месяц запись либо
подтверждается, либо нет — и узнать это можно только пересчётом.

## 🔴 Почему СКРИПТ, а не агент — отклонение от буквы ROADMAP

`ROADMAP` называет `acceptance-auditor` **агентом (sonnet)**. Здесь он сделан
скриптом, и вот основания:

| | агент | скрипт |
|---|---|---|
| цена вызова | **полный контекст**; замер 29.08: субагенты — 40 % расхода за день | ~2 с |
| повторяемость | недетерминирован | тот же вход → тот же выход |
| можно в гейт | нет | да |
| что делает | считает файлы, сравнивает числа | то же самое |

**Работа здесь механическая целиком:** посчитать файлы, сложить слагаемые,
сравнить. Суждения нет — а именно суждение оправдывает цену агента.
Отдать машине арифметику и заплатить за это контекстом значит выбрать
дорогую ошибку вместо дешёвой (`/auto` §1.4).

🔴 **Что теряется:** агент прочитал бы `decisions.md` целиком и заметил бы
странность, для которой нет правила («в записи упомянута репа, которой нет»).
Скрипт проверяет то, что ему сказали проверять. Это записано здесь, чтобы
следующая вахта знала цену выбора, а не переоткрывала его.

## Что проверяется

1. **Сумма сходится** — правая часть равна левой. Арифметика записи.
2. **«Всего файлов» совпадает с диском СЕГОДНЯ** — и если нет, показано,
   выросла репа или уменьшилась.
3. **Названные репы существуют** — слагаемое «`character-a-analysis` 148»
   ссылается на репу; исчезла — вычитание не воспроизводится.

🔴 ЧЕГО НЕ ПРОВЕРЯЕТ (`71` §7г-бис):
  · **правдивость слагаемых** — что «база 77» действительно 77 совпавших
    файлов. Это требует пересчёта sha256 против базы **той версии**, которая
    названа в скобках; старых версий базы на диске нет;
  · **что «прочитано и решено» действительно прочитано** — это работа вахты,
    её след в `decisions.md`, а не число;
  · **появились ли КОПИИ репы** — считается отдельным инструментом
    (`find_duplicates.py`), здесь не дублируется.

Расхождение «всего» — **не обязательно дефект**: репа могла законно вырасти
после закрытия. Инструмент показывает **факт расхождения и его знак**,
а решение — работа вахты.

ЗАПУСК
    acceptance_audit.py              все записи приёмки
    acceptance_audit.py --repo ИМЯ   одна репа
    acceptance_audit.py --selftest
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402

BASE_REPO, REPOS, FROM_KIT = resolve_roots(__file__)

# 🔴 СЧЁТ ВЕДЁТСЯ ТЕМ ЖЕ ПРАВИЛОМ, ЧТО ВЕЛА ПРИЁМКА (`PROCEDURE.md` §1.1):
#
#     find . -type f -not -path "*/.git/*" -not -path "./_base/*" | wc -l
#
# То есть исключаются РОВНО ДВА пути: `.git` и `_base`. Больше ничего —
# ни `node_modules`, ни `__pycache__`, ни `.DS_Store`.
#
# Первая редакция этого скрипта взяла привычный набор `JUNK_DIRS` остальных
# инструментов системы — и **все девятнадцать реп показались выросшими**:
# `control-panel` 36 → 697, `self-map` 629 → 6773. Роста не было: сравнивались
# два разных определения «файла в репе», и разница определений выглядела
# как изменение состояния.
#
# 🔴 Урок общий: сравнивать можно только величины, посчитанные ОДНИМ правилом.
# Инструмент проверки обязан наследовать счёт у проверяемого, а не приносить
# свой — иначе он измеряет себя.
EXCLUDE_PARTS = (".git", "_base")
JUNK_NAMES: set[str] = set()      # приёмка `.DS_Store` не исключала

# `<репа>: всего N = слагаемое M + слагаемое K + …`
LINE = re.compile(r"^([a-z0-9][a-z0-9._-]*): всего (\d+) = (.+)$", re.M)
# Слагаемое: имя (возможно со скобкой версии) и число.
TERM = re.compile(r"([^+]*?)\s*(\d+)\s*(?:\+|$)")


def count_files(repo: Path) -> int:
    """Файлов в репе — тем же счётом, что вела приёмка (`PROCEDURE` §1.1).

    🔴 `_base/` НЕ ВХОДИТ — так считала приёмка (§1.1 исключает `./_base/*`).
    Проверено эмпирически: `control-panel` записан как 36, а с `_base` там
    только кита 634 файла. Гипотеза «база вычитается слагаемым, значит входит
    в всего» была бы правдоподобной и неверной — её опроверг счёт, а не чтение.
    """
    n = 0
    for p in repo.rglob("*"):
        # 🔴 `is_symlink()` ПЕРВЫМ: `find -type f` символьные ссылки НЕ считает,
        # а `Path.is_file()` идёт по ссылке и возвращает True. Разница нашлась
        # сверкой с точной командой §1.1 на `control-panel`: 4352 против 4349 —
        # ровно три ссылки в `.venv/bin` (`python`, `python3`, `python3.13`).
        #
        # Три файла из четырёх тысяч — но проверка, которая «почти совпадает»,
        # не проверка: на репе поменьше эти же три дали бы ложное расхождение.
        if p.is_symlink() or not p.is_file():
            continue
        if any(part in EXCLUDE_PARTS for part in p.relative_to(repo).parts):
            continue
        if p.name in JUNK_NAMES:
            continue
        n += 1
    return n


# Каталоги, порождаемые сборкой: их появление — не изменение содержания репы.
GENERATED = {"node_modules", ".venv", "venv", "dist", "build", ".next",
             "__pycache__", ".pytest_cache", "target", ".cache"}


def growth_breakdown(repo: Path, top: int = 3) -> str:
    """Где именно прибавилось: топ каталогов верхнего уровня, с пометкой сборки.

    Каталог верхнего уровня, а не полный путь: приёмка принимала решения
    по каталогам (`PROCEDURE` §2), и разбор в тех же единицах читается,
    а разбор по всем вложенным — нет.
    """
    counts: dict[str, int] = {}
    gen = 0
    for p in repo.rglob("*"):
        if p.is_symlink() or not p.is_file():
            continue
        rel = p.relative_to(repo)
        if any(part in EXCLUDE_PARTS for part in rel.parts):
            continue
        head = rel.parts[0] if len(rel.parts) > 1 else "(корень)"
        counts[head] = counts.get(head, 0) + 1
        if any(part in GENERATED for part in rel.parts):
            gen += 1
    top_dirs = sorted(counts.items(), key=lambda kv: -kv[1])[:top]
    parts = [f"{d} {n}" + (" ⚙" if d in GENERATED else "") for d, n in top_dirs]
    tail = f" · из них порождено сборкой: {gen} ⚙" if gen else " · сборочного нет"
    return ", ".join(parts) + tail


def parse_line(line: str) -> tuple[str, int, list[tuple[str, int]]] | None:
    """Разобрать строку приёмки. None — строка не является записью приёмки."""
    m = LINE.match(line.strip())
    if not m:
        return None
    repo, total, rest = m.group(1), int(m.group(2)), m.group(3)
    terms = [(name.strip(" +"), int(num)) for name, num in TERM.findall(rest)]
    return repo, total, terms


def audit_one(repo_name: str, total: int, terms: list[tuple[str, int]]) -> list[str]:
    """Проверки по одной записи. Пустой список — запись подтверждается."""
    out = []
    s = sum(n for _, n in terms)
    if s != total:
        out.append(f"арифметика записи не сходится: {total} ≠ {s} "
                   f"({' + '.join(str(n) for _, n in terms)})")

    repo = REPOS / repo_name
    if not repo.is_dir():
        out.append("репы нет на диске — запись не воспроизводится")
        return out

    now = count_files(repo)
    if now != total:
        знак = "выросла" if now > total else "уменьшилась"
        out.append(f"«всего» разошлось с диском: было {total}, сейчас {now} "
                   f"({знак} на {abs(now - total)})")
        # 🔴 РОСТ БЫВАЕТ РАЗНЫЙ, и различать его — половина пользы инструмента.
        # `node_modules` и `.venv` не «содержание, которое не прочитали»:
        # они порождаются сборкой и не были предметом приёмки вовсе.
        # Без этой разбивки вывод «все 19 реп разошлись» верен и бесполезен:
        # он не отличает репу, куда владелец добавил 200 документов, от репы,
        # где просто встал `npm install`.
        if now > total:
            out.append("   рост по каталогам: " + growth_breakdown(repo))

    # Слагаемое, названное именем репы, обязано ссылаться на существующую репу:
    # иначе вычитание «совпало с закрытой репой» не проверить уже никогда.
    for name, _ in terms:
        base = re.sub(r"\(.*?\)", "", name).strip()
        if re.fullmatch(r"[a-z0-9][a-z0-9._-]*", base) and base not in {
                "база", "С", "М", "прочитано", "решено"}:
            if not (REPOS / base).is_dir():
                out.append(f"слагаемое ссылается на репу «{base}», которой нет")
    return out


def find_records(root: Path) -> list[tuple[Path, int, str]]:
    """Все строки приёмки во всех журналах прогонов: (файл, номер строки, текст)."""
    out = []
    runs = root / "05-infra-synthesis-lab" / "runs"
    if not runs.is_dir():
        return out
    for dec in sorted(runs.rglob("decisions.md")):
        for i, line in enumerate(dec.read_text(encoding="utf-8",
                                               errors="replace").splitlines(), 1):
            if LINE.match(line.strip()):
                out.append((dec, i, line.strip()))
    return out


def selftest() -> bool:
    """Канарейка: разбор и оба исхода проверки. Проверяется РАЗЛИЧЕНИЕ.

    🔴 Проверка, которую нельзя провалить, — не проверка (`71` §7в). Поэтому
    сходящаяся запись обязана давать пусто, а несходящаяся — находку.
    """
    ok = True

    def check(cond: bool, why: str) -> None:
        nonlocal ok
        if not cond:
            print(f"🔴 канарейка: {why}", file=sys.stderr)
            ok = False

    p = parse_line("self-map: всего 629 = база(v2.18.0) 77 + "
                   "character-a-analysis 148 + С 371 + прочитано и решено 33")
    check(p is not None, "строка приёмки не разобрана")
    if p:
        repo, total, terms = p
        check(repo == "self-map", f"имя репы: {repo}")
        check(total == 629, f"всего: {total}")
        check(sum(n for _, n in terms) == 629,
              f"слагаемые дают {sum(n for _, n in terms)}, а не 629")

    check(parse_line("просто текст про всего 5 файлов") is None,
          "обычный текст принят за запись приёмки")

    # Обратное направление: несходящаяся арифметика обязана ловиться.
    bad = audit_one("несуществующая-репа-для-канарейки", 100,
                    [("база", 40), ("С", 30)])
    check(any("арифметика" in b for b in bad), "несходящаяся сумма не поймана")
    check(any("нет на диске" in b for b in bad), "отсутствие репы не поймано")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="аудит записанных приёмок")
    ap.add_argument("--repo", help="проверить одну репу")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        ok = selftest()
        print("канарейка аудита приёмки: " + ("🟢 зелёная" if ok else "🔴 красная"))
        return 0 if ok else 1

    records = find_records(BASE_REPO)
    if a.repo:
        records = [r for r in records if r[2].startswith(f"{a.repo}:")]
        if not records:
            print(f"записи приёмки для «{a.repo}» нет")
            return 2

    print(f"записей приёмки: {len(records)}\n")
    bad_total = 0
    for dec, ln, text in records:
        parsed = parse_line(text)
        if not parsed:
            continue
        repo, total, terms = parsed
        problems = audit_one(repo, total, terms)
        mark = "🟢" if not problems else "🔴"
        print(f"{mark} {repo}")
        for pr in problems:
            print(f"     · {pr}")
            bad_total += 1
        if problems:
            print(f"     запись: {dec.relative_to(BASE_REPO)}:{ln}")

    print(f"\nрасхождений: {bad_total}")
    if bad_total:
        print("\n🔴 Расхождение «всего» — НЕ обязательно дефект: репа могла")
        print("   законно вырасти после закрытия. Инструмент показывает факт")
        print("   и знак; решение — работа вахты (`PROCEDURE.md` §6).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
