#!/usr/bin/env python3
"""Диф батча одной страницей — локально, без публикации куда-либо.

🔴 ЗАЧЕМ. Заказ владельца 07.09.2026: показывать изменения «в доп окне
справа», как это делает панель артефактов. Развилка решена им же в пользу
**локального файла**: содержимое базы приватно, и уносить его на сторонние
серверы ради удобства просмотра — плохой размен.

🔴 ПОЧЕМУ СТРАНИЦА, А НЕ ВЫВОД В ТЕРМИНАЛ. Замер 05.09.2026: iTerm
и WindowServer вместе брали до **80 % ядра** на отрисовке вывода вахты
поверх игры (`LOAD-CLASSES.md` §4д). Длинный цветной диф в терминале —
это кадры владельца. Файл открывается тогда, когда он сам захочет.

🔴 ЧЕГО НЕ ДЕЛАЕТ: не коммитит, не пушит, не трогает рабочее дерево.
Только читает `git diff` и пишет один HTML в каталог артефактов.

Применение:
    diff_view.py                 диф рабочей копии против HEAD
    diff_view.py --open          и сразу открыть в браузере
    diff_view.py --selftest      канарейка
"""

from __future__ import annotations

import argparse
import html
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from _roots import artifacts_dir
except Exception:                                     # noqa: BLE001
    artifacts_dir = lambda: Path.home() / "Developer"  # noqa: E731

СТИЛЬ = """
:root{--fon:#14161a;--karta:#1b1e24;--ramka:#2a2f38;--tekst:#d6dae1;
--tusklo:#8b929e;--plus:#3fb950;--minus:#f85149;--shapka:#58a6ff}
*{box-sizing:border-box}
body{margin:0;background:var(--fon);color:var(--tekst);
font:14px/1.55 -apple-system,BlinkMacSystemFont,"SF Pro Text",sans-serif}
.obolochka{max-width:1100px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:20px;font-weight:600;margin:0 0 4px}
.pod{color:var(--tusklo);font-size:13px;margin-bottom:22px}
.svodka{display:flex;gap:22px;flex-wrap:wrap;background:var(--karta);
border:1px solid var(--ramka);border-radius:10px;padding:14px 18px;margin-bottom:24px}
.svodka div{font-size:13px}.svodka b{font-size:18px;display:block;font-weight:600}
.plus{color:var(--plus)}.minus{color:var(--minus)}
.fajl{background:var(--karta);border:1px solid var(--ramka);border-radius:10px;
margin-bottom:14px;overflow:hidden}
.imya{padding:10px 16px;border-bottom:1px solid var(--ramka);
font-weight:600;font-size:13px;display:flex;justify-content:space-between;gap:12px}
.imya span{color:var(--tusklo);font-weight:400}
pre{margin:0;padding:12px 16px;overflow-x:auto;
font:12.5px/1.5 "SF Mono",ui-monospace,Menlo,monospace}
.l{display:block;white-space:pre;padding:0 4px;border-radius:3px}
.l.p{background:rgba(63,185,80,.12);color:var(--plus)}
.l.m{background:rgba(248,81,73,.12);color:var(--minus)}
.l.h{color:var(--shapka);margin-top:6px}
.pusto{color:var(--tusklo);padding:30px;text-align:center}
.novye li{color:var(--plus);font-family:"SF Mono",monospace;font-size:12.5px}
"""


def _git(*аргументы: str) -> str:
    res = subprocess.run(["git", *аргументы], capture_output=True,
                         text=True, encoding="utf-8")
    return res.stdout


def разобрать(диф: str) -> list[tuple[str, list[str]]]:
    """Разбивает сплошной вывод `git diff` на пары «файл → строки»."""
    файлы: list[tuple[str, list[str]]] = []
    имя, строки = None, []
    for стр in диф.splitlines():
        if стр.startswith("diff --git "):
            if имя:
                файлы.append((имя, строки))
            имя = стр.split(" b/")[-1]
            строки = []
        elif имя is not None and not стр.startswith(("index ", "--- ", "+++ ")):
            строки.append(стр)
    if имя:
        файлы.append((имя, строки))
    return файлы


def класс(строка: str) -> str:
    if строка.startswith("+"):
        return "p"
    if строка.startswith("-"):
        return "m"
    if строка.startswith("@@"):
        return "h"
    return ""


def собрать(версия: str, файлы: list, новые: list[str], статистика: str) -> str:
    плюсов = sum(1 for _, стр in файлы for с in стр if с.startswith("+"))
    минусов = sum(1 for _, стр in файлы for с in стр if с.startswith("-"))
    куски = [f"<!doctype html><html lang=ru><head><meta charset=utf-8>",
             f"<meta name=viewport content='width=device-width,initial-scale=1'>",
             f"<title>diff {версия}</title><style>{СТИЛЬ}</style></head><body>",
             "<div class=obolochka>",
             f"<h1>base-repo · {html.escape(версия)}</h1>",
             f"<div class=pod>собрано {datetime.now():%d.%m.%Y %H:%M} · "
             f"локальный файл, ничего не отправлено</div>",
             "<div class=svodka>",
             f"<div><b>{len(файлы)}</b>изменено файлов</div>",
             f"<div><b class=plus>+{плюсов}</b>строк добавлено</div>",
             f"<div><b class=minus>−{минусов}</b>строк удалено</div>",
             f"<div><b>{len(новые)}</b>новых путей</div>",
             "</div>"]
    if новые:
        куски.append("<div class=fajl><div class=imya>Новое, ещё не в истории</div>"
                     "<pre class=novye>" +
                     "".join(f"<span class='l p'>?? {html.escape(п)}</span>" for п in новые) +
                     "</pre></div>")
    if not файлы:
        куски.append("<div class='fajl pusto'>Изменений против HEAD нет</div>")
    for имя, строки in файлы:
        свои_плюсы = sum(1 for с in строки if с.startswith("+"))
        свои_минусы = sum(1 for с in строки if с.startswith("-"))
        куски.append(f"<div class=fajl><div class=imya>{html.escape(имя)}"
                     f"<span><span class=plus>+{свои_плюсы}</span> "
                     f"<span class=minus>−{свои_минусы}</span></span></div><pre>")
        for с in строки:
            куски.append(f"<span class='l {класс(с)}'>{html.escape(с) or '&nbsp;'}</span>")
        куски.append("</pre></div>")
    куски.append("</div></body></html>")
    return "".join(куски)


def selftest() -> bool:
    """Канарейка: разбор различает файлы, а раскраска — знаки строк.

    🔴 Проверяет и то, что инструмент НЕ красит лишнего: контекстная строка
    обязана остаться без класса, иначе диф превратится в сплошную заливку.
    """
    образец = ("diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n"
               "@@ -1 +1 @@\n-старое\n+новое\n контекст\n"
               "diff --git a/y.md b/y.md\n+одна\n")
    файлы = разобрать(образец)
    if len(файлы) != 2 or файлы[0][0] != "x.py" or файлы[1][0] != "y.md":
        return False
    return (класс("+a") == "p" and класс("-a") == "m"
            and класс("@@ x") == "h" and класс(" ctx") == "")


def main() -> int:
    р = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    р.add_argument("--open", action="store_true", help="открыть в браузере")
    р.add_argument("--selftest", action="store_true")
    a = р.parse_args()

    if a.selftest:
        ок = selftest()
        print("🟢 канарейка: разбор и раскраска различают" if ок
              else "🔴 КАНАРЕЙКА УПАЛА")
        return 0 if ок else 1

    if not Path(".git").exists():
        print("🔴 в этой репе нет .git — сравнивать не с чем")
        return 2

    версия = Path("VERSION").read_text(encoding="utf-8").strip() if Path("VERSION").is_file() else "?"
    диф = _git("diff", "HEAD")
    новые = [с[3:] for с in _git("status", "--short").splitlines() if с.startswith("??")]
    файлы = разобрать(диф)

    куда = Path(artifacts_dir()) / f"diff-{версия}.html"
    куда.write_text(собрать(версия, файлы, новые, _git("diff", "--stat", "HEAD")),
                    encoding="utf-8")
    print(f"🟢 {куда}")
    print(f"   файлов изменено: {len(файлы)} · новых путей: {len(новые)}")
    if a.open:
        subprocess.run(["open", str(куда)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
