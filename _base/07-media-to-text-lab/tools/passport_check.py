#!/usr/bin/env python3
"""passport_check.py — проверяет, что заметки о первоисточниках несут ПАСПОРТ КАЧЕСТВА.

🔴 ПОВОД. 05.09.2026 три заметки в `health-vault` написаны без паспорта.
Не по небрежности: `METHOD_IMAGES.md` §4 требовал три слоя (0a/0b/0c),
а канон `00-infrastructure/65-visual-source-pipeline.md` §6.1а — ещё и паспорт
как условие закрытия. Два документа базы расходились, и заметка, полная
по одному, была неполна по другому. Расхождение не ловилось ничем.

ЧТО ДЕЛАЕТ. Механическая проверка присутствия пяти полей паспорта.
🔴 НЕ судит о качестве разбора и не проверяет честность оценки — отличить
добросовестные 74/100 от нарисованных 95/100 может только чтение.
Инструмент отвечает на один вопрос: «паспорт вообще есть?»

ЧТО СЧИТАЕТСЯ ЗАМЕТКОЙ О ПЕРВОИСТОЧНИКЕ
    · `raspoznavanie.md` — разбор серии изображений;
    · `<имя>.pdf.md` / `<имя>.jpeg.md` и т.п. — парная заметка к файлу,
      у которого нет текстового слоя.
Обычные документы репы не проверяются: паспорт нужен там, где текст
получен ГЛАЗАМИ из пикселей, а не скопирован.

ЗАГЛУШКИ. Заметка, честно сообщающая «текстового слоя нет, содержание
не извлечено», паспорта не требует: она не утверждает, что источник прочитан.
Такие считаются отдельно — это очередь на работу, а не брак.

ЗАПУСК
    passport_check.py                    по всей системе
    passport_check.py --repo health-vault
    passport_check.py --repo health-vault -v    с перечнем полей, которых нет
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BASE_REPO = Path(__file__).resolve().parent.parent.parent
REPOS = BASE_REPO.parent
SKIP_PARTS = {"_base", ".git", "node_modules", ".venv", "__pycache__", "dist"}

MEDIA_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".webp", ".tiff", ".gif"}

# 🔴 Поля признаются ПО СМЫСЛУ, а не по буквальному имени.
#
# Живые паспорта `character-a-analysis` (47 сессий) называют их свободно:
# «Формат», «Формат заметок», «Уникальный контент» вместо «Что взято»;
# покрытие часто вписано прямо в строку режима — «A — 8+8=16/16 страниц
# открыто глазами». Это не брак: паспорт своё дело делает, читателю всё ясно.
#
# Требовать буквальных имён значило бы объявить дефектными 40 работающих
# документов и переписать их ради формы. Поэтому канон (`65` §6.1а) называет
# канонические имена для НОВЫХ заметок, а проверка принимает и исторические.
FIELDS = {
    "режим": re.compile(r"^\s*\|?\s*\**(режим|mode)\b", re.I | re.M),
    "покрытие": re.compile(
        r"^\s*\|?\s*\**(покрыти|прочитан|охват|обработан)"      # своей строкой
        r"|\d+\s*(?:\+\s*\d+\s*=\s*\d+)?\s*/\s*\d+\s*"   # или дробью X/Y
        r"(?:стр|страниц|файл|кадр|запис|строк|шт)",
        re.I | re.M),
    "что взято": re.compile(
        r"^\s*\|?\s*\**(что взято|что снято|глубина|формат|"
        r"уникальный контент|содержани|захвачено)", re.I | re.M),
    "ограничения": re.compile(r"^\s*\|?\s*\**(ограничени|трудност)", re.I | re.M),
    "оценка": re.compile(r"\b\d{1,3}\s*/\s*100\b"),
}

STUB = re.compile(r"текста нет|текстовый слой пуст|содержание не извлечено", re.I)

# 🔴 Машинное извлечение — НЕ чтение зрением, и паспорт режима A к нему неприменим:
# там нет ни режима, ни пикселей, ни риска додумать. Признак — строка «извлечено
# знаков: N» при N > 0. Поймано 05.09.2026: первая редакция инструмента объявила
# 63 такие заметки дефектными, то есть выдала 63 ложных срабатывания из 63.
MACHINE = re.compile(r"извлечено\s+знаков\s*\|?\s*(\d+)", re.I)

# Порог «это ещё заглушка, а не разбор». Заглушки, которые писал прежний заход,
# укладываются в ~900 знаков; самый короткий настоящий разбор в системе — вчетверо
# длиннее. 2500 выбрано с запасом в обе стороны.
STUB_MAX_BYTES = 2500


# 🔴 Что считается заметкой о первоисточнике — три признака, все проверяемые.
#
# История двух неверных редакций, обе поймано 05.09.2026:
#   1) только имена файлов → не увидел 29 паспортов в `character-a-analysis`,
#      где заметки названы по источнику (`notion-diary-photos.md`, `vkgraph.md`).
#      Отчёт вышел бы наоборот: эталон пуст, система — сплошной брак;
#   2) «упоминает режим A» → поймал методички и `00-infrastructure/README.md`,
#      то есть документы ПРО метод, а не заметки ПО методу. 495 срабатываний.
#
# 🔴 ЧЕСТНАЯ ГРАНИЦА: механически отличить «заметку об источнике» от «текста,
# рассказывающего о заметках», по содержанию нельзя. Поэтому признаки — только
# структурные: имя файла, каталог по конвенции, уже проставленный паспорт.
# Заметка, названная произвольно и лежащая вне `02-notes/`, инструментом
# НЕ НАЙДЁТСЯ. Это пропуск, а не ложная тревога, и он предпочтён обратному.
# Каталоги, где по конвенции лежат ЗАМЕТКИ ОБ ИСТОЧНИКАХ.
# 🔴 `01-registry`, `00-protocol`, `09-history` исключены намеренно: там реестры,
# правила и архив редакций. Они содержат оценки `/100` (ссылаются на закрытые
# источники) и потому выглядят как заметки, но паспорта не требуют — источник
# описывают не они. Поймано 05.09.2026: без этого 22 протокола и реестра
# попали в дефекты, и правка пошла бы в документы, которым паспорт не нужен.
NOTES_DIRS = {"02-notes", "notes"}
# 🔴 `reports` целиком исключать НЕЛЬЗЯ: в `reports/imports/` лежат разобранные
# серии (telegram-photos и прочие импорты). Поймано сразу после введения списка —
# шесть настоящих дефектов исчезли из отчёта, и он показал ложное благополучие.
# Исключается только каталог готовых отчётов `03-reports`.
SKIP_DIRS = {"00-protocol", "01-registry", "09-history", "runs", "03-reports"}
HAS_PASSPORT = re.compile(r"ПАСПОРТ\s+КАЧЕСТВА", re.I)
SKIP_METHODICAL = re.compile(r"^(README|METHOD|LESSONS|PITFALLS|CHANGELOG|"
                             r"WATCHLOG|ROADMAP|TASKS)", re.I)


def is_source_note(path: Path, text: str) -> bool:
    """Заметка ли это о первоисточнике, прочитанном глазами.

    Args:
        path: путь к файлу.
        text: содержимое — нужно для признака «паспорт уже есть».

    Returns:
        True для парных заметок по имени, файлов в каталогах заметок
        и любого файла с проставленным паспортом.
    """
    if SKIP_METHODICAL.match(path.stem):
        return False
    if SKIP_DIRS & set(path.parts):
        return False
    if path.name == "raspoznavanie.md":
        return True
    if Path(path.stem).suffix.lower() in MEDIA_SUFFIXES:
        return True
    if HAS_PASSPORT.search(text):
        return True
    return bool(NOTES_DIRS & set(path.parts))


def missing_fields(text: str) -> list[str]:
    """Названия полей паспорта, которых в тексте нет."""
    return [name for name, pattern in FIELDS.items() if not pattern.search(text)]


def scan(root: Path) -> tuple[list[tuple[Path, list[str]]], list[Path], int, int]:
    """Обойти репу: вернуть (дефектные, заглушки, полных, машинных извлечений)."""
    broken: list[tuple[Path, list[str]]] = []
    stubs: list[Path] = []
    ok = 0
    machine = 0
    for path in sorted(root.rglob("*.md")):
        if SKIP_PARTS & set(path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not is_source_note(path, text):
            continue
        extracted = MACHINE.search(text)
        if extracted:
            if int(extracted.group(1)) > 0:
                machine += 1
            else:
                stubs.append(path)
            continue
        # 🔴 Фраза-маркер заглушки засчитывается ТОЛЬКО в коротком файле.
        # Поймано 05.09.2026 на второй правке: разобранная заметка процитировала
        # «прежняя заметка была заглушкой: текстовый слой пуст» — и выпала
        # из проверки целиком. Цитата не должна прятать документ от гейта,
        # поэтому решает не наличие слов, а объём: заглушки в системе ≈900 байт,
        # разбор режима A — тысячи.
        if STUB.search(text) and len(text) < STUB_MAX_BYTES:
            stubs.append(path)
            continue
        gaps = missing_fields(text)
        if gaps:
            broken.append((path, gaps))
        else:
            ok += 1
    return broken, stubs, ok, machine


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", help="имя одной репы; без него — вся система")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="перечислить недостающие поля по каждой заметке")
    args = ap.parse_args()

    roots = [REPOS / args.repo] if args.repo else [
        p for p in sorted(REPOS.iterdir())
        if p.is_dir() and not p.name.startswith(".")
    ]

    total_broken = 0
    total_stubs = 0
    total_ok = 0
    total_machine = 0
    for root in roots:
        if not root.is_dir():
            print(f"нет такой репы: {root}", file=sys.stderr)
            return 2
        broken, stubs, ok, machine = scan(root)
        total_broken += len(broken)
        total_stubs += len(stubs)
        total_ok += ok
        total_machine += machine
        if broken:
            print(f"\n🔴 {root.name}: без паспорта — {len(broken)}")
            for path, gaps in broken:
                rel = path.relative_to(root)
                print(f"   · {rel}")
                if args.verbose:
                    print(f"       не хватает: {', '.join(gaps)}")
        if stubs and args.verbose:
            print(f"\n🟡 {root.name}: заглушек (очередь на разбор) — {len(stubs)}")
            for path in stubs:
                print(f"   · {path.relative_to(root)}")

    print(f"\n  с паспортом: {total_ok} · без паспорта: {total_broken} · "
          f"заглушек: {total_stubs} · машинных извлечений: {total_machine}")
    print("  Машинное извлечение текстового слоя паспорта не требует: "
          "там нет чтения зрением.")
    print("  🔴 Проверка механическая: наличие полей, НЕ качество разбора "
          "и НЕ честность оценки.")
    print("  Канон — 00-infrastructure/65-visual-source-pipeline.md §6.1а, "
          "точка применения — 07-media-to-text-lab/METHOD_IMAGES.md §0г.")
    return 1 if total_broken else 0


if __name__ == "__main__":
    sys.exit(main())
