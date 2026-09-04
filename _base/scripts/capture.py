#!/usr/bin/env python3
"""capture.py — заведение служебного файла одной командой.

ЗАЧЕМ. `20-knowledge-capture-protocol.md` §1 перечисляет восемь классов триггеров
(T1–T8), по каждому артефакт обязан появиться «сразу, не откладывая». §4 честно
признавался, что это «реализовано как **дисциплина вахты**»: фиксируй в момент,
веди §4 по ходу, не закрывай батч с неоформленным триггером.

Дисциплина — это намерение, а закон кампании (`05-infra-synthesis-lab/STANDARD.md`
§00 п.1) звучит иначе: **приёмка сильнее намерения**. Правила «читай всё» и
«записывай в момент» существовали ДО прогона и не исполнялись; заработали, когда
стали арифметикой, которая не сходится.

Почему намерение отказывало именно здесь — измеримо. Завести карточку значило
сделать руками пять шагов: найти свободный номер, написать каркас, дописать строку
в реестр, поставить перекрёстную ссылку в `WATCHLOG` §4, не промахнуться форматом.
Пять шагов на находку, которая «и так понятна», — и находка не записывается.
Это не лень, это цена. Скрипт убирает цену: один вызов вместо пяти шагов.

🔴 **Номер выделяет машина, и это не удобство, а починка дефекта.** 22.08.2026
`adr_003` и `adr_004` разошлись с реестром, и поймала это не проверка, а
**коллизия номера при заведении** — то есть случайность. Здесь номер берётся
максимумом по ВСЕМ источникам сразу (файлы каталога + все упоминания в тексте),
поэтому коллизия невозможна по построению.

🔴 **Реестр пишется той же операцией, что и карточка.** Правило из того же случая:
«список, который ведут руками, отстаёт всегда — вопрос только в том, ловится ли
отставание». Список, который не ведут руками, не отстаёт вовсе.

ЧЕГО СКРИПТ НЕ ДЕЛАЕТ — названо вслух, чтобы не считали его умнее, чем он есть
(`71` §7г-бис): он не решает, СТОИТ ли фиксировать. Порог «фиксировать / не
фиксировать» — §6 протокола, это суждение вахты. Скрипт снимает механику, а не
суждение.

ЗАПУСК:
    python3 scripts/capture.py pit "короткое имя находки"
    python3 scripts/capture.py syn "находка о методе сбора"
    python3 scripts/capture.py adr "принятое решение"
    python3 scripts/capture.py class PIT-G "случай одной строкой"

    --symptom / --root-cause / --rule   заполнить поля каркаса сразу
    --no-watchlog                       не ставить строку в WATCHLOG §4
    --dry                               показать план, ничего не писать
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

PIT_CARDS = REPO / "reports" / "pitfalls.md"
SYN_CARDS = REPO / "05-infra-synthesis-lab" / "PITFALLS.md"
ADR_DIR = REPO / "reports" / "adr"
ADR_REGISTRY = ADR_DIR / "README.md"
CLASS_BOARD = REPO / "reports" / "incidents" / "PITFALLS.md"
WATCHLOG = REPO / "WATCHLOG.md"

TODAY = dt.date.today().isoformat()
# 🔴 Время наравне с датой — заказ владельца 03.09.2026 21:29. За сутки
# заводится до десяти карточек; по одной дате их порядок не восстановить,
# а порядок находок и есть ход разбора (`00-infrastructure/94` §3).
STAMP = f"{TODAY} {dt.datetime.now():%H:%M}"


# --------------------------------------------------------------------------- #
# выделение номера
# --------------------------------------------------------------------------- #
def next_number(prefix: str, sources: list[Path], width: int = 3) -> int:
    """Максимум по ВСЕМ источникам + 1.

    Считаются и карточки, и любые упоминания в тексте: карточка может быть
    заведена, а в реестр не попасть (ровно случай adr_003/adr_004), и наоборот —
    номер может быть занят ссылкой раньше, чем создан файл. Берём максимум по
    объединению, иначе выделенный номер окажется уже занятым.
    """
    pat = re.compile(rf"{prefix}-(\d{{{width}}})\b")
    best = 0
    for src in sources:
        if src.is_dir():
            for p in src.rglob("*.md"):
                best = max([best] + [int(m) for m in pat.findall(p.name)])
                try:
                    best = max([best] + [int(m) for m in pat.findall(p.read_text(encoding="utf-8", errors="ignore"))])
                except OSError:
                    pass
        elif src.is_file():
            best = max([best] + [int(m) for m in pat.findall(src.name)])
            try:
                best = max([best] + [int(m) for m in pat.findall(src.read_text(encoding="utf-8", errors="ignore"))])
            except OSError:
                pass
    return best + 1


def adr_next_number() -> int:
    """ADR нумеруются `adr_NNN_*.md`, а ссылаются на них как `ADR-NNN`.

    Две записи одного номера — два независимых источника отставания, поэтому
    сканируются обе формы.
    """
    best = 0
    for p in ADR_DIR.glob("adr_*.md"):
        m = re.match(r"adr_(\d+)_", p.name)
        if m:
            best = max(best, int(m.group(1)))
    if ADR_REGISTRY.is_file():
        txt = ADR_REGISTRY.read_text(encoding="utf-8", errors="ignore")
        best = max([best] + [int(m) for m in re.findall(r"adr_(\d{3})_", txt)])
        best = max([best] + [int(m) for m in re.findall(r"ADR-(\d{3})\b", txt)])
    return best + 1


def slugify(title: str) -> str:
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    out = "".join(translit.get(ch, translit.get(ch.lower(), ch)) if ch.lower() in translit else ch
                  for ch in title.lower())
    out = re.sub(r"[^a-z0-9]+", "_", out).strip("_")
    return out[:48] or "record"


def already_captured(path: Path, title: str) -> str | None:
    """Идемпотентность: тот же заголовок сегодня — не заводим второй раз."""
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("#") and title.strip().lower() in line.lower():
            return line.strip()
    return None


# --------------------------------------------------------------------------- #
# запись
# --------------------------------------------------------------------------- #
def append(path: Path, text: str, dry: bool) -> None:
    if dry:
        print(f"  [dry] дописал бы в {path.relative_to(REPO)}:\n{text}")
        return
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)


def sync_prose_count(prefix: str, cards: Path, dry: bool) -> None:
    """Число карточек в прозе README — пересчитать той же операцией.

    🔴 ЗАЧЕМ ЭТО ЗДЕСЬ, А НЕ «ПОТОМ РУКАМИ». `check_prose_counts` сверяет
    «карточек PIT: в прозе N, на диске M». Каждая заведённая карточка сдвигает M,
    и без пересчёта **любой** запуск генератора оставляет гейт красным.

    Красный гейт после штатного действия — это не строгость, а трение: ровно та
    цена, ради снятия которой скрипт и написан. Инструмент, который чинит одну
    ручную операцию и заводит вторую, не окупается.

    Правило общее (`72` §4б-бис): у копии числа обязан быть механизм обновления,
    и владеет им тот, кто число меняет.
    """
    readme = REPO / "README.md"
    if not readme.is_file() or not cards.is_file():
        return
    level = r"###" if prefix == "PIT" else r"##"
    total = len(re.findall(rf"^{level}\s+{prefix}-\d+", cards.read_text(encoding="utf-8"), re.M))
    txt = readme.read_text(encoding="utf-8")
    pat = re.compile(rf"\*\*(\d+) карточ\w+ `{prefix}-NNN`\*\*")
    m = pat.search(txt)
    if not m:
        return
    if int(m.group(1)) == total:
        return
    if dry:
        print(f"  [dry] README: карточек {prefix} {m.group(1)} → {total}")
        return
    readme.write_text(pat.sub(lambda _: f"**{total} карточек `{prefix}-NNN`**", txt, count=1),
                      encoding="utf-8")
    print(f"✓ README: карточек {prefix} {m.group(1)} → {total}")


def watchlog_line(ident: str, title: str, rule: str, link: str, dry: bool) -> None:
    """Строка-выжимка в §4. Журнал не дублирует карточку — только суть и ссылка."""
    if not WATCHLOG.is_file():
        return
    txt = WATCHLOG.read_text(encoding="utf-8")
    anchor = "## §4. Находки и грабли (не переоткрывать)"
    if anchor not in txt:
        print("  ! §4 в WATCHLOG не найден — строка не поставлена", file=sys.stderr)
        return
    line = f"\n- **{STAMP}** — `{ident}` {title}. {rule or 'Правило — в карточке.'} → `{link}`\n"
    if dry:
        print(f"  [dry] в WATCHLOG §4:{line}")
        return
    head, _, tail = txt.partition(anchor)
    WATCHLOG.write_text(head + anchor + "\n" + line + tail.lstrip("\n"), encoding="utf-8")


# --------------------------------------------------------------------------- #
# типы артефактов
# --------------------------------------------------------------------------- #
def make_card(kind: str, args) -> None:
    # 🔴 Уровень заголовка — не косметика, а видимость для гейта.
    # `check_dangling_registry_refs` собирает существующие карточки регулярками
    # `^###\s+PIT-` и `^##\s+SYN-`. Карточка, написанная не на том уровне,
    # для гейта НЕ СУЩЕСТВУЕТ: ссылки на неё пройдут как висячие, а сама она
    # не попадёт в `max(своих номеров)` и обрежет диапазон проверки.
    # Так и случилось с PIT-115 и PIT-116 (найдено 22.08.2026, поправлено).
    if kind == "pit":
        prefix, path, level = "PIT", PIT_CARDS, "###"
        sources = [REPO / "reports", REPO / "00-infrastructure"]
    else:
        prefix, path, level = "SYN", SYN_CARDS, "##"
        sources = [REPO / "05-infra-synthesis-lab"]

    dup = already_captured(path, args.title)
    if dup:
        print(f"✗ похоже, уже заведено — {dup}")
        print("  повтор не создаю. Другая находка → уточни заголовок.")
        args.refused = True
        return

    num = next_number(prefix, sources)
    ident = f"{prefix}-{num:03d}"
    card = (
        f"\n{level} {ident} — {args.title} ({STAMP})\n\n"
        f"- **Симптом.** {args.symptom or '[что увидели, как проявилось]'}\n\n"
        f"- **Корень.** {args.root_cause or '[настоящая причина, а не поверхностная]'}\n\n"
        f"- **Правило.** {args.rule or '[что делать впредь — одной фразой]'}\n\n"
        f"- **Свой вклад.** [что сделал не так сам — чтобы не повторить; нет — так и написать]\n\n"
        f"- **Родня:** [смежные карточки и разделы]\n"
    )
    append(path, card, args.dry)
    print(f"✓ {ident} → {path.relative_to(REPO)}")
    sync_prose_count(prefix, path, args.dry)
    if not args.no_watchlog:
        watchlog_line(ident, args.title, args.rule, path.relative_to(REPO).as_posix(), args.dry)


def make_adr(args) -> None:
    num = adr_next_number()
    ident = f"adr_{num:03d}_{slugify(args.title)}"
    path = ADR_DIR / f"{ident}.md"
    if path.exists():
        print(f"✗ {path.name} уже существует")
        return

    body = (
        f"# ADR-{num:03d} — {args.title}\n\n"
        f"**Статус:** черновик, вынесен владельцу · {TODAY}\n\n"
        f"---\n\n"
        f"## 1. Контекст\n\n{args.symptom or '[что заставило принимать решение]'}\n\n"
        f"## 2. Что измерено, а не предположено\n\n[числа с командой, которой они получены]\n\n"
        f"## 3. Решение\n\n{args.rule or '[что решили — одной фразой, потом раскрыть]'}\n\n"
        f"## 4. Рассмотрено и отклонено\n\n"
        f"| Вариант | Почему нет |\n|---|---|\n| [альтернатива] | [причина] |\n\n"
        f"## 5. Чего это ADR НЕ решает\n\n[границы, названные вслух]\n"
    )
    if args.dry:
        print(f"  [dry] создал бы {path.relative_to(REPO)}")
    else:
        path.write_text(body, encoding="utf-8")
    print(f"✓ ADR-{num:03d} → {path.relative_to(REPO)}")

    # реестр — той же операцией, иначе он отстанет (случай 22.08.2026)
    if ADR_REGISTRY.is_file():
        row = (f"| [`{ident}`](./{ident}.md) | {TODAY} | {args.title} "
               f"| **Черновик, вынесен владельцу** |\n")
        txt = ADR_REGISTRY.read_text(encoding="utf-8")
        lines = txt.splitlines(keepends=True)
        last = max((i for i, l in enumerate(lines) if l.startswith("| [`adr_")), default=None)
        if last is None:
            print("  ! строка реестра не вставлена: таблица не найдена", file=sys.stderr)
        elif args.dry:
            print(f"  [dry] в реестр: {row}")
        else:
            lines.insert(last + 1, row)
            ADR_REGISTRY.write_text("".join(lines), encoding="utf-8")
            print(f"✓ строка в реестре {ADR_REGISTRY.relative_to(REPO)}")
    if not args.no_watchlog:
        watchlog_line(f"ADR-{num:03d}", args.title, args.rule,
                      path.relative_to(REPO).as_posix(), args.dry)


def bump_class(args) -> None:
    """+1 к счётчику класса в лидерборде. Счётчик не сбрасывается никогда."""
    if not CLASS_BOARD.is_file():
        print(f"✗ нет {CLASS_BOARD}")
        return
    txt = CLASS_BOARD.read_text(encoding="utf-8")
    pat = re.compile(rf"(##\s*\S*\s*{re.escape(args.title)}\s*·.*?—\s*\*\*)(\d+)(\s*повтор\w*\*\*)")
    m = pat.search(txt)
    if not m:
        print(f"✗ класс {args.title} в лидерборде не найден.")
        print("  Новый класс добавляется руками — у него нужен разбор, а не счётчик.")
        return
    old = int(m.group(2))
    new = old + 1
    if args.dry:
        print(f"  [dry] {args.title}: {old} → {new} повторов")
        return
    txt = txt[: m.start()] + m.group(1) + str(new) + m.group(3) + txt[m.end():]
    CLASS_BOARD.write_text(txt, encoding="utf-8")
    print(f"✓ {args.title}: {old} → {new} повторов")
    if args.case:
        append(CLASS_BOARD, f"\n- **{STAMP}** — {args.case}\n", args.dry)
        print("✓ случай дописан строкой")
    else:
        print("  ! случай строкой не дописан — счётчик без случая бесполезен, добавь --case")


# --------------------------------------------------------------------------- #
def main() -> int:
    p = argparse.ArgumentParser(description="Завести служебный файл одной командой")
    p.add_argument("kind", choices=["pit", "syn", "adr", "class"])
    p.add_argument("title", help="заголовок находки (для class — идентификатор, напр. PIT-G)")
    p.add_argument("case", nargs="?", help="для class: случай одной строкой")
    p.add_argument("--symptom", default="")
    p.add_argument("--root-cause", dest="root_cause", default="")
    p.add_argument("--rule", default="")
    p.add_argument("--no-watchlog", action="store_true")
    p.add_argument("--dry", action="store_true")
    args = p.parse_args()

    if args.dry:
        print("── режим --dry: ничего не пишется\n")

    if args.kind in ("pit", "syn"):
        make_card(args.kind, args)
    elif args.kind == "adr":
        make_adr(args)
    else:
        bump_class(args)

    if not args.dry and not getattr(args, "refused", False):
        print("\n  Дальше: заполни поля каркаса содержательно — скрипт ставит форму,")
        print("  а порог «стоит ли фиксировать» и содержание остаются за вахтой (§6).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
