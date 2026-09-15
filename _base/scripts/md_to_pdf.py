#!/usr/bin/env python3
"""md_to_pdf.py — Markdown → PDF без установки чего-либо.

🔴 ПОВОД. Владелец попросил онбординг **в PDF**: *«сделай pdf инструкции
онбординга»*. На машине нет ни `pandoc`, ни `wkhtmltopdf`, ни `weasyprint`,
а ставить их ради одного документа — лишняя зависимость в системе, где
владелец следит за диском (занято 95 %).

ЧЕМ ДЕЛАЕТСЯ:

    Markdown → HTML (свой конвертер) → Chrome --headless --print-to-pdf

🔴 ПУТЬ ВЫБРАН ЗАМЕРОМ, А НЕ ПО ПАМЯТИ. Проверены пять вариантов:

    cupsfilter из RTF        🔴 «No filter to convert from text/rtf»
    cupsfilter из HTML       🔴 то же самое для text/html
    PyObjC + WebKit          🔴 модуля `Quartz` нет ни в brew-, ни в системном python
    groff -T pdf             🔴 groff в системе отсутствует
    Chrome --headless        🟢 23 КБ PDF за секунду, CSS применяется полностью

Первая редакция этого файла была написана под `cupsfilter` **по рассуждению**
(«штатное средство macOS, значит есть») и упала на первом же запуске.
`PIT-184`: утверждение о своих возможностях требует того же основания,
что утверждение о состоянии диска, — команды, которая это показала.

🔴 ПОЧЕМУ СВОЙ КОНВЕРТЕР, А НЕ БИБЛИОТЕКА. Нужен не полный Markdown,
а тот, которым написаны документы системы: заголовки, таблицы, списки,
цитаты, код, **жирный**, `моно`. Полный CommonMark — это зависимость
ради процента возможностей, который здесь не используется.

ГРАНИЦА, НАЗВАННАЯ ВСЛУХ: вложенные списки глубже двух уровней, сноски
и HTML внутри Markdown не поддержаны. В документах системы их нет
(проверено), а поддерживать неиспользуемое — тот же лишний вес.

ЗАПУСК:
    python3 scripts/md_to_pdf.py ONBOARDING.md
    python3 scripts/md_to_pdf.py ONBOARDING.md --out ~/Developer/onboarding.pdf
"""
from __future__ import annotations

import argparse
import html
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CSS = """
@page { margin: 18mm 16mm; }
body { font: 11pt/1.55 -apple-system, "Helvetica Neue", sans-serif;
       color: #1a1a1a; max-width: 100%; }
h1 { font-size: 20pt; border-bottom: 2px solid #d0d0d0; padding-bottom: 6px;
     margin: 0 0 14px; }
h2 { font-size: 15pt; margin: 22px 0 8px; color: #0a0a0a; }
h3 { font-size: 12.5pt; margin: 16px 0 6px; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 10pt; }
th, td { border: 1px solid #c8c8c8; padding: 5px 8px; text-align: left;
         vertical-align: top; }
th { background: #f0f0f0; font-weight: 600; }
code { font: 10pt "SF Mono", Menlo, monospace; background: #f3f3f3;
       padding: 1px 4px; border-radius: 3px; }
pre { background: #f6f6f6; border-left: 3px solid #b0b0b0; padding: 8px 12px;
      font: 9.5pt "SF Mono", Menlo, monospace; white-space: pre-wrap; }
pre code { background: none; padding: 0; }
blockquote { border-left: 3px solid #999; margin: 10px 0; padding: 2px 14px;
             color: #333; background: #fafafa; }
li { margin: 3px 0; }
hr { border: none; border-top: 1px solid #ddd; margin: 18px 0; }
"""


def inline(s: str) -> str:
    """Разметка внутри строки. Порядок важен: код раньше остального."""
    parts, out, i = [], [], 0
    # `код` вынимается первым — внутри него разметка не действует.
    for m in re.finditer(r"`([^`]+)`", s):
        out.append(html.escape(s[i:m.start()]))
        parts.append(m.group(1))
        out.append(f"\x00{len(parts)-1}\x00")
        i = m.end()
    out.append(html.escape(s[i:]))
    t = "".join(out)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<a href='\2'>\1</a>", t)
    for n, c in enumerate(parts):
        t = t.replace(f"\x00{n}\x00", f"<code>{html.escape(c)}</code>")
    return t


def to_html(md: str, title: str) -> str:
    out: list[str] = []
    lines = md.splitlines()
    i, in_code, in_list = 0, False, False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    while i < len(lines):
        ln = lines[i]

        if ln.lstrip().startswith("```"):
            if in_code:
                out.append("</code></pre>")
            else:
                close_list()
                out.append("<pre><code>")
            in_code = not in_code
            i += 1
            continue
        if in_code:
            out.append(html.escape(ln))
            i += 1
            continue

        # Таблица: строка с | и следующая — разделитель
        if ln.startswith("|") and i + 1 < len(lines) and re.match(
                r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            close_list()
            head = [c.strip() for c in ln.strip("|").split("|")]
            out.append("<table><tr>" + "".join(
                f"<th>{inline(c)}</th>" for c in head) + "</tr>")
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip("|").split("|")]
                out.append("<tr>" + "".join(
                    f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
                i += 1
            out.append("</table>")
            continue

        if m := re.match(r"^(#{1,4})\s+(.*)$", ln):
            close_list()
            n = len(m.group(1))
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
        elif ln.startswith(">"):
            # 🔴 Цитата собирается ЦЕЛИКОМ, а не построчно. Первая редакция
            # оборачивала каждую строку в свой <blockquote>: многострочная
            # цитата рвалась на куски, а курсив `*…*`, начатый в одной строке
            # и закрытый в другой, не срабатывал вовсе — что и было видно
            # в первом собранном PDF.
            close_list()
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i].lstrip(">").lstrip())
                i += 1
            out.append(f"<blockquote>{inline(' '.join(buf))}</blockquote>")
            continue
        elif re.match(r"^\s*[-*·]\s+", ln):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(re.sub(r'^\\s*[-*·]\\s+', '', ln))}</li>")
        elif re.match(r"^\s*\d+\.\s+", ln):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(re.sub(r'^\\s*\\d+\\.\\s+', '', ln))}</li>")
        elif ln.strip() in ("---", "***"):
            close_list()
            out.append("<hr>")
        elif not ln.strip():
            close_list()
        else:
            close_list()
            out.append(f"<p>{inline(ln)}</p>")
        i += 1
    close_list()

    return (f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
            f"<body>{''.join(out)}</body></html>")


def find_chrome() -> str | None:
    """Путь к Chrome — ПОИСКОМ, а не одной зашитой строкой.

    🔴 Владелец разложил программы по папкам-категориям: реальный Chrome лежит
    в `/Applications/browsers/`, а в корне — алиас Finder. Проверка «есть ли
    /Applications/Google Chrome.app» дала бы ложное «нет» (`PIT-187`).
    """
    for pat in ("/Applications/*/Google Chrome.app", "/Applications/Google Chrome.app",
                "/Applications/*/Chromium.app", "/Applications/Chromium.app",
                "/Applications/*/Brave Browser.app", "/Applications/*/Microsoft Edge.app"):
        for app in sorted(Path("/").glob(pat.lstrip("/"))):
            exe = app / "Contents" / "MacOS" / app.stem
            if exe.is_file():
                return str(exe)
    return None


def convert(src: Path, dst: Path) -> int:
    if not src.is_file():
        print(f"🔴 нет файла: {src}")
        return 2
    chrome = find_chrome()
    if not chrome:
        print("🔴 не найден Chrome — он нужен для печати в PDF.")
        print("   Искали: /Applications/**/Google Chrome.app, Chromium, Brave, Edge.")
        return 2

    body = to_html(src.read_text(encoding="utf-8"), src.stem)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as d:
        h = Path(d) / "page.html"
        h.write_text(body, encoding="utf-8")
        # 🔴 `--no-pdf-header-footer` убирает колонтитул с путём к временному
        # файлу: без него в шапке каждой страницы печатается `/var/folders/...`,
        # что выглядит мусором в документе, который отдают человеку.
        r = subprocess.run(
            [chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
             f"--print-to-pdf={dst}", h.as_uri()],
            capture_output=True, timeout=120)
        if not dst.exists() or dst.stat().st_size < 1000:
            err = (r.stderr or b"").decode(errors="replace")[:200]
            print(f"🔴 PDF не собрался: {err}")
            return 1
    print(f"🟢 {dst} · {dst.stat().st_size/1024:.0f} КБ")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="исходный .md")
    ap.add_argument("--out", help="куда положить .pdf")
    a = ap.parse_args()
    src = Path(a.src).resolve()
    dst = Path(a.out).expanduser() if a.out else src.with_suffix(".pdf")
    return convert(src, dst)


if __name__ == "__main__":
    sys.exit(main())
