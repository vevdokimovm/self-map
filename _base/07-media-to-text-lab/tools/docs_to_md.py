#!/usr/bin/env python3
"""docs_to_md.py — перевод документов в текст: PDF, DOCX, PPTX, RTF → `.md`.

🔴 ПОВОД — `PIT-138`, найденный владельцем 23.08.2026:

    «ты же не сделал тяжёлую работу — ревизию. Такое ощущение, как будто ты даже
    не начинал её. Файлы не переведены из медиа в служебные заметки»

Замер подтвердил: в репах **5 236** медиа-файлов, из них `.md`-выжимку имеют **23**
(0.4 %). Ревизия свелась к механике — раскладке, дедупу, путям, — потому что механика
отчитывается числами и создаёт ощущение движения.

> **Признак подмены: все закрытые пункты измеряются числом файлов, ни один — числом
> прочитанных документов.**

ЧТО ДЕЛАЕТ. Извлекает **текстовый слой** и кладёт рядом `<имя>.<ext>.md` — паспорт
плюс содержимое. Оригинал **не трогается**: правило владельца «эталон остаётся, рядом
появляется выжимка» (`_base/00-infrastructure/87-file-to-repo-routing.md` §3).

ЧЕМ. Системными инструментами macOS, без сторонних библиотек:

| Формат | Инструмент | Что берёт |
|---|---|---|
| `.pdf` | `pdftotext -layout` | текстовый слой; у сканов его нет — см. границу |
| `.docx`, `.doc`, `.rtf`, `.odt` | `textutil -convert txt` | текст документа |
| `.pptx` | распаковка XML + разбор `a:t` | текст слайдов |
| `.xlsx` | распаковка XML + `sharedStrings` | текст ячеек |

🔴 ГРАНИЦА, НАЗВАННАЯ ВСЛУХ (`71` §7г-бис). Скрипт извлекает **текст, который в файле
уже есть**. Он НЕ распознаёт:

- сканы без текстового слоя — им нужен OCR, и служебка честно пишет «текста нет,
  вероятно скан»;
- изображения и диаграммы — их содержание не в тексте;
- смысл — выжимка это извлечение, а не пересказ. Пересказ делает вахта, читая.

Поэтому результат называется **выжимкой**, а не конспектом: она даёт возможность
искать и понимать, о чём файл, но не заменяет чтение.

ЗАПУСК
    docs_to_md.py --repo health-vault            что будет сделано
    docs_to_md.py --repo health-vault --apply    сделать
    docs_to_md.py --all --apply --limit 500      по всем репам, не больше 500 файлов
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import zipfile
from pathlib import Path

BASE_REPO = Path(__file__).resolve().parent.parent.parent
REPOS = BASE_REPO.parent
SKIP_PARTS = {"_base", ".git", "node_modules", ".venv", "__pycache__", "90-imported"}

PDF = {".pdf"}
TEXTUTIL = {".docx", ".doc", ".rtf", ".odt", ".pages"}
PPTX = {".pptx"}
XLSX = {".xlsx"}
SUPPORTED = PDF | TEXTUTIL | PPTX | XLSX


def run(cmd: list[str], timeout: int = 60) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


def from_pdf(p: Path) -> tuple[str, int]:
    out = run(["pdftotext", "-layout", "-enc", "UTF-8", str(p), "-"], timeout=120)
    if out is None:
        return "", 0
    pages = out.count("\f") + 1
    return out, pages


def from_textutil(p: Path) -> tuple[str, int]:
    out = run(["textutil", "-convert", "txt", "-stdout", str(p)], timeout=90)
    return (out or ""), 0


def from_pptx(p: Path) -> tuple[str, int]:
    """Текст слайдов из XML: <a:t>…</a:t> — то, что видно на слайде."""
    try:
        z = zipfile.ZipFile(p)
    except Exception:
        return "", 0
    slides = sorted(n for n in z.namelist()
                    if re.match(r"ppt/slides/slide\d+\.xml$", n))
    parts = []
    for i, name in enumerate(slides, 1):
        xml = z.read(name).decode("utf-8", "replace")
        texts = re.findall(r"<a:t>(.*?)</a:t>", xml, re.S)
        body = "\n".join(t.strip() for t in texts if t.strip())
        if body:
            parts.append(f"### Слайд {i}\n\n{body}")
    return "\n\n".join(parts), len(slides)


def from_xlsx(p: Path) -> tuple[str, int]:
    """Текстовые ячейки: sharedStrings даёт всё, что набрано словами."""
    try:
        z = zipfile.ZipFile(p)
        xml = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
    except Exception:
        return "", 0
    vals = [re.sub(r"<[^>]+>", "", t) for t in re.findall(r"<si>(.*?)</si>", xml, re.S)]
    sheets = sum(1 for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
    return "\n".join(v.strip() for v in vals if v.strip()), sheets


EXTRACT = [(PDF, from_pdf), (TEXTUTIL, from_textutil), (PPTX, from_pptx), (XLSX, from_xlsx)]


def note(p: Path, repo: Path, text: str, units: int) -> str:
    kind = {".pdf": "PDF", ".pptx": "презентация", ".xlsx": "таблица"}.get(
        p.suffix.lower(), "документ")
    mb = p.stat().st_size / 2**20
    chars = len(text.strip())
    unit_line = ""
    if units and p.suffix.lower() == ".pdf":
        unit_line = f"| страниц | {units} |\n"
    elif units and p.suffix.lower() == ".pptx":
        unit_line = f"| слайдов | {units} |\n"
    elif units:
        unit_line = f"| листов | {units} |\n"

    if chars < 40:
        body = f"""## Текста нет

🔴 **Текстовый слой пуст** — вероятно, это скан или файл из одних изображений.
Извлечение текста здесь бессильно: нужен OCR, а его в системе пока нет
(`_base/07-media-to-text-lab/README.md` §5 — «PDF → .md» числится нужным).

Оригинал на месте и остаётся эталоном. Эта заметка фиксирует состояние
«файл есть, содержание не извлечено», а не притворяется выжимкой."""
    else:
        body = f"""## Извлечённый текст

> Ниже — **текстовый слой файла**, а не пересказ. Извлечено машинно; смысл, структура
> и то, что было картинкой, здесь не появятся. Оригинал остаётся эталоном.

{text.strip()}"""

    return f"""# {p.stem} — выжимка

| | |
|---|---|
| оригинал | `{p.name}` (рядом, не тронут) |
| тип | {kind} |
| размер | {mb:.1f} МБ |
{unit_line}| извлечено знаков | {chars} |

{body}
"""


def process(repo: Path, apply: bool, limit: int, force_stubs: bool = False) -> tuple[int, int, int]:
    done = empty = skipped = 0
    for p in sorted(repo.rglob("*")):
        if done + empty >= limit:
            break
        if not p.is_file() or any(x in p.parts for x in SKIP_PARTS):
            continue
        if p.suffix.lower() not in SUPPORTED:
            continue
        out = p.with_suffix(p.suffix + ".md")
        if out.exists():
            skipped += 1
            continue
        try:
            # 🔴 PIT-145 (26.08.2026): st_blocks==0 при почти полном диске значит
            # «сейчас не резидентно», не «данных нет» — materialize-on-read работает
            # за миллисекунды, macOS просто тут же вытесняет обратно. --force-stubs
            # читает такие файлы всё равно (симметрично с pack_release.py).
            if p.stat().st_blocks == 0 and not force_stubs:
                skipped += 1
                continue
        except OSError:
            continue
        if not apply:
            done += 1
            continue
        text, units = "", 0
        for exts, fn in EXTRACT:
            if p.suffix.lower() in exts:
                text, units = fn(p)
                break
        out.write_text(note(p, repo, text, units), encoding="utf-8")
        if len(text.strip()) < 40:
            empty += 1
        else:
            done += 1
    return done, empty, skipped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=100000)
    ap.add_argument("--force-stubs", action="store_true",
                     help="читать файлы с st_blocks==0 всё равно (PIT-145)")
    a = ap.parse_args()

    targets = ([REPOS / a.repo] if a.repo
               else sorted(d for d in REPOS.iterdir() if d.is_dir()) if a.all else [])
    if not targets:
        ap.error("нужен --repo ИМЯ или --all")

    td = te = ts = 0
    for t in targets:
        if not t.is_dir():
            continue
        d, e, s = process(t, a.apply, a.limit - td - te, a.force_stubs)
        if d or e or s:
            print(f"  {t.name:<26} выжимок {d:>4} · без текста {e:>4} · пропущено {s:>4}")
        td += d
        te += e
        ts += s

    print(f"\n  выжимок сделано: {td} · текста не оказалось: {te} · пропущено: {ts}")
    if not a.apply:
        print("  (сухой прогон; --apply чтобы сделать)")
    else:
        print("  🔴 Выжимка — извлечённый текст, не пересказ. Смысл остаётся за вахтой.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
