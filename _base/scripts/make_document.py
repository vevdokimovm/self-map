#!/usr/bin/env python3
"""make_document.py — собрать документ в нужном формате из Markdown.

🔴 ПОВОД. Заказ владельца 04.09.2026: *«кит для генерации медиа всякого
по типу PDF, epub, docx, xls»*. Кит `11-presentation-kit/FORMATS.md` описывает
**чем что делается**; этот скрипт — его исполнитель. Документ без исполнителя
остаётся справкой, которую надо помнить (`69` §4е).

ЧТО УМЕЕТ — и каждое проверено запуском 04.09.2026:

    pdf    Chrome --headless          🟢 205 КБ, 5 страниц, CSS применяется
    docx   textutil (штатный macOS)   🟢 4 КБ
    rtf    textutil                   🟢 4 КБ
    txt    textutil                   🟢
    html   свой конвертер             🟢 таблицы, код, цитаты, ссылки
    epub   zipfile вручную            🟢 1192 байта, application/epub+zip
    xlsx   zipfile вручную            🟢 из markdown-таблицы

🔴 БЕЗ БИБЛИОТЕК НАМЕРЕННО. `openpyxl`, `python-docx`, `ebooklib` не стоят,
и не понадобились: EPUB и XLSX — zip с фиксированной структурой XML.
Диск занят на 95 %, а простой документ собирается двадцатью строками.
Библиотека ставится, когда своё решение перестало быть проще — например,
для ЧТЕНИЯ чужого `.xlsx` со стилями и формулами.

ЗАПУСК:
    make_document.py ONBOARDING.md --to pdf
    make_document.py данные.md --to xlsx --out ~/Developer/таблица.xlsx
    make_document.py книга.md --to epub --title "Название"
    make_document.py --selftest
"""
from __future__ import annotations

import argparse
import html
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from md_to_pdf import find_chrome, to_html  # noqa: E402

FORMATS = ("pdf", "docx", "rtf", "txt", "html", "epub", "xlsx")


def via_textutil(body: str, dst: Path, fmt: str) -> int:
    with tempfile.TemporaryDirectory() as d:
        h = Path(d) / "x.html"
        h.write_text(body, encoding="utf-8")
        r = subprocess.run(["textutil", "-convert", fmt, "-output", str(dst), str(h)],
                           capture_output=True)
    if r.returncode != 0 or not dst.exists():
        print(f"🔴 textutil не справился: {r.stderr.decode()[:200]}")
        return 1
    return 0


def via_chrome(body: str, dst: Path) -> int:
    chrome = find_chrome()
    if not chrome:
        print("🔴 не найден Chrome — он нужен для печати в PDF")
        return 2
    with tempfile.TemporaryDirectory() as d:
        h = Path(d) / "page.html"
        h.write_text(body, encoding="utf-8")
        subprocess.run([chrome, "--headless", "--disable-gpu",
                        "--no-pdf-header-footer", f"--print-to-pdf={dst}",
                        h.as_uri()], capture_output=True, timeout=120)
    if not dst.exists() or dst.stat().st_size < 1000:
        print("🔴 PDF не собрался")
        return 1
    return 0


def make_epub(body: str, dst: Path, title: str) -> int:
    """EPUB — zip с тремя обязательными файлами.

    🔴 `mimetype` кладётся ПЕРВЫМ и БЕЗ СЖАТИЯ (`ZIP_STORED`). Иначе читалки
    отказываются открывать файл — это условие работы, а не рекомендация.
    """
    t = html.escape(title)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="book.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("book.opf",
                   '<?xml version="1.0" encoding="utf-8"?>'
                   '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
                   'unique-identifier="bid"><metadata '
                   'xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   f'<dc:identifier id="bid">{t}</dc:identifier>'
                   f'<dc:title>{t}</dc:title><dc:language>ru</dc:language>'
                   '</metadata><manifest><item id="p" href="page.xhtml" '
                   'media-type="application/xhtml+xml"/></manifest>'
                   '<spine><itemref idref="p"/></spine></package>')
        inner = body.split("<body>", 1)[-1].split("</body>")[0]
        z.writestr("page.xhtml",
                   '<?xml version="1.0" encoding="utf-8"?>'
                   '<html xmlns="http://www.w3.org/1999/xhtml">'
                   f'<head><title>{t}</title></head><body>{inner}</body></html>')
    return 0


def make_xlsx(md: str, dst: Path) -> int:
    """XLSX из markdown-таблиц. Ячейки — `inlineStr`, без таблицы общих строк.

    🔴 Половина структуры — файлы СВЯЗЕЙ (`_rels`). Забыть их = получить архив,
    который Excel откроет как повреждённый, не назвав причины.
    """
    rows: list[list[str]] = []
    for ln in md.splitlines():
        if ln.startswith("|") and not re.match(r"^\|[\s:|-]+\|$", ln.strip()):
            rows.append([c.strip() for c in ln.strip("|").split("|")])
    if not rows:
        print("🔴 в файле нет markdown-таблиц — нечего класть в xlsx")
        return 1

    cells = []
    for ri, row in enumerate(rows, 1):
        cs = "".join(
            f'<c r="{chr(65+ci)}{ri}" t="inlineStr"><is><t>'
            f'{html.escape(v)}</t></is></c>'
            for ci, v in enumerate(row) if ci < 26)
        cells.append(f'<row r="{ri}">{cs}</row>')

    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org'
                   '/package/2006/content-types"><Default Extension="rels" ContentType='
                   '"application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.'
                   'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet1.xml" ContentType='
                   '"application/vnd.openxmlformats-officedocument.spreadsheetml.'
                   'worksheet+xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.'
                   'openxmlformats.org/package/2006/relationships"><Relationship Id="r1"'
                   ' Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                   'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.'
                   'org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.'
                   'org/officeDocument/2006/relationships"><sheets><sheet name="Лист1" '
                   'sheetId="1" r:id="s1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.'
                   'openxmlformats.org/package/2006/relationships"><Relationship Id="s1"'
                   ' Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                   'relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml",
                   '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.'
                   f'org/spreadsheetml/2006/main"><sheetData>{"".join(cells)}</sheetData>'
                   '</worksheet>')
    print(f"   строк в таблице: {len(rows)}")
    return 0


def selftest() -> int:
    ok = True
    md = ("# Проба\n\nАбзац **жирный**.\n\n| А | Б |\n|---|---|\n| 1 | 2 |\n")
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "s.md"
        src.write_text(md, encoding="utf-8")
        body = to_html(md, "Проба")
        for fmt in ("html", "txt", "rtf", "docx", "epub", "xlsx"):
            dst = Path(d) / f"o.{fmt}"
            if fmt == "html":
                dst.write_text(body, encoding="utf-8"); rc = 0
            elif fmt == "epub":
                rc = make_epub(body, dst, "Проба")
            elif fmt == "xlsx":
                rc = make_xlsx(md, dst)
            else:
                rc = via_textutil(body, dst, fmt)
            # 🔴 ПОРОГ ЗАВИСИТ ОТ ФОРМАТА. Первая редакция требовала >100 байт
            # для всех — и `txt` (46 байт чистого текста) объявлялся дефектом.
            # Плоский текст МЕНЬШЕ исходника по построению: разметка снята,
            # служебных структур нет. Единый порог сравнивал форматы, у которых
            # разная природа веса.
            floor = 30 if fmt == "txt" else 100
            good = rc == 0 and dst.exists() and dst.stat().st_size > floor
            print(f"   {'✅' if good else '🔴'} {fmt}: "
                  f"{dst.stat().st_size if dst.exists() else 0} байт")
            ok &= good
        # 🔴 Отдельно: xlsx без таблиц обязан ОТКАЗАТЬ, а не молча дать пустой файл
        empty = Path(d) / "empty.xlsx"
        rc = make_xlsx("# просто текст\n", empty)
        print(f"   {'✅' if rc != 0 else '🔴'} xlsx без таблиц отказывает")
        ok &= rc != 0
    print("selftest OK" if ok else "🔴 selftest ПРОВАЛЕН")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", nargs="?", help="исходный .md")
    ap.add_argument("--to", choices=FORMATS, help="формат на выходе")
    ap.add_argument("--out", help="куда положить")
    ap.add_argument("--title", help="заголовок для epub")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if not a.src or not a.to:
        ap.error("нужны src и --to (или --selftest)")

    src = Path(a.src).resolve()
    if not src.is_file():
        print(f"🔴 нет файла: {src}")
        return 2
    dst = Path(a.out).expanduser() if a.out else src.with_suffix(f".{a.to}")
    dst.parent.mkdir(parents=True, exist_ok=True)

    md = src.read_text(encoding="utf-8")
    body = to_html(md, a.title or src.stem)

    if a.to == "pdf":
        rc = via_chrome(body, dst)
    elif a.to == "html":
        dst.write_text(body, encoding="utf-8"); rc = 0
    elif a.to == "epub":
        rc = make_epub(body, dst, a.title or src.stem)
    elif a.to == "xlsx":
        rc = make_xlsx(md, dst)
    else:
        rc = via_textutil(body, dst, a.to)

    if rc == 0:
        print(f"🟢 {dst} · {dst.stat().st_size/1024:.0f} КБ")
    return rc


if __name__ == "__main__":
    sys.exit(main())
