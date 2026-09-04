#!/usr/bin/env python3
"""runtime_writes.py — какие файлы раздаваемого набора система пишет о СВОЕЙ РАБОТЕ.

🔴 ПОВОД — `ADR-007` закрыл один экземпляр класса вместо класса. 03.09.2026
журнал прогона `auto.log` был исключён из отпечатка канона: он лежит в
раздаваемом ките, и каждая строка о закрытом батче делала все 63 копии
«разошедшимися». Исключение записали **списком из одного пути**.

Через двадцать минут владелец запустил `/machine`, и стало видно, что список
неполон. Перепись по коду нашла **девять** мест записи, объявлен был **один**:

    06-autonomous-mode-kit/runs/auto.log              auto_log.py
    06-autonomous-mode-kit/limits.json                limits_watch.py
    12-workstation-kit/observations/measurements.csv  machine_probe.py
    12-workstation-kit/snapshots/*.json               inventory.py
    reports/releases/LEDGER.tsv                       pack_release.py
    reports/durations.tsv                             timing.py
    reports/infra-liveness.md                         sync_base_local + owner_blockers
    reports/adr/README.md, incidents/PITFALLS.md      capture.py      ← канон
    README.md, repos-map.md                           capture, retire_repo ← канон

🔴 **Два последних — не исключения, а разобранные случаи.** Инструмент туда
пишет, но это содержание канона, и копия обязана его видеть; см. пометку
`канон:` ниже. Различие найдено самой переписью: она сообщает о факте записи,
а журнал это или содержание — **суждение вахты**, и оно записывается строкой.

> `PIT-097` требует **свойство, а не список**, и в `sync_base_local.py` это
> прямо написано — рядом со списком из одного элемента. Правило было записано
> и не исполнялось: список короче признака ровно до того дня, когда он врёт.

ЧТО ЗДЕСЬ ВМЕСТО СПИСКА. Признак: **файл объявлен тем каталогом, чей инструмент
его пишет** — строкой в `<каталог>/.runtime-writes`. Объявление лежит рядом
с писателем, а не в раздатчике: заводя новый журнал, правишь тот же каталог,
в котором его заводишь. Список в раздатчике требовал бы вспомнить про раздатчик —
а её-то и не вспоминают (`PIT-G`, 16 повторов).

ФОРМАТ `.runtime-writes` — по строке на путь, относительно каталога с файлом,
`*` и `?` допускаются, `#` начинает комментарий:

    # что пишет machine_probe.py при каждом запуске
    observations/measurements.csv
    snapshots/*.json

    # 🔴 инструмент сюда пишет, но это СОДЕРЖАНИЕ, а не журнал:
    канон: adr/README.md

**Две разные вещи, и путать их нельзя.** Обычная строка — «исключить из
отпечатка»; строка `канон:` — «здесь тоже пишет инструмент, но это канон,
и копия обязана это видеть». Вторая ничего не исключает: она гасит перепись,
подтверждая, что случай разобран, а не пропущен.

Различие не формальное. `capture.py` дописывает строку в реестр ADR и в реестр
классов `incidents/PITFALLS.md` — по букве это «инструмент пишет в раздаваемое»,
по существу это правка канона, которая обязана доехать до наследников. Исключи
их из отпечатка — и правка реестра перестанет доезжать молча.

ПОЧЕМУ ЭТИ ФАЙЛЫ ВООБЩЕ ИСКЛЮЧАЮТСЯ. Отпечаток отвечает на вопрос «то ли
содержимое у копии». Журнал прогона базы, доехавший до наследника, копии
**не принадлежит** и сравнивать его не с чем: расхождение здесь ничего
не значит, а тревогу поднимает. Хуже: отпечаток становится нестабильным
по построению — посчитали, раздали, инструмент дописал строку, и следующая
же проверка объявляет расхождение.

🔴 ЧЕГО НЕ РЕШАЕТ (`71` §7г-бис):
  · **не мешает файлу раздаваться.** Журнал по-прежнему копируется наследникам,
    которым не принадлежит. Это долг `ADR-007` §6, снимается переносом
    журналов за пределы раздаваемого, а не исключением из отпечатка;
  · **не ловит путь, собранный из переменных или пришедший аргументом.**
    `scan_writers()` разбирает литералы — см. его докстроку;
  · **не судит о содержании.** Объявить можно что угодно, включая канон;
    защита от этого — ревью, а не разбор.
"""
from __future__ import annotations

import fnmatch
import re
import sys
from pathlib import Path

DECL_NAME = ".runtime-writes"


def declared(base: Path, within: tuple[str, ...] | None = None,
             include_canon: bool = False) -> set[str]:
    """Объявленные пути, относительно корня базы. Шаблоны сохраняются как есть.

    `within` — имена верхнего уровня, внутри которых искать объявления
    (обычно раздаваемый набор). None — искать по всей базе.

    🔴 `include_canon` РАЗДЕЛЯЕТ ДВА ВОПРОСА, и по умолчанию он выключен:
      · False (отпечаток) — только то, что исключается: журналы и замеры;
      · True (перепись)   — плюс помеченное `канон:`, то есть разобранное
        и оставленное в отпечатке намеренно.
    Умолчание выбрано так, что ошибка вызова **не исключает лишнего**:
    забыть `include_canon` значит получить лишнюю строку в переписи,
    а не молча выкинуть канон из сверки.
    """
    roots = [base / n for n in within] if within is not None else [base]
    # 🔴 Плюс объявление в КОРНЕ базы. Раздаваемый набор — это каталоги-киты
    # И ОТДЕЛЬНЫЕ ФАЙЛЫ (`README.md`, `repos-map.md`); файл объявления рядом
    # с собой нести не может, поэтому у корневых файлов оно одно на всех.
    # Без этого `capture.py` и `retire_repo.py`, пишущие в корневые файлы,
    # оставались бы в переписи вечно — а вечная строка в переписи учит
    # не читать перепись.
    if within is not None:
        roots.append(base)
    out: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        decls = [root / DECL_NAME] if root.is_file() else list(root.rglob(DECL_NAME))
        for decl in decls:
            if not decl.is_file():
                continue
            rel_dir = decl.parent.relative_to(base)
            for line in decl.read_text(encoding="utf-8").splitlines():
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                if line.startswith("канон:"):
                    if not include_canon:
                        continue
                    line = line[len("канон:"):].strip()
                    if not line:
                        continue
                out.add(str(rel_dir / line) if str(rel_dir) != "." else line)
    return out


def is_declared(rel: Path | str, patterns: set[str]) -> bool:
    """Совпадает ли путь с объявлением. Шаблон — `fnmatch`, не регулярка.

    🔴 Сравнение по СТРОКЕ пути, а не по частям: `snapshots/*.json` обязан
    ловить `12-workstation-kit/snapshots/2026-09-03.json` и не ловить
    `12-workstation-kit/snapshots/старое/x.json` — `fnmatch` со `*`,
    не пересекающим разделитель, этого не даёт, поэтому проверяется
    и точное равенство, и шаблон по полному пути.
    """
    s = str(rel)
    for pat in patterns:
        if s == pat or fnmatch.fnmatchcase(s, pat):
            return True
    return False


# --- перепись по коду ---------------------------------------------------------

# `X = <якорь> / "литерал" / "литерал"` — путь, собранный из литералов.
# 🔴 Имя переменной — ЛЮБОЕ, не только ПРОПИСНОЕ. Первая редакция брала
# `[A-Z_][A-Z0-9_]*` (константы), и перепись не увидела `pack_release.py`,
# который пишет реестр выпусков в локальную `ledger`. Ограничение было
# незаписанным потолком: докстрока обещала «литеральные пути», а на деле
# ловились литеральные пути В КОНСТАНТАХ. Поймано снятием объявления.
_ASSIGN = re.compile(
    r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$', re.M)
# Запись: `X.open("a"`, `X.open("w"`, `X.write_text(`, `open(X, "a"`,
# `(X / …).write_text(`, `with X.open(`.
_WRITE = re.compile(
    r'\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:\.open\(\s*["\'][aw]["\']'
    r'|\.write_text\('
    r'|\s*/\s*[^)]*\)\s*\.write_text\()'
    r'|open\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*["\'][aw]["\']')


def _anchor(expr: str, script: Path, base: Path) -> Path | None:
    """Куда указывает начало выражения. None — начало не распознано."""
    if "Path(__file__)" in expr:
        # 🔴 СЧЁТ ОТ ФАЙЛА, А НЕ ОТ ЕГО КАТАЛОГА. Прежняя редакция начинала
        # с `script.parent` — то есть первый `.parent` в выражении съедался
        # молча, — и потом применяла ВСЕ `.parent` ещё раз. Якорь выходил
        # на уровень выше настоящего.
        #
        # Замер 04.09.2026: `OUT = Path(__file__).resolve().parent / "scan.csv"`
        # в `05-infra-synthesis-lab/tools/` давал цель
        # `05-infra-synthesis-lab/scan.csv`. Отказ обманчив: проверка краснеет
        # ПРАВИЛЬНО (объявление действительно нужно), но требует объявить путь,
        # которого нет. Объявишь по её словам — она замолчит, а настоящий файл
        # так и останется необъявленным.
        p = script.resolve()
        for _ in range(expr.count(".parent")):
            p = p.parent
        return p
    if re.match(r'^\s*(BASE_REPO|REPO)\b', expr):
        return base
    return None           # прочее разрешается вторым проходом по известным


def scan_writers(base: Path, within: tuple[str, ...]) -> list[tuple[Path, str]]:
    """Найти файлы раздаваемого набора, в которые пишут инструменты базы.

    Возвращает пары (путь относительно базы, кто пишет).

    🔴 ПОТОЛОК, названный явно (`71` §7г-бис). Разбираются **литеральные**
    пути: `X = Path(__file__).resolve().parent.parent / "runs" / "auto.log"`
    и `X = BASE_REPO / "reports" / "durations.tsv"`. НЕ разбираются:
      · путь, пришедший аргументом (`Path(sys.argv[1])`) — таких в наборе
        два (`scan_lessons.py`, `tg_export_to_md.py`), и они пишут туда,
        куда скажут, то есть вне набора по умолчанию;
      · путь, собранный из переменной в другом файле;
      · запись из shell — она проверена вручную 03.09.2026 и вся идёт
        в `/tmp` и `$HOME`, но автоматически здесь не ловится.
    Поэтому перепись — **помощник ревью, а не доказательство полноты**.
    """
    # 🔴 КОРЕНЬ СВОДИТСЯ, ИНАЧЕ ВСЕ НАХОДКИ МОЛЧА ПРОПАДАЮТ. Цель считается
    # от `Path(__file__).resolve()`, то есть уже сведена; если корень пришёл
    # через симлинк, `relative_to` кидает ValueError, и `_scan_one` честно
    # отвечает «пишет вне базы — не наше дело». На этой машине риск живой:
    # `~/Documents/base-repo` — симлинк на `система_репозиториев/base-repo`.
    # Найдено 04.09.2026 канарейкой на адрес, где `/var` → `/private/var`.
    base = base.resolve()
    found: list[tuple[Path, str]] = []
    for name in within:
        root = base / name
        if not root.is_dir():
            continue
        for script in sorted(root.rglob("*.py")):
            if "__pycache__" in script.parts:
                continue
            found.extend(_scan_one(script, base, within))
    for script in sorted((base / "scripts").glob("*.py")):
        found.extend(_scan_one(script, base, within))
    # дедуп с сохранением порядка
    seen, out = set(), []
    for rel, who in found:
        if str(rel) not in seen:
            seen.add(str(rel))
            out.append((rel, who))
    return out


def _scan_one(script: Path, base: Path, within: tuple[str, ...]) -> list[tuple[Path, str]]:
    try:
        text = script.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    # 1. собрать литеральные пути переменных
    paths: dict[str, Path] = {}
    for _ in range(2):                      # второй проход — для цепочек через уже известные
        for m in _ASSIGN.finditer(text):
            name, expr = m.group(1), m.group(2)
            if "/" not in expr or name in paths:
                continue
            anchor = _anchor(expr, script, base)
            if anchor is None:
                head = re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\b', expr)
                if not (head and head.group(1) in paths):
                    continue
                anchor = paths[head.group(1)]
                for _p in range(expr.split("/")[0].count(".parent")):
                    anchor = anchor.parent
            segs = re.findall(r'/\s*["\']([^"\']+)["\']', expr)
            if not segs:
                continue
            paths[name] = anchor.joinpath(*segs)

    # 2. найти записи в эти переменные
    out = []
    for m in _WRITE.finditer(text):
        var = m.group(1) or m.group(2)
        target = paths.get(var)
        if target is None:
            continue
        try:
            rel = target.relative_to(base)
        except ValueError:
            continue                        # пишет вне базы — не наше дело
        if rel.parts and rel.parts[0] in within:
            out.append((rel, script.relative_to(base).as_posix()))
    return out


def undeclared(base: Path, within: tuple[str, ...]) -> list[tuple[Path, str]]:
    """Что пишется в раздаваемое, но не объявлено. Пусто — признак исполняется."""
    pats = declared(base, within, include_canon=True)
    return [(rel, who) for rel, who in scan_writers(base, within)
            if not is_declared(rel, pats)]


def selftest(base: Path | None = None, within: tuple[str, ...] | None = None) -> bool:
    """Канарейка: строит СВОЮ опору и проверяет РАЗЛИЧЕНИЕ, а не исполнение.

    🔴 ПЕРВАЯ РЕДАКЦИЯ ОПИРАЛАСЬ НА ЖИВУЮ БАЗУ — и падала на свежей репе,
    у которой объявлений ещё нет. Поймано `test_repo_lifecycle.sh` в тот же
    час: конструктор реп гоняет гейт на только что созданной репе, и красная
    канарейка откатывала создание целиком.
    Урок ровно тот, ради которого канарейки и заводятся: **проверка, знающая
    про одну конкретную установку, проверяет установку, а не механизм.**
    Аргументы оставлены ради совместимости вызова и намеренно игнорируются.

    Четыре утверждения, каждое падает по своей причине:
      1. объявленный путь признаётся объявленным;
      2. необъявленный — не признаётся (иначе исключалось бы всё);
      3. шаблон ловит свой файл, включая ещё не существовавший при объявлении;
      4. шаблон НЕ ловит соседний каталог (иначе `*` съедал бы разделитель).
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        # `.resolve()` — на macOS `/var` это симлинк на `/private/var`
        root = Path(tmp).resolve()
        kit = root / "12-проба-кит"
        (kit / "snapshots").mkdir(parents=True)
        (kit / "observations").mkdir()
        (kit / DECL_NAME).write_text(
            "# проба\nobservations/measurements.csv\nsnapshots/*.json\n"
            "канон: README.md\n", encoding="utf-8")

        excl = declared(root, ("12-проба-кит",))
        both = declared(root, ("12-проба-кит",), include_canon=True)

        checks = [
            (is_declared("12-проба-кит/observations/measurements.csv", excl),
             "объявленный путь не признан объявленным"),
            (not is_declared("12-проба-кит/observations/чужой.csv", excl),
             "необъявленный путь признан объявленным"),
            (is_declared("12-проба-кит/snapshots/2099-01-01.json", excl),
             "шаблон не поймал файл, которого при объявлении не было"),
            (not is_declared("12-проба-кит/observations/2099-01-01.json", excl),
             "шаблон поймал соседний каталог — `*` съел разделитель"),
            (not is_declared("12-проба-кит/README.md", excl),
             "помеченное `канон:` попало в ИСКЛЮЧЕНИЯ — канон перестал бы доезжать"),
            (is_declared("12-проба-кит/README.md", both),
             "помеченное `канон:` не видно переписи — случай считался бы пропущенным"),
        ]

        # 🔴 «НАШЁЛ» И «НАШЁЛ ТАМ» — ДВА УТВЕРЖДЕНИЯ (`PIT-192`). Четыре
        # проверки выше судят различение, и ни одна не судит АДРЕС. Именно
        # адрес и был неверен: якорь `Path(__file__)` поднимался на уровень
        # выше настоящего, проверка краснела правильно и называла путь,
        # которого нет. Починка по её выводу заглушила бы её навсегда.
        tools = kit / "tools"
        tools.mkdir()
        (tools / "писака.py").write_text(
            'from pathlib import Path\n'
            'OUT = Path(__file__).resolve().parent / "снимок.csv"\n'
            'UP = Path(__file__).resolve().parent.parent / "наверху.csv"\n'
            'def go():\n'
            '    OUT.write_text("x")\n'
            '    UP.write_text("y")\n', encoding="utf-8")
        found = {rel.as_posix() for rel, _ in scan_writers(root, ("12-проба-кит",))}
        checks += [
            (f"12-проба-кит/tools/снимок.csv" in found,
             f"адрес записи назван неверно: ждал tools/снимок.csv, получил {found}"),
            (f"12-проба-кит/наверху.csv" in found,
             f"`.parent.parent` разобран неверно: {found}"),
        ]
        for ok, why in checks:
            if not ok:
                print(f"🔴 канарейка runtime-записей: {why}", file=sys.stderr)
                return False
    return True


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from sync_base_local import BASE_REPO, _distribute      # noqa: E402

    within = _distribute()
    if "--selftest" in sys.argv:
        ok = selftest(BASE_REPO, within)
        print("канарейка: " + ("🟢 зелёная" if ok else "🔴 красная"))
        return 0 if ok else 1

    pats = declared(BASE_REPO, within)
    print(f"объявлено путей: {len(pats)}")
    for p in sorted(pats):
        print(f"  · {p}")

    bad = undeclared(BASE_REPO, within)
    print(f"\nпишется в раздаваемое, но НЕ объявлено: {len(bad)}")
    for rel, who in bad:
        print(f"  🔴 {rel}  ← {who}")
    if bad:
        print("\n   Объявить строкой в <каталог>/.runtime-writes — или перенести")
        print("   файл за пределы раздаваемого набора, если он там не нужен.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
