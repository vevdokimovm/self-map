#!/usr/bin/env python3
"""revision_check.py — runnable-гейт ревизии knowledge-репы (stdlib-only).

Автоматизированная часть протокола ревизии (21-revision-protocol.md).
Идея перенесена из FINPILOT (tools/revision/revision_check.py): часть осей
ревизии проверяется скриптом за секунды, а не глазами за час. Exit 0 = CLEAN
(или только warnings), exit 1 = DRIFT (есть FAIL; с --strict валят и warnings).

Проверки:
  1. Битые относительные ссылки в ЖИВЫХ .md (замороженные зоны пропускаются:
     история не переписывается — 21-revision-protocol.md §1).
  2. Порча имён `#Uxxxx` (Info-ZIP без UTF-8 флага — PIT-009) -> FAIL.
  3. Крупные файлы: > WARN_FILE_MB -> warning, > FAIL_FILE_MB -> FAIL
     (жёсткий лимит GitHub 100 МБ на файл).
  4. Суммарный размер дерева против порогов 01-repo-standard.md
     (цель 50 МБ -> warning, мягкий 100 МБ -> warning, жёсткий 500 МБ -> FAIL).
  5. Пустые папки -> warning (мусор структуры).
  6. Архивы/тяжёлые бинарники в git-дереве -> warning
     («zip — транспорт, а не версионируемый исходник», 15-gotchas §2).

Запуск из корня репы:
    python3 scripts/revision_check.py [--strict] [--root PATH]

Allowlist ссылок (по одной на строку, относительный путь как в ссылке):
    .revision_allowlist в корне репы.
"""

from __future__ import annotations

import argparse
import os
import re
from urllib.parse import unquote
import sys
from pathlib import Path

WARN_FILE_MB = 20
FAIL_FILE_MB = 95
REPO_TARGET_MB = 50
REPO_SOFT_MB = 100
REPO_HARD_MB = 500

FROZEN_DIRS = (
    "reports/incidents",
    "reports/investigations",
    "reports/merges",
    "reports/situations",
    "reports/releases",
    "reports/audits",
)
FROZEN_FILES = ("CHANGELOG.md",)
# Каталоги машинных выгрузок из внешних сервисов: содержимое — дословный
# слепок источника, ссылки внутри отражают состояние ТАМ, а не здесь.
# Каталоги ЧУЖИХ материалов: скачанные курсы, склонированные репозитории,
# выгрузки сервисов. Их README ссылается на файлы, которых в нашей копии нет
# (не все части курса скачаны, не весь репозиторий склонирован) — это факт
# источника, а не дефект. Править чужой README нельзя: он перестанет быть
# дословной копией, и следующая сверка с оригиналом покажет ложное расхождение.
EXPORT_DIRS = ("notion-reflections", "md_files", "exports", "90-imported",
               "old-before-claude", "deep-learning-school")
LINK_SKIP_DIRS = ("templates",)  # шаблоны содержат намеренные плейсхолдеры-ссылки
SKIP_DIRS = (".git", ".venv", "node_modules", "__pycache__")
ARCHIVE_SUFFIXES = (".zip", ".tar", ".gz", ".7z", ".rar", ".dmg", ".iso")

MD_LINK_RE = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)\)")
IMG_LINK_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
HEX_NAME_RE = re.compile(r"#U[0-9a-fA-F]{4}")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


# ── Одно определение карточки реестра на весь гейт ──────────────────────
#
# 🔴 Было ПЯТЬ независимых определений в пяти местах, и два из них расходились
# с тремя другими: `check_prose_counts` и `PIT_CARD_RE` требовали ровно один
# пробел (`^### PIT-`), остальные — любой пробельный (`^###\s+PIT-`).
#
# На живом файле они совпали — 151 против 151, — и потому расхождение было
# невидимым. Оно проявилось бы на ПЕРВОЙ ЖЕ карточке с двойным пробелом:
# счётчик прозы насчитал бы на одну меньше и объявил число в тексте неверным,
# а проверки дублей и уровней заголовка остались бы довольны. Спор двух
# проверок о том, что такое карточка, — не тот спор, который кто-то станет
# разбирать: обе «работают».
#
# Это `parse, don't validate` в применимом объёме (кандидат №14): не переделка
# 33 проверок на единый парсер документа, а один источник для той вещи,
# которую пять мест понимали каждое по-своему.
CARD_KINDS = {
    # вид: (уровень заголовка, префикс номера, путь реестра от корня репы)
    "PIT": ("###", "PIT", ("reports", "pitfalls.md")),
    "SYN": ("##", "SYN", ("05-infra-synthesis-lab", "PITFALLS.md")),
}


def card_re(kind: str, *, capture: bool = False, wrong_level: bool = False) -> str:
    r"""Единственное место, где записано, как выглядит карточка реестра.

    `capture` — обернуть номер в группу; `wrong_level` — наоборот, поймать
    карточку на ЛЮБОМ уровне заголовка, кроме правильного (для проверки уровней).

    🔴 Пробел после решёток — `\s+`, а не литерал: мягкое понимание выбрано
    сознательно, потому что оно совпадает с тем, как заголовок читает сам
    Markdown. Строгий вариант был бы «правильнее» лишь в том смысле, что ловил
    бы неаккуратное оформление, — но ловить его должна отдельная проверка,
    а не молчаливое расхождение между пятью счётчиками.
    """
    level, prefix, _ = CARD_KINDS[kind]
    if wrong_level:
        others = "|".join(re.escape(x) for x in ("#", "##", "###", "####")
                          if x != level)
        return rf"^({others})\s+{prefix}-\d+"
    num = rf"({prefix}-\d+)" if capture else rf"{prefix}-\d+"
    return rf"^{re.escape(level)}\s+{num}"


def card_registry(root: Path, kind: str) -> Path:
    """Путь к реестру карточек этого вида — тоже в одном месте."""
    return root.joinpath(*CARD_KINDS[kind][2])


def selftest_card_re() -> bool:
    """Различение: правильный уровень ловится, чужой — нет, и оба пробела равны.

    🔴 Проверяется именно то, из-за чего сведение затевалось: строгий и мягкий
    пробел дают ОДИН результат, потому что источник теперь один. Прежде
    `^### PIT-` и `^###\\s+PIT-` жили в разных местах и расходились бы
    на первой же карточке с двойным пробелом.
    """
    ok = re.compile(card_re("PIT"), re.M)
    cap = re.compile(card_re("PIT", capture=True), re.M)
    bad = re.compile(card_re("PIT", wrong_level=True), re.M)
    probe = ("### PIT-001 один пробел\n"
             "###  PIT-002 два пробела\n"
             "## PIT-003 не тот уровень\n")
    if len(ok.findall(probe)) != 2:                      # оба пробела — карточки
        return False
    if cap.findall(probe) != ["PIT-001", "PIT-002"]:     # номер захвачен
        return False
    if bad.findall(probe) != ["##"]:                     # чужой уровень пойман один
        return False
    syn = re.compile(card_re("SYN", capture=True), re.M)
    return syn.findall("## SYN-007 x\n### SYN-008 не тот уровень\n") == ["SYN-007"]




def is_frozen(rel: Path) -> bool:
    posix = rel.as_posix()
    if rel.name in FROZEN_FILES:
        return True
    return any(posix.startswith(d + "/") or posix == d for d in FROZEN_DIRS)


def iter_files(root: Path) -> list[Path]:
    files = []
    for path in root.rglob("*"):
        rel_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if path.is_file():
            files.append(path)
    return files


def load_allowlist(root: Path) -> set[str]:
    allow = root / ".revision_allowlist"
    if not allow.is_file():
        return set()
    lines = allow.read_text(encoding="utf-8", errors="replace").splitlines()
    return {ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")}


def strip_code_fences(text: str) -> str:
    """Выкинуть содержимое ``` и ~~~ блоков.

    Ссылка внутри блока кода — это ПРИМЕР разметки, а не живая ссылка: пример из
    75-readme-status-block.md показывает, что вставить в README репы, где ROADMAP.md
    лежит рядом, — а сам документ лежит этажом ниже. Без этой отсечки любая методичка,
    показывающая markdown, даёт ложное падение, и лечится оно через .revision_allowlist,
    который потом глушит и НАСТОЯЩУЮ битую ссылку с тем же именем.
    """
    kept: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        marker = FENCE_RE.match(line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token == fence:
                fence = None
            continue
        if fence is None:
            kept.append(line)
    return "\n".join(kept)


# Схема URI по RFC 3986 §3.1: буква, затем буквы/цифры/`+`/`-`/`.`, затем `:`.
# Минимум две буквы — чтобы однобуквенный префикс (например, диск `C:`) не
# проглатывался молча; в этой системе таких путей нет, но правило не должно
# зависеть от того, что их нет.
URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]+:")


def selftest_uri_schemes() -> bool:
    """Схема пропускается, ОТНОСИТЕЛЬНЫЙ путь — нет. Различение, а не исполнение."""
    skip = ["data:image/png;base64,iVBOR", "https://example.org", "mailto:a@b.c",
            "obsidian://open?vault=x", "tel:+70000000000"]
    keep = ["docs/README.md", "./a.png", "../b/c.md", "docs/note: draft.md",
            "assets/charts/x.png"]
    return (all(URI_SCHEME_RE.match(t) for t in skip)
            and not any(URI_SCHEME_RE.match(t) for t in keep))


def check_links(root: Path, files: list[Path], allowlist: set[str]) -> tuple[list[str], int, int]:
    """Ссылка ведёт на существующий файл.

    🔴 ЧЕГО НЕ ЛОВИТ (`71` §7г-бис): ссылку, которая ведёт на существующий,
    но НЕ ТОТ файл — переименовали тему, путь остался валидным, содержание
    другое. Проверяется только существование цели, не её уместность.
    Также не видит ссылок внутри код-блоков (вырезаются намеренно: это
    примеры разметки) и адресов со схемой (`https:`, `data:` — не пути).
    """
    broken: list[str] = []
    checked = 0
    frozen_skipped = 0
    for path in files:
        if path.suffix.lower() != ".md":
            continue
        rel = path.relative_to(root)
        # 🔴 Исключение КАТАЛОГОМ. Тот же дефект, что найден утром
        # 29.08.2026 в `check_mixed_script_names`: `.revision_allowlist`
        # принимает форму `каталог/`, а проверка сверяла только точное
        # совпадение — и краснела на импортированном чужом материале
        # (файл со ссылками на не приложенные картинки).
        #
        # Класс тот же, что весь день: **исключение объявлено и не
        # действует**. Правку одной проверки надо было сразу проверить
        # на остальных — не проверил, и дефект нашёлся вторым прогоном.
        if any(a.endswith("/") and str(rel).startswith(a) for a in allowlist):
            continue
        # 🔴 28.08.2026: та же _base/-дыра, что в SECTION_DUPES_ALLOWLIST (PIT-153) —
        # `rel.parts[0]` был «templates» только для base-repo; в любой другой репе
        # шаблоны лежат под `_base/templates/`, и `rel.parts[0]` там — `_base`.
        parts = rel.parts[1:] if rel.parts and rel.parts[0] == "_base" else rel.parts
        # 🔴 `*.pdf.md` — МАШИННАЯ выжимка из PDF, не рукописный markdown.
        # Найдено 29.08.2026 на `science/04-fields/stati-ml/2303.08797v3.pdf.md`:
        # математика индикаторной функции `1( 1/2 ,1](t)x1` содержит `](`
        # и читается регуляркой как ссылка на «t». Это не дефект документа —
        # свойство экстракта: там формулы, переносы OCR, артефакты вёрстки.
        # Править вручную бессмысленно вдвойне: файл перегенерируется из PDF,
        # и правка исчезнет. В системе 929 таких файлов.
        if path.name.endswith(".pdf.md"):
            frozen_skipped += 1
            continue
        # 🔴 Машинные ВЫГРУЗКИ из внешних сервисов — тот же класс, что `.pdf.md`.
        # Найдено 29.08.2026: экспорт Notion в `self-map`/`misc-vault` даёт
        # **2088 «битых» ссылок** на картинки, которых сервис при выгрузке
        # просто не отдал (проверено: `*.jpeg` в каталоге экспорта — 0 штук).
        # Это факт исходной выгрузки, а не дефект репы; править вручную нельзя
        # (файлы — дословный слепок источника, правка исказит первоисточник),
        # а держать 2088 красных строк — гарантия, что гейт перестанут читать
        # целиком (`PIT-085`: шум такого масштаба хуже молчания).
        if any(p in EXPORT_DIRS for p in parts):
            frozen_skipped += 1
            continue
        # `templates/` пропускается на ЛЮБОЙ глубине, не только в корне.
        # Найдено 29.08.2026 в `misc-vault`: старая копия базы лежит внутри
        # `01-documents/claude-instructions/…/04_ИНФРАСТРУКТУРА_base-repo/`,
        # и её `templates/REPO_README_TEMPLATE.md` несёт намеренные
        # плейсхолдеры `./NN-folder` — ровно то, ради чего `LINK_SKIP_DIRS`
        # и заведён. Проверка смотрела только `parts[0]` и вложенную копию
        # не покрывала. Тот же класс `_base/`-дыры, что чинился в `PIT-153`.
        if is_frozen(rel) or any(p in LINK_SKIP_DIRS for p in parts):
            frozen_skipped += 1
            continue
        text = strip_code_fences(path.read_text(encoding="utf-8", errors="replace"))
        targets = MD_LINK_RE.findall(text) + IMG_LINK_RE.findall(text)
        for raw in targets:
            target = raw.split("#", 1)[0].strip()
            # 🔴 29.08.2026: список схем был ЗАХАРДКОЖЕН четырьмя штуками
            # (`http`, `https`, `mailto`, `tel`) — и `data:` в него не входил.
            # В `dota-dossier/docs/legacy/` лежат отчёты с ВСТРОЕННЫМИ картинками
            # `![…](data:image/png;base64,…)`: **16 «битых ссылок»** на изображения,
            # которые физически внутри файла и сломаться не могут в принципе.
            # Правило вместо перечня: адрес со СХЕМОЙ (RFC 3986) — не путь в файловой
            # системе, проверять его существованием файла бессмысленно, какая бы
            # схема ни встретилась завтра (`obsidian:`, `zotero:`, `file:`).
            # Двоеточие после `/` схемой не является — `docs/note: draft.md`
            # регуляркой не захватывается и проверяется как обычный путь.
            if not target or URI_SCHEME_RE.match(target):
                continue
            if (raw in allowlist or target in allowlist
                    or f"link: {target}" in allowlist or f"link:{target}" in allowlist
                    or f"link: {raw}" in allowlist or f"link:{raw}" in allowlist):
                continue
            # `...` в пути — ПРИМЕР синтаксиса, а не адрес. Найдено 29.08.2026:
            # `![Рисунок 4](../figures/...)` в инструкции о том, как оформлять
            # ссылки на рисунки. Многоточие надёжно отличает образец от пути:
            # в реальном имени файла его не бывает.
            if "..." in target:
                continue
            checked += 1
            # 🔴 URL-кодирование в ссылке — норма markdown, не дефект.
            # Найдено 29.08.2026 в `portrait-of-taste`: **315 «битых» ссылок**
            # вида `../photos/A_%D0%92%D0%B5%D1%80%D0%B0/A_01.jpg` при том,
            # что каталог `photos/A_Вера/` существует и файл на месте.
            # Редакторы markdown кодируют кириллицу в путях автоматически;
            # проверка сравнивала закодированную строку с именем на диске
            # и не находила совпадения. Декодируем перед сверкой.
            target = unquote(target)
            candidate = (path.parent / target).resolve()
            if not candidate.exists():
                # 🔴 28.08.2026: `_base/` переименовывает `VERSION` → `BASE_VERSION`
                # при раздаче (`sync-base.sh`, во избежание путаницы с VERSION самой
                # репы-хозяина) — ссылка `./VERSION` внутри `_base/README.md` живая
                # в base-repo и осознанно битая после раздачи. Не общий allowlist:
                # только эта конкретная, документированная замена имени.
                if ("_base" in rel.parts and candidate.name == "VERSION"
                        and (candidate.parent / "BASE_VERSION").is_file()):
                    continue
                # 🔴 28.08.2026, тот же класс: файлы, которые в `_base/` НЕ
                # раздаются по замыслу — журнал и задачи у каждой репы свои,
                # копировать их из канона значило бы подменить состояние репы
                # состоянием базы. Ссылки на них внутри `_base/README.md` живые
                # в base-repo и осознанно битые после раздачи. Замер: 54 репы,
                # то есть ВСЯ система, — жалоба была на конвенцию, не на дефект.
                if ("_base" in rel.parts
                        and candidate.name in {"WATCHLOG.md", "TASKS.md", "ROADMAP.md"}
                        and not candidate.exists()):
                    continue
                broken.append(f"{rel}: битая ссылка -> {raw}")
                continue
            # PIT-076: APFS (macOS, единственная платформа разработки этой системы)
            # регистронезависима — `exists()` молча резолвит `GLOSSARY.md` в лежащий
            # рядом `glossary.md`. На регистрочувствительной ФС (Linux CI) та же
            # ссылка битая, и результат один и тот же гейт даёт РАЗНЫЙ на двух
            # платформах. Сверяем точное имя конечного компонента через listdir —
            # это не зависит от того, чувствительна ли ФС, на которой запущен гейт.
            # Потолок: проверяется только последний компонент пути, не все
            # промежуточные каталоги.
            try:
                real_names = {p.name for p in candidate.parent.iterdir()}
            except OSError:
                real_names = set()
            if real_names and candidate.name not in real_names:
                broken.append(
                    f"{rel}: ссылка -> {raw} совпадает только БЕЗ УЧЁТА РЕГИСТРА "
                    f"(PIT-076) — битая на регистрочувствительной ФС")
    return broken, checked, frozen_skipped


# --- Канарейка на токен-слип модели ---------------------------------------------
# Многоязычная модель изредка берёт токен другого языка вместо целевого. Слип бывает
# СЕМАНТИЧЕСКИМ (иероглиф с тем же смыслом вместо русского слова) и потому проходит
# вычитку: смысл на месте, символ чужой. Найдено в живых репах трижды, и один раз —
# в этой самой базе, в слове «Авторизация» внутри методички.
# Разбор — reports/investigations/cjk_token_slip_investigation.md.
#
# АНТИ-САМОРЕФЕРЕНЦИЯ: репозиторий не содержит того, что запрещает. Диапазоны заданы
# числами, в текстах системы такие символы пишутся U+-нотацией, а тестовый образец
# конструируется через chr(). Иначе канарейка ловит собственные упоминания.
CJK_RANGES = (
    (0x3040, 0x30FF),  # кана
    (0x3400, 0x4DBF),  # CJK ext-A
    (0x4E00, 0x9FFF),  # CJK Unified
    (0xF900, 0xFAFF),  # CJK compat
    (0xAC00, 0xD7AF),  # хангыль
)
CJK_TEXT_EXT = {".py", ".md", ".sh", ".html", ".js", ".css", ".json",
                ".yml", ".yaml", ".cfg", ".ini", ".toml", ".txt"}
# Осознанные исключения: относительный путь -> причина. Пусто и должно быть пустым.
CJK_ALLOWLIST: dict[str, str] = {}


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return any(low <= code <= high for low, high in CJK_RANGES)


# 🔴 29.08.2026, ЗАМЕР: `check_cjk` занимал **28.8 из 30 секунд** прогона
# на ПУСТОЙ репе — 96 % времени гейта. Причина: посимвольный обход каждой
# строки каждого файла с вызовом функции на символ. Регулярка делает то же
# самое в C и на порядок быстрее; диапазоны те же, поведение не меняется.
#
# Дефект производительности здесь — не про удобство: гейт, идущий десять
# минут по системе, начинают запускать реже, а проверка, которую не
# запускают, не отличается от отсутствующей.
CJK_RE = re.compile("[" + "".join(
    f"{chr(low)}-{chr(high)}" for low, high in CJK_RANGES) + "]")


def check_cjk(root: Path, files: list[Path],
              allowlist: set[str] | None = None) -> list[str]:
    """Иероглиф в тексте системы — почти всегда токен-слип, а не намерение.

    🔴 «Почти» — не «всегда». Найдено 28–29.08.2026: в `dota-dossier` лежит
    **легитимный китайско-русский глоссарий** терминов Dota под расшифровки
    китайских про-игроков — 518 срабатываний на материале, где китайский
    является предметом изучения. (Примеры иероглифов здесь намеренно НЕ
    приводятся: эта же проверка поймала их в первой редакции комментария —
    она не отличает пример от слипа, и правильно делает.) Исключение задаётся через
    `.revision_allowlist` репы **тремя формами**, от грубой к точной:

        knowledge/pro-thinking/     каталог целиком (корпус на языке-предмете)
        docs/glossary-cn.md         один файл
        cjk-term: <слово>           СЛОВАРНАЯ ЕДИНИЦА, разрешённая везде в репе

    🔴 Третья форма — единственная, которая НЕ выключает проверку. Найдено
    29.08.2026: в `dota-dossier` китайские термины цитируются в `CHANGELOG.md`
    и `ROADMAP.md` — живых документах, куда слипы как раз и попадают. Исключить
    файл целиком значило бы ослепить канарейку ровно там, где она нужнее всего,
    и это не теория: в том же прогоне в двух файлах `coaching/` нашлись **живые
    слипы** — корейский слог внутри русского слова и китайский иероглиф вместо
    русского. Оба пролежали месяцами и были бы прощены исключением по файлу.

    Разрешённый термин вырезается из строки ПЕРЕД поиском, поэтому любой другой
    иероглиф в той же строке по-прежнему краснеет. Способность различать
    проверяется канарейкой `selftest_cjk_terms`.

    (Примеры иероглифов в этом комментарии намеренно НЕ приводятся: эта же
    проверка поймала их в первой редакции — она не отличает пример от слипа,
    и правильно делает.)

    🔴 ЧЕГО НЕ ЛОВИТ: слип внутри своего алфавита. Подменённое кириллическое слово в кириллическом тексте не отличается от намеренного — ловится только чужая письменность.
    """
    hits = []
    allow = allowlist or set()
    terms = sorted(cjk_terms(allow), key=len, reverse=True)
    for path in files:
        if path.suffix.lower() not in CJK_TEXT_EXT:
            continue
        rel = path.relative_to(root).as_posix()
        if rel in CJK_ALLOWLIST or rel in allow:
            continue
        if any(a.endswith("/") and rel.startswith(a) for a in allow):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        # Быстрый отсев: в файле вообще нет CJK — не разбираем построчно.
        # На системе из 63 реп подавляющее большинство файлов чисты, и одна
        # проверка на файл заменяет тысячи построчных.
        if not CJK_RE.search(text):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if not CJK_RE.search(line):
                continue
            for term in terms:
                if term in line:
                    line = line.replace(term, "")
            m = CJK_RE.search(line)
            if m:
                hits.append(f"{rel}:{number}: U+{ord(m.group()):04X}")
    return hits


CJK_TERM_PREFIX = "cjk-term:"


def cjk_terms(allow: set[str]) -> set[str]:
    """Словарные единицы из `.revision_allowlist` — форма `cjk-term: <слово>`."""
    return {a[len(CJK_TERM_PREFIX):].strip() for a in allow
            if a.startswith(CJK_TERM_PREFIX) and a[len(CJK_TERM_PREFIX):].strip()}


def selftest_cjk_terms() -> bool:
    """Разрешённый термин молчит, ЛЮБОЙ другой иероглиф в той же строке — нет.

    Канарейка проверяет не «код исполняется», а способность РАЗЛИЧАТЬ: без
    второй половины исключение по термину неотличимо от выключенной проверки.
    """
    import tempfile
    term, alien = chr(0x5927) + chr(0x54E5), chr(0xCF54)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.md").write_text(f"перевод {term} есть в глоссарии\n", encoding="utf-8")
        (root / "b.md").write_text(f"нет{alien}д в русском слове\n", encoding="utf-8")
        allow = {f"{CJK_TERM_PREFIX} {term}"}
        files = [root / "a.md", root / "b.md"]
        hits = check_cjk(root, files, allow)
        return [h.split(":")[0] for h in hits] == ["b.md"]


def selftest_cjk() -> bool:
    """Способность ловить проверяется всегда, даже когда дерево чистое.

    Канарейка, которая никогда не срабатывала, неотличима от сломанной.
    """
    return _is_cjk(chr(0x4E00)) and not _is_cjk("а")


MIXED_CYR = re.compile(r"[А-Яа-яЁё]")
MIXED_LAT = re.compile(r"[A-Za-z]")
# разделители слов внутри имени файла: всё, что не буква и не цифра
MIXED_SPLIT = re.compile(r"[^0-9A-Za-zА-Яа-яЁё]+")


def check_mixed_script_names(root: Path, files: list[Path],
                             allowlist: set[str] | None = None) -> list[str]:
    """Кириллица и латиница в ОДНОМ имени файла — почти всегда слип, а не замысел.

    Нейминг системы: имена латиницей, кириллица только внутри содержимого
    (01-repo-standard.md). Смешение обычно означает, что при наборе транслитерации
    часть слова осталась кириллицей — глазами это не видно, а путь ломает
    предпросмотр у части инструментов (PIT-085). Поймано на живом случае:
    файл ситуации-репорта был создан с кириллическим слогом внутри латинского имени.

    🔴 ЧЕГО НЕ ЛОВИТ: имя целиком на чужом алфавите. `pecypc.md` кириллицей выглядит латинским и смеси не содержит — единственность алфавита проверяется, верность его нет.
    """
    allowlist = allowlist or set()
    bad = []
    for path in files:
        rel = str(path.relative_to(root))
        # Осознанное исключение с записанной причиной — `.revision_allowlist`.
        # Нужно для имён исходных документов (чужая фамилия, версия «V1»),
        # которые переименовывать нельзя: это не наш артефакт.
        # 🔴 Исключение КАТАЛОГОМ, а не только точным именем. Найдено
        # 29.08.2026 при импорте Telegram: `.revision_allowlist` содержал
        # `reports/imports/` с причиной «это чужой материал», а проверка
        # сверяла лишь точное совпадение пути или имени — и краснела
        # на присланном кем-то PDF с опечаткой в названии.
        # Форма `каталог/` уже принята другими проверками; здесь она
        # не работала, то есть исключение было объявлено и не действовало.
        if rel in allowlist or path.name in allowlist:
            continue
        if any(a.endswith("/") and rel.startswith(a) for a in allowlist):
            continue
        # 🔴 Смешение считается ВНУТРИ одного слова, а не по всему имени.
        # Замерено 28.08.2026 по всем 63 репам: правило «есть кириллица и есть
        # латиница где-нибудь в имени» давало **2659 срабатываний, из которых
        # реальным был 1** (точность 0.04 %). Шумели два законных класса:
        #   · расширение — оно ВСЕГДА латиницей (`Синергии_генотипов.docx`),
        #     2117 срабатываний;
        #   · латинская аббревиатура или имя собственное отдельным словом
        #     (`ВКР_магистра_FINPILOT`, `02_IDEF0_новый_стиль`, `README-…`),
        #     ещё ~540.
        # Ни то, ни другое не является слипом. Дефект, ради которого карточка
        # заводилась, другой: кириллический слог ВНУТРИ латинского слова —
        # `README-revizия` (`reviz` + `ия`), глазами неотличимо. Новое правило
        # ловит ровно его. Гейт, который кричит 2659 раз, чтобы быть правым
        # однажды, не читают вовсе — шум такого масштаба хуже молчания.
        stem = path.name
        while "." in stem[1:]:
            stem = stem.rsplit(".", 1)[0]
        for token in MIXED_SPLIT.split(stem):
            if token and MIXED_CYR.search(token) and MIXED_LAT.search(token):
                bad.append(f"{path.relative_to(root)} (слово «{token}»)")
                break
    return bad


def selftest_mixed_script() -> bool:
    """Канарейка `PIT-085`: слип внутри слова ловится, законное соседство — нет.

    Проверяется РАЗЛИЧЕНИЕ. Ужесточение обратно до «есть оба алфавита где-нибудь
    в имени» уронит канарейку на законных именах; ослабление до «никогда» —
    на настоящем слипе.
    """
    import tempfile

    must_flag = [
        "README-revizия.md",          # reviz + кириллическое «ия» — живой случай
        "otchёt.md",                  # ё внутри латинского слова
        "sитуация.md",
    ]
    must_pass = [
        "Синергии_генотипов_Евдокимов.docx",   # латиница только в расширении
        "ВКР_магистра_FINPILOT.docx.md",       # аббревиатура отдельным словом
        "02_IDEF0_новый_стиль.png",
        "README-происхождение.md",
        "plain-latin-name.md",
        "полностью_кириллица.md",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for n in must_flag + must_pass:
            (root / n).write_text("x", encoding="utf-8")
        files = [root / n for n in must_flag + must_pass]
        flagged = {r.split(" (")[0] for r in check_mixed_script_names(root, files)}
    return flagged == set(must_flag)


def check_names(root: Path, files: list[Path]) -> list[str]:
    """Имя файла не несёт порчи вида `#U0418` (`PIT-009`).

    Порча появляется при переносе между файловыми системами: кириллица
    в имени превращается в escape-последовательность, файл перестаёт
    открываться по ссылке.

    🔴 ЧЕГО НЕ ЛОВИТ: имя, читаемое машиной, но бессмысленное для человека
    (`документ1.md`, `новый файл.md`), и имя, разошедшееся с содержанием.
    Осмысленность имени — суждение, гейт его не выносит.
    """
    bad = []
    for path in files:
        if HEX_NAME_RE.search(path.name):
            bad.append(str(path.relative_to(root)))
    return bad


EXEC_BIT_GLOBS = (
    ".claude/hooks/*.sh",
    ".githooks/*",
    "tests/bin/*",
)


def check_exec_bits(root: Path) -> list[str]:
    """Исполняемые стабы/хуки теряют бит `+x` при раунд-трипе через архив/синк (PIT-151).

    Найдено 27.08.2026: `tests/bin/gh` (заглушка `gh` для тестового стенда) лежал
    с правами `-rw-r--r--`. Шелл при резолюции `PATH` **молча пропускает
    неисполняемый файл** и уходит к следующему совпадению — тесты дёрнули настоящий
    `/usr/local/bin/gh`, неавторизованный в песочнице, и 130 кейсов упали с
    правдоподобной, но нерелевантной причиной («code sломан», а не «стенд сломан»).
    В тот же день с теми же правами нашлись ещё два файла (`protect-base-mirror.sh`,
    `ritual-gate.sh`) — владелец зафиксировал это как повторяющийся по СИСТЕМЕ класс,
    не разовую случайность одного файла.

    Проверяется не только `tests/bin/` (где нашли), а весь известный набор мест,
    где неисполняемый файл ломается ТИХО: хуки Claude Code, git-хуки, тестовые стабы.

    🔴 ЧЕГО НЕ ЛОВИТ: файл с битом `+x`, который не запускается: битый shebang, интерпретатор не по адресу. Бит — разрешение, а не работоспособность.
    """
    problems: list[str] = []
    for pattern in EXEC_BIT_GLOBS:
        for p in sorted(root.glob(pattern)):
            if p.is_file() and not os.access(p, os.X_OK):
                problems.append(f"{p.relative_to(root)}: нет +x (PIT-151) — почини: chmod +x {p.relative_to(root)}")
    return problems


def selftest_exec_bits() -> bool:
    """Канарейка (71 §7в): ловит подсаженный неисполняемый файл, молчит на исполняемом."""
    import stat
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "tests" / "bin").mkdir(parents=True)
        bad = root / "tests" / "bin" / "gh"
        bad.write_text("#!/bin/sh\necho stub\n", encoding="utf-8")
        bad.chmod(0o644)
        if not check_exec_bits(root):
            return False                              # обязан поймать
        bad.chmod(bad.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return check_exec_bits(root) == []            # обязан молчать на исполняемом


def check_sizes(root: Path, files: list[Path]) -> tuple[list[str], list[str], float]:
    """Вес дерева и отдельных файлов против порогов.

    🔴 ЧЕГО НЕ ЛОВИТ: **оправданность** веса. 500 МБ медицинских сканов
    и 500 МБ забытых дублей выглядят для проверки одинаково — разницу
    показал только `find_duplicates.py` (29.08.2026: 89 МБ из 528 в
    `health-vault` были копиями). Порог отвечает «много ли», а не «зачем».
    """
    warns: list[str] = []
    fails: list[str] = []
    total = 0
    # 🔴 Размер считается по тому, что ПОПАДЁТ В АРХИВ, а не по всему дереву.
    # Порог 500 МБ заведён ради одного: «Claude берёт архив целиком»
    # (`13-github-limits-and-rendering.md` — у GitHub лимит 5 ГБ, наш строже
    # и по другой причине). Каталоги, которые упаковщик исключает, на эту
    # способность не влияют вовсе.
    #
    # Найдено 29.08.2026: после импорта 17 364 фото три репы вышли за порог,
    # хотя архив `self-map` при 614 МБ на диске весит **144 МБ** — Claude
    # берёт его целиком. Проверка краснела на том, что порог не измеряет.
    #
    # Список синхронизирован с `pack_release.JUNK_DIRS`: расхождение между
    # тем, что упаковщик выбрасывает, и тем, что проверка считает, — это
    # два источника правды об одном (`72`).
    NOT_PACKED = {"telegram-photos", "telegram-media", "photo-archive",
                  "heavy-originals",
                  "node_modules", "dist", "build",
                  ".venv", "venv", ".next", ".turbo", "__pycache__"}
    gi = root / ".gitignore"
    gitignore_lines = (gi.read_text(encoding="utf-8", errors="replace").splitlines()
                       if gi.is_file() else [])
    gitignore_lines = [l for l in gitignore_lines
                       if l.strip() and not l.startswith("#")]

    for path in files:
        size = path.stat().st_size
        mb = size / 1024 / 1024
        rel = path.relative_to(root)
        not_packed = any(part in NOT_PACKED for part in path.parts)

        # 🔴 РАЗМЕР ДЕРЕВА и ЛИМИТ НА ФАЙЛ — РАЗНЫЕ ВОПРОСЫ, и исключение
        # действует только на первый. Найдено 29.08.2026: убрав `heavy-originals`
        # из подсчёта, я заодно ослепил проверку лимита GitHub — а файл 208 МБ
        # никуда не делся и сломал бы push, если бы попал в git.
        #
        # Порог дерева отвечает «возьмёт ли Claude архив целиком» — на него
        # исключённое не влияет. Лимит 100 MiB на файл — жёсткое ограничение
        # GitHub, и оно не знает про наши исключения из архива.
        if not not_packed:
            total += size
        if mb > FAIL_FILE_MB:
            # 🔴 Файл, исключённый из git через `.gitignore`, до GitHub
            # не доедет — значит его лимит не касается. Проверка обязана
            # это знать, иначе краснеет на том, что не может случиться,
            # и через пару прогонов перестаёт читаться (`PIT-085`).
            #
            # Проверяется НАЛИЧИЕ правила, а не работа git: `.gitignore`
            # может быть неточен, и это честная граница проверки.
            ignored = any(line.strip().rstrip("/") and
                          str(rel).startswith(line.strip().rstrip("/"))
                          for line in gitignore_lines)
            if ignored:
                warns.append(f"{rel}: {mb:.1f} МБ — выше лимита GitHub, "
                             f"но исключён через .gitignore: в git не поедет")
            else:
                fails.append(f"{rel}: {mb:.1f} МБ (> {FAIL_FILE_MB} МБ, "
                             f"лимит GitHub рядом)")
        elif mb > WARN_FILE_MB:
            warns.append(f"{rel}: {mb:.1f} МБ (> {WARN_FILE_MB} МБ — кандидат на сжатие, док 06)")
        if path.suffix.lower() in ARCHIVE_SUFFIXES:
            warns.append(f"{rel}: архив в дереве («zip — транспорт», 15-gotchas §2)")
    return warns, fails, total / 1024 / 1024


REPO_META_DESC_MAX = 220


def check_repo_meta_schema(root: Path) -> list[str]:
    """`.repo-meta` — данные без схемы, значит гниёт без напоминаний (ООП-аналогия
    27.08.2026: класс есть, `.repo-class`, а проверки инвариантов полей не было).

    Найдено в тот же день: 12 из ~60 `.repo-meta` несли описание на 200-344 символа —
    «эссе», которое на GitHub-карточке обрезается многоточием посреди предложения.
    Починено руками один раз; без проверки тот же дрейф вернётся молча через месяц —
    `08-automation-triggers.md` «Автоматизация отваливается молча», тот же принцип,
    только про формат поля, а не про запуск скрипта.

    🔴 ЧЕГО НЕ ЛОВИТ: поле по схеме с неверным значением. Схема отвечает за форму: `версия: 0.0.0` при живой репе законна по всем правилам.
    """
    if not (root / "repos-map.md").is_file():
        return []

    problems: list[str] = []
    for p in sorted(root.parent.iterdir()):
        if not p.is_dir() or p == root:
            continue
        meta = p / ".repo-meta"
        if not meta.is_file():
            continue
        text = meta.read_text(encoding="utf-8", errors="replace")
        fields: dict[str, str] = {}
        for line in text.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                fields[k.strip()] = v.strip()

        desc = fields.get("description", "")
        if len(desc) > REPO_META_DESC_MAX:
            problems.append(
                f"{p.name}/.repo-meta: description {len(desc)} символов "
                f"(потолок {REPO_META_DESC_MAX}) — обрежется на GitHub-карточке"
            )

        priv = fields.get("private")
        if priv is not None and priv not in ("true", "false"):
            problems.append(f"{p.name}/.repo-meta: private={priv!r}, должно быть true/false")

        topics = fields.get("topics", "")
        if topics:
            for tok in topics.split(","):
                if tok != tok.strip():
                    problems.append(
                        f"{p.name}/.repo-meta: topics содержит пробел вокруг «{tok.strip()}»"
                    )
                elif not re.match(r"^[a-z0-9][a-z0-9-]*$", tok):
                    problems.append(
                        f"{p.name}/.repo-meta: topic «{tok}» не kebab-case (латиница/цифры/дефис)"
                    )
    return problems


def check_repos_map_sync(root: Path) -> tuple[list[str], list[str]]:
    """`repos-map.md` не должна отставать от того, что реально лежит на диске.

    Найдено 27.08.2026: владелец завёл несколько новых реп и они не были описаны
    в карте — обнаружено не гейтом, а глазами владельца. `deploy.sh` регистрирует
    репу в карте заглушкой при первом деплое (76-repo-classes.md §4.1), но это не
    защищает от разрыва между «репа создана локально» и «репа задеплоена» — а именно
    в этом окне карта отстаёт молча. Проверка здесь — локальная, по `~/repos/`, не по
    `gh repo list`: ловит разрыв на день раньше, до первого деплоя, и не требует сети.

    🔴 ЧЕГО НЕ ЛОВИТ: репу, которая есть и на карте, и на диске, но описана неверно. Сверяется список имён, не то, что про них написано.
    """
    map_file = root / "repos-map.md"
    if not map_file.is_file():
        return ([], [])
    # 🔴 Карта системы — ОДНА, и она принадлежит `base-repo`. Найдено 28.08.2026:
    # проверка запускалась в любой репе, у которой при корне оказался файл с этим
    # именем, — и сравнивала с диском устаревшие снимки карты, лежавшие в корне
    # `academic-portfolio`/`it-base`/`portrait-of-taste` с ранней эпохи. Гейт
    # честно краснел («не хватает 46–54»), но требовал невозможного: чтобы
    # каждая репа вела полную карту системы. Это ровно тот второй источник
    # правды, который ADR запрещает. Шестой случай класса «гейт под один
    # частный мир» (PIT-153/157/158/159).
    repo_id = root / ".repo-id"
    if repo_id.is_file():
        owner = repo_id.read_text(encoding="utf-8", errors="replace").strip()
        if not owner.endswith("/base-repo"):
            return ([], [])

    text = map_file.read_text(encoding="utf-8", errors="replace")
    # Нежадный `[^\n]*?` — у temp-класса в заголовке два backtick-токена
    # («## `algorithms`  ·  родитель `it-base`»), жадный вариант захватывал
    # второй (родителя) вместо имени самой репы (найдено 27.08.2026).
    mapped = set(re.findall(r"^## [^\n]*?`([a-zA-Z0-9._-]+)`", text, re.MULTILINE))

    # Известные постоянные исключения — не заводятся как обычная репа
    # (88-local-repo-location-standard.md §3): не получают `.repo-class`,
    # найти их обходом ~/repos/ нельзя, но в карте они законно есть.
    MAP_STALE_ALLOWLIST = {"finpilot"}

    repos_dir = root.parent
    on_disk = {root.name}  # база описывает сама себя — не самостоятельное расхождение
    for p in repos_dir.iterdir():
        if not p.is_dir() or p.name.startswith("."):
            continue
        if p == root:
            continue
        if (p / ".repo-class").is_file() or (p / ".repo-id").is_file():
            on_disk.add(p.name)

    missing = sorted(on_disk - mapped)
    stale = sorted(mapped - on_disk - MAP_STALE_ALLOWLIST)
    return (missing, stale)


def check_empty_dirs(root: Path) -> list[str]:
    """Пустой каталог — след незавершённой операции.

    Он ничего не ломает, но означает, что что-то перенесли и не убрали
    за собой, либо собирались наполнить и забыли.

    🔴 ЧЕГО НЕ ЛОВИТ: каталог с одним `.gitkeep` или `README.md` — формально
    не пуст, фактически пуст. Отличить «место застолблено намеренно» от
    «забыли» по содержимому нельзя, и проверка намеренно не пытается.
    """
    empty = []
    for path in root.rglob("*"):
        rel_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if path.is_dir() and not any(path.iterdir()):
            empty.append(str(path.relative_to(root)))
    return empty


def check_navigator(root: Path) -> tuple[list[str], int, int]:
    """Навигатор знает обо ВСЕХ пронумерованных документах кита.

    Наблюдение, повторившееся трижды за сутки 21.08.2026: навигатор базы кончался
    на 41 при 78 документах на диске · навигатор mission-control терял колонки с 12-й
    строки и не знал о протоколах 20–21 · реестр ADR не знал о 011. Общая причина одна:
    **правка списка не требуется ни одним гейтом**, поэтому список отстаёт первым.

    Ось ревизии «актуальность» (§2) проверяла содержимое документов, но не полноту
    того, что на них указывает. Навигатор, не знающий половины кита, перестаёт быть
    входом в тему — а выглядит рабочим.

    🔴 ЧЕГО НЕ ЛОВИТ: строку навигатора, называющую документ неверно. Упомянут — значит найден; что описание разошлось с содержимым, видно только человеку.
    """
    nav = root / "00-infrastructure" / "README.md"
    if not nav.is_file():
        return ([], 0, 0)

    text = nav.read_text(encoding="utf-8", errors="replace")
    on_disk = sorted(
        p.name for p in (root / "00-infrastructure").glob("*.md")
        if re.match(r"^\d{2}-", p.name)
    )
    # Упоминанием считается имя файла или его номер в начале строки таблицы —
    # навигаторы в системе ведутся обоими способами.
    missing = []
    for name in on_disk:
        num = name[:2]
        if name in text:
            continue
        if re.search(rf"^\|\s*`?{num}`?\s*\|", text, re.MULTILINE):
            continue
        missing.append(name)
    return (missing, len(on_disk), len(on_disk) - len(missing))


def check_watchlog(root: Path) -> list[str]:
    """Точка входа в вахту не отстала от версии репы.

    PIT-094: версия в шапке §0 поднимается скриптом, тело правится руками — и §0
    четыре версии подряд описывал состояние, которого уже не было, **выглядя свежим**.
    Документ, объявленный точкой входа, обязан иметь машинную проверку свежести:
    без неё он самый опасный файл в репе, потому что выглядит достоверно и врёт.

    Проверяется только машинная половина — совпадение версии. Содержательную свежесть
    машина не проверит, для неё есть ручной приём «три утверждения»
    (04-watchlog-protocol.md).

    🔴 ЧЕГО НЕ ЛОВИТ: точку входа с верной версией и неверным содержанием. Сходятся числа, а не смысл: свежая версия при описании позавчерашнего состояния пройдёт.
    """
    version_file = root / "VERSION"
    watchlog = root / "WATCHLOG.md"
    if not version_file.is_file() or not watchlog.is_file():
        return []

    version = version_file.read_text(encoding="utf-8").strip()
    text = watchlog.read_text(encoding="utf-8", errors="replace")
    # Корневой журнал может быть указателем на настоящий в `docs/` — идём по нему.
    pointed = _follow_pointer(root, watchlog, text)
    if pointed is not None:
        text = pointed.read_text(encoding="utf-8", errors="replace")

    found = re.findall(r"[Тт]екущая точка:\s*\**v?(\d+\.\d+\.\d+)", text)
    if not found:
        return ["в WATCHLOG §0 нет строки «Текущая точка: vX.Y.Z» — §0 не читается "
                "машиной. Починит `bump_repo.py` при следующем подъёме версии"]
    if found[0] != version:
        return [f"WATCHLOG §0 говорит v{found[0]}, а VERSION — {version}: "
                f"точка входа в вахту отстала (PIT-094)"]
    return []


def check_resume_point_content(root: Path, allowlist: set[str] | None = None) -> list[str]:
    """Точка входа не только совпадает по версии, но и остаётся ТОЧКОЙ ВХОДА.

    PIT-116, найдено владельцем 22.08.2026: «мы сто тысяч гейтов сделали, чтобы точка
    входа ВСЕГДА обновлялась, без неё всё ломается». И тем не менее сломалась.

    ПОЧЕМУ СТАРЫЙ ГЕЙТ НЕ ПОМОГ. check_watchlog (PIT-094) сверяет номер версии в §0
    с VERSION. Номер поднимается РИТУАЛОМ, то есть машиной, и потому не отставал никогда —
    гейт был вечно зелёным. Ломалась вторая половина: тело §0 правится руками, разрослось
    до 1291 строки и накопило устаревшее (закрытая кампания описана как «14 из 57»,
    удалённый каталог назван действующим).

        Гейт мерил ту половину, которая не ломается, — и потому не мерил ничего.

    ЧТО МАШИНА МОЖЕТ ПРОВЕРИТЬ В СОДЕРЖАНИИ. Три вещи, каждая механическая:

      1. РАЗМЕР. Точка входа, не влезающая на экран, уже не точка входа — независимо
         от того, что в ней написано. Потолок 80 строк: это примерно два экрана.
      2. МЁРТВЫЕ ПУТИ. §0 ссылается на файл или каталог, которого нет. Прямое
         доказательство, что текст описывает несуществующее состояние.
      3. ОТСТАВШИЕ ВЕРСИИ. §0 упоминает версию, отставшую от текущей больше чем
         на 10 минорных. Свежая точка входа говорит о том, что происходит сейчас.

    ЧЕГО ГЕЙТ НЕ ЛОВИТ (названо, чтобы не считали проверку полной): утверждение,
    устаревшее по смыслу, но без мёртвого пути и без номера версии. Для этого
    остаётся ручной приём «три утверждения» (04-watchlog-protocol.md).
    """
    import re

    watchlog = root / "WATCHLOG.md"
    version_file = root / "VERSION"
    if not watchlog.is_file():
        return []
    text = watchlog.read_text(encoding="utf-8")
    # 🔴 29.08.2026: ФАЙЛ-УКАЗАТЕЛЬ — не пустой файл, и требовать от него
    # содержания нельзя. У `personal-finance-dss` своя продуктовая конвенция:
    # вся документация живёт в `docs/`, и журнал с роадмапом там же; в корне
    # стоят указатели, заведённые ради guard'а доставки (`74-planner-bridge.md`
    # §4а требует `ROADMAP.md` и `TASKS.md` именно в корне). Гейт требовал §0
    # в указателе — то есть требовал ДУБЛЬ, который сам же ловит как второй
    # источник правды (`72`). Указатель распознаётся по ссылке на настоящий
    # файл, и проверка уходит по этой ссылке.
    real = _follow_pointer(root, watchlog, text)
    if real is not None:
        watchlog, text = real, real.read_text(encoding="utf-8", errors="replace")
    # 🔴 Обе конвенции заголовка равноправны: `## §0. Где стоим` и `## §0 — Где стоим`.
    # Замерено 28.08.2026: 53 репы пишут с точкой, **8 — через тире**
    # (`biology`, `chemistry`, `history`, `mathematics`, `nationality`, `physics`,
    # `salvation`, `speed-reading`). Прежняя регулярка требовала точку и для этих
    # восьми возвращала «в WATCHLOG нет секции §0 — точки входа не существует»,
    # хотя §0 у них есть и заполнен. Диагноз был не просто ложным, а
    # противоположным факту, и в том же выводе соседняя проверка сообщала
    # «WATCHLOG §0 совпадает с VERSION» — гейт противоречил сам себе.
    # Тот же класс, что PIT-153/157/158/159/160/085.
    m = re.search(r"^## §0[.\s].*?(?=^## §1[.\s])", text, re.M | re.S)
    if not m:
        return ["в WATCHLOG нет секции §0 — точки входа не существует"]
    body = m.group(0)
    problems = []

    lines = body.splitlines()
    LIMIT = 80
    if len(lines) > LIMIT:
        problems.append(
            f"§0 разросся до {len(lines)} строк при потолке {LIMIT} — "
            f"это архив, а не точка входа (PIT-116)")

    # мёртвые пути: `путь/` или `путь.md` в обратных кавычках
    seen = set()
    for ref in re.findall(r"`([\w./-]+\.(?:md|py|sh|json|tsv|csv)|[\w./-]+/)`", body):
        if ref in seen or ref.startswith(("http", "~")):
            continue
        seen.add(ref)
        if "*" in ref or ref.count("/") > 4:
            continue
        # ищем по имени где угодно в репе — §0 ссылается коротко
        name = ref.rstrip("/").split("/")[-1]
        if (root / ref).exists():
            continue
        if any(True for _ in root.rglob(name)):
            continue
        # 🔴 Ссылка на ЧУЖУЮ репу — не висячая. Найдено 28.08.2026 на пятом
        # подряд срабатывании: `mission-control/BACKLOG.md` в §0 у
        # `dota-dossier`/`health-vault`/`legal-knowledge-base` — это законная
        # кросс-репная ссылка (репы живут рядом в `~/repos/`), а проверка
        # искала файл ВНУТРИ текущей репы и жаловалась. Вахта четыре раза
        # переписывала прозу, чтобы обойти гейт, — то есть чинила журнал под
        # инструмент вместо инструмента. Тот же класс, что PIT-153/157/158.
        first = ref.split("/")[0]
        if first != root.name and (root.parent / first).is_dir():
            sibling = root.parent / ref
            if sibling.exists() or any(True for _ in (root.parent / first).rglob(name)):
                continue
        # Документ базы, названный коротким именем. Так на него ссылаются ВСЕ репы:
        # `83-project-maturity-levels.md`, `71-fail-loud-and-sourcing.md` — это
        # канон, живущий в `base-repo/00-infrastructure/`, и цитировать его
        # коротко — конвенция системы, а не висячая ссылка. Найдено 28.08.2026
        # на `salvation` (продуктовая репа, `_base/` в неё не раздаётся, поэтому
        # локально документа нет и быть не должно).
        base_repo = root.parent / "base-repo"
        if base_repo.is_dir() and base_repo != root:
            if any(True for _ in base_repo.rglob(name)):
                continue
        if ref in (allowlist or set()):
            continue
        # 🔴 Утверждение об ОТСУТСТВИИ — не ссылка. Найдено 29.08.2026 сразу
        # в 6 репах: «импорт разобран, `90-imported/` растворён», «`_base/`
        # наружу не идёт». Журнал обязан фиксировать, что каталога больше нет,
        # — иначе следующая вахта будет искать его заново. Гейт же читал такую
        # фразу как висячую ссылку и требовал вернуть то, что осознанно удалено.
        # Признак берём из САМОГО предложения, а не из списка путей: рядом с
        # упоминанием стоит слово, означающее исчезновение.
        GONE = ("раствор", "удал", "не существует", "больше нет", "снят",
                "наружу не идёт", "упразднён", "расформирован")
        line = next((l for l in body.splitlines() if f"`{ref}`" in l), "")
        if any(w in line.lower() for w in GONE):
            continue
        problems.append(f"§0 ссылается на несуществующее: `{ref}` (PIT-116) — либо поправь путь, либо убери упоминание: точка входа не архив")

    # отставшие версии
    #
    # 🔴 Версия считается СВОЕЙ, только если строка не говорит о чужой репе.
    # Прежняя редакция собирала все `vN.M.x` из §0 подряд и на историческую прозу
    # («`family` → 1.0.0», «`control-panel` [0.13.0]») отвечала «эта репа отстала
    # на 70 минорных». Пункт полгода стоял в ROADMAP как «осознанно не чинится:
    # надёжный regex рискует замолчать реальный дрейф» — но regex и не нужен:
    # список соседних реп лежит на диске, и упоминание чужого имени в строке —
    # факт, а не догадка. Починено 28.08.2026 по прямому вопросу владельца
    # («все ли питфолы обросли сторожами… чтобы не просто сухая теория была»).
    # Седьмой случай класса PIT-153/157/158/159/160/085.
    if version_file.is_file():
        cur = version_file.read_text(encoding="utf-8").strip()
        cm = re.match(r"(\d+)\.(\d+)\.", cur)
        if cm:
            cur_major, cur_minor = int(cm.group(1)), int(cm.group(2))
            siblings = {d.name for d in root.parent.iterdir()
                        if d.is_dir() and d.name != root.name} if root.parent.is_dir() else set()
            own = set()
            for line in body.splitlines():
                if any(s in line for s in siblings):
                    continue          # строка про чужую репу — её версии не наши
                # `[3.61.0]` в квадратных скобках — ЦИТАТА секции CHANGELOG,
                # а не заявление о текущей точке. Это устоявшаяся конвенция
                # системы: «кампания закрыта [3.61.0]» отсылает к записи, где
                # это описано. Требовать от неё свежести — требовать, чтобы
                # журнал не ссылался на собственную историю.
                stripped = re.sub(r"\[\d+\.\d+\.\d+\]", "", line)
                found = re.findall(r"v?(\d+)\.(\d+)\.\d+", stripped)
                own |= {(int(a), int(b)) for a, b in found}
            for vmaj, vmin in own:
                if vmaj == cur_major and cur_minor - vmin > 10:
                    problems.append(
                        f"§0 говорит о v{vmaj}.{vmin}.x при текущей {cur} — "
                        f"отставание {cur_minor - vmin} минорных версий (PIT-116)")
    return problems


# Слова, по которым раздел журнала опознаётся как ЖУРНАЛ ПОСЛЕДНИХ БАТЧЕЙ.
# Не «батч» в одиночку: у `portrait-of-taste` есть раздел «Контекст батчей»,
# где батч — партия анализируемых людей, а не версия репы.
# 🔴 «История вахт» СЮДА НЕ ВХОДИТ, и это разбор, а не недосмотр: у `science`
# и `mission-control` так называется РАСТУЩАЯ ТАБЛИЦА всех версий репы (у
# `science` — с 0.1.0), а правило «ровно 10» описывает СКОЛЬЗЯЩИЙ журнал
# последних изменений. Требовать десяти строк от полной истории значило бы
# требовать стирать историю. Два разных артефакта с похожим названием.
BATCH_LOG_WORDS = ("последние 10", "последних 10", "последние батчи",
                   "последних батчей", "журнал батчей", "хронология батчей")


def find_batch_log(watchlog_text: str) -> str | None:
    """Тело раздела-журнала, если он в этом WATCHLOG вообще есть.

    Возвращает None, когда журнала нет: у большинства реп его и не должно быть,
    и требовать 10 записей от несуществующего раздела бессмысленно.
    """
    lines = watchlog_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("## "):
            if start is not None:
                return "\n".join(lines[start:i])
            low = line.lower()
            if any(w in low for w in BATCH_LOG_WORDS):
                start = i
    return "\n".join(lines[start:]) if start is not None else None


def selftest_batch_log() -> bool:
    """Журнал опознаётся по заголовку; чужой раздел с тем же номером — нет."""
    log = ("## §0. Где стоим\nтекст\n"
           "## §3. Последние батчи\n- **2026-08-29** раз\n"
           "## §4. Прочее\nхвост\n")
    body = find_batch_log(log)
    if body is None or "раз" not in body or "хвост" in body:
        return False
    alien = ("## §3. Что делать НЕЛЬЗЯ\nправила\n"
             "## §4. Контекст батчей\n| таблица |\n")
    if find_batch_log(alien) is not None:
        return False
    # 🔴 Полная история версий журналом последних изменений НЕ является:
    # она растёт, а правило «ровно 10» — про скользящее окно.
    history = ("## §1. История вахт\n| Версия | Дата |\n| 0.1.0 | 2026-08-04 |\n")
    if find_batch_log(history) is not None:
        return False
    return find_batch_log("## §0. Где стоим\nтекст\n") is None


# Указатель — короткий файл, чьё единственное содержание: «настоящий лежит там».
# Признак: файл мал И несёт ссылку на одноимённый файл в подкаталоге.
POINTER_MAX_LINES = 40


def _follow_pointer(root: Path, path: Path, text: str) -> Path | None:
    """Настоящий файл, если этот — указатель на него; иначе None."""
    lines = text.splitlines()
    if len(lines) > POINTER_MAX_LINES:
        return None
    for m in re.finditer(r"\[[^\]]*\]\(([^)]+)\)|`([^`]+)`", text):
        target = (m.group(1) or m.group(2) or "").strip()
        if not target or target.startswith(("http", "#")):
            continue
        if Path(target).name != path.name:
            continue
        candidate = (path.parent / target).resolve()
        if candidate.is_file() and candidate != path.resolve():
            return candidate
    return None


def selftest_pointer_files() -> bool:
    """Указатель распознаётся, обычный короткий файл — нет.

    Вторая половина обязательна: без неё «указателем» станет любой короткий
    файл, и проверка перестанет требовать содержания вообще.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "docs").mkdir()
        real = root / "docs" / "WATCHLOG.md"
        real.write_text("## §0. Где стоим\nтекст\n## §1. Прочее\n", encoding="utf-8")
        ptr = root / "WATCHLOG.md"
        ptr.write_text("# Указатель\n\nНастоящий журнал — [`docs/WATCHLOG.md`](docs/WATCHLOG.md).\n",
                       encoding="utf-8")
        if _follow_pointer(root, ptr, ptr.read_text(encoding="utf-8")) != real.resolve():
            return False
        # Короткий файл БЕЗ ссылки на одноимённый — не указатель.
        plain = root / "ROADMAP.md"
        plain.write_text("# Роадмап\n\n- [ ] что-то\n", encoding="utf-8")
        if _follow_pointer(root, plain, plain.read_text(encoding="utf-8")) is not None:
            return False
        # Длинный файл со ссылкой — тоже не указатель, это документ.
        long_one = root / "TASKS.md"
        long_one.write_text("см. [`docs/TASKS.md`](docs/TASKS.md)\n" + "строка\n" * 60,
                            encoding="utf-8")
        return _follow_pointer(root, long_one, long_one.read_text(encoding="utf-8")) is None


def check_living_documents(root: Path) -> list[str]:
    """Живые документы обязаны отражать текущее состояние — проверяется машиной.

    PIT-116, заказ владельца 22.08.2026: «сделай как можно больше проверок на то, чтобы
    ВСЕГДА поддерживались и обновлялись: точка входа, вотчлог, ридми».

    ПОЧЕМУ ЭТО ОТДЕЛЬНЫЙ КЛАСС. Замороженный документ устаревает заметно: он про прошлое
    и не претендует на большее. Живой документ устаревает НЕЗАМЕТНО — он выглядит
    описанием настоящего и читается как оно. Чем он важнее, тем дороже его молчаливая ложь.

        Самый опасный файл в репе — не пустой и не сломанный, а тот, который выглядит
        достоверно и врёт.

    ЧТО ПРОВЕРЯЕТСЯ (каждая — механическая, без суждения):

      1. §3 журнала держит РОВНО 10 записей. Правило записано в шапке самого §3
         и не исполнялось 32 версии подряд, потому что исполнителя у него не было.
      2. CHANGELOG имеет секцию текущей версии. Версия поднята, а записи нет —
         значит поднята вхолостую.
      3. README несёт блок статуса с текущей версией (детально — readme_status_gate.py).
      4. ROADMAP: указатель «СЛЕДУЮЩАЯ ЗАДАЧА» существует и не пуст.
      5. Реестр ADR совпадает с составом каталога. Найдено 22.08: реестр отстал на две
         записи, поймала случайная коллизия номера, а не проверка.

    ЧЕГО НЕ ЛОВИТ: содержательное устаревание без структурного следа. Для него —
    ручной приём «три утверждения» (04-watchlog-protocol.md).
    """
    import re

    problems = []
    version = (root / "VERSION").read_text(encoding="utf-8").strip() \
        if (root / "VERSION").is_file() else None

    # --- 1. Журнал последних батчей: ровно 10 записей -------------------------
    # 🔴 29.08.2026: проверка опознавала журнал ПО НОМЕРУ раздела — искала
    # ровно `## §3.` и требовала внутри 10 датированных записей. Номер оказался
    # плохим признаком: у большинства реп (`science`, `it-base`, `dota-dossier`)
    # раздела §3 нет вовсе, и проверка молча пропускала их; у `portrait-of-taste`
    # §3 называется «Что делать НЕЛЬЗЯ», а §4 — «Контекст батчей», где слово
    # «батч» означает партию анализируемых людей, а не версию. Итог: репа
    # краснела за то, что её §3 не является журналом, которым он и не назывался.
    # Опознаём журнал ПО ЗАГОЛОВКУ, как и всё остальное в этом гейте.
    watchlog = root / "WATCHLOG.md"
    if watchlog.is_file():
        text = watchlog.read_text(encoding="utf-8")
        section = find_batch_log(text)
        if section is not None:
            # Время опционально: записи до 03.09.2026 законны без него.
            # Без `(?:...)?` запись со временем не считалась бы записью вовсе,
            # и гейт объявил бы журнал неполным — ложь, выглядящая находкой.
            entries = re.findall(
                r"^- \*\*\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?\*\*", section, re.M)
            if len(entries) != 10:
                problems.append(
                    f"журнал последних батчей держит {len(entries)} записей "
                    f"вместо 10 — правило в шапке самого раздела (PIT-116)")

    # --- 2. CHANGELOG: секция текущей версии ---------------------------------
    changelog = root / "CHANGELOG.md"
    if version and changelog.is_file():
        # 🔴 29.08.2026: проверка требовала ровно `[1.22.0]` — конвенцию
        # Keep a Changelog — и валила `exam-kit`, который с 07.2026 ведёт
        # журнал в столь же законной форме `## v1.22.0 — дата`. Секция там
        # ЕСТЬ, а гейт сообщал «версия поднята без записи»: он проверял не
        # наличие записи, а совпадение с одной из двух живых конвенций.
        # Тот же класс, что перечень схем URI и дословные заголовки отчётов:
        # проверять надо предмет, а не его оформление.
        text = changelog.read_text(encoding="utf-8")
        if f"[{version}]" not in text and not re.search(
                rf"^#{{1,3}}\s+v?{re.escape(version)}\b", text, re.M):
            problems.append(
                f"CHANGELOG.md не содержит секции [{version}] — "
                f"версия поднята без записи (PIT-116)")

    # --- 3. README: блок статуса с текущей версией ----------------------------
    readme = root / "README.md"
    if version and readme.is_file():
        rt = readme.read_text(encoding="utf-8")
        if "<!-- STATUS -->" not in rt:
            problems.append("README.md без блока <!-- STATUS --> (75 §1)")
        elif f"`v{version}`" not in rt:
            problems.append(
                f"README.md: блок статуса не назвал v{version} — "
                f"витрина отстала от VERSION (PIT-116)")

    # --- 4. ROADMAP: указатель следующей задачи ------------------------------
    roadmap = root / "ROADMAP.md"
    if roadmap.is_file():
        rm = roadmap.read_text(encoding="utf-8")
        # Тот же случай, что с журналом выше: корневой `ROADMAP.md` может быть
        # указателем на настоящий план в `docs/`. Требовать указатель следующей
        # задачи от файла-указателя — требовать дубль.
        pointed = _follow_pointer(root, roadmap, rm)
        if pointed is not None:
            rm = pointed.read_text(encoding="utf-8", errors="replace")
        # Указатель принимается и по-английски: публичные витринные репы
        # (`claude-usage` и др.) ведутся на английском по замыслу — там стоит
        # «NEXT TASK:», и это тот же указатель, а не его отсутствие. Найдено
        # 28.08.2026 при сплошной проверке: 1 репа из 63 фейлилась по языку,
        # а не по существу. Тот же класс, что PIT-153/157/158 — проверка,
        # откалиброванная под один частный мир (здесь: под русский язык).
        if not any(k in rm for k in ("СЛЕДУЮЩАЯ ЗАДАЧА", "NEXT TASK")):
            problems.append(
                "ROADMAP.md без указателя «СЛЕДУЮЩАЯ ЗАДАЧА» / «NEXT TASK» — "
                "непонятно, с чего продолжать (30-roadmap-protocol.md)")

    # --- 5. Реестр ADR совпадает с каталогом ----------------------------------
    adr_dir = root / "reports" / "adr"
    adr_readme = adr_dir / "README.md"
    if adr_dir.is_dir() and adr_readme.is_file():
        files = {p.stem for p in adr_dir.glob("adr_[0-9]*.md")}
        listed = set(re.findall(r"adr_\d+[\w-]*", adr_readme.read_text(encoding="utf-8")))
        missing = files - listed
        if missing:
            problems.append(
                f"реестр ADR не содержит {len(missing)} записей: "
                f"{', '.join(sorted(missing))} (PIT-116)")

    return problems


def check_registry_dupes(root: Path) -> list[str]:
    """Сквозные реестры не содержат повторяющихся номеров.

    72-source-of-truth.md §4а: четыре аккаунта работают параллельно и не видят чужих
    чатов. Для ВЕРСИЙ спасает GitHub — общее место, где номер видно занятым. Для реестров
    внутри репы общего места нет: две вахты честно берут «следующий» номер от того, что
    видят, и коллизия обнаруживается только после слияния.

    Случай, из которого правило: в exam-kit задвоились и версия `v1.9.0`, и урок `L-016` —
    обе линии нумерации сразу, обе разводили задним числом. Проверка там стоит в
    `build/release.sh` (`grep … | sort | uniq -d`) и стоит одну команду.

    Дубль номера не ломает файл и не виден при чтении: две карточки с одним номером
    выглядят нормально каждая по отдельности. Ломается адресация — ссылка «см. PIT-089»
    перестаёт указывать на одно место.

    🔴 ЧЕГО НЕ ЛОВИТ: дыру в нумерации. Повтор виден, пропуск — нет: №14 после №12 проходит молча.
    """
    registries = [
        ("PIT", card_registry(root, "PIT"), card_re("PIT", capture=True)),
        ("SYN", card_registry(root, "SYN"), card_re("SYN", capture=True)),
        ("CHANGELOG", root / "CHANGELOG.md", r"^##\s+\[(\d+\.\d+\.\d+)\]"),
    ]
    problems: list[str] = []
    for label, path, pattern in registries:
        if not path.is_file():
            continue
        found = re.findall(pattern, path.read_text(encoding="utf-8", errors="replace"), re.M)
        seen: set[str] = set()
        dupes = sorted({x for x in found if x in seen or seen.add(x)})
        if dupes:
            problems.append(f"{label} ({path.name}): повторяются {', '.join(dupes)}")

    adr_dir = root / "reports" / "adr"
    if adr_dir.is_dir():
        nums = [m.group(1) for p in adr_dir.glob("adr_*.md")
                if (m := re.match(r"adr_(\d+)_", p.name))]
        seen = set()
        dupes = sorted({x for x in nums if x in seen or seen.add(x)})
        if dupes:
            problems.append(f"ADR: два файла с номером {', '.join(dupes)}")
    return problems


def selftest_registry_dupes() -> bool:
    """Та же канарейка, что у CJK: проверка, которая никогда не краснела, — не проверка.

    Реестры базы обычно чисты, значит `check_registry_dupes` в норме всегда возвращает
    пусто — и сломайся регулярка, гейт молча оставался бы зелёным (71 §7в).
    Здесь на временном дереве подсаживается по дублю в каждый из четырёх реестров.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "reports" / "adr").mkdir(parents=True)
        (root / "05-infra-synthesis-lab").mkdir()
        (root / "reports" / "pitfalls.md").write_text(
            "### PIT-001 — раз\n### PIT-002 — два\n### PIT-001 — дубль\n", encoding="utf-8")
        (root / "05-infra-synthesis-lab" / "PITFALLS.md").write_text(
            "## SYN-001 — раз\n## SYN-001 — дубль\n", encoding="utf-8")
        (root / "CHANGELOG.md").write_text(
            "## [1.0.0] — x\n## [1.0.0] — дубль\n", encoding="utf-8")
        (root / "reports" / "adr" / "adr_001_a.md").write_text("", encoding="utf-8")
        (root / "reports" / "adr" / "adr_001_b.md").write_text("", encoding="utf-8")

        caught = check_registry_dupes(root)
        # Ловится каждый из четырёх реестров, а не «хоть что-нибудь»:
        # общая проверка `len(caught) > 0` прошла бы и при трёх сломанных из четырёх.
        return len(caught) == 4 and not check_registry_dupes(Path(tmp) / "nonexistent")


SECTION_TOKEN = re.compile(r"^[0-9][0-9A-Za-zА-Яа-яЁё.\-]*\.?$")
# Заголовок-дата — это запись журнала, а не номер раздела: повтор даты законен.
# Заголовок-ДАТА повтором раздела не является: журнал решений может нести
# несколько записей за один день, и это норма, а не сломанная адресация.
# 🔴 29.08.2026: регулярка знала только ISO (`2026-08-04`) и валила
# `master-admission/docs/decisions.md`, где даты записаны по-русски через
# точку (`02.06.2026`) — три решения за 2 июня. Формат записи даты к предмету
# проверки отношения не имеет.
SECTION_DATE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}|~?\d{2}\.\d{2}\.\d{4}|~?\d{2}\.\d{2}\.\d{2})\.?$")
# Осознанные исключения: относительный путь -> причина. Каждая строка проверяется
# на существование файла (selftest), чтобы исключение не пережило свой предмет.
# 🔴 29.08.2026: ПЕРЕЧЕНЬ ЗАМЕНЁН ПРАВИЛОМ. Здесь стоял жёсткий словарь из
# четырёх путей base-repo, и у всех четырёх причина была ОДНА — «конкатенация
# нескольких документов, нумерация источников сохранена намеренно». Перечень
# закрывал ровно те файлы, которые кто-то однажды увидел: тот же самый
# `СБОРКА_всё.md`, лежащий копией в `misc-vault`, краснел, потому что его путь
# в словарь не попал. Признак конкатенации структурный, его незачем перечислять.
#
# ПРАВИЛО: **больше одного заголовка первого уровня = это сборка, а не документ.**
# У обычного документа ровно один `# `. Повтор `## 1` в сборке неизбежен и
# чинится только переписыванием чужих исходников — то есть не чинится.
#
# 🔴 Код-блоки вырезаются ДО подсчёта, и это не мелочь: `it-base/…/vk-graph/
# README.md` несёт внутри примера строку `# Вставь токен в .env` — комментарий
# bash, не заголовок. Без вырезания файл сошёл бы за сборку и **скрыл настоящий
# дефект**: у него два разных `### 3` («Запуск через Docker» и «Запуск локально»),
# и читатель, идущий по «шагу 3», попадает не туда. Правило обязано отличать
# сборку от документа с реальным дефектом — это и проверяет канарейка.
SECTION_DUPES_ALLOWLIST: dict[str, str] = {}


def is_assembly(text: str) -> bool:
    """Сборка нескольких документов в один файл — повторы нумерации неизбежны."""
    body = strip_code_fences(text)
    return sum(1 for line in body.splitlines() if line.startswith("# ")) > 1


def check_section_dupes(root: Path, files: list[Path]) -> list[str]:
    """Внутри одного документа номер раздела не повторяется.

    Класс тот же, что у check_registry_dupes, но адресация ломается ВНУТРИ файла:
    два раздела с одним номером выглядят нормально каждый по отдельности, а ссылка
    «см. §6» перестаёт указывать на одно место. Читающий переходит по ней и попадает
    туда, куда попал первым, — молча и без признака ошибки.

    Живые случаи: 69-agents-hooks-and-gates.md нёс два раздела `## 4а`, причём обе
    нумерации уже стояли в живых ссылках (найдено v1.89.0); 65-visual-source-pipeline.md
    нёс два `## 6` (найдено v1.94.0, через пять версий после того, как класс был
    известен). Первый случай починили поштучно и класс не подмели — отсюда эта проверка.

    Считается пара (уровень заголовка, номер): `## 6` и `### 6.1` не конфликтуют.
    Заголовки без номера («### 🔴 …») и шаблонные («## [X.Y.Z] — …») пропускаются.

    🔴 ЧЕГО НЕ ЛОВИТ: два раздела с разными номерами и одинаковым содержанием. Уникальность номера — не уникальность мысли.
    """
    problems: list[str] = []
    for path in files:
        if path.suffix != ".md":
            continue
        rel = path.relative_to(root)
        rel_posix = rel.as_posix()
        if is_frozen(rel):
            continue
        raw = path.read_text(encoding="utf-8", errors="replace")
        # Сборка нескольких документов — повторы нумерации в ней неизбежны
        # и не чинятся. Признак структурный, не списочный: см. `is_assembly`.
        # 🔴 Прежняя редакция вместо этого держала словарь из четырёх путей
        # base-repo и не покрывала их же копии в других репах (`PIT-142`,
        # «копия видна под другим путём»).
        if is_assembly(raw):
            continue
        text = strip_code_fences(raw)
        seen: dict[tuple[str, int, str], int] = {}
        dupes: list[str] = []
        # 🔴 29.08.2026: номер подраздела считается В ПРЕДЕЛАХ СВОЕГО РАЗДЕЛА,
        # а не через весь файл. Прежняя редакция сравнивала пару (уровень,
        # номер) глобально — и валила учебные работы `academic-portfolio`,
        # где под `## 4 РЕАЛИЗАЦИЯ` идёт перечисление `### 1 … ### 5`, а под
        # `## 6 ЭКОНОМИКА` — своё `### 1 … ### 3`. Это НЕ двусмысленность:
        # ссылка «§4, пункт 1» указывает ровно в одно место, и переномеровать
        # сданную курсовую ради гейта было бы правкой текста под проверку
        # (`PIT-159`). Ломается адресация только когда номер повторяется
        # у ОДНОГО родителя — вот это и ловится.
        parent = ""
        for line in text.splitlines():
            m = re.match(r"^(#{2,3})\s+(\S+)(?:\s|$)", line)
            if not m:
                continue
            level, token = len(m.group(1)), m.group(2)
            if level == 2:
                parent = line.strip()
            if not SECTION_TOKEN.match(token) or SECTION_DATE.match(token):
                continue
            # У `##` родителя нет — область видимости весь файл.
            scope = "" if level == 2 else parent
            key = (scope, level, token.rstrip("."))
            seen[key] = seen.get(key, 0) + 1
            if seen[key] == 2:
                where = f" (внутри «{parent.lstrip('# ')[:40]}»)" if scope else ""
                dupes.append(f"{'#' * level} {key[2]}{where}")
        if dupes:
            problems.append(f"{rel}: повторяются разделы {', '.join(dupes)}")
    return problems


def selftest_section_dupes() -> bool:
    """Канарейка (71 §7в). В норме проверка всегда пуста — значит её поломка невидима.

    Требуется ровно ДВА срабатывания на двух разных файлах и ноль на чистом:
    условие `len(caught) > 0` прошло бы и при одной сломанной половине.
    Отдельно проверяется, что подраздел `### 6.1` не считается дублем `## 6`
    и что шаблонный заголовок `## [X.Y.Z]` не ловится.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bad1 = root / "a.md"
        bad1.write_text("## 6. Раз\n## 6. Два\n", encoding="utf-8")
        bad2 = root / "b.md"
        bad2.write_text("## 4а. Раз\n### x\n## 4а. Два\n", encoding="utf-8")
        good = root / "c.md"
        good.write_text(
            "## 6. Раз\n### 6.1 Подраздел\n### 6.1а Ещё\n## 7. Два\n"
            "## [X.Y.Z] — шаблон\n## [X.Y.Z] — второй шаблон\n"
            "### 🔴 Без номера\n### 🔴 Тоже без номера\n",
            encoding="utf-8")
        good.write_text(good.read_text(encoding="utf-8")
                        + "## 2026-08-04 — запись\n## 2026-08-04 — вторая запись\n",
                        encoding="utf-8")
        # 🔴 Половина канарейки, добавленная 29.08.2026 вместе с заменой
        # перечня исключений правилом. Проверяются ОБЕ стороны различения:
        # сборка (два `# `) прощается, а документ, где второй `# ` — это
        # комментарий bash внутри код-блока, проверяется как обычный и
        # свой настоящий дефект не прячет. Без второй половины правило
        # неотличимо от «прощать всё, где есть решётка в тексте».
        assembly = root / "d.md"
        assembly.write_text("# Док один\n## 1. Раз\n\n# Док два\n## 1. Раз\n",
                            encoding="utf-8")
        # 🔴 Половина канарейки про область видимости. Без неё правило
        # неотличимо от «прощать любые повторы подразделов».
        scoped = root / "f.md"
        scoped.write_text(
            "# Работа\n"
            "## 4 РЕАЛИЗАЦИЯ\n### 1. Раз\n### 2. Два\n"
            "## 6 ЭКОНОМИКА\n### 1. Раз\n### 2. Два\n",
            encoding="utf-8")
        if check_section_dupes(root, [scoped]) != []:
            return False
        broken_scope = root / "g.md"
        broken_scope.write_text(
            "# Работа\n## 4 РЕАЛИЗАЦИЯ\n### 1. Раз\n### 1. Тоже раз\n",
            encoding="utf-8")
        if len(check_section_dupes(root, [broken_scope])) != 1:
            return False

        fenced = root / "e.md"
        fenced.write_text("# README\n### 3. Docker\n```bash\n"
                          "# Вставь токен в .env\n```\n### 3. Локально\n",
                          encoding="utf-8")
        caught = check_section_dupes(root, [bad1, bad2, good, assembly, fenced])
        names = {c.split(":")[0] for c in caught}
        return (len(caught) == 3 and "c.md" not in names
                and "d.md" not in names and "e.md" in names)


# Числа, которые пишутся в прозе руками и потому устаревают молча (PIT-091).
# Каждая тройка: подпись · как посчитать по диску · регулярка поиска в прозе.
# Регулярка обязана иметь ровно одну группу — само число.
PROSE_COUNTS = (
    ("карточек PIT", lambda root: _count_matches(root / "reports" / "pitfalls.md", card_re("PIT")),
     # 🔴 Без привязки к `**`. Прежняя регулярка требовала жирный шрифт
     # НЕПОСРЕДСТВЕННО перед числом — и пропустила расхождение 148 против 151
     # в том же README, потому что во второй записи звёздочки стояли раньше:
     # `**`pitfalls.md`, 148 карточек`. Проверка зависела от оформления,
     # а не от смысла, и молчала при живом расхождении. Найдено 29.08.2026
     # при сборе метрик для оценки системы.
     r"(\d+)\s+карточ\w*\s+`?PIT-NNN`?"),
    ("карточек SYN", lambda root: _count_matches(root / "05-infra-synthesis-lab" / "PITFALLS.md", card_re("SYN")),
     r"(\d+)\s+карточ\w*\s+`?SYN-NNN`?"),
    ("документов кита", lambda root: len(list((root / "00-infrastructure").glob("[0-9][0-9]-*.md"))),
     r"\*\*(\d+)\s+документ\w*\*\*"),
)
PROSE_FILES = ("README.md", "00-infrastructure/README.md", "START-HERE.md")


def _count_matches(path: Path, pattern: str) -> int:
    if not path.is_file():
        return -1
    return len(re.findall(pattern, path.read_text(encoding="utf-8", errors="replace"), re.M))


CAMPAIGN_ACTIVE_DAYS = 30   # кампания считается живой, если журнал прогона трогали недавно


def _newest_run(root: Path) -> Path | None:
    runs = root / "05-infra-synthesis-lab" / "runs"
    if not runs.is_dir():
        return None
    dirs = [d for d in runs.iterdir() if d.is_dir() and (d / "decisions.md").is_file()]
    return max(dirs, key=lambda d: (d / "decisions.md").stat().st_mtime) if dirs else None


def check_campaign_log(root: Path) -> list[str]:
    """Пока идёт кампания синтеза, каждая версия обязана оставить след в её журнале.

    ПОЧЕМУ ЭТО ГЕЙТ, А НЕ ПРАВИЛО. Правило существовало и было записано трижды:
    `00-CLAUDE-STOP.md` §Пятое («записывай находки В МОМЕНТ, не в конце сессии —
    токены кончаются внезапно»), `05-infra-synthesis-lab/STANDARD.md` §0а (триггеры),
    `18-documentation-philosophy.md` §10 («потом задокументирую» — точка потери).
    Владельцу всё равно приходилось напоминать вслух. Правило без исполнителя —
    обещание (`21-revision-protocol.md` §4г), и здесь исполнителем становится гейт:
    подъём версии физически не проходит, пока в журнале прогона нет записи этой даты.

    ЧТО ИМЕННО ПРОВЕРЯЕТСЯ. Дата верхней записи `CHANGELOG.md` обязана встречаться
    в `decisions.md` свежего прогона. Проверка по СОДЕРЖАНИЮ, а не по времени файла:
    `mtime` меняется от любого касания, в том числе от `--fix` соседнего гейта,
    и такую проверку легко пройти случайно (`71` §7в).

    КАК ЗАКРЫТЬ ЧЕСТНО, ЕСЛИ КАМПАНИЯ В ЭТОЙ ВЕРСИИ НЕ ДВИГАЛАСЬ. Написать это строкой
    в `decisions.md` с сегодняшней датой. Это не формальность: «в этой версии по репам
    не работали, занимались гейтами» — такой же результат прогона, как находка,
    и следующая вахта по нему видит, что пауза была осознанной, а не забытой.

    🔴 ПОТОЛОК (`71` §7г-бис): гейт видит ФАКТ записи, но не её содержательность.
    Строку-заглушку он пропустит. Он закрывает «забыл записать», а не «записал плохо» —
    второе ловится ревизией и признаками из `00-CLAUDE-STOP.md` §Пятое
    (записей меньше, чем прочитано файлов; ноль новых карточек за прогон).

    🔴 ЧЕГО НЕ ЛОВИТ: отписку. Строка «кампания не двигалась» проходит ровно так же, как содержательный отчёт о продвижении: гейт требует следа, а не работы.
    """
    import datetime

    run = _newest_run(root)
    chlog = root / "CHANGELOG.md"
    if run is None or not chlog.is_file():
        return []

    dec = run / "decisions.md"
    age_days = (datetime.datetime.now().timestamp() - dec.stat().st_mtime) / 86400
    if age_days > CAMPAIGN_ACTIVE_DAYS:
        return []                       # кампания не идёт — гейт молчит

    head = chlog.read_text(encoding="utf-8", errors="replace")[:4000]
    m = re.search(r"^##\s+\[(\d+\.\d+\.\d+)\]\s*[—–-]\s*(\d{4}-\d{2}-\d{2})", head, re.M)
    if not m:
        return ["верхняя запись CHANGELOG.md без версии и даты — гейт кампании не может проверить"]
    version, date = m.group(1), m.group(2)

    if date in dec.read_text(encoding="utf-8", errors="replace"):
        return []
    return [f"v{version} от {date}: в {dec.relative_to(root)} нет ни одной записи этой даты. "
            f"Идёт кампания — версия не закрывается без следа в её журнале "
            f"(00-CLAUDE-STOP.md §Пятое). Кампания не двигалась — так и написать строкой."]


def selftest_campaign_log() -> bool:
    """Канарейка (71 §7в): нужны ОБА исхода и молчание на неактивной кампании."""
    import tempfile, datetime, os

    today = datetime.date.today().isoformat()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run = root / "05-infra-synthesis-lab" / "runs" / "2026-01-01-run"
        run.mkdir(parents=True)
        dec = run / "decisions.md"
        chlog = root / "CHANGELOG.md"
        chlog.write_text(f"# CHANGELOG\n\n## [9.9.9] — {today} — тезис (MINOR)\n", encoding="utf-8")

        dec.write_text("журнал без сегодняшней записи\n", encoding="utf-8")
        if not check_campaign_log(root):
            return False                                  # обязан краснеть

        dec.write_text(f"## {today} — репа N: сделано то-то\n", encoding="utf-8")
        if check_campaign_log(root):
            return False                                  # обязан молчать

        old = datetime.datetime.now().timestamp() - (CAMPAIGN_ACTIVE_DAYS + 5) * 86400
        dec.write_text("старый прогон\n", encoding="utf-8")
        os.utime(dec, (old, old))
        return check_campaign_log(root) == []             # кампания не идёт — молчит


def check_journals(root: Path) -> list[str]:
    """Журналы системы: порядок событий и учёт (`00-infrastructure/94`).

    🔴 ПОЧЕМУ ГЕЙТ, А НЕ ПРАВИЛО. Стандарт запрещает переставлять строки
    журнала событий, но запрет без исполнителя есть обещание (`21` §4г).
    Нарушение при этом невидимо глазом: журнал на 517 строк после сортировки
    выглядит ровно так же, а производная — темп работы, ряд замеров, интервалы
    между батчами — уже уничтожена.

    Проверяет ПЕРЕСТАНОВКУ и УЧЁТ, не правдивость: полный разбор границ —
    в докстроке `journal_audit.py`, здесь он не пересказывается, чтобы
    не разойтись с ней.
    """
    if not (root / "scripts" / "journal_audit.py").is_file():
        return []                       # не база — предмета нет
    sys.path.insert(0, str(root / "scripts"))
    try:
        import journal_audit
    except Exception as exc:            # noqa: BLE001
        return [f"аудит журналов не запускается: {exc}"]
    return journal_audit.audit()


def selftest_journals(root: Path) -> bool:
    """Канарейка: ловит ли проверка подсаженную перестановку."""
    sys.path.insert(0, str(root / "scripts"))
    try:
        import journal_audit
    except Exception:                   # noqa: BLE001
        return True                     # модуля нет — сторожить нечего
    return journal_audit.selftest()


def check_orphans(root: Path) -> list[str]:
    """Документы, на которые не ссылается ни один файл базы.

    🔴 ЗАЧЕМ ГЕЙТ. Недостижимый документ не «лежит про запас» — **его не
    найдут**. Работа сделана и оплачена токенами, а следующая вахта начнёт
    заново, потому что не узнает о ней. Класс `PIT-176`: невидимое не станет
    красным, оно перестанет существовать для того, кто ищет.

    Замер перед заведением (04.09.2026): **14 недостижимых** из 578 файлов,
    среди них три исследования по безопасности и три расследования. Причина
    оказалась глубже забывчивости — **в четырёх каталогах не было навигатора
    вовсе**, и ссылку было некуда положить.

    Все 14 разобраны, гейт заведён на ноле. Порядок обязателен: гейт,
    рождающийся красным, отключают в тот же день.

    🔴 ЧЕГО НЕ ЛОВИТ (`71` §7г-бис) — границы наследуются у `refs_index`:
    ссылку по номеру («см. `71` §7ж» не содержит имени файла), ложные
    совпадения частых имён, и главное — **упоминание не есть польза**.
    Гейт отвечает «на что не ссылаются», а не «что не нужно».
    """
    if not (root / "scripts" / "refcount.py").is_file():
        return []                       # не база — предмета нет
    sys.path.insert(0, str(root / "scripts"))
    try:
        import refs_index
        import refcount
    except Exception as exc:            # noqa: BLE001
        return [f"счётчик ссылок не запускается: {exc}"]
    corpus = refs_index.build(root)
    cand = [rel for rel, _ in corpus if rel.name not in refcount.ROOTS]
    return [str(rel) for rel in refs_index.unreferenced(cand, corpus)]


def check_runtime_writes(root: Path) -> list[str]:
    """Инструмент пишет в раздаваемый набор — объявлен ли этот файл.

    🔴 ПОЧЕМУ ГЕЙТ. Необъявленный журнал не молчит — он врёт: копии начинают
    показываться «разошедшимися» после каждого запуска инструмента, и вахта
    читает это как «раздача не запускалась». Сигнал громкий, но указывает
    не туда, а такой хуже тихого: по нему принимают неверное действие
    (гонят раздачу заново) и оно «помогает» до следующего запуска.

    ЧТО ПРОВЕРЯЕТСЯ: каждый литеральный путь записи внутрь раздаваемого
    набора либо объявлен исключением, либо помечен `канон:` — то есть
    разобран вахтой, а не пропущен.

    🔴 ЧЕГО НЕ ЛОВИТ: путь из переменной или аргумента (`runtime_writes.
    scan_writers` называет это своей докстрокой) и запись из shell.
    Гейт закрывает «завёл журнал и забыл про раздачу», а не «спрятал путь».
    """
    # 🔴 Проверка ТОЛЬКО для базы. У наследника раздатчик лежит в `_base/`,
    # своего раздаваемого набора у него нет, и спрашивать с него объявления
    # значило бы требовать исполнения правила, которого он не адресат.
    # Молчание здесь — не пропуск: у репы просто нет предмета проверки.
    if not (root / "scripts" / "sync_base_local.py").is_file():
        return []
    sys.path.insert(0, str(root / "scripts"))
    try:
        import runtime_writes
        from sync_base_local import _distribute
    except Exception as exc:                          # noqa: BLE001
        return [f"перепись runtime-записей не запускается: {exc}"]
    bad = runtime_writes.undeclared(root, _distribute())
    return [f"{rel} ← пишет {who}; объявить в <каталог>/.runtime-writes "
            f"или пометить `канон:`" for rel, who in bad]


def selftest_runtime_writes(root: Path) -> bool:
    """Канарейка признака: различает объявленное и необъявленное."""
    sys.path.insert(0, str(root / "scripts"))
    try:
        import runtime_writes
    except Exception:                                 # noqa: BLE001
        return True     # модуля нет — это не база, канарейке нечего сторожить
    return runtime_writes.selftest()


def check_dangling_registry_refs(root: Path, files: list[Path]) -> list[str]:
    """Ссылка `PIT-NNN` / `SYN-NNN` в пределах СВОЕЙ нумерации ведёт на живую карточку.

    Дубль номера ломает адресацию в одну сторону (PIT-098), пропажа карточки — в другую:
    ссылка остаётся, цель исчезает, читающий видит номер, которого нигде нет.
    Линк-чекер этого не ловит: это не markdown-ссылка, а номер в прозе.

    🔴 ПОТОЛОК ПРОВЕРКИ, названный вслух (71 §7г-бис). Синтаксис `PIT-NNN` в системе
    обозначает И свою карточку, И чужую: `reports/pitfalls.md` штатно цитирует источники
    как «`portrait-of-taste` (portrait-of-taste:PIT-114)», где 114 — номер в ЧУЖОЙ нумерации. Различить
    их по тексту нельзя — нотация одна. Поэтому проверяется только диапазон
    **1…max(своих номеров)**: внутри него номер заведомо адресует свою карточку,
    выше — чужое пространство имён (`portrait-of-taste` держит portrait-of-taste:PIT-101…116 намеренно).

    Следствие потолка: когда своя нумерация дорастёт до чужого диапазона, проверка
    начнёт краснеть на законных цитатах — и это правильный момент **развести нотацию**
    (`repo:PIT-NNN` для чужих), а не глушить проверку. Задача записана в `ROADMAP.md`.
    """
    existing: dict[str, set[int]] = {}
    # 🔴 `ADR` живёт не одним файлом, а каталогом карточек — поэтому
    # собирается отдельно, ниже.
    for prefix, path, pattern in (
        ("PIT", root / "reports" / "pitfalls.md", r"^###\s+PIT-(\d+)"),
        ("SYN", root / "05-infra-synthesis-lab" / "PITFALLS.md", r"^##\s+SYN-(\d+)"),
    ):
        if path.is_file():
            existing[prefix] = {int(x) for x in re.findall(
                pattern, path.read_text(encoding="utf-8", errors="replace"), re.M)}

    adr_dir = root / "reports" / "adr"
    if adr_dir.is_dir():
        nums = set()
        for f in adr_dir.glob("adr_*.md"):
            m = re.search(r"adr_(\d+)_", f.name)
            if m:
                nums.add(int(m.group(1)))
        if nums:
            existing["ADR"] = nums

    # 🔴 Нотация чужих номеров, заведённая 22.08.2026 (задача из ROADMAP исполнена).
    # Потолок, описанный ниже, перестал быть теоретическим: своя нумерация доросла
    # до PIT-116 и накрыла чужой диапазон `portrait-of-taste` portrait-of-taste:PIT-101…116, после чего
    # законные цитаты стали неотличимы от висячих ссылок. Лечение — то, которое
    # предписал сам докстринг: развести нотацию, а не глушить проверку.
    #
    # Чужой номер пишется с квалификатором: `portrait-of-taste:PIT-114`.
    # Lookbehind ниже пропускает такие ссылки — они адресуют чужое пространство
    # имён и проверке не подлежат по определению.
    # 🔴 `ADR` добавлен 04.09.2026. Повод: **44 ссылки** в базе вели на
    # `ADR`-009…`ADR`-012, которых в её реестре нет — там семь. Они живут
    # в `mission-control`, у которой СВОЯ серия нумерации, и пересечение
    # уже случилось: `ADR`-010 это и «Claude Code zones» планировщика,
    # и «метрология парсера» у `personal-finance-dss`.
    #
    # Проверка не заметила бы их сама: она знала только PIT и SYN.
    # 🔴 НОТАЦИЯ ЧУЖОГО ПРОСТРАНСТВА ИМЁН — `репа::КОД`, ДВОЙНОЕ ДВОЕТОЧИЕ.
    # Предложено владельцем 04.09.2026 дословно: «может тогда включить тоже
    # нотацию как в плюсах используют? типо там пишут класс базовый через
    # `std::`, `Base::` когда функции одинаковые».
    #
    # Довод сильный и не эстетический: одинарное двоеточие в русском тексте
    # стоит после каждого второго слова («Сделано:», «см:»), и отличить
    # квалификатор от обычной пунктуации регуляркой нельзя. `::` не встречается
    # в прозе вовсе — значит распознаётся однозначно.
    #
    # Одинарная форма ОСТАЁТСЯ ЧИТАЕМОЙ: 27 мест уже написаны так, и часть
    # из них — журналы событий, которые правке не подлежат (`94` §2).
    ref_rx = re.compile(r"(?<![\w.-]::)(?<![\w.-]:)\b(PIT|SYN|ADR)-(\d{2,3})\b")
    dangling: dict[str, list[str]] = {}
    for path in files:
        if path.suffix not in {".md", ".py", ".sh"}:
            continue
        # 🔴 ЖУРНАЛЫ СОБЫТИЙ ИСКЛЮЧЕНЫ — добавлено 04.09.2026 вместе с `ADR`.
        # `CHANGELOG`, `decisions.md`, реестры случаев записывают, что было
        # сказано ТОГДА. Ссылка в них могла указывать на живую карточку в свой
        # день и осиротеть позже — это не дефект, а история (`94` §2).
        #
        # Требовать от журнала актуальных ссылок значит требовать правки
        # задним числом, а она не исправляет показание, а уничтожает его.
        # Первый прогон с `ADR` дал 17 таких строк по одному `CHANGELOG`.
        if any(j in path.name for j in
               ("CHANGELOG", "HISTORY", "PITFALLS", "pitfalls", "decisions")) \
                or "incidents" in path.parts or "runs" in path.parts:
            continue
        # Замороженные артефакты не ведут: отставные скрипты в `_archive/` несут
        # номера той репы, из которой пришли, и правиться уже не будут.
        if "_archive" in path.parts:
            continue
        rel = path.relative_to(root)
        for i, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in ref_rx.finditer(line):
                prefix, num = m.group(1), int(m.group(2))
                nums = existing.get(prefix)
                # 🔴 29.08.2026: своё пространство имён — интервал, который
                # карточки репы РЕАЛЬНО занимают, а не «от единицы до максимума».
                # Прежняя редакция брала 1…max и валила `portrait-of-taste`
                # **98 ложными строками**: репа намеренно нумерует свои карточки
                # с номера 101 (нотация PIT-NNN здесь намеренно разорвана:
                # написанный целиком номер проверка сочтёт живой ссылкой),
                # чтобы не пересекаться с базой, а ссылки на номера 1…100
                # приходят из розданной `_base/` и адресуют реестр base-repo,
                # которого здесь нет и быть не должно. Ниже min — чужой адрес
                # ровно так же, как выше max; асимметрия была допущением, а не
                # свойством данных.
                # 🔴 ДИАПАЗОН ПРИМЕНЯЕТСЯ ТОЛЬКО К `PIT`/`SYN`, НЕ К `ADR`.
                # Замер 04.09.2026: подсаженная битая ссылка `ADR`-099
                # НЕ ЛОВИЛАСЬ — своих ADR семь, и всё выше 007 считалось
                # чужим пространством имён. То есть проверка была добавлена
                # и не работала: зелёный вердикт означал «не проверялось».
                #
                # Для `PIT`/`SYN` диапазон нужен: чужие репы нумеруют свои
                # карточки СО СМЕЩЕНИЕМ (portrait-of-taste начинает со 101),
                # и голый номер там законно адресует чужой реестр.
                # У `ADR` смещения нет — **каждая репа начинает с 001**,
                # и чужой номер отличается только квалификатором `репа::ADR-N`.
                # Значит голый `ADR-NNN` обязан быть своим, каким бы он ни был.
                if prefix == "ADR":
                    # 🔴 `nums` бывает None: у репы-наследника нет `reports/adr/`,
                    # и `existing["ADR"]` не заводится вовсе. Первая редакция
                    # падала `TypeError` на КАЖДОЙ такой репе — то есть гейт
                    # ломался у 64 из 65, проверенный только на базе.
                    #
                    # Нет своего реестра — нечего и проверять: любой `ADR-NNN`
                    # здесь адресует чужой, и это законно.
                    if not nums or num in nums:
                        continue
                elif not nums or not (min(nums) <= num <= max(nums)):
                    continue
                if num not in nums:
                    dangling.setdefault(f"{prefix}-{m.group(2)}", []).append(f"{rel}:{i}")
    return [f"{ref} — карточки нет, ссылаются: {', '.join(loc[:4])}"
            + (f" (и ещё {len(loc) - 4})" if len(loc) > 4 else "")
            for ref, loc in sorted(dangling.items())]


def selftest_dangling_refs() -> bool:
    """Канарейка (71 §7в): ловится КАЖДЫЙ реестр по отдельности, а не «хоть один».

    АНТИ-САМОРЕФЕРЕНЦИЯ, как у канарейки CJK: синтетические номера собираются из кусков,
    иначе проверка ловит собственный исходник — что и произошло на первом прогоне.
    """
    import tempfile

    pit, syn = "PIT" + "-005", "SYN" + "-003"          # дыры внутри своей нумерации
    pit_ok, syn_ok = "PIT" + "-001", "SYN" + "-001"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "reports").mkdir()
        (root / "05-infra-synthesis-lab").mkdir()
        (root / "reports" / "pitfalls.md").write_text(
            "### " + pit_ok + " — есть\n### PIT" + "-009 — есть\n", encoding="utf-8")
        (root / "05-infra-synthesis-lab" / "PITFALLS.md").write_text(
            "## " + syn_ok + " — есть\n## SYN" + "-009 — есть\n", encoding="utf-8")
        doc = root / "d.md"

        doc.write_text(f"см. {pit_ok}, {pit} и {syn_ok}, {syn}\n", encoding="utf-8")
        if {c.split(" ")[0] for c in check_dangling_registry_refs(root, [doc])} != {pit, syn}:
            return False

        # вне своей нумерации (чужое пространство имён) — молчим
        doc.write_text("источник: `portrait-of-taste` (PIT" + "-114)\n", encoding="utf-8")
        if check_dangling_registry_refs(root, [doc]) != []:
            return False

        doc.write_text(f"см. {pit_ok} и {syn_ok}\n", encoding="utf-8")
        # 🔴 Половина канарейки про НИЖНЮЮ границу своего пространства имён.
        # Без неё правило «min…max» неотличимо от прежнего «1…max».
        low = root / "low.md"
        reg = root / "reports" / "pitfalls.md"
        reg.parent.mkdir(parents=True, exist_ok=True)
        p101, p116 = "PIT-" + "101", "PIT-" + "116"
        reg.write_text(f"### {p101} — раз\n### {p116} — два\n", encoding="utf-8")
        low.write_text(f"ссылка на {'PIT-' + '004'} из розданной базы\n"
                       f"и на {'PIT-' + '109'}, которой в реестре нет\n",
                       encoding="utf-8")
        got = check_dangling_registry_refs(root, [low])
        # PIT-004 ниже своего диапазона — чужой адрес, молчим.
        # Номер 109 внутри 101…116, карточки нет — обязаны поймать.
        if len(got) != 1 or "109" not in got[0]:
            return False
        return check_dangling_registry_refs(root, [doc]) == []


def selftest_resume_point_refs() -> bool:
    """Канарейка §0-ссылок: кросс-репные проходят, настоящие висячие — краснеют.

    🔴 Заведена 28.08.2026 после ПЯТОГО подряд ложного срабатывания. §0 у
    `dota-dossier`/`health-vault`/`legal-knowledge-base` законно ссылался на
    `mission-control/BACKLOG.md` — репы лежат рядом в `~/repos/`, — а проверка
    искала файл внутри текущей репы. Вахта четыре раза переписывала прозу
    журнала, чтобы обойти гейт: чинила журнал под инструмент вместо инструмента.

    Проверяется РАЗЛИЧЕНИЕ, а не «не падает»: смягчение обязано пропустить
    существующий соседний файл и при этом **не ослепнуть** ни к
    несуществующему у соседа, ни к несуществующему у себя.
    """
    import tempfile

    body = (
        "## §0. Где стоим\n\n"
        "**Версия:** 1.0.0 · **Дата:** 2026-08-28 · Текущая точка: v1.0.0\n\n"
        "- сосед, файл есть: `otherrepo/REAL.md`\n"
        "- сосед, файла нет: `otherrepo/NOPE.md`\n"
        "- своя репа, файла нет: `local-missing.md`\n\n"
        "## §1. Дальше\nпусто\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp).resolve()
        me = workspace / "myrepo"
        other = workspace / "otherrepo"
        me.mkdir()
        other.mkdir()
        (other / "REAL.md").write_text("x", encoding="utf-8")
        (me / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        (me / "WATCHLOG.md").write_text(body, encoding="utf-8")

        found = {
            p.split("`")[1]
            for p in check_resume_point_content(me)
            if "несуществующее" in p
        }
        # сосед с живым файлом обязан молчать; оба отсутствующих — краснеть
        return found == {"otherrepo/NOPE.md", "local-missing.md"}


def selftest_stale_version_prose() -> bool:
    """Канарейка `PIT-116`-версий: чужое и цитаты молчат, своё отставание — краснеет.

    Проверяется РАЗЛИЧЕНИЕ трёх случаев в одном §0:
      · `family` → 1.0.0        — чужая репа, молчит
      · закрыто [3.61.0]        — цитата секции CHANGELOG, молчит
      · стоим на v3.10.0        — своё заявление, при текущей 3.95.0 краснеет
    Возврат к «собирать все версии подряд» уронит канарейку на первых двух;
    ослабление до «никогда» — на третьем.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp).resolve()
        (ws / "family").mkdir()
        me = ws / "myrepo"
        me.mkdir()
        (me / "VERSION").write_text("3.95.0\n", encoding="utf-8")
        (me / "WATCHLOG.md").write_text(
            "## §0. Где стоим\n\n"
            "**Версия:** 3.95.0 · Текущая точка: v3.95.0\n\n"
            "- `family` доведена до 1.0.0 — чужая версия в рассказе о батче\n"
            "- кампания синтеза закрыта [3.61.0] — цитата секции CHANGELOG\n"
            "- ранее стояли на v3.10.0 и это реальное отставание\n\n"
            "## §1. Дальше\nпусто\n",
            encoding="utf-8")
        got = [p for p in check_resume_point_content(me) if "отставание" in p]
    # ровно одна жалоба, и именно про 3.10
    return len(got) == 1 and "v3.10" in got[0]


def check_card_heading_levels(root: Path) -> list[str]:
    """Карточка реестра написана на том уровне заголовка, который видит гейт.

    🔴 ЗАЧЕМ ОТДЕЛЬНАЯ ПРОВЕРКА. `check_dangling_registry_refs` собирает список
    существующих карточек регулярками `^###\\s+PIT-` и `^##\\s+SYN-`. Карточка,
    написанная не на том уровне, для гейта **не существует**, и ломается это
    молча в обе стороны:

    · ссылки на неё становятся «висячими» — но не краснеют, потому что номер
      оказывается выше `max(своих номеров)` и трактуется как чужое пространство имён;
    · сама она обрезает диапазон проверки для ВСЕХ номеров выше себя.

    Найдено 22.08.2026: `PIT-115` и `PIT-116` стояли на `##` при 98 карточках на
    `###`. То есть две свежайшие карточки — включая ту, что описывает класс
    «гейт мерил половину, которая не ломается», — сами были невидимы гейту.

    Это тот же класс, что PIT-116, применённый к нему самому: проверка опиралась
    на форму, которую никто не проверял. Форму правит рука, значит она портится —
    и значит её надо проверять (`21` §4г).

    🔴 ЧЕГО НЕ ЛОВИТ: карточку на верном уровне и с пустым содержанием. Уровень заголовка — про видимость для гейта, не про то, что под заголовком написано.
    """
    problems: list[str] = []
    for label, path, good, bad in (
        ("PIT", card_registry(root, "PIT"), card_re("PIT"), card_re("PIT", wrong_level=True)),
        ("SYN", card_registry(root, "SYN"), card_re("SYN"), card_re("SYN", wrong_level=True)),
    ):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        for i, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if re.match(good, line):
                continue
            if re.match(bad, line):
                problems.append(
                    f"{rel}:{i} — карточка {label} не на своём уровне заголовка, "
                    f"гейт её не увидит: {line.strip()[:70]}")
    return problems


def selftest_card_heading_levels() -> bool:
    """Канарейка (71 §7в): проверка обязана ловить подсаженный кривой уровень."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "reports").mkdir()
        (root / "05-infra-synthesis-lab").mkdir()
        pit = root / "reports" / "pitfalls.md"
        syn = root / "05-infra-synthesis-lab" / "PITFALLS.md"

        # всё по канону — молчим
        pit.write_text("### PIT" + "-001 — ок\n### PIT" + "-002 — ок\n", encoding="utf-8")
        syn.write_text("## SYN" + "-001 — ок\n", encoding="utf-8")
        if check_card_heading_levels(root) != []:
            return False

        # подсаженный кривой уровень в каждом реестре по отдельности
        pit.write_text("### PIT" + "-001 — ок\n## PIT" + "-002 — кривая\n", encoding="utf-8")
        if len(check_card_heading_levels(root)) != 1:
            return False

        pit.write_text("### PIT" + "-001 — ок\n", encoding="utf-8")
        syn.write_text("### SYN" + "-001 — кривая\n", encoding="utf-8")
        return len(check_card_heading_levels(root)) == 1


def check_prose_counts(root: Path) -> list[str]:
    """Число в прозе обязано совпадать с тем, что реально лежит на диске.

    v1.87.0 записала правило: «любое число в прозе — снимок, сделанный однажды;
    либо у него есть гейт, либо оно устареет». Правило записали, гейт не построили —
    и через семь версий README.md противоречил сам себе: **97 карточек PIT** в одной
    строке и **88 карточек PIT** в другой, в одном файле. Правка v1.87.0 нашла первое
    вхождение и не искала второе (PIT-098: починка случая не закрывает класс).

    Проверяются только числа, которые можно посчитать командой. Всё остальное
    («пять классов», «десять инструментов») сюда не годится и правится ревизией.

    🔴 ЧЕГО НЕ ЛОВИТ: утверждение без числа. «Документов стало заметно больше» не сверяется ни с чем: проверке нужна цифра, чтобы было что сравнивать.
    """
    problems: list[str] = []
    for label, counter, pattern in PROSE_COUNTS:
        actual = counter(root)
        rx = re.compile(pattern)
        # PIT-091-родня, найдено 28.08.2026: `actual < 0` раньше проваливал гейт
        # безусловно, даже для реп, у которых просто нет своего реестра PIT/SYN
        # (например `mission-control` — этот реестр ведёт `base-repo`, а прозы,
        # заявляющей число карточек, у неё нет вовсе). Правильный вопрос —
        # «проза заявляет число, которое нельзя проверить?», не «источник вообще
        # существует?». Собираем совпадения сначала, жалуемся на «источник не
        # найден» только если хоть одно реально нашлось.
        found_claim = False
        for rel in PROSE_FILES:
            path = root / rel
            if not path.is_file():
                continue
            for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                for m in rx.finditer(line):
                    found_claim = True
                    if actual < 0:
                        continue  # ниже отдельным problem, не дублировать на каждую строку
                    if int(m.group(1)) != actual:
                        problems.append(
                            f"{rel}:{i} — {label}: в прозе {m.group(1)}, на диске {actual}")
        if actual < 0 and found_claim:
            problems.append(f"{label}: источник для подсчёта не найден")
    return problems


def selftest_prose_counts() -> bool:
    """Канарейка (71 §7в). В норме проверка пуста, значит её поломка невидима.

    Требуется, чтобы ловилось КАЖДОЕ из трёх чисел по отдельности, а не «хоть что-то»:
    при трёх сломанных регулярках из трёх условие `len(caught) > 0` всё равно прошло бы
    за счёт четвёртой. Плюс отдельно проверяется, что верное число НЕ ловится.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "reports").mkdir()
        (root / "05-infra-synthesis-lab").mkdir()
        (root / "00-infrastructure").mkdir()
        (root / "reports" / "pitfalls.md").write_text(
            "### PIT-001 — раз\n### PIT-002 — два\n", encoding="utf-8")
        (root / "05-infra-synthesis-lab" / "PITFALLS.md").write_text(
            "## SYN-001 — раз\n", encoding="utf-8")
        for n in ("01-a.md", "02-b.md", "03-c.md"):
            (root / "00-infrastructure" / n).write_text("x", encoding="utf-8")

        (root / "README.md").write_text(
            "**9 карточек `PIT-NNN`** и **9 карточек `SYN-NNN`** и **9 документов**\n",
            encoding="utf-8")
        caught = check_prose_counts(root)
        labels = {c.split(" — ")[1].split(":")[0] for c in caught}
        if labels != {"карточек PIT", "карточек SYN", "документов кита"}:
            return False

        (root / "README.md").write_text(
            "**2 карточки `PIT-NNN`** и **1 карточка `SYN-NNN`** и **3 документа**\n",
            encoding="utf-8")
        if check_prose_counts(root) != []:
            return False

        # PIT-091-родня, 28.08.2026: репа без собственного реестра PIT/SYN
        # (реестр только у base-repo) и без прозы, заявляющей число, — не
        # проблема, «источник для подсчёта не найден» не должно всплывать
        # безусловно. Живой пример поймал `mission-control`.
        (root / "reports" / "pitfalls.md").unlink()
        (root / "05-infra-synthesis-lab" / "PITFALLS.md").unlink()
        (root / "README.md").write_text("ничего про карточки здесь нет\n", encoding="utf-8")
        return check_prose_counts(root) == []


# Разделы, без которых отчёт исследования неотличим от эссе по памяти.
# Заведено 29.08.2026 вместе с доводкой агента `researcher`: агент ОБЯЗАН
# раскрывать процесс (тип запроса, число субагентов, что осталось неизвестным),
# иначе читатель не может оценить, насколько выводам верить. Правило в промпте
# агента — совет; проверка файла на диске — механизм.
# 🔴 Проверяется СОДЕРЖАНИЕ раздела, а не его точная формулировка.
# Первая редакция требовала дословных заголовков «Как это исследовалось» и
# «Что осталось неизвестным» — и тут же покраснела на двух существующих
# отчётах, где ровно эти разделы есть под именами «Как это делалось» и
# «7. Что осталось неизвестным». Проверка на дословность ловит не отсутствие
# раздела, а несовпадение слов, и лечится она переписыванием заголовка —
# то есть учит подгонять формулировку под гейт вместо того, чтобы писать
# отчёт. Тот же класс, что `PIT-159` (проза правилась под ложное срабатывание).
RESEARCH_SECTIONS = (
    ("раскрытие процесса", ("как это исследовал", "как это делалось",
                            "как исследовал", "методика", "как это искалось")),
    ("что осталось неизвестным", ("осталось неизвестн", "не выяснен",
                                  "чего не знаем", "открытые вопрос")),
)


def check_research_reports(root: Path) -> list[str]:
    """Отчёт исследования обязан раскрывать процесс, а не только результат.

    🔴 Проверяется КАТАЛОГ `reports/research/`, а не всякий файл со словом
    «исследование»: адрес — это обещание формата. Файл, положенный туда,
    заявляет себя отчётом агента; конспект или заметка живут в другом месте.

    🔴 ЧЕГО НЕ ЛОВИТ: описанный процесс, которого не было. Раздел «как искали» присутствует — чем он заполнен, проверить нечем.
    """
    folder = root / "reports" / "research"
    if not folder.is_dir():
        return []
    problems = []
    for path in sorted(folder.glob("*.md")):
        if path.name in {"README.md", "TEMPLATE.md"}:
            continue
        # Структурный маркер — не только заголовок. Найдено 29.08.2026 на
        # `agent-skill-plugin-sources-2026-08-28.md`: раскрытие процесса там
        # есть и написано честно («реальных субагентов запущено 0 — в тулсете
        # не было инструмента спавна»), но оформлено жирным зачином внутри
        # раздела «Прямой ответ», а не своим заголовком. Требовать именно
        # заголовок значило бы придираться к вёрстке при выполненном условии.
        # Жирный зачин в начале строки — такой же блочный маркер markdown,
        # а вот упоминание в середине абзаца — нет, и оно не засчитывается.
        heads = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("#"):
                heads.append(line.lstrip("#").strip().lower())
            elif line.startswith("**"):
                heads.append(line.split("**")[1].strip().lower() if "**" in line[2:] else "")
        missing = [label for label, keys in RESEARCH_SECTIONS
                   if not any(k in h for h in heads for k in keys)]
        if missing:
            rel = path.relative_to(root).as_posix()
            problems.append(f"{rel}: отчёт не содержит — {', '.join(missing)} "
                            f"(образец: templates/RESEARCH_REPORT_TEMPLATE.md)")
    return problems


def selftest_research_reports() -> bool:
    """Ловит отчёт без раскрытия процесса; НЕ придирается к формулировке.

    Вторая половина — та, ради которой канарейка и переписана: заголовок
    с номером и синонимом обязан проходить, иначе проверка требует не
    содержания, а конкретных слов.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder = root / "reports" / "research"
        folder.mkdir(parents=True)
        (folder / "bad.md").write_text("# Тема\n\n## Находки\nтекст\n", encoding="utf-8")
        if len(check_research_reports(root)) != 1:
            return False
        (folder / "bad.md").write_text(
            "# Тема\n\n## Как это делалось\nтаблица\n"
            "\n## 7. Что осталось неизвестным\nстрока\n", encoding="utf-8")
        if check_research_reports(root) != []:
            return False
        # Жирный зачин засчитывается, упоминание в середине абзаца — нет.
        (folder / "bad.md").write_text(
            "# Тема\n\n**Как это делалось.** три поиска\n"
            "\n**Что осталось неизвестным.** ничего\n", encoding="utf-8")
        if check_research_reports(root) != []:
            return False
        (folder / "bad.md").write_text(
            "# Тема\n\nВ тексте сказано как это делалось и что осталось "
            "неизвестным, но структурно не выделено.\n", encoding="utf-8")
        return len(check_research_reports(root)) == 1


def check_secret_hygiene(root: Path) -> tuple[list[str], list[str]]:
    """Секрет, лежащий в файле репы, — это секрет в архиве и в бэкапе.

    🔴 Заведено 29.08.2026 вместе с решением по хранению
    (`00-infrastructure/94-secret-storage.md`): канон — связка ключей macOS,
    файл `.env` собирается из неё по требованию и живёт ровно столько, сколько
    работает приложение. Проверка ловит два разных дефекта:

      FAIL — `.env` есть, а правила `.env` в `.gitignore` НЕТ. Это прямой путь
             секрета в историю, откуда он уже не удаляется, а только
             отзывается у провайдера.
      WARN — `.env` есть и в нём НЕПУСТОЕ значение секретного ключа. Файл
             легитимен (его собирает `secret.py env`), но пока он лежит на
             диске, он попадает в Time Machine и в любую ручную упаковку.
             Правильнее `secret.py run <репа> -- команда`: файла не возникает
             вовсе.

    Классификация «секрет или настройка» берётся из `secret.py` — единственного
    места, где она определена. Импорт не удался — проверка НЕ молчит: молчание
    неотличимо от «всё чисто» (`71-fail-loud-and-sourcing.md` §7ж).

    🔴 ЧЕГО НЕ ЛОВИТ: секрет, не похожий на секрет. Короткий пароль, кодовое слово, имя базы — всё это ловится глазом, а не образцом.
    """
    envs = []
    for path in root.rglob(".env"):
        if any(p in {"node_modules", ".venv", "venv", ".git", "_base"} for p in path.parts):
            continue
        if path.is_file():
            envs.append(path)
    if not envs:
        return [], []

    fails, warns = [], []
    gitignore = (root / ".gitignore")
    gi_text = gitignore.read_text(encoding="utf-8", errors="replace") if gitignore.is_file() else ""
    if not re.search(r"^\s*\*?\.env\s*$", gi_text, re.M):
        fails.append(f"есть .env, но в .gitignore нет правила `.env` "
                     f"({len(envs)} файл(ов)) — секрет уедет в историю")

    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from secret import is_secret_name, secret_names_for
    except Exception as exc:
        fails.append(f"проверка секретов не выполнена: не импортируется secret.py ({exc})")
        return fails, warns

    for env in envs:
        rel = env.relative_to(root).as_posix()
        # 🔴 Судить о живом `.env` правилом «пусто = секрет» НЕЛЬЗЯ: там всё
        # заполнено по определению. Источник правды — соседний `.env.example`
        # (он для того и коммитится); нет образца — грубый признак по имени.
        declared = secret_names_for(env)
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            name = name.strip()
            if not value.strip():
                continue
            secret_here = name in declared if declared is not None else is_secret_name(name)
            if secret_here:
                warns.append(f"{rel}: `{name}` лежит значением в файле — "
                             f"канон связка ключей (secret.py run/env)")
    return fails, warns


def selftest_secret_hygiene() -> bool:
    """Ловит отсутствие правила и НЕ ругается на закрытую правилом репу."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".env").write_text("VK_TOKEN=abc123\nVAULT_ROOT=/x\n", encoding="utf-8")
        open_fails, open_warns = check_secret_hygiene(root)
        if not open_fails or not open_warns:
            return False
        (root / ".gitignore").write_text(".env\n", encoding="utf-8")
        closed_fails, closed_warns = check_secret_hygiene(root)
        # Правило закрыло FAIL, но значение в файле по-прежнему WARN —
        # это разные дефекты, и второй не лечится первым.
        return closed_fails == [] and len(closed_warns) == 1


def selftest_changelog_conventions() -> bool:
    """Обе живые конвенции журнала засчитываются, отсутствие записи — нет.

    Третья половина обязательна: без неё «принимать обе» неотличимо от
    «не проверять вовсе».
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "VERSION").write_text("1.22.0\n", encoding="utf-8")
        (root / "WATCHLOG.md").write_text("## §0\nv1.22.0\n", encoding="utf-8")

        def probe(body: str) -> bool:
            (root / "CHANGELOG.md").write_text(body, encoding="utf-8")
            return any("не содержит секции" in x for x in check_living_documents(root))

        keep_a_changelog = probe("## [1.22.0] — 2026-08-29\nтекст\n")
        v_prefixed = probe("## v1.22.0 — 2026-08-26\nтекст\n")
        absent = probe("## v1.21.1 — 2026-07-23\nтекст\n")
        return not keep_a_changelog and not v_prefixed and absent


# Порог длины описания. Не эстетика: описание — ЕДИНСТВЕННОЕ, что модель
# видит до загрузки тела правила (progressive disclosure, Anthropic «Agent
# Skills», 16.10.2025). Решение «сработать или нет» принимается по нему, значит
# правило с пустым или общим описанием **невидимо**, сколько бы хорошего ни было
# написано внутри. Двадцать символов — не «хорошее описание», а нижняя граница,
# ниже которой описания заведомо нет.
DESCRIPTION_MIN = 20
# Слова, по которым видно, что описание отвечает на «КОГДА это применять».
# Описание, отвечающее только на «что это такое», не даёт основания сработать.
TRIGGER_WORDS = ("когда", "если", "вызывать", "использовать", "применять",
                 "на запрос", "при ", "нужен", "нужна", "нужно")


def check_rule_descriptions(root: Path) -> list[str]:
    """У скилла и агента обязано быть описание, называющее ПОВОД сработать.

    🔴 Заведено 29.08.2026 по исследованию `reports/research/
    system-building-and-analysis-2026-08-29.md` (кандидат №2). Механизм
    прогрессивного раскрытия устроен так, что тело правила загружается ТОЛЬКО
    если описание убедило. Пустое описание — это выключенное правило, и внешне
    оно неотличимо от работающего: файл на месте, содержание отличное.

    Проверяются два свойства, оба механические:
      · описание есть и не короче `DESCRIPTION_MIN`;
      · в нём есть слово-повод — «когда», «если», «вызывать», «при»…
    Качество формулировки не проверяется: это суждение, и гейт его не выносит.

    🔴 ЧЕГО НЕ ЛОВИТ: повод, сформулированный так, что не отличает свои случаи от чужих. «Когда нужно разобраться» — описание есть, различающей силы в нём нет.
    """
    problems: list[str] = []
    targets: list[Path] = []
    targets += sorted(root.glob(".claude/skills/*/SKILL.md"))
    targets += sorted(root.glob(".claude/agents/*.md"))
    for path in targets:
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.startswith("---"):
            problems.append(f"{rel}: нет фронтматтера — описание негде объявить")
            continue
        head = text.split("---", 2)[1]
        desc = ""
        for line in head.splitlines():
            if line.startswith("description:"):
                desc = line[len("description:"):].strip().strip('"\'')
                break
        if len(desc) < DESCRIPTION_MIN:
            problems.append(f"{rel}: описание пустое или короче {DESCRIPTION_MIN} "
                            f"символов — правило невидимо до загрузки тела")
        elif not any(w in desc.lower() for w in TRIGGER_WORDS):
            problems.append(f"{rel}: описание не называет ПОВОД сработать "
                            f"(«когда», «если», «вызывать»…) — модель не сможет "
                            f"решить, применять ли правило")
    return problems


def selftest_rule_descriptions() -> bool:
    """Ловит пустое описание и описание без повода; молчит на полном."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        d = root / ".claude" / "skills" / "x"
        d.mkdir(parents=True)
        f = d / "SKILL.md"

        def probe(desc: str) -> int:
            f.write_text(f"---\nname: x\ndescription: {desc}\n---\nтело\n",
                         encoding="utf-8")
            return len(check_rule_descriptions(root))

        empty = probe("")
        no_trigger = probe("Инструмент для разбора длинных документов системы")
        good = probe("Вызывать, когда владелец просит разобрать длинный документ")
        return empty == 1 and no_trigger == 1 and good == 0


# Каталоги, которых в README быть не обязано: служебные, раздаваемые, скрытые.
# `_base/` — копия базы, её состав объявлен в самой базе, а не у хозяина.
REFLEXION_SKIP = {
    "_base", "node_modules", "dist", "build", "venv", "reports",
    "templates", "scripts", "tests", "assets", "cache", "tmp",
    # Порождается инструментом, а не автором: объявлять в README нечего.
    "__pycache__", "__MACOSX", "htmlcov", "site-packages", "egg-info",
}


def check_reflexion_model(root: Path) -> list[str]:
    """Заявленная структура репы против фактической — reflexion model.

    🔴 Заведено 29.08.2026 по исследованию `reports/research/
    system-building-and-analysis-2026-08-29.md` (кандидат №1, ранг 1).
    Метод: Murphy, Notkin, Sullivan, «Software Reflexion Models», FSE 1995 —
    высокоуровневая модель, которую держит в голове автор, сверяется с моделью,
    которую можно снять с артефакта, и **расхождение показывается явно**.

    Для этой системы модель заявлена в таблице структуры `README.md`, факт —
    в списке каталогов на диске. Ловится ровно одно, зато молчаливое: **каталог,
    заведённый и не объявленный**. Он не ломает ни одной ссылки, не роняет ни
    одной проверки — просто через месяц никто не помнит, что там и зачем, и это
    первый шаг архитектурной эрозии.

    🔴 Метод выбран **именно потому, что не требует истории коммитов** — у
    рабочих реп нет `.git`, и все методы измерения деградации, завязанные на
    `git blame`/`git log` (энтропия изменений Хассана, возраст SATD), для них
    неопределены. Reflexion работает по одному срезу.

    Обратное направление (объявлен, но не существует) уже ловят битые ссылки.

    🔴 ЧЕГО НЕ ЛОВИТ: согласованную ошибку. Если заявленная структура и фактическая неверны одинаково, расхождения нет — а неправда есть.
    """
    readme = root / "README.md"
    if not readme.is_file():
        return []
    text = readme.read_text(encoding="utf-8", errors="replace")
    actual = {d.name for d in root.iterdir()
              if d.is_dir() and not d.name.startswith(".")
              and d.name not in REFLEXION_SKIP}
    if not actual:
        return []
    # Каталог считается объявленным, если его имя встречается в README где
    # угодно — таблицей, ссылкой или прозой. Проверяется НАЛИЧИЕ упоминания,
    # а не его форма: три репы описывают структуру списком, а не таблицей,
    # и требовать таблицу значило бы проверять вёрстку вместо предмета.
    undeclared = sorted(d for d in actual if d not in text)
    if not undeclared:
        return []
    return [f"каталог заведён, но в README не объявлен: {d}/" for d in undeclared]


def selftest_reflexion_model() -> bool:
    """Ловит необъявленный каталог, молчит на объявленном и на служебном."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "docs").mkdir()
        (root / "_base").mkdir()
        (root / "README.md").write_text("# Репа\n\n| `docs/` | что внутри |\n",
                                        encoding="utf-8")
        if check_reflexion_model(root) != []:
            return False
        (root / "новый-каталог").mkdir()
        got = check_reflexion_model(root)
        return len(got) == 1 and "новый-каталог" in got[0]


# Реестр вахт — единственный источник соответствия «почта → буква».
WATCH_REGISTRY = "00-infrastructure/84-claude-accounts.md"


def check_watch_identity_sources(root: Path) -> list[str]:
    """Никто не хранит соответствие «почта → вахта» СВОИМ перечнем.

    🔴 Заведено 29.08.2026, класс сработал ТРИЖДЫ подряд:
      · `PIT-163` — буква вахты стояла литералом «V» в `bump_repo.py`,
        один прогон `--all` разложил неверную букву по 45 репам;
      · починка ввела перечень из ДВУХ вахт — мягче, но тот же дефект:
        две работали, три молча получали «?»;
      · хук `watch-identity.sh` знал те же две литералами, а искал остальные
        в файле, где почт нет вовсе, — и на вахте S промолчал.

    Каждый раз чинилось место, а не класс. Проверка ловит **сам приём**:
    почтовый адрес вахты, вписанный в код или в хук. Единственное законное
    место такого адреса — реестр `84-claude-accounts.md`; всё остальное
    обязано его читать.

    🔴 ЧЕГО НЕ ЛОВИТ: устаревание единственного законного источника. Правило гонит все перечни к одному месту; верно ли то место — вопрос вне его области.
    """
    problems: list[str] = []
    registry = root / WATCH_REGISTRY
    for rel in ("scripts", ".claude/hooks", ".githooks"):
        folder = root / rel
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".sh", ""}:
                continue
            if path.resolve() == registry.resolve():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for number, line in enumerate(text.splitlines(), 1):
                # Ищем адрес рядом с буквой вахты — то есть готовое
                # соответствие, а не просто упоминание почты.
                if re.search(r"[\w.+-]+@[\w.-]+\.\w+", line) and re.search(
                        r"[\"']\s*[VJMSA]\s*[\"']", line):
                    problems.append(
                        f"{path.relative_to(root)}:{number}: соответствие "
                        f"«почта → вахта» вписано в код — источник только "
                        f"`{WATCH_REGISTRY}`")
    return problems


def selftest_watch_identity_sources() -> bool:
    """Ловит перечень в коде и молчит на чтении реестра."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "scripts").mkdir()
        bad = root / "scripts" / "плохо.py"
        # 🔴 Анти-самореференция, как у канареек CJK и реестров: образец
        # собирается ИЗ КУСКОВ, иначе проверка честно находит саму себя
        # в собственном исходнике и краснеет на своей же канарейке.
        # Рвётся ИМЕННО буква, а не адрес: разрыв адреса убивает первый
        # признак, и образец перестаёт быть образцом (проверено — было).
        letter = chr(86)  # «V»
        sample = 'MAP = {"кто-то@example.com": "' + letter + '"}'
        bad.write_text(sample + "\n", encoding="utf-8")
        if len(check_watch_identity_sources(root)) != 1:
            return False
        bad.write_text('for line in registry_lines:\n'
                       '    if email in line: return match(line)\n',
                       encoding="utf-8")
        return check_watch_identity_sources(root) == []


def check_pointer_purity(root: Path) -> list[str]:
    """Файл-указатель не хранит состояния — иначе он не указатель, а копия.

    🔴 Заведено 29.08.2026 после того, как `bump_repo.py` вписал строку
    `**Версия:**` прямо в указатель `personal-finance-dss/WATCHLOG.md` — и тем
    восстановил третий источник правды о состоянии репы, убранный оттуда
    в том же батче. Инструмент, не различающий документ и указатель, отменяет
    разведение источников молча и на каждом подъёме версии.

    Указатель обязан отвечать «настоящий лежит там» и ничего не утверждать
    сам: версия, дата, вахта, «текущая точка» — состояние, у него один дом
    (`72-source-of-truth.md`).

    🔴 ЧЕГО НЕ ЛОВИТ: указатель, ведущий не туда. Проверяется отсутствие состояния, а не верность адреса — пустой указатель на несуществующий дом чист.
    """
    problems = []
    for name in ("WATCHLOG.md", "ROADMAP.md", "TASKS.md", "CHANGELOG.md"):
        path = root / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if _follow_pointer(root, path, text) is None:
            continue
        for marker in ("**Версия:**", "Текущая точка:"):
            if marker in text:
                problems.append(
                    f"{name}: указатель хранит состояние («{marker}») — "
                    f"это второй источник правды, у него один дом")
    return problems


def selftest_pointer_purity() -> bool:
    """Ловит состояние в указателе; молчит на чистом указателе и на документе."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "docs").mkdir()
        (root / "docs" / "WATCHLOG.md").write_text("## §0. Где стоим\n", encoding="utf-8")
        ptr = root / "WATCHLOG.md"
        ptr.write_text("# Указатель\n\nЖурнал — [`docs/WATCHLOG.md`](docs/WATCHLOG.md).\n",
                       encoding="utf-8")
        if check_pointer_purity(root) != []:
            return False
        ptr.write_text("# Указатель\n\n**Версия:** 1.0.0\n\n"
                       "Журнал — [`docs/WATCHLOG.md`](docs/WATCHLOG.md).\n",
                       encoding="utf-8")
        return len(check_pointer_purity(root)) == 1


# Разделы с жёстким пределом числа пунктов. Маркеры несут лимит в себе:
# `<!-- WIP:START limit=2 -->` — чтобы правило и проверка не разошлись
# (число живёт в одном месте, а не в файле И в коде).
LIMIT_RE = re.compile(r"<!--\s*(\w+):START\s+limit=(\d+)\s*-->(.*?)<!--\s*\1:END\s*-->",
                      re.S)


# Срок у задачи: «[зав. 29.08]» — день и месяц, год подразумевается текущий.
DUE_RE = re.compile(r"\[зав\.\s*(?:до\s*)?(\d{2})\.(\d{2})\]")


def check_task_expiry(root: Path) -> list[str]:
    """Просроченный пункт обязан получить исход, а не тихо жить дальше.

    🔴 Заведено 29.08.2026 по `reports/research/
    task-classification-2026-08-29.md` §5. Приём взят из архивного дела
    (ISO 15489): у записи в момент создания задано не только сколько её
    хранить, но и **что сделать по истечении срока**. Личные системы задач
    этой оси не имеют вовсе — записи копятся бессрочно, а решение «удалить»
    принимается в состоянии перегрузки и на глаз.

    Без механизма поле срока — украшение: дата проходит, и не меняется
    ничего. Проверка делает истечение **видимым**, а исход — обязательным:
    перенести с новой датой · в «не делаем» с причиной · вычеркнуть.

    🔴 ЧЕГО НЕ ПОЙМАЕТ (`71` §7г-бис):
      · **не судит, честно ли перенесён срок.** Сдвинуть дату вперёд, ничего
        не сделав, — ровно то, чем эта проверка обманывается, и защиты от
        этого в коде быть не может: различие между «сдвинул обоснованно»
        и «сдвинул, чтобы не краснело» — смысловое;
      · пункт **без срока вовсе** здесь не ловится — это забота проверки
        обязательности поля, не этой;
      · год не хранится в поле, поэтому пункт, просроченный больше чем
        на год, читается как срочный на днях.
    """
    import datetime
    today = datetime.date.today()
    problems = []
    for path in sorted(root.glob("TASKS.md")) + sorted(root.glob("*/TASKS.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for num, line in enumerate(text.splitlines(), 1):
            if not line.lstrip().startswith("- [ ]"):
                continue
            m = DUE_RE.search(line)
            if not m:
                continue
            day, month = int(m.group(1)), int(m.group(2))
            try:
                due = datetime.date(today.year, month, day)
            except ValueError:
                problems.append(f"{path.relative_to(root)}:{num} — "
                                f"нет такой даты: {m.group(0)}")
                continue
            if due < today:
                overdue = (today - due).days
                problems.append(
                    f"{path.relative_to(root)}:{num} — срок прошёл "
                    f"{overdue} дн. назад ({m.group(0)}), исход не выбран: "
                    f"перенести · в «не делаем» · вычеркнуть")
    return problems


def selftest_task_expiry() -> bool:
    """Ловит просроченное, молчит на будущем — обе половины обязательны."""
    import datetime, tempfile
    today = datetime.date.today()
    past = today - datetime.timedelta(days=10)
    future = today + datetime.timedelta(days=10)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fmt = lambda d: f"{d.day:02d}.{d.month:02d}"
        (root / "TASKS.md").write_text(
            f"# Задачи\n\n- [ ] [зав. {fmt(future)}] будущее\n"
            f"- [x] [зав. {fmt(past)}] закрытое, срок не важен\n",
            encoding="utf-8")
        if check_task_expiry(root) != []:
            return False          # будущее и закрытое краснеть не должны
        (root / "TASKS.md").write_text(
            f"# Задачи\n\n- [ ] [зав. {fmt(past)}] просрочено\n",
            encoding="utf-8")
        return len(check_task_expiry(root)) == 1


# Живой маркер долга: в начале комментария кода или пункта списка.
# Упоминание слова внутри текста («385 заглушек TODO закрыты») маркером
# НЕ является — иначе проверка утонет в собственных журналах.
DEBT_CODE_RE = re.compile(r"^\s*#\s*(TODO|FIXME|HACK|XXX)\b(.*)$")
DEBT_DOC_RE = re.compile(r"^\s*[-*]\s*(?:\*\*)?(TODO|FIXME)\b(.*)$")
DEBT_DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}|\d{4}-\d{2}-\d{2}")


def check_debt_markers(root: Path) -> list[str]:
    """Маркер технического долга обязан нести дату заведения.

    🔴 Кандидат №1 очереди внедрения. Смысл даты: без неё невозможно
    отличить долг недельной давности от полугодового, а именно возраст
    и решает, чинить его или признать нормой.

    ЗАМЕРЕНО 29.08.2026 перед тем, как писать проверку: живых маркеров
    в базе **ноль**. Все 119 совпадений по словам TODO/FIXME/костыль —
    упоминания внутри текстов и журналов («385 заглушек TODO закрыты»),
    а не маркеры. Поэтому проверка заводится не как чистка, а **как защита
    на будущее**: первый же появившийся маркер обязан прийти с датой.

    🔴 ЧЕГО НЕ ПОЙМАЕТ (`71` §7г-бис):
      · **долг без слова-маркера** — а это большинство настоящего долга.
        Код, который просто плох, никакого TODO над собой не имеет;
      · дату можно поставить любую: проверяется наличие, не правдивость;
      · «временное решение», описанное прозой в середине абзаца, —
        не маркер по форме, хотя маркер по смыслу.

    🔴 ЧЕГО НЕ ЛОВИТ: долг, не помеченный маркером вовсе, и дату, поставленную наугад. Проверяется наличие даты у маркера, а не честность обеих.
    """
    # 🔴 Исключения репы уважаются, и это не поблажка. Прогон по `it-base`
    # дал 109 находок, все в `02-code-archive/` — архиве ЧУЖОГО учебного кода
    # (задачи CodeSignal), где `TODO` часть условия задачи, а не наш долг.
    # Проверка, краснеющая на чужом коде, перестаёт читаться целиком
    # (`PIT-085`), а решение «этот каталог не наш» принимает вахта репы,
    # не автор проверки.
    allow = load_allowlist(root)
    problems = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in {".py", ".sh", ".md"} or not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if any(str(rel) == a or str(rel).startswith(a.rstrip("/") + "/")
               for a in allow):
            continue
        pattern = DEBT_DOC_RE if path.suffix == ".md" else DEBT_CODE_RE
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for num, line in enumerate(lines, 1):
            m = pattern.match(line)
            if m and not DEBT_DATE_RE.search(m.group(2)):
                problems.append(
                    f"{path.relative_to(root)}:{num} — маркер {m.group(1)} "
                    f"без даты: возраст долга неизвестен")
    return problems


def selftest_debt_markers() -> bool:
    """Ловит маркер без даты, молчит на маркере с датой и на упоминании."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.py").write_text(
            "# TODO 29.08.2026 — починить разбор\n"      # с датой, законно
            "x = 1  # TODO вот это не маркер начала строки\n",
            encoding="utf-8")
        (root / "b.md").write_text(
            "# Док\n\n385 заглушек TODO закрыты механизмом\n",  # упоминание
            encoding="utf-8")
        if check_debt_markers(root) != []:
            return False
        (root / "c.py").write_text("# TODO починить когда-нибудь\n",
                                   encoding="utf-8")
        return len(check_debt_markers(root)) == 1


# Карточка ловушки: «### PIT-NNN — заголовок (ГГГГ-ММ-ДД)».
PIT_CARD_RE = re.compile(card_re("PIT", capture=True) + r"[^\n]*\((\d{4})-(\d{2})-(\d{2})\)",
                         re.M)
# С этого дня карточка обязана отвечать не только «чем ловится», но и «зачем».
RESOLVE_SINCE = (2026, 8, 29)


def check_pitfall_resolution(root: Path) -> list[str]:
    """Новая карточка ловушки обязана отвечать: разрешить или растворить.

    🔴 Кандидат №3 очереди внедрения. Поле «Гейт:» отвечает на вопрос **чем**
    ловится дефект. Это поле отвечает на другой: **что мы вообще собираемся
    с ним делать** —

      · **разрешить** (resolve) — починить в существующем устройстве;
      · **растворить** (dissolve) — перестроить так, чтобы дефект стал
        невозможен, а не ловился.

    Различие не академическое. `PIT-165` (правка двух файлов упала посередине)
    можно было бы «разрешить», поправив якорь, — и он вернулся бы на следующем
    несовпавшем тексте. Растворяет его двухфазная правка: сначала весь разбор,
    потом все записи. Без этого поля выбор делается молча и почти всегда
    в пользу разрешения, потому что оно дешевле сегодня.

    🔴 ТРЕБУЕТСЯ ТОЛЬКО ОТ НОВЫХ КАРТОЧЕК (с 29.08.2026). Из 118 карточек
    с датой поле есть у двух. Требовать его от всех — переписать 116 записей
    задним числом, то есть **подделать свидетельства**: автор тогдашней
    карточки этого выбора не делал, и приписывать ему его нельзя.

    🔴 ЧЕГО НЕ ПОЙМАЕТ (`71` §7г-бис): написать «растворить» и починить
    по-быстрому никто не мешает. Проверяется наличие ответа, не его честность
    и не соответствие ответа сделанному.

    🔴 ЧЕГО НЕ ЛОВИТ: неверно сделанный выбор. Поле «разрешить или растворить» заполнено — гейт доволен; было ли решение правильным, он не судит.
    """
    registry = root / "reports" / "pitfalls.md"
    if not registry.is_file():
        return []
    text = registry.read_text(encoding="utf-8", errors="replace")
    matches = list(PIT_CARD_RE.finditer(text))
    problems = []
    for i, m in enumerate(matches):
        when = (int(m.group(2)), int(m.group(3)), int(m.group(4)))
        if when < RESOLVE_SINCE:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.start():end]
        if "азрешить или раствор" not in body:
            problems.append(
                f"{m.group(1)} ({'-'.join(m.group(2, 3, 4))}) — нет ответа "
                f"«разрешить или растворить»: непонятно, чиним дефект "
                f"или делаем его невозможным")
    return problems


def selftest_pitfall_resolution() -> bool:
    """Ловит новую карточку без поля; молчит на старой и на заполненной."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "reports").mkdir()
        reg = root / "reports" / "pitfalls.md"
        reg.write_text(
            "### PIT-001 — старая, поля не требуем (2026-01-01)\n\nтекст\n\n"
            "### PIT-002 — новая с полем (2026-08-29)\n\n"
            "- **Разрешить или растворить:** растворить\n",
            encoding="utf-8")
        if check_pitfall_resolution(root) != []:
            return False          # старая и заполненная краснеть не должны
        reg.write_text(reg.read_text(encoding="utf-8")
                       + "\n### PIT-003 — новая без поля (2026-08-30)\n\nтекст\n",
                       encoding="utf-8")
        return len(check_pitfall_resolution(root)) == 1


def check_wip_limits(root: Path) -> list[str]:
    """Предел числа задач в работе — единственный механизм, который
    останавливает рост очереди.

    🔴 Заведено 29.08.2026. Закон Литтла — тождество: `среднее время жизни
    задачи = число открытых ÷ скорость закрытия`, и **он не зависит от
    дисциплины очереди**. Значит переприоритизация не уменьшает ни L, ни
    среднее ожидание; помогают только три вещи — поднять скорость, снизить
    приток, явно отбросить.

    Раздел «В работе» с пределом 2 задаёт время прохождения (Литтл);
    раздел «Готово к запуску» с пределом 5 — это **верёвка**: конечный буфер
    превращает неограниченный рост очереди в явный отказ на входе.

    Правило без проверки — пожелание: третий пункт «в работе» появляется
    незаметно и не вызывает ничего. Здесь он даёт FAIL.

    🔴 ЧЕГО НЕ ЛОВИТ: пункт, лежащий в «в работе» месяцами. Предел ограничивает
    ЧИСЛО, а не возраст — застоявшуюся задачу видит только человек либо
    отдельная проверка по дате (её пока нет).
    """
    problems: list[str] = []
    for name in ("TASKS.md", "ROADMAP.md", "BOARD.md"):
        path = root / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in LIMIT_RE.finditer(text):
            label, limit, body = match.group(1), int(match.group(2)), match.group(3)
            count = len([l for l in body.splitlines()
                         if re.match(r"^\s*[-*]\s*\[[ xX]\]", l)])
            if count > limit:
                problems.append(
                    f"{name}: в разделе {label} {count} пунктов при пределе {limit} — "
                    f"убери лишнее обратно в очередь; предел на вход и есть "
                    f"единственное, что останавливает рост L (закон Литтла)")
    return problems


def selftest_wip_limits() -> bool:
    """Ловит превышение и молчит на пределе ровно. Обе половины обязательны:
    без второй проверка краснела бы на заполненном под завязку разделе.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        f = root / "TASKS.md"

        def probe(n: int) -> int:
            items = "\n".join(f"- [ ] задача {i}" for i in range(n))
            f.write_text(f"<!-- WIP:START limit=2 -->\n{items}\n<!-- WIP:END -->\n",
                         encoding="utf-8")
            return len(check_wip_limits(root))

        if probe(0) or probe(1) or probe(2):
            return False          # до предела включительно — молчим
        if probe(3) != 1:
            return False          # превышение — ловим
        # Раздел без маркеров лимита не проверяется вовсе.
        f.write_text("- [ ] раз\n- [ ] два\n- [ ] три\n- [ ] четыре\n", encoding="utf-8")
        return check_wip_limits(root) == []


# Порог числа исключений: больше — значит правило неверно, а не мир виноват.
EXCEPTION_BUDGET = 12


def check_exception_budget(root: Path) -> tuple[list[str], list[str]]:
    """Исключение без срока пересмотра — тихая деградация стандарта.

    🔴 Заведено 29.08.2026 по исследованию рисков. Индустриальная практика
    ведения принятых рисков (risk acceptance / documented exception) требует
    у записи **три** вещи, а не одну: причину, **дату пересмотра** и владельца.
    У нас была только причина.

    Почему срок важнее, чем кажется: то, что принято «на время», живёт вечно
    и через год читается как норма. Это дрейф, который **не порождает
    инцидентов, пока не станет поздно**, — тот же класс, что «drift to low
    performance» у Meadows и миграция практики у Rasmussen.

    Второе — **счётчик как индикатор**. Мониторить надо не отдельное
    исключение, а их **число и темп роста**: рост означает либо что проверка
    настроена слишком строго (чинить проверку), либо что стандарт де-факто
    изменился (переписать стандарт). Порог один: больше `EXCEPTION_BUDGET` —
    это уже не исключения, это неверное правило.

    🔴 ЧЕГО НЕ ЛОВИТ: осмысленность причины. «Потому что так надо» пройдёт
    проверку так же, как разбор на десять строк. Качество обоснования —
    суждение, гейт его не выносит (`69` §4д).
    """
    fails: list[str] = []
    warns: list[str] = []
    total = 0
    for name in (".revision_allowlist", ".size-exception"):
        path = root / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        entries = [l for l in text.splitlines()
                   if l.strip() and not l.lstrip().startswith("#")]
        total += len(entries)
        if entries and not re.search(r"пересмотр|срок действия|действует до", text, re.I):
            warns.append(f"{name}: {len(entries)} исключений без срока пересмотра — "
                         f"добавь строку «Пересмотр: ДД.ММ.ГГГГ»; принятое «на время» "
                         f"без даты живёт вечно и становится нормой")
    if total > EXCEPTION_BUDGET:
        fails.append(f"исключений в репе {total} при бюджете {EXCEPTION_BUDGET} — "
                     f"это уже не исключения, а неверное правило: чини проверку "
                     f"или переписывай стандарт")
    return fails, warns


def selftest_exception_budget() -> bool:
    """Ловит отсутствие срока и превышение бюджета; молчит на здоровом файле."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        f = root / ".revision_allowlist"

        f.write_text("# причина\nодин.md\nдва.md\n", encoding="utf-8")
        fails, warns = check_exception_budget(root)
        if fails or len(warns) != 1:
            return False          # без срока — предупреждение

        f.write_text("# причина\n# Пересмотр: 01.12.2026\nодин.md\n", encoding="utf-8")
        fails, warns = check_exception_budget(root)
        if fails or warns:
            return False          # со сроком — молчим

        many = "\n".join(f"файл{i}.md" for i in range(EXCEPTION_BUDGET + 1))
        f.write_text(f"# Пересмотр: 01.12.2026\n{many}\n", encoding="utf-8")
        fails, warns = check_exception_budget(root)
        return len(fails) == 1 and not warns


def check_allowlist_rot(root: Path) -> list[str]:
    """Исключение, пережившее свой предмет, — тихо выключенная проверка.

    Строка в allowlist снимает контроль с файла или каталога. Если предмет
    переименован или удалён, строка остаётся и ничего видимого не делает —
    но следующий файл с таким путём родится уже без проверки
    (`21-revision-protocol.md` §4а, календарные мины).

    🔴 29.08.2026 проверка переведена с жёсткого словаря внутри гейта на
    `.revision_allowlist` каждой репы — туда исключения и переехали, когда
    перечень путей заменили правилом (`is_assembly`). Побочная выгода: теперь
    контроль распространяется на ВСЕ исключения всех реп, а не на четыре
    записи про base-repo.

    🔴 ЧЕГО НЕ ЛОВИТ: исключение, чей предмет ЖИВ, а причина давно неверна. Файл на месте, срок не вышел — а основание, по которому его вывели из проверки, отпало год назад.
    """
    allow_file = root / ".revision_allowlist"
    if not allow_file.is_file():
        return []
    problems: list[str] = []
    for raw in allow_file.read_text(encoding="utf-8", errors="replace").splitlines():
        entry = raw.strip()
        if not entry or entry.startswith("#"):
            continue
        # Словарная единица (`cjk-term: …`) предмета на диске не имеет —
        # она про содержимое, а не про путь. Протухнуть ей нечем.
        if entry.startswith("cjk-term:"):
            continue
        # 🔴 `link:` — цель ссылки, которой НЕ ДОЛЖНО существовать. Найдено
        # 29.08.2026 в `master-admission`: план будущей ВКР намеренно ссылается
        # на рисунки, которые ещё предстоит сделать («здесь будет рисунок»),
        # и семь таких записей моя же проверка объявила протухшими. Ошибка была
        # в проверке: она считала, что всякое исключение называет существующий
        # файл, тогда как исключение для БИТОЙ ссылки указывает в пустоту
        # по замыслу — в этом весь его смысл.
        if entry.startswith("link:"):
            continue
        # 🔴 `gone:` — предмет, которого НЕ ДОЛЖНО существовать. Найдено
        # 29.08.2026 в `salvation`: исключение на `_base/` заведено потому,
        # что журнал говорит «`_base/` наружу не идёт» — это утверждение ОБ
        # ОТСУТСТВИИ каталога у публичной репы, куда база не раздаётся
        # по замыслу. Проверка протухания требовала, чтобы предмет существовал,
        # и объявила протухшим исключение, которое живо ровно потому, что
        # предмета нет. Третья форма исключения, у которой предмета на диске
        # быть не может — как `cjk-term:` и `link:`.
        if entry.startswith("gone:"):
            continue
        target = root / entry.rstrip("/")
        if not target.exists():
            problems.append(f"исключение указывает в пустоту: {entry}")
    return problems


def selftest_allowlist_rot() -> bool:
    """Ловит мёртвую запись и молчит на живой; словарную единицу не трогает."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "жив.md").write_text("x\n", encoding="utf-8")
        (root / ".revision_allowlist").write_text(
            "# причина\nжив.md\nумер.md\ncjk-term: X\n"
            "link: figures/будет-позже.png\n"
            "gone: _base/\n", encoding="utf-8")
        got = check_allowlist_rot(root)
        # Ровно ОДНА находка: `умер.md`. `cjk-term:` и `link:` предмета на
        # диске не имеют по построению — объявить их протухшими значит
        # требовать существования того, чего не должно быть.
        return len(got) == 1 and "умер.md" in got[0]


# 🔴 ЧТО ГЕЙТ НЕ ПРОВЕРЯЕТ — печатается вместе с вердиктом, всегда.
#
# Заведено 29.08.2026 по исследованию human factors, и это не педантизм,
# а самая дорогая находка дня. Alberdi et al. (маммография с подсказчиком):
# обнаружение непомеченных системой раков упало с **46 % до 21 %** — врачи
# трактовали ОТСУТСТВИЕ метки как доказательство отсутствия болезни.
#
# > **Молчащий проверяющий делает человека хуже, чем отсутствие проверяющего.**
#
# Строка «ИТОГ: CLEAN» — ровно такой пустой положительный вердикт. Она
# читается как «в репе всё в порядке», хотя означает лишь «ни одна из 26
# проверок не сработала». Разница огромна, и без явного списка непокрытого
# её не видно.
#
# Второе основание — automation bias (Parasuraman & Manzey, Human Factors
# 2010): благодушие к автоматике не лечится ни тренировкой, ни инструкцией,
# ни у новичков, ни у экспертов. Работает только изменение самого вывода.
OVERRIDES_FILE = ".base-overrides"


def load_overrides(root: Path) -> set[str]:
    """Объявленные отклонения репы от канона базы.

    Формат — как у `.revision_allowlist`: строки-предметы, `#` — причина.
    Пустой или отсутствующий файл означает «отклонений не объявлено»,
    а не «отклонений нет»: второе проверяется, первое лишь заявляется.
    """
    f = root / OVERRIDES_FILE
    if not f.is_file():
        return set()
    return {ln.strip() for ln in f.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")}


def check_declared_overrides(root: Path) -> tuple[list[str], list[str]]:
    """Отклонение репы от канона обязано быть ОБЪЯВЛЕННЫМ, а не молчаливым.

    Внедрение кандидата №8 из `08-systems-theory-lab/INDUSTRY_VS_US.md`.
    До сих пор у репы было два исхода: подчиниться канону или молча
    разойтись с ним. Третьего, законного, не было — и потому расхождение
    выглядело одинаково и когда оно ошибка, и когда осознанный выбор.

    Проверяется один наблюдаемый вид отклонения: локальный документ
    `00-infrastructure/NN-*.md`, занявший номер, который в каноне
    (`_base/00-infrastructure/`) держит другой документ. Замер 30.08.2026:
    23 таких столкновения, все в `mission-control`, где своя серия
    документов идёт параллельно канонической и намеренно.

    🔴 Вред пока потенциальный, и это сказано честно: из двух ссылок вида
    «см. `NN`» в репе двусмысленных ноль — обе указывают на номера вне
    локального диапазона. Правило заводится не на случившийся ущерб,
    а на то, что при следующей ссылке «см. `14`» адресат будет неопределён,
    и определить его будет уже нечем.

    Объявление — строка `00-infrastructure/NN-имя.md` в `.base-overrides`
    с причиной выше по файлу. Объявлено — молчим: выбор сделан и виден.

    🔴 ЧЕГО НЕ ЛОВИТ: отклонение в СОДЕРЖАНИИ при неконфликтном имени.
    Локальный документ, тихо противоречащий канону под собственным номером,
    здесь невидим — сравниваются имена, а не утверждения. Это тот же предел,
    что у всего гейта: форма проверяема, смысл нет.
    """
    base = root / "_base" / "00-infrastructure"
    own = root / "00-infrastructure"
    if not (base.is_dir() and own.is_dir()):
        return [], []          # база сама себе не наследник — проверять нечего
    canon = {p.name.split("-")[0]: p.name for p in base.glob("*.md")
             if p.name[:1].isdigit()}
    declared = load_overrides(root)
    silent = []
    for p in sorted(own.glob("*.md")):
        if not p.name[:1].isdigit():
            continue
        other = canon.get(p.name.split("-")[0])
        if other and other != p.name:
            rel = f"00-infrastructure/{p.name}"
            if rel not in declared:
                silent.append(f"{rel} занял номер канона ({other}) — не объявлено")
    return [], silent


def selftest_declared_overrides() -> bool:
    """Различение: объявленное молчит, необъявленное названо.

    🔴 Канарейка строит репы во временном каталоге, а не судит по живой:
    на живой она повторяла бы результат самой проверки и была бы тождеством —
    ровно тот дефект, что уже ловили у порога `system_status.py`.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "_base" / "00-infrastructure").mkdir(parents=True)
        (root / "00-infrastructure").mkdir()
        (root / "_base" / "00-infrastructure" / "14-canon.md").write_text("k", encoding="utf-8")
        (root / "00-infrastructure" / "14-local.md").write_text("l", encoding="utf-8")

        if len(check_declared_overrides(root)[1]) != 1:      # столкновение видно
            return False
        (root / OVERRIDES_FILE).write_text(
            "# причина\n00-infrastructure/14-local.md\n", encoding="utf-8")
        if check_declared_overrides(root)[1]:                # объявленное молчит
            return False
        plain = root / "plain"                               # репа без _base/ — не тревога
        (plain / "00-infrastructure").mkdir(parents=True)
        (plain / "00-infrastructure" / "14-x.md").write_text("x", encoding="utf-8")
        return check_declared_overrides(plain) == ([], [])


RITUAL_SCRIPTS = ("close_batch.py", "sync_base_local.py",
                  "bump_repo.py", "pack_release.py")
CONTRACT_FIELDS = ("ПРЕДУСЛОВИЯ", "ПОСТУСЛОВИЯ", "ИНВАРИАНТ")


def check_ritual_contracts(root: Path) -> tuple[list[str], list[str]]:
    """Скрипт-ритуал объявляет предусловия, постусловия и инвариант.

    Внедрение кандидата №10 из `08-systems-theory-lab/INDUSTRY_VS_US.md`
    (design by contract, Meyer). Замер 30.08.2026: из четырёх ритуалов поля
    были только у `close_batch.py` — у трёх остальных **ноль из трёх**.

    🔴 Разница не в оформлении. Постусловие отвечает на вопрос, который
    «шаги не упали» не покрывает: **результат на месте?** Батч, где версия
    поднята, а архива нет, выглядит закрытым и не пережил бы обрыва — ровно
    тот случай, ради которого `close_batch.py` и заводился.

    Требуется от ритуалов — скриптов, которые **меняют состояние системы**
    и потому могут оборваться посередине. От измеряющих скриптов не требуется:
    у замера нет постусловия, кроме напечатанного числа.

    🔴 ЧЕГО НЕ ЛОВИТ: правдивость контракта. Объявленное постусловие,
    которое код не проверяет, пройдёт эту проверку полностью. Форма
    проверяема механически, соответствие формы коду — нет; для второго
    есть только чтение человеком.
    """
    import ast as _ast
    scripts = root / "scripts"
    if not scripts.is_dir():
        return [], []
    missing = []
    for name in RITUAL_SCRIPTS:
        f = scripts / name
        if not f.is_file():
            continue
        try:
            doc = _ast.get_docstring(_ast.parse(f.read_text(encoding="utf-8"))) or ""
        except (SyntaxError, OSError, UnicodeError):
            missing.append(f"{name}: докстрока не читается")
            continue
        absent = [x for x in CONTRACT_FIELDS if x not in doc]
        if absent:
            missing.append(f"{name}: нет полей контракта — {', '.join(absent)}")
    return [], missing


def selftest_ritual_contracts() -> bool:
    """Различение: полный контракт молчит, неполный назван.

    🔴 Синтетический каталог, а не живой: на живом канарейка повторяла бы
    вывод самой проверки и была бы тождеством.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "scripts").mkdir()
        full = '"""Р.\n\nПРЕДУСЛОВИЯ: а\nПОСТУСЛОВИЯ: б\nИНВАРИАНТ: в\n"""\n'
        (root / "scripts" / "close_batch.py").write_text(full, encoding="utf-8")
        (root / "scripts" / "bump_repo.py").write_text(
            '"""Р. ПРЕДУСЛОВИЯ: а."""\n', encoding="utf-8")
        _, warns = check_ritual_contracts(root)
        if len(warns) != 1 or "bump_repo.py" not in warns[0]:
            return False
        if "ПОСТУСЛОВИЯ" not in warns[0] or "ИНВАРИАНТ" not in warns[0]:
            return False          # названы именно недостающие поля
        return check_ritual_contracts(root / "нет-такой") == ([], [])


BLIND_SPOT_MARKERS = (
    # Форма прижилась сама: 7 из 10 первых объявлений написаны как
    # «ЧЕГО НЕ ЛОВИТ». Остальные варианты приняты, чтобы канонизация
    # формы не объявила вне закона уже написанное по делу.
    "ЧЕГО НЕ ЛОВИТ", "НЕ ЛОВИТ", "не ловит", "не поймает",
    "не увидит", "не покрывает", "здесь не ловится",
)


def check_blind_spots_declared(root: Path) -> tuple[list[str], list[str]]:
    """Каждая проверка обязана назвать класс ошибки, который принципиально не поймает.

    Внедрение кандидата №2 из `08-systems-theory-lab/INDUSTRY_VS_US.md`:
    расширяет `71` §7г-бис с инструментов на отдельные проверки. До сих пор
    границы объявлял гейт ЦЕЛИКОМ (константа `UNCOVERED`, четыре строки),
    а каждая отдельная `check_*` выглядела полной в своей области.

    🔴 Разница практическая, а не эстетическая. Общее «гейт не видит
    содержательного устаревания» не подсказывает, что `check_links` считает
    ссылку на существующий, но неверный файл здоровой. Читающий вывод
    `[OK] Ссылки целы` делает вывод сильнее, чем проверка даёт.

    Работает интроспекцией по своему же файлу: `check_*` без объявления —
    предупреждение с именем. Порог мягкий (`warn`, не `fail`) намеренно:
    новая проверка не должна валить гейт до того, как автор успел подумать
    над её слепым пятном — но и пройти незамеченной не должна.

    ЧЕГО НЕ ЛОВИТ: **правдивость** объявления. Строка «не ловит опечатки»
    у проверки, которая на деле не ловит половину своей области, пройдёт.
    Форма проверяема механически, точность — нет. Это ровно тот случай,
    где `UNCOVERED` называет «осмысленность формулировок» непокрытой.
    """
    import ast as _ast
    src = Path(__file__).read_text(encoding="utf-8")
    fns = [n for n in _ast.walk(_ast.parse(src))
           if isinstance(n, _ast.FunctionDef) and n.name.startswith("check_")]
    silent = []
    for f in fns:
        doc = _ast.get_docstring(f) or ""
        if not any(w in doc for w in BLIND_SPOT_MARKERS):
            silent.append(f.name)
    if silent:
        return [], [f"не объявила слепое пятно: {n}" for n in sorted(silent)]
    return [], []


def selftest_blind_spots_declared() -> bool:
    """Проверяется РАЗЛИЧЕНИЕ: объявление видно, его отсутствие видно тоже.

    🔴 Канарейка на живом файле была бы тождеством: она бы повторяла
    результат самой проверки. Поэтому разбирается синтетический исходник
    с двумя функциями — одна объявила, другая нет.
    """
    import ast as _ast
    fake = (
        'def check_a(root):\n'
        '    """Делает А.\n\n    ЧЕГО НЕ ЛОВИТ: класс Б.\n    """\n'
        '    return [], []\n'
        'def check_b(root):\n'
        '    """Делает Б, и молчит о границах."""\n'
        '    return [], []\n'
    )
    fns = [n for n in _ast.walk(_ast.parse(fake))
           if isinstance(n, _ast.FunctionDef) and n.name.startswith("check_")]
    silent = [f.name for f in fns
              if not any(w in (_ast.get_docstring(f) or "") for w in BLIND_SPOT_MARKERS)]
    # объявившая молчит, умолчавшая названа — ровно одна, и это check_b
    return silent == ["check_b"]


UNCOVERED = (
    "содержательное устаревание: текст, верный по форме и ложный по сути",
    "осмысленность формулировок — правил, имён, причин в исключениях",
    "полнота: правило, которого нет вовсе, не может быть нарушено",
    "верна ли сама проверка (validation) — гейт умеет только verification",
)


def print_coverage(checks_run: int) -> None:
    """Покрытие и его границы — рядом с вердиктом, а не в документации."""
    import ast as _ast
    # 🔴 Было литералом «23», и любая новая канарейка молча делала число
    # ложным. Счётчик, который не считает, — та же болезнь, что проверка,
    # которая не проверяет.
    canaries = sum(
        1 for n in _ast.walk(_ast.parse(Path(__file__).read_text(encoding='utf-8')))
        if isinstance(n, _ast.FunctionDef) and n.name.startswith("selftest_"))
    print(f"    покрыто проверками: {checks_run} · канареек: {canaries}")
    print("    🔴 НЕ покрыто (гейт этого не видит):")
    for item in UNCOVERED:
        print(f"       · {item}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Ревизионный гейт knowledge-репы")
    parser.add_argument("--root", default=".", help="корень репы (по умолчанию текущая папка)")
    parser.add_argument("--strict", action="store_true", help="warnings тоже валят гейт")
    parser.add_argument("--blind-spots", action="store_true",
                        help="карта: что каждая проверка принципиально не ловит")
    args = parser.parse_args()

    if args.blind_spots:
        import ast as _ast
        src = Path(__file__).read_text(encoding="utf-8")
        fns = [n for n in _ast.walk(_ast.parse(src))
               if isinstance(n, _ast.FunctionDef) and n.name.startswith("check_")]
        print("Карта слепых пятен: что каждая проверка принципиально НЕ ловит\n")
        named = silent = 0
        for f in sorted(fns, key=lambda n: n.name):
            doc = _ast.get_docstring(f) or ""
            line = next((l.strip() for l in doc.splitlines()
                         if any(w in l for w in BLIND_SPOT_MARKERS)), "")
            if line:
                named += 1
                # 🔴 Отрезать префикс можно ТОЛЬКО когда маркер начинает строку.
                # Иначе у «пункт без срока здесь не ловится» отрезалось начало,
                # и оставалось «ся — это забота проверки»: обрезка по маркеру
                # предполагала форму, которой держатся не все объявления.
                for w in BLIND_SPOT_MARKERS:
                    head = line.lstrip("🔴 ·*")
                    if head.startswith(w):
                        line = head[len(w):].lstrip(" :*(").rstrip()
                        break
                else:
                    line = line.lstrip("🔴 ·*").rstrip()
                print(f"  {f.name}")
                print(f"      не ловит: {line[:96]}")
            else:
                silent += 1
                print(f"  {f.name}")
                print(f"      🔴 слепое пятно НЕ объявлено")
        print(f"\nобъявили: {named} · молчат: {silent} · всего проверок: {len(fns)}")
        print("\n🔴 Объявление проверяется по ФОРМЕ, не по правдивости:")
        print("   строка на месте ≠ строка верна. Это граница самого механизма.")
        return 0

    root = Path(args.root).resolve()
    files = iter_files(root)
    allowlist = load_allowlist(root)

    failures: list[str] = []
    warnings: list[str] = []

    if not selftest_uri_schemes():
        failures.append("канарейка схем URI сломана: перестала отличать "
                        "адрес со схемой от относительного пути")
        print("[FAIL] Канарейка схем URI: самопроверка не прошла")

    broken, checked, frozen_skipped = check_links(root, files, allowlist)
    if broken:
        failures.extend(broken)
        print(f"[FAIL] Битые ссылки: {len(broken)}")
        for line in broken:
            print(f"    · {line}")
    else:
        print("[OK] Битые ссылки")
    print(f"    · проверено ссылок: {checked}; замороженных .md пропущено: {frozen_skipped}; allowlist: {len(allowlist)}")

    bad_names = check_names(root, files)
    if bad_names:
        failures.extend(bad_names)
        print(f"[FAIL] Имена с порчей #Uxxxx (PIT-009): {len(bad_names)}")
        for line in bad_names:
            print(f"    · {line}")
    else:
        print("[OK] Имена файлов (нет #Uxxxx-порчи)")

    mixed = check_mixed_script_names(root, files, allowlist)
    if mixed:
        failures.extend(mixed)
        print(f"[FAIL] Кириллица+латиница ВНУТРИ одного слова (PIT-085): {len(mixed)}")
        for line in mixed:
            print(f"    · {line}")
    else:
        if selftest_mixed_script():
            print("[OK] Имена без смешения кириллицы и латиницы внутри слова")
        else:
            failures.append("канарейка PIT-085 сломана")
            print("[FAIL] Канарейка PIT-085: слип внутри слова и законное "
                  "соседство алфавитов не различаются")

    dupes = check_registry_dupes(root)
    if dupes:
        failures.extend(dupes)
        print(f"[FAIL] Дубли номеров в сквозных реестрах (72 §4а): {len(dupes)}")
        for line in dupes:
            print(f"    · {line}")
    else:
        if selftest_registry_dupes():
            print("[OK] Сквозные реестры: дублей номеров нет (PIT/SYN/ADR/CHANGELOG)")
        else:
            failures.append("канарейка реестров сломана: не ловит подсаженные дубли")
            print("[FAIL] Канарейка реестров: самопроверка не прошла")

    # 🔴 03.09.2026: мета-гейт нашёл эту канарейку ОПРЕДЕЛЁННОЙ, НО НЕ ВЫЗЫВАЕМОЙ.
    # Написана она была ровно затем, чтобы пять счётчиков карточек не разошлись
    # между собой, — и три недели не проверяла ничего. Тот же класс, что весь
    # этот батч: механизм есть, исполнителя нет (`69` §4г — гейт был красным
    # 41 день, и никто не смотрел).
    if selftest_card_re():
        print("[OK] Канарейка разбора карточек: уровни и пробелы различаются")
    else:
        failures.append("канарейка card_re сломана: счётчики карточек разойдутся молча")
        print("[FAIL] Канарейка разбора карточек: самопроверка не прошла")

    camp = check_campaign_log(root)
    if camp:
        failures.extend(camp)
        print(f"[FAIL] Кампания синтеза не записана в журнал прогона: {len(camp)}")
        for line in camp:
            print(f"    · {line}")
    else:
        if selftest_campaign_log():
            print("[OK] След кампании в журнале прогона за текущую версию есть")
        else:
            failures.append("канарейка журнала кампании сломана")
            print("[FAIL] Канарейка журнала кампании: самопроверка не прошла")

    # 🔴 Заведено 03.09.2026 после того, как `ADR-007` закрыл ОДИН экземпляр
    # класса вместо класса: журнал прогона исключили из отпечатка канона
    # списком, а перепись по коду нашла семь таких файлов. Гейт следит,
    # чтобы восьмой был объявлен, а не обнаружен через месяц по ложным
    # «разошедшимся» копиям. Разбор — `scripts/runtime_writes.py`.
    # 🔴 Заведено 03.09.2026 вместе со стандартом `00-infrastructure/94`.
    # Журналы — единственный механизм, дающий системе производную: не «как
    # сейчас», а «как менялось». Перестановка строк уничтожает именно её,
    # и заметить это глазами нельзя: файл на 517 строк выглядит так же.
    jr = check_journals(root)
    if jr:
        failures.extend(jr)
        print(f"[FAIL] Журналы: порядок или учёт нарушены (94): {len(jr)}")
        for line in jr:
            print(f"    · {line}")
    else:
        if selftest_journals(root):
            print("[OK] Журналы: порядок событий не нарушен, все учтены")
        else:
            failures.append("канарейка журналов сломана")
            print("[FAIL] Канарейка журналов: самопроверка не прошла")

    # 🔴 Заведено 04.09.2026, ПОСЛЕ разбора четырнадцати существующих сирот.
    # Порядок важен: гейт, рождающийся красным, отключают в тот же день.
    # Сначала предмет приведён в порядок (14 → 0), потом поставлен сторож.
    orph = check_orphans(root)
    if orph:
        failures.extend(orph)
        print(f"[FAIL] Документы, на которые никто не ссылается: {len(orph)}")
        for line in orph[:8]:
            print(f"    · {line}")
        if len(orph) > 8:
            print(f"    · … и ещё {len(orph) - 8}")
    else:
        print("[OK] Недостижимых документов нет: на каждый есть входящая ссылка")

    rw = check_runtime_writes(root)
    if rw:
        failures.extend(rw)
        print(f"[FAIL] Пишется в раздаваемое, но не объявлено (ADR-007): {len(rw)}")
        for line in rw:
            print(f"    · {line}")
    else:
        if selftest_runtime_writes(root):
            print("[OK] Записи в раздаваемое объявлены (журналы вне отпечатка)")
        else:
            failures.append("канарейка объявлений runtime-записей сломана")
            print("[FAIL] Канарейка объявлений runtime-записей: самопроверка не прошла")

    dangling = check_dangling_registry_refs(root, files)
    if dangling:
        failures.extend(dangling)
        print(f"[FAIL] Ссылки на несуществующие карточки реестров: {len(dangling)}")
        for line in dangling:
            print(f"    · {line}")
    else:
        if selftest_dangling_refs():
            print("[OK] Все ссылки PIT-NNN / SYN-NNN ведут на живые карточки")
        else:
            failures.append("канарейка висячих ссылок сломана")
            print("[FAIL] Канарейка висячих ссылок: самопроверка не прошла")

    levels = check_card_heading_levels(root)
    if levels:
        failures.extend(levels)
        print(f"[FAIL] Карточки реестров не на своём уровне заголовка: {len(levels)}")
        for line in levels:
            print(f"    · {line}")
    else:
        if selftest_card_heading_levels():
            print("[OK] Карточки PIT/SYN на уровне, который видит гейт")
        else:
            failures.append("канарейка уровней заголовков сломана")
            print("[FAIL] Канарейка уровней заголовков: самопроверка не прошла")

    prose = check_prose_counts(root)
    if prose:
        failures.extend(prose)
        print(f"[FAIL] Числа в прозе разошлись с диском (PIT-091): {len(prose)}")
        for line in prose:
            print(f"    · {line}")
    else:
        if selftest_prose_counts():
            print("[OK] Числа в прозе совпадают с диском (PIT/SYN/документы кита)")
        else:
            failures.append("канарейка чисел сломана: не ловит подсаженное расхождение")
            print("[FAIL] Канарейка чисел в прозе: самопроверка не прошла")

    if not selftest_research_reports():
        failures.append("канарейка отчётов исследования сломана: не ловит отчёт "
                        "без раскрытия процесса")
        print("[FAIL] Канарейка отчётов исследования: самопроверка не прошла")
    else:
        rr = check_research_reports(root)
        if rr:
            failures.extend(rr)
            print(f"[FAIL] Отчёт исследования не раскрывает процесс: {len(rr)}")
            for line in rr:
                print(f"    · {line}")

    if not selftest_secret_hygiene():
        failures.append("канарейка гигиены секретов сломана: не ловит .env "
                        "без правила в .gitignore либо ругается на закрытую репу")
        print("[FAIL] Канарейка гигиены секретов: самопроверка не прошла")
    else:
        sec_fails, sec_warns = check_secret_hygiene(root)
        if sec_fails:
            failures.extend(sec_fails)
            print(f"[FAIL] Секреты в файлах репы: {len(sec_fails)}")
            for line in sec_fails:
                print(f"    · {line}")
        if sec_warns:
            warnings.extend(sec_warns)
            print(f"[WARN] Секрет лежит значением в `.env` (канон — связка ключей): {len(sec_warns)}")
            for line in sec_warns:
                print(f"    · {line}")
        if not sec_fails and not sec_warns:
            print("[OK] Гигиена секретов: значений в файлах репы нет")

    if not selftest_exception_budget():
        failures.append("канарейка бюджета исключений сломана")
        print("[FAIL] Канарейка бюджета исключений: самопроверка не прошла")
    else:
        ex_f, ex_w = check_exception_budget(root)
        if ex_f:
            failures.extend(ex_f)
            print(f"[FAIL] Бюджет исключений превышен: {len(ex_f)}")
            for line in ex_f:
                print(f"    · {line}")
        if ex_w:
            warnings.extend(ex_w)
            print(f"[WARN] Исключения без срока пересмотра: {len(ex_w)}")
            for line in ex_w:
                print(f"    · {line}")

    if not selftest_wip_limits():
        failures.append("канарейка предела задач сломана: не ловит превышение "
                        "либо краснеет на заполненном под завязку разделе")
        print("[FAIL] Канарейка предела задач: самопроверка не прошла")
    else:
        wip = check_wip_limits(root)
        if wip:
            failures.extend(wip)
            print(f"[FAIL] Предел числа задач превышен: {len(wip)}")
            for line in wip:
                print(f"    · {line}")

    if not selftest_pointer_purity():
        failures.append("канарейка чистоты указателя сломана: не ловит "
                        "состояние внутри файла-указателя")
        print("[FAIL] Канарейка чистоты указателя: самопроверка не прошла")
    else:
        pp = check_pointer_purity(root)
        if pp:
            failures.extend(pp)
            print(f"[FAIL] Указатель хранит состояние: {len(pp)}")
            for line in pp:
                print(f"    · {line}")

    # 🔴 ПРЕДУПРЕЖДЕНИЕ, А НЕ ОТКАЗ — и это осознанный выбор.
    # Просроченные пункты `TASKS.md` — действия, которые может совершить
    # ТОЛЬКО владелец. Красный гейт здесь заблокировал бы закрытие батчей
    # вахты за то, что вахта физически не может исправить, и приучил бы
    # закрывать батчи с `--skip-gate` — то есть отменил бы гейт целиком
    # (`PIT-085`: проверка, краснеющая на том, что нельзя починить,
    # перестаёт читаться). Задача проверки — сделать истечение ВИДИМЫМ,
    # а не остановить работу.
    if not selftest_task_expiry():
        failures.append("канарейка срока задач сломана: не отличает "
                        "просроченное от будущего")
        print("[FAIL] Канарейка срока задач: самопроверка не прошла")
    else:
        expired = check_task_expiry(root)
        if expired:
            warnings.extend(expired)
            print(f"[WARN] Срок прошёл, исход не выбран: {len(expired)}")
            for line in expired[:6]:
                print(f"    · {line}")
            if len(expired) > 6:
                print(f"    · … и ещё {len(expired) - 6}")

    if not selftest_debt_markers():
        failures.append("канарейка маркеров долга сломана: не отличает "
                        "маркер без даты от упоминания слова")
        print("[FAIL] Канарейка маркеров долга: самопроверка не прошла")
    else:
        debt = check_debt_markers(root)
        if debt:
            failures.extend(debt)
            print(f"[FAIL] Маркер долга без даты: {len(debt)}")
            for line in debt[:5]:
                print(f"    · {line}")

    if not selftest_pitfall_resolution():
        failures.append("канарейка поля разрешения сломана: не отличает "
                        "новую карточку без поля от старой")
        print("[FAIL] Канарейка поля разрешения: самопроверка не прошла")
    else:
        unresolved = check_pitfall_resolution(root)
        if unresolved:
            failures.extend(unresolved)
            print(f"[FAIL] Карточка без ответа о разрешении: {len(unresolved)}")
            for line in unresolved[:5]:
                print(f"    · {line}")

    if not selftest_pointer_files():
        failures.append("канарейка файлов-указателей сломана: не отличает "
                        "указатель от короткого документа")
        print("[FAIL] Канарейка файлов-указателей: самопроверка не прошла")

    if not selftest_watch_identity_sources():
        failures.append("канарейка источника вахты сломана: не ловит перечень "
                        "«почта → буква» в коде")
        print("[FAIL] Канарейка источника вахты: самопроверка не прошла")
    elif (root / WATCH_REGISTRY).is_file():
        # Проверка осмысленна только там, где реестр и лежит, — в базе.
        wi = check_watch_identity_sources(root)
        if wi:
            failures.extend(wi)
            print(f"[FAIL] Соответствие «почта → вахта» вписано в код: {len(wi)}")
            for line in wi:
                print(f"    · {line}")

    if not selftest_batch_log():
        failures.append("канарейка журнала батчей сломана: не отличает журнал "
                        "от чужого раздела с тем же номером")
        print("[FAIL] Канарейка журнала батчей: самопроверка не прошла")

    if not selftest_reflexion_model():
        failures.append("канарейка reflexion сломана: не ловит необъявленный каталог")
        print("[FAIL] Канарейка reflexion-модели: самопроверка не прошла")
    else:
        refl = check_reflexion_model(root)
        if refl:
            warnings.extend(refl)
            print(f"[WARN] Структура разошлась с README (reflexion): {len(refl)}")
            for line in refl:
                print(f"    · {line}")

    if not selftest_rule_descriptions():
        failures.append("канарейка описаний правил сломана: не различает "
                        "описание с поводом сработать и без него")
        print("[FAIL] Канарейка описаний правил: самопроверка не прошла")
    else:
        rd = check_rule_descriptions(root)
        if rd:
            failures.extend(rd)
            print(f"[FAIL] Описание скилла/агента не даёт повода сработать: {len(rd)}")
            for line in rd:
                print(f"    · {line}")

    if not selftest_changelog_conventions():
        failures.append("канарейка конвенций журнала сломана: перестала "
                        "различать наличие секции версии и её оформление")
        print("[FAIL] Канарейка конвенций CHANGELOG: самопроверка не прошла")

    if not selftest_allowlist_rot():
        failures.append("канарейка протухших исключений сломана: не ловит "
                        "запись, указывающую в пустоту")
        print("[FAIL] Канарейка протухших исключений: самопроверка не прошла")
    rot = check_allowlist_rot(root)
    if rot:
        failures.extend(rot)
        print(f"[FAIL] Протухшие исключения гейта: {len(rot)}")
        for line in rot:
            print(f"    · {line}")

    sec_dupes = check_section_dupes(root, files)
    if sec_dupes:
        failures.extend(sec_dupes)
        print(f"[FAIL] Повторяющиеся номера разделов внутри документа: {len(sec_dupes)}")
        for line in sec_dupes:
            print(f"    · {line}")
    else:
        if selftest_section_dupes():
            print("[OK] Номера разделов внутри документов уникальны "
                  "(сборки — по числу H1, не по списку путей)")
        else:
            failures.append("канарейка разделов сломана: не ловит подсаженные дубли")
            print("[FAIL] Канарейка разделов: самопроверка не прошла")

    if not selftest_cjk():
        failures.append("канарейка CJK сломана: не ловит синтетический образец")
        print("[FAIL] Канарейка CJK: самопроверка не прошла")
    elif not selftest_cjk_terms():
        # 🔴 Отдельная канарейка: первая проверяет, что иероглиф ЛОВИТСЯ,
        # вторая — что разрешённый термин не глушит проверку целиком.
        failures.append("канарейка cjk-term сломана: исключение по термину "
                        "глушит проверку вместо сужения")
        print("[FAIL] Канарейка cjk-term: самопроверка не прошла")
    else:
        cjk_hits = check_cjk(root, files, allowlist)
        if cjk_hits:
            failures.extend(cjk_hits)
            print(f"[FAIL] Токен-слип модели, иероглифы в тексте: {len(cjk_hits)}")
            for line in cjk_hits:
                print(f"    · {line}")
        else:
            print("[OK] Канарейка CJK (нет токен-слипа)")

    if not selftest_exec_bits():
        failures.append("канарейка exec-bit сломана: не ловит подсаженный неисполняемый файл")
        print("[FAIL] Канарейка exec-bit: самопроверка не прошла")
    else:
        exec_problems = check_exec_bits(root)
        if exec_problems:
            failures.extend(exec_problems)
            print(f"[FAIL] Потерян бит +x на исполняемых стабах/хуках (PIT-151): {len(exec_problems)}")
            for line in exec_problems:
                print(f"    · {line}")
        else:
            print("[OK] Биты +x на месте (.claude/hooks, .githooks, tests/bin)")

    size_warns, size_fails, total_mb = check_sizes(root, files)
    if size_fails:
        failures.extend(size_fails)
        print(f"[FAIL] Файлы у жёсткого лимита: {len(size_fails)}")
        for line in size_fails:
            print(f"    · {line}")
    if size_warns:
        warnings.extend(size_warns)
        print(f"[WARN] Тяжёлое в дереве: {len(size_warns)}")
        for line in size_warns:
            print(f"    · {line}")
    label = "OK"
    if total_mb > REPO_HARD_MB:
        failures.append(f"размер репы {total_mb:.1f} МБ > жёсткого порога {REPO_HARD_MB} МБ")
        label = "FAIL"
    elif total_mb > REPO_SOFT_MB:
        warnings.append(f"размер репы {total_mb:.1f} МБ > мягкого порога {REPO_SOFT_MB} МБ")
        label = "WARN"
    elif total_mb > REPO_TARGET_MB:
        warnings.append(f"размер репы {total_mb:.1f} МБ > целевого порога {REPO_TARGET_MB} МБ")
        label = "WARN"
    print(f"[{label}] Размер дерева: {total_mb:.1f} МБ (цель {REPO_TARGET_MB} / мягкий {REPO_SOFT_MB} / жёсткий {REPO_HARD_MB})")

    rp_problems = check_resume_point_content(root, allowlist)
    if rp_problems:
        failures.extend(rp_problems)
        print("[FAIL] Точка входа: содержание протухло (PIT-116)")
        for line in rp_problems:
            print(f"    · {line}")
    else:
        canaries_ok = selftest_resume_point_refs() and selftest_stale_version_prose()
        if canaries_ok:
            print("[OK] Точка входа §0: размер, ссылки и версии свежие")
        else:
            failures.append("канарейка §0 сломана")
            print("[FAIL] Канарейка §0: кросс-репные ссылки/чужие версии/цитаты "
                  "CHANGELOG не отличаются от своих — смягчение ослепило проверку")

    lv_problems = check_living_documents(root)
    if lv_problems:
        failures.extend(lv_problems)
        print("[FAIL] Живые документы отстали (PIT-116)")
        for line in lv_problems:
            print(f"    · {line}")
    else:
        print("[OK] Живые документы: §3, CHANGELOG, README, ROADMAP, реестр ADR — свежие")

    wl_problems = check_watchlog(root)
    if wl_problems:
        failures.extend(wl_problems)
        print("[FAIL] Точка входа в вахту отстала (PIT-094)")
        for line in wl_problems:
            print(f"    · {line}")
    elif (root / "WATCHLOG.md").is_file():
        print(f"[OK] WATCHLOG §0 совпадает с VERSION "
              f"({(root / 'VERSION').read_text(encoding='utf-8').strip()})")

    nav_missing, nav_total, nav_listed = check_navigator(root)
    if nav_total:
        if nav_missing:
            warnings.extend(f"нет в навигаторе: {n}" for n in nav_missing)
            print(f"[WARN] Навигатор отстал: перечислено {nav_listed} из {nav_total}, "
                  f"не хватает {len(nav_missing)}")
            for line in nav_missing[:12]:
                print(f"    · {line}")
            if len(nav_missing) > 12:
                print(f"    · … ещё {len(nav_missing) - 12}")
        else:
            # Чистая проверка печатает числа: «ок» не отличить от «сверил пустоту».
            print(f"[OK] Навигатор полон: {nav_listed} из {nav_total} документов")

    meta_problems = check_repo_meta_schema(root)
    if meta_problems:
        failures.extend(meta_problems)
        print(f"[FAIL] .repo-meta нарушает схему: {len(meta_problems)}")
        for line in meta_problems:
            print(f"    · {line}")
    elif (root / "repos-map.md").is_file():
        print("[OK] .repo-meta всех реп проходит схему (description/private/topics)")

    map_missing, map_stale = check_repos_map_sync(root)
    if map_missing:
        failures.extend(f"нет в repos-map.md: {n}" for n in map_missing)
        print(f"[FAIL] repos-map.md отстала от диска — не хватает {len(map_missing)}")
        for line in map_missing:
            print(f"    · {line}")
    if map_stale:
        warnings.extend(f"в repos-map.md, нет на диске: {n}" for n in map_stale)
        print(f"[WARN] repos-map.md называет репы, которых нет на диске: {len(map_stale)}")
        for line in map_stale:
            print(f"    · {line}")
    if not map_missing and not map_stale and (root / "repos-map.md").is_file():
        print("[OK] repos-map.md совпадает с ~/repos/ на диске")

    if not selftest_ritual_contracts():
        failures.append("канарейка контрактов ритуалов сломана")
        print("[FAIL] Канарейка контрактов ритуалов: самопроверка не прошла")
    else:
        _, rc_warns = check_ritual_contracts(root)
        if rc_warns:
            warnings.extend(rc_warns)
            print(f"[WARN] Ритуалы без объявленного контракта: {len(rc_warns)}")
            for line in rc_warns:
                print(f"    · {line}")
        elif (root / "scripts").is_dir():
            print("[OK] Ритуалы объявили предусловия, постусловия и инвариант")

    if not selftest_declared_overrides():
        failures.append("канарейка объявленных отклонений сломана")
        print("[FAIL] Канарейка объявленных отклонений: самопроверка не прошла")
    else:
        _, ov_warns = check_declared_overrides(root)
        if ov_warns:
            warnings.extend(ov_warns)
            print(f"[WARN] Молчаливые отклонения от канона: {len(ov_warns)}")
            for line in ov_warns:
                print(f"    · {line}")
        elif (root / "_base" / "00-infrastructure").is_dir():
            print("[OK] Отклонения от канона объявлены или отсутствуют")

    if not selftest_blind_spots_declared():
        failures.append("канарейка объявления слепых пятен сломана")
        print("[FAIL] Канарейка слепых пятен: самопроверка не прошла")
        bs_warns = []
    else:
        _, bs_warns = check_blind_spots_declared(root)
    if bs_warns:
        warnings.extend(bs_warns)
        print(f"[WARN] Проверки, не объявившие слепое пятно: {len(bs_warns)}")
        for line in bs_warns:
            print(f"    · {line}")
    else:
        print("[OK] Каждая проверка объявила, чего принципиально не ловит")

    empty = check_empty_dirs(root)
    if empty:
        warnings.extend(f"пустая папка: {d}" for d in empty)
        print(f"[WARN] Пустые папки: {len(empty)}")
        for line in empty:
            print(f"    · {line}")
    else:
        print("[OK] Пустых папок нет")

    print()
    import ast as _ast
    checks_run = sum(
        1 for n in _ast.walk(_ast.parse(Path(__file__).read_text(encoding="utf-8")))
        if isinstance(n, _ast.FunctionDef) and n.name.startswith("check_"))

    if failures or (args.strict and warnings):
        print(f"ИТОГ: DRIFT (fail: {len(failures)}, warn: {len(warnings)})")
        print_coverage(checks_run)
        return 1
    if warnings:
        print(f"ИТОГ: CLEAN с предупреждениями (warn: {len(warnings)})")
        print_coverage(checks_run)
        return 0
    # 🔴 «CLEAN» БЕЗ ПОКРЫТИЯ НЕ ПЕЧАТАЕТСЯ НИКОГДА — см. UNCOVERED выше.
    print("ИТОГ: ни одна из проверок не сработала")
    print_coverage(checks_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
