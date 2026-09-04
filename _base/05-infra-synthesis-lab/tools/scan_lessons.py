#!/usr/bin/env python3
"""Режим А для синтеза: открыть КАЖДЫЙ файл и судить по содержимому, не по имени.

Имя файла ничего не гарантирует: LESSONS.md может быть пустым шаблоном, а notes-01.md —
нести разбор на 400 строк. Поэтому читается текст, а решение принимается по признакам
внутри него.

Семейства признаков (каждое считается ОДИН раз, чтобы длинный файл не выигрывал объёмом):
  STRUCT  — структура разбора: Симптом / Причина / Корень / Правило / Как правильно
  POSTMOR — пост-мортем: Root cause / 5 Whys / Impact / Timeline / Lessons learned
  REGISTRY— нумерованный реестр уроков: PIT-, L-0, У-0, SYN-, INV-, INC-, BUG-
  RETRO   — ретроспектива: что сработало / что пошло не так / чему научились
  RULE    — нормативка: протокол, стандарт, запрещено, обязательно, никогда не
  META    — рефлексия о работе: ошибся, переделка, не повторять, потеряли время
"""
from __future__ import annotations

import csv
import hashlib
import re
import sys
import os
from pathlib import Path

# Путь к базе — через окружение, иначе от места скрипта (`ROADMAP.md` §P0 п. 6).
# Скрипт лежит в `05-infra-synthesis-lab/tools/`, то есть на два уровня ниже корня.
BASE = Path(os.environ.get("BASE_REPO") or Path(__file__).resolve().parents[2]).expanduser()
ROOT = BASE.parent
# 🔴 ПЕРЕПИСЬ ЛОЖИТСЯ РЯДОМ С ИНСТРУМЕНТОМ, А НЕ ТУДА, ГДЕ ТЫ СТОИШЬ.
# Замер 04.09.2026: умолчание было `Path("scan.csv")` — относительно ТЕКУЩЕГО
# каталога. Запуск из корня репы (`python3 05-infra-synthesis-lab/tools/
# scan_lessons.py`) написал `base-repo/scan.csv`, а настоящая перепись
# осталась нетронутой. Скрипт при этом бодро сказал «записано: scan.csv».
#
# Отказ тихий и обманчивый: команда успешна, файл создан, данные новые —
# просто не там, где их читают. Это `PIT-G` (артефакт кладут туда, где
# удобно оказаться, а не туда, где ему место по канону).
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "scan.csv"

SKIP_DIR_PARTS = {".git", "node_modules", "__pycache__", ".venv", "venv", "__MACOSX"}

# НИКАКОГО БЕЛОГО СПИСКА КАТАЛОГОВ. Решение владельца 20.08.2026 + два инцидента подряд.
#
# Дважды список путей писался по памяти и дважды выбрасывал именно то, ради чего репа
# читается: `enumerate_candidates.py` — 545 файлов справочника в «читать» и половину метода
# exam-kit в «содержание»; первая редакция этого сканера — 3437 файлов, включая
# `personal-finance-dss/knowledge/guides` (29 методичек) и `character-a-analysis/10-life-history/
# 09-history` (38, там `metodika-analiza.md`).
#
# Поэтому фильтра по путям НЕТ. Читается КАЖДЫЙ файл, решение — по содержимому.
# Личное содержание (дневники, профили, молитвы, клиника) не исключается молча: оно
# получает низкий балл по признакам метода и остаётся видимым в описи, чтобы решение
# принимал человек, а не невидимая эвристика.

# Носители метода бывают не только в .md — скрипт с шапкой-инструкцией это тоже методичка.
SCAN_SUFFIXES = {".md", ".py", ".sh", ".yml", ".yaml", ".toml"}
# Плоские копии базы внутри реп — это база, а не материал репы.
SKIP_PATH_RE = re.compile(r"(^|/)(_base|base-repo)(/|$)")

FAMILIES = {
    "STRUCT": [
        r"\*\*Симптом", r"\*\*Причина", r"\*\*Корень", r"\*\*Правило", r"\*\*Урок",
        r"^Симптом[:.]", r"^Корень[:.]", r"Как правильно", r"\*\*Как правильно",
    ],
    "POSTMOR": [
        r"Root cause", r"5 Whys", r"Lessons learned", r"Post-?mortem", r"постмортем",
        r"пост-мортем", r"^## Impact", r"^## Timeline", r"^## Detection", r"^## Resolution",
    ],
    "REGISTRY": [
        r"\bPIT-\d", r"\bL-\d{3}", r"\bУ-\d", r"\bSYN-\d", r"\bINV-[A-ZА-Я]", r"\bINC-[A-ZА-Я]",
        r"\bBUG-\d", r"\bADR-\d",
    ],
    "RETRO": [
        r"[Чч]то сработало", r"[Чч]то пошло не так", r"[Чч]ему научил", r"[Рр]етроспектив",
        r"[Чч]то не сработало", r"[Гг]де ошибал", r"[Чч]то помогало", r"[Оо]шибки и уроки",
    ],
    "RULE": [
        r"[Пп]ротокол", r"[Сс]тандарт", r"[Зз]апрещ", r"[Оо]бязательн", r"[Нн]икогда не",
        r"[Чч]ек-лист", r"[Жж]елезное правило", r"[Пп]равила ",
    ],
    "META": [
        r"[Нн]е повтор", r"[Пп]еределк", r"[Пп]отеря(?:но|ли) время", r"[Мм]ой косяк",
        r"[Гг]рабл", r"[Нн]аступ(?:ать|или) на", r"[Вв]скрылось", r"[Иі]ллюзия готовности",
    ],
}
COMPILED = {k: [re.compile(p, re.M) for p in v] for k, v in FAMILIES.items()}


# 🔴 ПОЧТИ-КОПИЯ ДЛЯ sha256 — ЧУЖОЙ ФАЙЛ. Замер 04.09.2026:
# `personal-finance-dss/docs/documentation_methodology.md` (score 651, третий
# в переписи) оказался ТЕМ ЖЕ документом, что `02-methodology-library/
# incident_process_documentation_methodology.md` в базе: 481 строка против
# 481, заголовки совпадают все до одного. После снятия эмодзи-маркеров
# важности (🔥⭐💼, база проставила их себе сама) различий осталось
# **2 строки из 351** — один путь в примере.
#
# Для sha256 это другой файл, поэтому `in_base` пуст, и кандидат три недели
# стоял в очереди как неразобранный. Разбирать было нечего.
#
# 🔴 ПОЧЕМУ НЕ НОРМАЛИЗОВАННЫЙ ХЭШ. Пробовал первым — не сработало ровно
# на этом случае: две строки расхождения дают другой хэш, а «почти» хэшем
# не выражается. Порог похожести по всему тексту стоил бы 652 × 3660
# сравнений. Подпись по ЗАГОЛОВКАМ дешевле и точнее: структура документа
# при переносе не меняется, а формулировки — меняются.
#
# ГРАНИЦА: подпись ловит перенесённую КОПИЮ, а не поднятый урок. Урок
# переписывают своими словами, и заголовки у него другие — для этого есть
# `reviewed` из `ROADMAP.md`. Один переименованный заголовок ломает подпись;
# такие случаи добивает `headings_overlap` попарно, по решению вахты.
HEAD_RE = re.compile(r"^#{2,3}\s+(.+)$", re.M)
_MARKERS = str.maketrans("", "", "🔥⭐💼🆕🔴🟢🟡✅🔲⛔️")
MIN_HEADS = 5      # ниже этого совпадение структуры ничего не значит


def head_signature(text: str) -> frozenset[str] | None:
    """Подпись документа — множество заголовков без маркеров важности."""
    heads = {" ".join(h.translate(_MARKERS).split())[:22]
             for h in HEAD_RE.findall(text)}
    return frozenset(heads) if len(heads) >= MIN_HEADS else None


def base_signatures() -> dict[frozenset[str], str]:
    """Подписи документов базы → путь. Первый выигрывает, их там не дублируют."""
    out: dict[frozenset[str], str] = {}
    for f in sorted(BASE.rglob("*.md")):
        # 🔴 ФОРМЫ ИСКЛЮЧЕНЫ, И ЭТО НЕ ПРИДИРКА. Первый прогон дал 48 находок,
        # из них **16** — заполненные `MANIFEST.md` разных реп, совпавшие
        # с `templates/MANIFEST_TEMPLATE.md`. Совпадение верное: заголовки
        # шаблона копируются дословно, содержание пишется под ними.
        #
        # Но вывод из него ложный: манифест `edu-base` — не копия шаблона,
        # а уникальный документ в его форме. Форма на то и форма, чтобы
        # совпадать; совпасть с ней — не признак дубля.
        #
        # Остальные 32 находки проверены поштучно и все настоящие: один
        # документ под разными именами в разных репах.
        if ".git" in f.parts or "_base" in f.parts or "templates" in f.parts:
            continue
        try:
            sig = head_signature(f.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if sig is not None:
            out.setdefault(sig, f.relative_to(BASE).as_posix())
    return out


def base_hashes() -> set[str]:
    """Хэши всего, что уже лежит в живой базе — чтобы не предлагать своё же.

    🔴 ГРАНИЦА, НАЗВАННАЯ ВСЛУХ (замер 04.09.2026). Сравнение идёт по sha256,
    то есть `in_base=yes` означает **побайтовую копию**, а не «урок отсюда
    уже поднят».

    Разобранный кандидат, чей урок **переписан своими словами** — а именно так
    и работает подъём в базу (`PROCEDURE.md`), — навсегда останется
    `in_base=""`. Все три разобранных к 04.09 кандидата (`LESSONS.md`,
    `inc_null_deadline`, `e2e_incident_postmortem`) в переписи числятся
    неразобранными.

    Значит колонка отвечает на вопрос «не предлагаю ли я базе её же файл»,
    и **не отвечает** на «не разобран ли этот файл». Второе ведётся вручную
    в `ROADMAP.md` — по полному пути, а не по имени: `CHANGELOG.md` есть
    у всех 66 реп, и сверка по имени даёт девять ложных «уже разобрано».
    """
    out = set()
    for p in BASE.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            try:
                out.add(hashlib.sha256(p.read_bytes()).hexdigest())
            except OSError:
                pass
    return out


def reviewed_paths() -> set[str]:
    """Пути, РАЗОБРАННЫЕ вахтой — из `ROADMAP.md`, а не из хешей.

    🔴 Отвечает на вопрос, на который `in_base` ответить не может: урок
    подняли, переписав своими словами, и побайтового совпадения нет.
    Единственное место, где факт разбора записан, — очередь задач.

    Сверка по ПОЛНОМУ пути. По имени файла нельзя: `CHANGELOG.md` есть
    у всех 66 реп, и такая сверка даёт девять ложных «уже разобрано»
    (замер 04.09.2026).
    """
    rm = BASE / "ROADMAP.md"
    if not rm.is_file():
        return set()
    return {rm.read_text(encoding="utf-8", errors="replace")}


def headings_overlap(src: Path, base_doc: Path) -> tuple[int, int, int]:
    """(разделов у источника, у документа базы, уникальных у источника).

    🔴 ПОВОД, 04.09.2026. Дважды за час решение «поднимать или дубль»
    принималось вручную, и оба раза дорого: первый — чтением 180 строк,
    второй — построчной сверкой заголовков скриптом на месте.

    Вывод «дубль» НА ГЛАЗ — тот же класс, что «уже разобрано» по имени файла
    (9 ложных срабатываний в тот же день). Выглядит проверкой и ею не является.

    Сравниваются заголовки `##`/`###` по первым 22 символам: полное совпадение
    строк не годится — при подъёме формулировку правят, и это нормально.

    🔴 ГРАНИЦА: совпадение заголовков не означает совпадения содержания.
    Инструмент отвечает «стоит ли читать», а не «дубль ли это» — решение
    остаётся за вахтой.
    """
    def heads(f: Path) -> list[str]:
        try:
            return [h.strip() for h in re.findall(
                r"^#{2,3}\s+(.+)$", f.read_text(encoding="utf-8", errors="replace"), re.M)]
        except OSError:
            return []
    s, b = heads(src), heads(base_doc)
    uniq = [h for h in s if not any(h[:22] in x for x in b)]
    return len(s), len(b), len(uniq)


def scan() -> list[dict]:
    known = base_hashes()
    base_sigs = base_signatures()
    _roadmap = reviewed_paths()
    roadmap_text = next(iter(_roadmap), "")
    print(f"файлов в живой базе: {len(known)}", file=sys.stderr)
    rows = []
    seen = 0
    for path in ROOT.rglob("*"):
        if path.suffix.lower() not in SCAN_SUFFIXES:
            continue
        if not path.is_file():
            continue
        if SKIP_DIR_PARTS & set(path.parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if SKIP_PATH_RE.search(rel):
            continue
        seen += 1
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8", errors="replace")
        except OSError:
            continue
        digest = hashlib.sha256(raw).hexdigest()
        hits = {}
        for fam, pats in COMPILED.items():
            n = sum(len(p.findall(text)) for p in pats)
            if n:
                hits[fam] = n
        if not hits:
            continue
        rows.append({
            "repo": rel.split("/")[0],
            "path": rel,
            "lines": text.count("\n") + 1,
            "bytes": len(raw),
            "families": len(hits),
            "score": len(hits) * 100 + min(sum(hits.values()), 99),
            "fam_detail": ";".join(f"{k}={v}" for k, v in sorted(hits.items())),
            "in_base": "yes" if digest in known else "",
            # 🔴 Побайтово другой, по содержанию тот же — см. `normalize`.
            # Такому кандидату разбор не нужен: он УЖЕ в базе, просто под
            # другим именем и с проставленными маркерами.
            "near_base": ("" if digest in known
                          else base_sigs.get(head_signature(text) or frozenset(), "")),
            "sha": digest[:12],
            # 🔴 РАЗОБРАН ≠ СКОПИРОВАН. `in_base` ловит побайтовую копию,
            # `reviewed` — факт разбора, записанный вахтой в `ROADMAP.md`.
            # Все три разобранных к 04.09 кандидата имеют `in_base=""`:
            # их уроки переписаны своими словами, как и требует `PROCEDURE`.
            "reviewed": "yes" if rel in roadmap_text else "",
        })
    print(f"просмотрено файлов: {seen}; с признаками метода: {len(rows)}", file=sys.stderr)
    return rows


# 🔴 СЧЁТЧИК ДВИЖЕНИЯ ОЧЕРЕДИ (`PIT-195`). Перепись отвечает «что читать»
# и отвечала верно ВОСЕМЬ ДНЕЙ, пока очередь стояла: 27.08 разобран первый
# кандидат, дальше ноль до 04.09. Простой был невидим — ни одна проверка
# не считала, сколько кандидатов разобрано за период.
#
# Журнал append-only, по строке на прогон. `.tsv` не входит в `SCAN_SUFFIXES`,
# поэтому счётчик НЕ попадает в то, что сам измеряет (`/auto` §2г п.2).
PROGRESS = Path(__file__).resolve().parent / "census-progress.tsv"

# 🔴 ЧТО НЕ СЧИТАЕТСЯ ОЧЕРЕДЬЮ. Первая редакция счётчика напечатала «37»,
# пока вахта докладывала владельцу «8» — два числа об одном факте, и ни одно
# не сверялось с другим (`21` §4е-бис п.3, поднято этим же днём).
#
# Расходились не подсчёты, а определение: вахта отсеивала журналы и сырые
# выгрузки глазами, инструмент — нет. Отсев перенесён СЮДА, чтобы число
# было одно.
#
# Признак по свойству, а не список файлов: журнал СОБЫТИЙ (`94` §1) и сырая
# выгрузка — это материал, а не метод. Ключевые слова метода в них есть
# всегда, потому что они пересказывают работу, — и потому они всегда наверху
# ранга и всегда бесполезны для подъёма.
NOISE_RE = re.compile(
    r"(^|/)(CHANGELOG|WATCHLOG|ROADMAP|TASKS|decisions|auto\.log)"
    r"|(^|/)(telegram|10-life-history|06-communication)(/|-)", re.I)


def log_progress(rows: list[dict]) -> None:
    """Дописать строку: дата · разобрано · очередь ≥400 · всего."""
    import datetime
    reviewed = sum(1 for r in rows if r["reviewed"])
    queue = sum(1 for r in rows
                if not r["in_base"] and not r["near_base"] and not r["reviewed"]
                and r["score"] >= 400 and not NOISE_RE.search(r["path"]))
    line = "\t".join((datetime.date.today().isoformat(),
                       str(reviewed), str(queue), str(len(rows))))
    head = "" if PROGRESS.exists() else "дата\tразобрано\tочередь_400\tвсего\n"
    with PROGRESS.open("a", encoding="utf-8") as fh:
        fh.write(head + line + "\n")
    prev = [l.split("\t") for l in PROGRESS.read_text(encoding="utf-8").splitlines()[1:-1]]
    if prev:
        was = int(prev[-1][1])
        delta = reviewed - was
        mark = "🟢" if delta > 0 else "🔴"
        print(f"{mark} разобрано: {reviewed} (было {was}, {delta:+d}) · "
              f"очередь ≥400: {queue}", file=sys.stderr)
    else:
        print(f"разобрано: {reviewed} · очередь ≥400: {queue}", file=sys.stderr)


def main() -> int:
    rows = sorted(scan(), key=lambda r: -r["score"])
    log_progress(rows)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"записано: {OUT}")
    return 0


# 🔴 ТЕЛО ПОД ГВАРДОМ, А НЕ НА ВЕРХНЕМ УРОВНЕ. Замер 04.09.2026: попытка
# импортировать модуль ради ОДНОЙ функции (`headings_overlap`) запустила
# полный обход **11 935 файлов** и перезаписала `scan.csv` — то есть чтение
# кода изменило состояние.
#
# Побочный эффект при импорте — это ещё и ловушка для любого будущего
# инструмента, который захочет переиспользовать отсюда функцию: он получит
# не библиотеку, а запуск.
if __name__ == "__main__":
    raise SystemExit(main())
