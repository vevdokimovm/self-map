#!/usr/bin/env python3
"""archive_closed_tasks.py — вынести закрытые пункты из рабочих файлов в историю.

ЗАЧЕМ. `task-hygiene.sh` **находит** накопленное закрытое, но намеренно не
переносит: перенос требует суждения. Однако у одного класса переноса суждения
нет вовсе — механический вынос `- [x]` вместе с его продолжением в
файл-приёмник. Это он и делает, оставляя вахте только то, где суждение
действительно нужно (формулировка итога, решение «а закрыт ли пункт вообще»).

ГРАНИЦА, НАЗВАННАЯ ВСЛУХ (`71` §7г-бис):
  делает      — переносит помеченное `[x]` в `*_HISTORY.md`, схлопывает пустые
                секции в строку-пойнтер, печатает числа до/после;
  НЕ делает   — не решает, закрыт ли пункт (это уже решено чекбоксом), не
                переписывает формулировки, не трогает зачёркнутые строки
                таблиц (`| ~~…~~ |`) — там перенос ломает разметку и требует
                ручного разбора.

ПОЧЕМУ ФОРМУЛИРОВКИ ПЕРЕНОСЯТСЯ КАК ЕСТЬ. У части закрытых пунктов ценность
именно в обосновании снятия («снято архитектурно», «устарело», «снято фактом»),
а не в факте закрытия. Сокращать их при переносе — терять то, ради чего
история и ведётся.

ЗАПУСК
    archive_closed_tasks.py <репа>            сухой прогон (по умолчанию)
    archive_closed_tasks.py <репа> --apply    выполнить
    archive_closed_tasks.py --all [--apply]   по всем репам с VERSION
    archive_closed_tasks.py --selftest        канарейка
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

REPOS = Path(__file__).resolve().parent.parent.parent

# рабочий файл → приёмник
PAIRS = {
    "ROADMAP.md": "ROADMAP_HISTORY.md",
    "TASKS.md": "TASKS_HISTORY.md",
}

DONE_RE = re.compile(r"^\s*[-*]\s*\[x\]", re.IGNORECASE)
OPEN_RE = re.compile(r"^\s*[-*]\s*\[ \]")


def split_closed(text: str) -> tuple[str, list[str]]:
    """Разделить на «остаётся» и «уезжает».

    Продолжением пункта считается отступ — так пишутся многострочные пункты
    во всей системе. Строка, начинающаяся с маркера или заголовка, продолжением
    не является, даже если отступ есть.
    """
    kept: list[str] = []
    moved: list[str] = []
    skipping = False
    for line in text.split("\n"):
        if DONE_RE.match(line):
            skipping = True
            moved.append(line)
            continue
        if skipping:
            is_cont = line.startswith("  ") and line.strip() and not re.match(r"^\s*[-*#]", line)
            if is_cont:
                moved.append(line)
                continue
            skipping = False
        kept.append(line)
    return "\n".join(kept), moved


def collapse_empty_sections(text: str) -> tuple[str, list[str]]:
    """Секция, опустевшая после выноса, получает строку-пойнтер, а не удаляется.

    Удалять нельзя: раздел живой, просто сейчас пуст — и на него могут
    ссылаться. Пустой заголовок при этом хуже пойнтера: он выглядит потерей.
    """
    lines = text.split("\n")
    heads = [(i, l) for i, l in enumerate(lines) if re.match(r"^#{2,3} ", l)]
    emptied: list[str] = []
    inserts: dict[int, str] = {}
    for n, (i, title) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        body = "\n".join(lines[i + 1:end]).strip().strip("-").strip()
        if not body:
            name = title.lstrip("# ").strip()
            emptied.append(name)
            inserts[i] = ("\nВсе пункты закрыты — детали и обоснования "
                          "в файле-истории.\n")
    if not inserts:
        return text, emptied
    out: list[str] = []
    for i, l in enumerate(lines):
        out.append(l)
        if i in inserts:
            out.append(inserts[i])
    return "\n".join(out), emptied


def process(repo: Path, apply: bool) -> dict:
    stats = {"repo": repo.name, "files": []}
    for work, sink in PAIRS.items():
        wp = repo / work
        if not wp.is_file():
            continue
        original = wp.read_text(encoding="utf-8", errors="replace")
        kept, moved = split_closed(original)
        n_moved = sum(1 for m in moved if DONE_RE.match(m))
        if not n_moved:
            continue
        kept, emptied = collapse_empty_sections(kept)
        kept = re.sub(r"\n{4,}", "\n\n\n", kept)
        stats["files"].append({
            "file": work,
            "moved": n_moved,
            "lines_before": original.count("\n") + 1,
            "lines_after": kept.count("\n") + 1,
            "emptied": emptied,
        })
        if apply:
            wp.write_text(kept, encoding="utf-8")
            sp = repo / sink
            head = (f"# {sink.replace('.md', '')} — закрытое, `{repo.name}`\n\n"
                    f"> Куда переезжают выполненные пункты `{work}`.\n"
                    f"> Формулировки перенесены как есть — вместе с обоснованием\n"
                    f"> снятия: у части пунктов ценность именно в нём.\n")
            body = sp.read_text(encoding="utf-8") if sp.is_file() else head
            body += f"\n---\n\n## Вынесено {date.today().isoformat()}\n\n" + "\n".join(moved) + "\n"
            sp.write_text(body, encoding="utf-8")
    return stats


def selftest() -> int:
    """Канарейка: закрытое уезжает, открытое остаётся, продолжение не теряется."""
    import tempfile

    sample = (
        "# T\n\n## A\n\n"
        "- [ ] открытая задача\n"
        "- [x] закрытая задача\n"
        "      её продолжение с отступом\n"
        "- [ ] вторая открытая\n\n"
        "## B\n\n"
        "- [x] всё закрыто тут\n"
    )
    bad = []
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "TASKS.md").write_text(sample, encoding="utf-8")
        process(repo, apply=True)
        after = (repo / "TASKS.md").read_text(encoding="utf-8")
        hist = (repo / "TASKS_HISTORY.md").read_text(encoding="utf-8")

        if "открытая задача" not in after or "вторая открытая" not in after:
            bad.append("открытая задача пропала из рабочего файла")
        if "[x]" in after:
            bad.append("закрытое осталось в рабочем файле")
        if "закрытая задача" not in hist:
            bad.append("закрытое не доехало в историю")
        if "её продолжение с отступом" not in hist:
            bad.append("продолжение пункта потеряно при переносе")
        if "## B" not in after:
            bad.append("опустевшая секция удалена вместо пойнтера")

    if bad:
        print("selftest FAIL:")
        for b in bad:
            print("  ·", b)
        return 1
    print("selftest OK: закрытое уезжает с продолжением, открытое остаётся, "
          "опустевшая секция получает пойнтер")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if not a.repo and not a.all:
        ap.error("нужно имя репы или --all")

    targets = ([d for d in sorted(REPOS.iterdir())
                if d.is_dir() and (d / "VERSION").is_file()]
               if a.all else [REPOS / a.repo])

    total = 0
    for repo in targets:
        st = process(repo, a.apply)
        for f in st["files"]:
            total += f["moved"]
            print(f"  {st['repo']}/{f['file']}: {f['moved']} закрытых · "
                  f"{f['lines_before']} → {f['lines_after']} строк"
                  + (f" · опустело секций: {len(f['emptied'])}" if f["emptied"] else ""))
    print(f"\n{'ПРИМЕНЕНО' if a.apply else 'СУХОЙ ПРОГОН'}: {total} закрытых пунктов")
    return 0


if __name__ == "__main__":
    sys.exit(main())
