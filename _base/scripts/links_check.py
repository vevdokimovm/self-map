#!/usr/bin/env python3
"""links_check.py — markdown-ссылки внутри репы ведут на существующие файлы?

🔴 ПОВОД. Заказ владельца 04.09.2026: *«пофикси везде ссылки, а то мы недавно
стандарт ввели, но мне кажется много где ошибки ссылочные»*.

🔴 ЗАМЕР ВАЖНЕЕ ЗАКАЗА, И ОН ОПРОВЕРГ ОПАСЕНИЕ. Наивный проход дал
**2464 «битых» ссылки** по 11 репам. Разбор каждого класса:

    2090  импортированные экспорты Notion (`%20` в путях, чужие вложения)
      15  шаблоны репы целиком — `<./NN-folder>` там не путь, а место для имени
      14  математика: `[3]`, `[a2]`, `[m−1]` — индексы формул, не ссылки
       8  плейсхолдеры `<...>` в других документах
       5  цитаты чужого конфига: `[⬢ $version](bold green)` из starship
    ────
      11  каркасы черновиков: файл САМ объявлен «скелетом», рисунки будут позже
       1  🔴 настоящая: ссылка на удалённый каталог `04-deliverables`

**Из 2464 находок настоящая — ОДНА.** Разбор каждого класса занял час
и стоил того: 2463 «дефекта» оказались либо не ссылками, либо законными.

> Проверка, дающая тысячи находок при одной настоящей, **не сообщает ничего
> и учит не читать себя** (`69` §4з). Отсев здесь не «подгонка под ответ»,
> а ответ на вопрос **«что вообще считать ссылкой»**.

**У самой базы настоящих битых ссылок — НОЛЬ.** Две «находки» в
`75-readme-status-block.md` оказались образцом внутри блока кода: документ
ПОКАЗЫВАЕТ, как выглядит блок статуса, и ссылки в примере не должны вести
никуда.

> Проверка, дающая 2464 находки при 17 настоящих, не сообщает ничего
> и учит не читать себя (`69` §4з). Отсев здесь — не «подгонка под ответ»,
> а ответ на вопрос **«что вообще считать ссылкой»**.

ЧТО ОТСЕИВАЕТСЯ И ПОЧЕМУ — каждый класс проверен глазами на образцах:

  · внешние схемы (`http`, `mailto:`, `data:`) — не файлы;
  · строки длиннее 200 символов — base64-картинка, а не путь;
  · содержимое блоков ``` ``` ``` — это образец, а не живая ссылка;
  · `<...>` — плейсхолдер шаблона, он и не должен существовать;
  · файлы-шаблоны целиком (`*TEMPLATE*`, `*template*`);
  · импортированные каталоги — чужой экспорт, чинить его бессмысленно;
  · короткие `[3]`, `[a2]` — индексы формул в математических конспектах.

🔴 ГРАНИЦА: проверка смотрит только на **существование цели**. Ссылка
на существующий, но не тот файл ею не ловится — это работа чтения.

ЗАПУСК:
    python3 scripts/links_check.py              # база
    python3 scripts/links_check.py --all        # все репы
    python3 scripts/links_check.py --selftest
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402

LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
EXTERNAL = ("http", "mailto:", "tel:", "#", "data:", "javascript:", "ftp", "//")
SKIP_PARTS = ("_base", ".git", "node_modules", ".venv", "02-code-archive",
              "90-imported", "imports")
SKIP_HINTS = ("notion", "raznoe", "разное")
# Цель не является путём по своей форме.
NOT_A_PATH = (
    re.compile(r"^<.*>$"),                    # плейсхолдер шаблона
    re.compile(r"^[\d\s.,;:+\-−]+$"),         # индекс формулы: 3, m−1
    re.compile(r"^[a-zA-Z]\d*$"),             # a, a2, x
    re.compile(r"^(bold|dimmed|auto|italic)\b"),   # цвет в чужом конфиге
    re.compile(r"\.{3}$"),                    # обрезанный путь «../figures/...»
    re.compile(r"<[^>]+>"),                   # <N> внутри пути: task<N>_graph.png
)


def is_template(f: Path) -> bool:
    n = f.name.lower()
    return "template" in n or "шаблон" in n


def code_line_numbers(text: str) -> set[int]:
    """Номера строк ВНУТРИ блоков ``` — там ссылки это образец, а не адрес."""
    inside, out, fence = False, set(), False
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fence = not fence
            out.add(n)
            continue
        if fence:
            out.add(n)
    return out


def check(root: Path) -> list[tuple[str, int, str]]:
    bad: list[tuple[str, int, str]] = []
    for f in sorted(root.rglob("*.md")):
        rel = f.relative_to(root)
        s = rel.as_posix().lower()
        if any(p in rel.parts for p in SKIP_PARTS) or any(h in s for h in SKIP_HINTS):
            continue
        if is_template(f):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        skip_lines = code_line_numbers(text)
        # 🔴 CHANGELOG и прочие ЖУРНАЛЫ СОБЫТИЙ исключены: там записано,
        # что было сказано ТОГДА, включая цитаты чужих битых ссылок в разборе.
        # Правка задним числом не исправляет показание, а уничтожает его
        # (`94-change-journals.md` §2). Ровно этот файл и попал в находки:
        # `CHANGELOG.md:9307` цитирует пример синтаксиса из прошлого разбора.
        if any(j in f.name for j in ("CHANGELOG", "HISTORY", "PITFALLS",
                                     "pitfalls", "decisions", "LEDGER")):
            continue
        for ln, line in enumerate(text.splitlines(), 1):
            if ln in skip_lines:
                continue
            for m in LINK.finditer(line):
                tgt = m.group(2).split("#")[0].strip()
                if not tgt or tgt.lower().startswith(EXTERNAL) or len(tgt) > 200:
                    continue
                if any(rx.match(tgt) for rx in NOT_A_PATH):
                    continue
                dec = urllib.parse.unquote(tgt)
                try:
                    if (f.parent / dec).exists() or (f.parent / tgt).exists():
                        continue
                except OSError:
                    continue
                bad.append((rel.as_posix(), ln, tgt))
    return bad


def selftest() -> int:
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / "real.md").write_text("текст\n", encoding="utf-8")
        cases = [
            ("живая ссылка", "[тут](real.md)\n", False),
            ("битая ссылка", "[тут](нет-такого.md)\n", True),
            ("внешняя", "[сайт](https://x.ru/нет)\n", False),
            ("плейсхолдер", "[папка](<./NN-folder>)\n", False),
            ("индекс формулы", "коэффициент [3] тут\n", False),
            ("внутри блока кода", "```\n[a](нет.md)\n```\n", False),
            ("цвет в конфиге", "format = [⬢ $v](bold green)\n", False),
        ]
        for name, body, expect in cases:
            (r / "probe.md").write_text(body, encoding="utf-8")
            got = any(b[0] == "probe.md" for b in check(r))
            mark = "✅" if got == expect else "🔴"
            print(f"   {mark} {name}: {'ловится' if got else 'молчит'}")
            ok &= got == expect
    print("selftest OK" if ok else "🔴 selftest ПРОВАЛЕН")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    base, root, _ = resolve_roots(__file__)
    repos = ([d for d in sorted(root.iterdir())
              if d.is_dir() and (d / "VERSION").exists()] if a.all
             else [root / a.repo] if a.repo else [base])

    total = 0
    for repo in repos:
        if not repo.exists():
            print(f"🔴 нет репы: {repo.name}")
            return 2
        bad = check(repo)
        total += len(bad)
        if bad:
            print(f"\n🔴 {repo.name} — ссылок в никуда: {len(bad)}")
            for rel, ln, tgt in bad:
                print(f"   {rel}:{ln}  →  {tgt}")

    scope = f"{len(repos)} реп" if a.all else repos[0].name
    if total:
        print(f"\nИТОГ: {scope} · 🔴 {total} ссылок ведут в никуда")
        return 1
    print(f"ИТОГ: {scope} · 🟢 все ссылки ведут на существующие файлы")
    return 0


if __name__ == "__main__":
    sys.exit(main())
