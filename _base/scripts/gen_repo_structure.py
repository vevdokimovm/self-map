#!/usr/bin/env python3
"""Структура репы по требованию — не снимок, который хранится и гниёт.

ПОЧЕМУ СКРИПТ, А НЕ ФАЙЛ В БАЗЕ (`76-repo-classes.md` §8 — та же ООП-логика,
что уже дважды подтвердилась 27.08.2026 на `repos-map.md` и `.repo-meta`):
сохранённый снимок структуры устареет в день, когда в любой репе появится
новая папка, и ничего не заметит расхождения. Читать с диска заново каждый
раз — единственный способ не соврать.

ЧТО ДЕЛАЕТ. Верхнеуровневые папки репы (глубина 1, без служебных) + число
файлов в каждой рекурсивно — таблица вида README-паттерна «Структура»,
уже используемого в `health-vault`/других репах. Столбец «Что внутри» —
не заполняется машиной (это синтез, не подсчёт) — оставляется TODO при
первой генерации, дальше правится руками и остаётся стабильным, пока сам
скрипт перезапускают только для чисел.

ЗАПУСК
    gen_repo_structure.py <репа>              таблица в stdout
    gen_repo_structure.py <репа> --update-readme   вписать/обновить блок в README.md
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

SKIP_DIRS = {
    ".git", "_base", "__MACOSX", "node_modules", ".idea", "__pycache__",
    ".venv", "venv", ".pytest_cache", "dist", "build", "web",
}
SKIP_PREFIX = ("_", ".")

MARKER_START = "<!-- STRUCTURE:AUTO:START -->"
MARKER_END = "<!-- STRUCTURE:AUTO:END -->"


def count_files(d: Path) -> int:
    n = 0
    for p in d.rglob("*"):
        if p.is_dir():
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(d).parts[:-1]):
            continue
        n += 1
    return n


PLACEHOLDER = "TODO — заполнить вручную"

# Файлы, по первой строке которых можно узнать, что в каталоге. Порядок —
# от самого авторитетного к запасному: README пишется ради ответа на этот
# вопрос, остальные отвечают на него попутно.
DESC_SOURCES = ("README.md", "readme.md", "index.md", "00-README.md",
                "MANIFEST.md", "00-MANIFEST.md")

# Как назвать содержимое по расширениям — тремя формами, потому что
# по-русски число управляет словом: 1 заметка · 2 заметки · 5 заметок.
# Строка «2 заметок» выдаёт машину с головой и читается как небрежность,
# а описание, которое читают как небрежность, перестают читать вовсе.
EXT_NAMES: dict[str, tuple[str, str, str]] = {}


def _register(forms: tuple[str, str, str], *exts: str) -> None:
    # Расширения одного рода склеиваются в ОДНУ строку описания:
    # `.jpg` и `.png` — оба «изображения», и «120 изображений, 4 изображения»
    # в одной строке было первым, что бросилось в глаза на живом прогоне.
    for e in exts:
        EXT_NAMES[e] = forms


_register(("заметка", "заметки", "заметок"), ".md")
_register(("текст", "текста", "текстов"), ".txt", ".rtf")
_register(("PDF", "PDF", "PDF"), ".pdf")
_register(("изображение", "изображения", "изображений"),
          ".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif", ".tiff", ".bmp", ".svg")
_register(("аудиозапись", "аудиозаписи", "аудиозаписей"),
          ".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac")
_register(("видео", "видео", "видео"), ".mp4", ".mov", ".avi", ".mkv", ".webm")
_register(("скрипт Python", "скрипта Python", "скриптов Python"), ".py")
_register(("скрипт оболочки", "скрипта оболочки", "скриптов оболочки"), ".sh", ".zsh", ".bash")
_register(("скрипт JS", "скрипта JS", "скриптов JS"), ".js", ".mjs", ".ts")
_register(("файл JSON", "файла JSON", "файлов JSON"), ".json")
_register(("таблица CSV", "таблицы CSV", "таблиц CSV"), ".csv", ".tsv")
_register(("таблица Excel", "таблицы Excel", "таблиц Excel"), ".xlsx", ".xls")
_register(("конфиг", "конфига", "конфигов"), ".yml", ".yaml", ".toml", ".ini", ".cfg")
_register(("страница HTML", "страницы HTML", "страниц HTML"), ".html", ".htm")
_register(("файл стилей", "файла стилей", "файлов стилей"), ".css", ".scss")
_register(("документ Word", "документа Word", "документов Word"), ".docx", ".doc")
_register(("презентация", "презентации", "презентаций"), ".pptx", ".ppt", ".key")
_register(("архив", "архива", "архивов"), ".zip", ".rar", ".7z", ".tar", ".gz")
_register(("компонент React", "компонента React", "компонентов React"), ".tsx", ".jsx")
_register(("шаблон", "шаблона", "шаблонов"), ".mako", ".j2", ".jinja", ".tmpl", ".template")
_register(("юнит systemd", "юнита systemd", "юнитов systemd"), ".service", ".timer", ".socket")
_register(("образец конфигурации", "образца конфигурации", "образцов конфигурации"), ".example", ".sample")
_register(("файл XML", "файла XML", "файлов XML"), ".xml")
_register(("файл без расширения", "файла без расширения", "файлов без расширения"), "")
_register(("подкаталог", "подкаталога", "подкаталогов"), "__subdirs__")


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """Русское согласование: 1 · 2–4 · 5+, с исключением на 11–14."""
    if n % 100 in (11, 12, 13, 14):
        return forms[2]
    last = n % 10
    if last == 1:
        return forms[0]
    if last in (2, 3, 4):
        return forms[1]
    return forms[2]


def first_meaningful_line(path: Path) -> str:
    """Первый содержательный заголовок или строка файла.

    Пропускается фронтматтер, разметка блока статуса и пустое: нужен ответ
    на вопрос «что тут», а не первая строка байтов.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":            # фронтматтер
        end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), 0)
        lines = lines[end + 1:]
    for line in lines[:40]:
        line = line.strip()
        if not line or line.startswith(("<!--", ">", "|", "-", "*", "```")):
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
        line = re.sub(r"\*\*|__|`", "", line)
        # Заголовок вида «07 — Лаборатория…»: номер повторяет имя каталога,
        # он в таблице уже есть слева и место занимает зря.
        line = re.sub(r"^\d+[\s—–-]+", "", line)
        if len(line) >= 8:
            return line
    return ""


def describe_by_composition(d: Path) -> str:
    """Состав каталога словами — когда описать иначе нечем.

    🔴 Это НЕ синтез и не выдаётся за него: строка отвечает на «что внутри»
    буквально, перечисляя, из чего каталог состоит. Такой ответ беднее
    человеческого, но он **верен и обновляется сам**, а `TODO — заполнить
    вручную` не верен и не обновляется. Между честным бедным и обещанием
    богатого выбирается первое (`71-fail-loud-and-sourcing.md`).
    """
    counts: dict[tuple[str, str, str], int] = {}
    subdirs = 0
    for child in d.iterdir():
        if child.is_dir() and not child.name.startswith(".") and child.name not in SKIP_DIRS:
            subdirs += 1
    for f in d.rglob("*"):
        if not f.is_file() or f.name.startswith("."):
            continue
        if any(part in SKIP_DIRS for part in f.relative_to(d).parts[:-1]):
            continue
        ext = f.suffix.lower()
        key = EXT_NAMES.get(ext)
        if key is None:
            # Незнакомое расширение называем им самим — это честнее, чем
            # «прочий файл», и подсказывает, что стоит завести в таблицу выше.
            label = ext.lstrip(".").upper()
            key = (f"файл {label}", f"файла {label}", f"файлов {label}")
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        # Каталог есть, а видимых файлов нет — обычно `.gitkeep`, то есть место
        # застолблено под будущее наполнение. Это факт, и сказать его честно
        # полезнее, чем оставить «TODO»: читатель сразу понимает, что искать
        # тут нечего, и не идёт проверять.
        keep = [f.name for f in d.iterdir() if f.is_file() and f.name.startswith(".")]
        if keep:
            return "пусто — место застолблено под наполнение"
        return ""
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
    parts = [f"{n} {plural(n, forms)}" for forms, n in top]
    if subdirs > 1:
        parts.append(f"{subdirs} {plural(subdirs, EXT_NAMES['__subdirs__'])}")
    return ", ".join(parts)


# Как выглядит описание, СДЕЛАННОЕ ЭТИМ СКРИПТОМ: «12 заметок, 3 PDF,
# 2 подкаталога» — перечисление «число + существительное» через запятую.
# 🔴 Зачем это нужно. Сгенерированное описание, попав в README, становится
# неотличимо от написанного рукой, и правило «руками написанное не трогать»
# начинает защищать в том числе и машинный вывод — то есть он застывает
# навсегда, включая огрехи вроде «1 файл MAKO». Найдено 29.08.2026 сразу
# после первого массового прогона: улучшение словаря расширений ничего
# не изменило в 52 репах, потому что старый вывод считался авторским.
# Правило: свой вывод скрипт узнаёт по форме и обновляет; всё остальное —
# авторский текст, он неприкосновенен.
# Сегмент машинного описания — строго «число + слова без знаков препинания»:
# `10 заметок`, `132 скрипта Python`, `1 файл без расширения`. Тире, двоеточие
# и точка внутри сегмента означают, что это писал человек.
# 🔴 Прежняя, более широкая редакция (`\d+\s+[^,]+`) считала своим авторскую
# строку «3 тома разбора — читать с первого» и затёрла бы её. Поймано
# отрицательной половиной канарейки, а не на живых репах.
_SEG = r"\d+ [^\W\d_][\w ]{0,40}"
GENERATED_RE = re.compile(
    rf"^(?:пусто — место застолблено под наполнение|{_SEG}(?:, {_SEG})*)$")


def looks_generated(note: str) -> bool:
    return bool(GENERATED_RE.match(note.strip()))


def describe(d: Path) -> str:
    """Описание каталога: сначала его собственные слова, потом состав.

    🔴 Заведено 29.08.2026. Прежде столбец «Что внутри» заполнялся строкой
    `TODO — заполнить вручную` в расчёте, что её потом заменят руками. Замер
    по системе: **385 таких строк в 52 репах** — то есть заглушка стала
    постоянным состоянием, а не временным. Владелец об этом же сказал прямо
    про README планировщика: «что это за дерьмо вообще».

    Причина не в лени: заполнять 385 описаний руками некому, и через месяц
    их станет больше. Значит нужен не призыв, а **источник**. Он есть:
    у половины каталогов лежит собственный README, у остальных состав файлов
    говорит достаточно. Машина не умеет синтезировать смысл — но умеет
    процитировать того, кто его уже записал.
    """
    for name in DESC_SOURCES:
        candidate = d / name
        if candidate.is_file():
            line = first_meaningful_line(candidate)
            if line:
                # Имя каталога в начале описания — тавтология: оно слева.
                # 🔴 Срезать надо и имя целиком, и его вариант БЕЗ числового
                # префикса: `first_meaningful_line` уже сняла «00-» с заголовка,
                # и сравнение с полным `00-infrastructure` промахивалось —
                # в таблице оставалось «infrastructure — как устроена…».
                # Варианты имени, которыми заголовок может начинаться:
                # с числовым префиксом и без, со слэшем и без. Слэш встретился
                # живьём: `author/README.md` открывается «# author/ — материалы
                # про автора», и без него в таблице оставалось «author/ — …».
                bare = re.sub(r"^\d+[-_]?", "", d.name)
                for variant in (d.name + "/", d.name, bare + "/", bare):
                    if not variant:
                        continue
                    line = re.sub(rf"^{re.escape(variant)}\s*[—–:-]\s*", "",
                                  line, flags=re.I).strip()
                # 🔴 Однословный заголовок описанием не является. Живой случай
                # 29.08.2026: `07-correspondence/README.md` начинался словом
                # «Correspondence» — то есть повторял имя каталога на другом
                # языке и не сообщал ничего. Состав файлов в таком случае
                # информативнее заголовка, взятого ради самого факта заголовка.
                if len(line.split()) >= 2 or len(line) >= 15:
                    return line[:150]
    return describe_by_composition(d)


def build_table(repo: Path, existing_notes: dict[str, str]) -> str:
    rows = []
    for child in sorted(repo.iterdir()):
        if not child.is_dir():
            continue
        if child.name in SKIP_DIRS or child.name.startswith(SKIP_PREFIX):
            continue
        n = count_files(child)
        if n == 0:
            continue
        # Написанное человеком не трогаем НИКОГДА — оно всегда лучше
        # выведенного. Заменяется только заглушка и пустое.
        note = existing_notes.get(child.name, "")
        if not note or note == PLACEHOLDER or looks_generated(note):
            note = describe(child) or PLACEHOLDER
        rows.append(f"| `{child.name}/` | {n} | {note} |")

    if not rows:
        return "_репа пуста или всё содержимое в служебных папках_\n"

    header = "| Папка | Файлов | Что внутри |\n|---|---|---|\n"
    return header + "\n".join(rows) + "\n"


def parse_existing_notes(readme_text: str) -> dict[str, str]:
    """Не затирать уже написанные вручную описания при перегенерации чисел."""
    notes: dict[str, str] = {}
    for line in readme_text.splitlines():
        m = re.match(r"\|\s*`([^`]+)/`\s*\|\s*\d+\s*\|\s*(.+?)\s*\|\s*$", line)
        if m:
            notes[m.group(1)] = m.group(2)
    return notes


def selftest() -> bool:
    """Проверяется РАЗЛИЧЕНИЕ, а не то, что код исполняется.

    Три умения, каждое ломается по-своему и молча:
      · согласование числительного — «2 заметок» выдаёт машину;
      · склейка расширений одного рода — «120 изображений, 4 изображения»;
      · отсев тавтологии — заголовок, повторяющий имя каталога, описанием
        не является, и состав файлов вместо него информативнее.
    """
    import tempfile

    forms = ("заметка", "заметки", "заметок")
    if [plural(n, forms) for n in (1, 2, 5, 11, 21, 22, 25, 111, 114)] != [
            "заметка", "заметки", "заметок", "заметок", "заметка",
            "заметки", "заметок", "заметок", "заметок"]:
        return False

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        mixed = root / "фото"
        mixed.mkdir()
        for i in range(3):
            (mixed / f"a{i}.jpg").write_bytes(b"x")
        for i in range(2):
            (mixed / f"b{i}.png").write_bytes(b"x")
        got = describe_by_composition(mixed)
        # Пять изображений ОДНОЙ строкой, а не двумя по расширению.
        if got != "5 изображений":
            return False

        tautology = root / "07-correspondence"
        tautology.mkdir()
        (tautology / "README.md").write_text("# Correspondence\n", encoding="utf-8")
        (tautology / "x.md").write_text("y\n", encoding="utf-8")
        if describe(tautology) != "2 заметки":
            return False

        real = root / "08-lab"
        real.mkdir()
        (real / "README.md").write_text(
            "# 08 — Лаборатория теории систем\n\nтекст\n", encoding="utf-8")
        if describe(real) != "Лаборатория теории систем":
            return False

        slashed = root / "author"
        slashed.mkdir()
        (slashed / "README.md").write_text(
            "# author/ — материалы про автора проекта\n", encoding="utf-8")
        if describe(slashed) != "материалы про автора проекта":
            return False

        placeheld = root / "03-funding"
        placeheld.mkdir()
        (placeheld / ".gitkeep").write_text("", encoding="utf-8")
        if describe(placeheld) != "пусто — место застолблено под наполнение":
            return False

        # Свой вывод узнаётся, авторский текст — нет. Обе половины обязательны:
        # без первой машинный огрех застывает навсегда, без второй скрипт
        # затрёт написанное человеком, а это потеря без возможности отката.
        if not all(looks_generated(x) for x in (
                "12 заметок", "1 заметка", "10 заметок, 8 PDF, 3 изображения",
                "пусто — место застолблено под наполнение")):
            return False
        if any(looks_generated(x) for x in (
                "Лаборатория теории систем",
                "материалы про автора проекта",
                "как устроена и ведётся эта репа",
                "3 тома разбора — читать с первого")):
            return False

        numbered = root / "00-infrastructure"
        numbered.mkdir()
        (numbered / "README.md").write_text(
            "# 00-infrastructure — как устроена и ведётся эта репа\n", encoding="utf-8")
        if describe(numbered) != "как устроена и ведётся эта репа":
            return False

    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", nargs="?")
    ap.add_argument("--update-readme", action="store_true")
    ap.add_argument("--force", action="store_true", help="вписать блок даже в product/profile-репу")
    ap.add_argument("--selftest", action="store_true", help="канарейка описаний")
    a = ap.parse_args()

    if a.selftest:
        ok = selftest()
        print("🟢 канарейка: числительные, склейка расширений, отсев тавтологии"
              if ok else "🔴 канарейка: РАЗЛИЧЕНИЕ СЛОМАНО")
        return 0 if ok else 1

    if not a.repo:
        ap.error("нужно имя репы (или --selftest)")
    repo = Path(a.repo).expanduser().resolve()
    if not repo.is_dir():
        print(f"нет такой репы: {repo}")
        return 2

    # PIT-156-родня, найдено 28.08.2026: блок «Структура» — служебная
    # навигация для личных репов, но был вписан и в публичные продукты
    # (`vevdokimovm.github.io`, `finpilot`, `algorithms-site`, `vk-graph`,
    # `salvation`, `game-analytics-engine`, `claude-usage`) — «TODO —
    # заполнить вручную» на живой странице выглядит как незаконченный
    # продукт перед работодателем/рекрутером. `.repo-class` — `product`
    # или `profile` — блокирует --update-readme без явного --force.
    if a.update_readme:
        class_file = repo / ".repo-class"
        repo_class = class_file.read_text(encoding="utf-8").strip() if class_file.is_file() else ""
        readme_probe = repo / "README.md"
        has_block = (readme_probe.is_file()
                     and MARKER_START in readme_probe.read_text(encoding="utf-8", errors="replace"))
        # 🔴 29.08.2026: сторож запрещал ЛЮБУЮ запись в публичную репу — и тем
        # самым консервировал ровно тот вред, ради которого заводился. Блок
        # «Структура» был вписан в три публичные репы ДО его появления, и внутри
        # осталось 18 строк «TODO — заполнить вручную» — то есть на витринной
        # странице перед работодателем висело незаполненное обещание, а сторож
        # отказывался его обновить.
        #
        # Различение, которого не хватало: ЗАВЕСТИ блок в публичной репе —
        # решение владельца (нужен `--force`); ОБНОВИТЬ уже стоящий там блок —
        # улучшение того, что и так опубликовано, и запрещать его вредно.
        # Правило выбирается по более дешёвой ошибке: лишнее точное описание
        # на публичной странице стоит ничего, «TODO» на ней стоит впечатления.
        if repo_class in {"product", "profile"} and not a.force and not has_block:
            print(
                f"{repo.name}: .repo-class = {repo_class} — публичный/витринный класс, "
                f"блока «Структура» в README нет. Заводить его на публичной странице — "
                f"решение владельца: добавь --force, если действительно нужно."
            )
            return 2

    readme = repo / "README.md"
    existing_notes: dict[str, str] = {}
    if readme.is_file():
        existing_notes = parse_existing_notes(readme.read_text(encoding="utf-8", errors="replace"))

    table = build_table(repo, existing_notes)

    if not a.update_readme:
        print(table)
        return 0

    if not readme.is_file():
        print(f"нет README.md в {repo} — не во что вписывать, запусти без --update-readme")
        return 2

    text = readme.read_text(encoding="utf-8", errors="replace")
    block = f"{MARKER_START}\n{table}{MARKER_END}"

    if MARKER_START in text and MARKER_END in text:
        # Уже маркирован нашим прошлым проходом — заменить только блок.
        text = re.sub(
            rf"{re.escape(MARKER_START)}.*?{re.escape(MARKER_END)}",
            block, text, flags=re.DOTALL,
        )
    else:
        # Найден ли уже заголовок "## Структура" (ручной, без маркеров)? Замена
        # ЕГО содержимого, а не добавление второго — баг 27.08.2026: 8 репо
        # получили дублированный заголовок именно из-за пропуска этой ветки.
        heading_re = re.compile(r"^## Структура\s*$", re.MULTILINE)
        m = heading_re.search(text)
        if m:
            start = m.end()
            next_heading = re.search(r"^## ", text[start:], re.MULTILINE)
            end = start + next_heading.start() if next_heading else len(text)
            text = text[:start] + "\n\n" + block + "\n" + text[end:]
        else:
            text = text.rstrip("\n") + "\n\n## Структура\n\n" + block + "\n"

    readme.write_text(text, encoding="utf-8")
    print(f"обновлено: {readme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
