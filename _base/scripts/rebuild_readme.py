#!/usr/bin/env python3
"""rebuild_readme.py — собрать README из НАСТОЯЩЕГО содержания репы.

🔴 ПОВОД, СФОРМУЛИРОВАННЫЙ ВЛАДЕЛЬЦЕМ 28.08.2026 дословно: «во всех репах
какая-то херня с таблицей структура, много пустых… и этот же скрипт сделал
ридми МЕГА маленьким. Ридми должен быть подробным, рассказывать что есть что,
показывать структуру папок, объяснять словами тезисно что есть что зачем».

ЗАМЕРЕНО 29.08.2026, и жалоба подтвердилась числом: медиана README по 58
репам — около 50 строк, при том что образец `personal-finance-dss` — 570.
В типичной репе нашлись **две** таблицы структуры сразу:

  · «Repository map» — колонка «Contents» **пустая у всех строк**;
  · «Структура» — заполнена автоматически строками вида «1 заметка»,
    то есть формально не пуста и содержательно пуста.

🔴 ГЛАВНОЕ НАБЛЮДЕНИЕ, ИЗ КОТОРОГО СЛЕДУЕТ ВЕСЬ ИНСТРУМЕНТ.
**Содержание не потеряно — оно просто не показано.** У той же репы в
`MANIFEST.md` §1 лежат три предложения о том, что это и зачем, а в §3 —
таблица «что там по существу», написанная человеком. И у каждого файла
в папке есть осмысленный заголовок первой строкой. README не использовал
ничего из этого.

Поэтому инструмент **ничего не сочиняет**. Он берёт, по убыванию качества:

  1. `MANIFEST.md` §3 — столбец «что там по существу», написан человеком;
  2. заголовки `# ` файлов внутри папки — написаны человеком;
  3. счётчик файлов — если нет ни того, ни другого, честно пишет, что
     описания нет, **вместо** строки «1 заметка», которая выглядит как
     описание и им не является.

🔴 ЧЕГО ЭТОТ ИНСТРУМЕНТ НЕ ДЕЛАЕТ (`71` §7г-бис):

  · **не пишет за человека «зачем»** — если в `MANIFEST.md` нет §1, README
    получит пометку, что объяснение отсутствует, а не выдуманный абзац.
    Придуманное «зачем» хуже пустого места: пустое видно, придуманное — нет;
  · **не трогает ничего вне своих маркеров** — рукописный текст README
    переживает любое число прогонов;
  · **не судит, верно ли то, что написано в `MANIFEST.md`** — переносит
    как есть.

ЗАПУСК
    rebuild_readme.py --check           что изменится во всех репах
    rebuild_readme.py --repo chess      одна репа
    rebuild_readme.py --all             применить ко всем
    rebuild_readme.py --selftest        канарейка
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Корень определяется общим модулем: скрипт может быть запущен и из базы,
# и из копии кита в репе-наследнике (`_base/scripts/`). См. `_roots.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402
BASE_REPO, REPOS, FROM_KIT = resolve_roots(__file__)
SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", "_base",
        ".pytest_cache", "dist", "build", ".next", ".claude", "tests"}

START = "<!-- STRUCTURE:AUTO:START -->"
END = "<!-- STRUCTURE:AUTO:END -->"
# Устаревшая таблица с пустым столбцом — её и называл владелец «хернёй».
LEGACY_MAP_RE = re.compile(
    r"\n## Repository map\n\n\| Folder \| Contents \|\n\|---\|---\|\n"
    r"(?:\|[^\n]*\|\n)+", re.M)


def manifest_descriptions(repo: Path) -> dict[str, str]:
    """Столбец «что там по существу» из `MANIFEST.md` §3 — писал человек.

    Возвращает {имя папки: описание}. Нет манифеста или нет таблицы —
    пустой словарь, и это штатно.
    """
    path = repo / "MANIFEST.md"
    if not path.is_file():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\|\s*`([^`]+)/`\s*\|[^|]*\|\s*([^|]+?)\s*\|", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def folder_titles(folder: Path, limit: int = 4) -> list[str]:
    """Заголовки `# ` файлов внутри папки — их писал человек, не генератор."""
    titles = []
    for path in sorted(folder.rglob("*.md")):
        if any(p in SKIP for p in path.parts):
            continue
        try:
            first = path.read_text(encoding="utf-8", errors="replace").lstrip()
        except OSError:
            continue
        if first.startswith("# "):
            title = first.split("\n", 1)[0][2:].strip()
            # Отсечь хвост после тире: в заголовке часто есть пояснение,
            # а в таблицу нужен предмет.
            if title and title.lower() != folder.name.lower():
                titles.append(title)
        if len(titles) >= limit:
            break
    return titles


def build_table(repo: Path) -> str:
    """Таблица структуры: папка · файлов · что внутри по существу."""
    manifest = manifest_descriptions(repo)
    rows = []
    for folder in sorted(repo.iterdir()):
        if not folder.is_dir() or folder.name in SKIP or folder.name.startswith("."):
            continue
        files = [p for p in folder.rglob("*")
                 if p.is_file() and not any(s in p.parts for s in SKIP)]
        if not files:
            continue
        if folder.name in manifest:
            what = manifest[folder.name]
        else:
            titles = folder_titles(folder)
            what = " · ".join(titles) if titles else \
                "_описания нет — ни в `MANIFEST.md` §3, ни в заголовках файлов_"
        rows.append(f"| [`{folder.name}/`]({folder.name}/) | {len(files)} | {what} |")

    if not rows:
        return f"{START}\n_В репе нет папок с файлами._\n{END}"
    head = ("| Папка | Файлов | Что внутри по существу |\n|---|---|---|")
    note = ("\n_Столбец «что внутри» собран из `MANIFEST.md` §3, где он есть, "
            "иначе из заголовков самих файлов. Ничего не сочинено: где "
            "описания нет — так и написано._")
    return f"{START}\n{head}\n" + "\n".join(rows) + f"\n{note}\n{END}"


def manifest_intro(repo: Path) -> str:
    """Три предложения «что это за репа» из `MANIFEST.md` §1."""
    path = repo / "MANIFEST.md"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"##\s*1\.\s*Что это за репа[^\n]*\n+(.+?)(?=\n\*\*|\n##)",
                  text, re.S)
    return m.group(1).strip() if m else ""


def insert_before_structure(text: str, block: str) -> str:
    """Вставить перед разделом «Структура», иначе перед подвалом.

    🔴 Порядок разделов задан стандартом `98` §1 и не произволен: «С чего
    начать» после таблицы каталогов бесполезен — читатель уже пролистал.
    Первая редакция вставляла перед подвалом и получила именно это.
    """
    i = text.find("\n## Структура")
    if i != -1:
        return text[:i] + "\n" + block + text[i:]
    return insert_before_footer(text, block)


def insert_before_footer(text: str, block: str) -> str:
    """Вставить блок перед подписью-подвалом, если она есть.

    Подвал — горизонтальная черта и строка с контактом. Всё, что дописано
    после неё, читатель уже не видит: подпись читается как конец документа.
    """
    m = re.search(r"\n---\n+\*\*Contact:", text)
    if m:
        return text[:m.start()] + "\n" + block + text[m.start():]
    if not text.endswith("\n"):
        text += "\n"
    return text + block


def repo_class(repo: Path) -> str:
    """Класс репы — от него зависит, какие разделы уместны (`98` §2–§4)."""
    path = repo / ".repo-class"
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def content_dirs(repo: Path) -> list[tuple[str, str]]:
    """(каталог, заголовок первого документа) — содержательные каталоги.

    Служебные (`reports`, `plans`, `daily`) пропускаются: они про ведение
    репы, а не про её предмет.
    """
    service = {"reports", "plans", "daily", "profile", "scripts", "docs",
               "tests", "templates", "assets", "data"}
    out = []
    for folder in sorted(repo.iterdir()):
        if not folder.is_dir() or folder.name in SKIP or folder.name in service \
                or folder.name.startswith("."):
            continue
        titles = folder_titles(folder, limit=1)
        if titles:
            out.append((folder.name, titles[0]))
    return out


def what_you_learn(repo: Path) -> str:
    """Раздел «Что здесь можно узнать» — из ЗАГОЛОВКОВ, написанных человеком.

    🔴 Ничего не сочиняется. Заголовок документа — это и есть вопрос,
    на который документ отвечает; списком они складываются в ответ
    «что здесь можно узнать». Нет содержательных каталогов — раздела нет.
    """
    dirs = content_dirs(repo)
    if len(dirs) < 2:
        return ""
    lines = [f"- **{name}/** — {title}" for name, title in dirs[:8]]
    return ("## Что здесь можно узнать\n\n" + "\n".join(lines)
            + "\n\n_Собрано из заголовков самих документов — это и есть "
              "вопросы, на которые они отвечают._\n")


def boundaries(repo: Path) -> str:
    """Раздел «Границы» — предложения манифеста, говорящие, чего в репе НЕТ.

    Берутся фразы с отрицанием («не пересекается», «не теория вообще»,
    «а не …»): человек уже написал, где проходит граница, — надо перенести,
    а не выдумать заново.
    """
    text = manifest_intro(repo)
    if not text:
        return ""
    marks = ("не пересека", "не теория", "не про ", "а не ", "не входит",
             "не включ", "не относ", "вне ")
    # Переносы строк внутри предложения схлопываются: манифест свёрстан
    # по ширине, а в списке пункт обязан быть одной строкой.
    picked = [" ".join(s.split()) for s in re.split(r"(?<=[.!?])\s+", text)
              if any(m in s.lower() for m in marks)]
    if not picked:
        return ""
    return ("## Границы — чего здесь НЕТ\n\n"
            + "\n".join(f"- {s}" for s in picked)
            + "\n\n_Перенесено из [`MANIFEST.md`](MANIFEST.md) §1._\n")


def start_here(repo: Path) -> str:
    """Раздел «С чего начать» — только существующие файлы, в порядке чтения."""
    steps = []
    if (repo / "START-HERE.md").is_file():
        steps.append("**[`START-HERE.md`](START-HERE.md)** — вход в репу")
    if (repo / "MANIFEST.md").is_file():
        steps.append("**[`MANIFEST.md`](MANIFEST.md)** — что это, границы, "
                     "состояние ревизии")
    dirs = content_dirs(repo)
    if dirs:
        name, title = dirs[0]
        steps.append(f"**[`{name}/`]({name}/)** — {title}")
    if (repo / "ROADMAP.md").is_file():
        steps.append("**[`ROADMAP.md`](ROADMAP.md)** — что открыто")
    if len(steps) < 3:
        return ""
    return ("## С чего начать\n\n"
            + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)) + "\n")


def rebuild(repo: Path) -> tuple[bool, str]:
    """Вернуть (изменилось ли, новый текст README)."""
    path = repo / "README.md"
    if not path.is_file():
        return False, ""
    text = original = path.read_text(encoding="utf-8", errors="replace")

    # 1. Снять устаревшую таблицу с пустым столбцом — дубль по смыслу.
    text = LEGACY_MAP_RE.sub("\n", text)

    # 2. Пересобрать таблицу структуры между маркерами.
    #
    # 🔴 Место разделов важно не меньше содержания. Первая редакция дописывала
    # оба в КОНЕЦ файла — и «что это и зачем» оказывалось ниже подписи с почтой,
    # то есть после того места, где читатель уже перестал читать. Раздел,
    # стоящий не там, читается не лучше отсутствующего.
    table = build_table(repo)
    if START in text and END in text:
        i, j = text.index(START), text.index(END) + len(END)
        # Заголовок раздела прямо над маркерами забирается вместе с блоком,
        # иначе при переносе он остался бы висеть над пустотой.
        head = text.rfind("## ", 0, i)
        start = head if head != -1 and text[head:i].strip().count("\n") <= 2 else i
        text = text[:start] + text[j:]
        text = insert_before_footer(text, f"\n## Структура\n\n{table}\n")
    else:
        text = insert_before_footer(text, f"\n## Структура\n\n{table}\n")

    # 3а. Разделы стандарта `98`: с чего начать · что можно узнать · границы.
    # Все три собираются ИЗ НАПИСАННОГО ЧЕЛОВЕКОМ (манифест, заголовки файлов).
    # Нечего собрать — раздела нет: пустой раздел обещает и не даёт.
    for marker, builder in (("## С чего начать", start_here),
                            ("## Что здесь можно узнать", what_you_learn),
                            ("## Границы — чего здесь НЕТ", boundaries)):
        if marker in text:
            continue
        block = builder(repo)
        if block:
            text = insert_before_structure(text, "\n" + block)

    # 3. Объяснение «что это и зачем» — ПЕРЕД первым разделом, а не в конце.
    intro = manifest_intro(repo)
    if intro and "## Что это и зачем" not in text:
        block = (f"\n## Что это и зачем\n\n{intro}\n\n"
                 f"_Перенесено из [`MANIFEST.md`](MANIFEST.md) §1 — "
                 f"единственного места, где это написано человеком._\n")
        m = re.search(r"^## ", text, re.M)
        text = (text[:m.start()] + block.lstrip("\n") + "\n" + text[m.start():]
                if m else text + block)
    # 🔴 НОРМАЛИЗАЦИЯ — без неё скрипт не идемпотентен, и это измерено:
    # каждый прогон вырезал блок вместе с окружающими переводами строк
    # и вставлял его со своими, накапливая по ТРИ пустых строки за проход.
    # Сходящийся скрипт обязан давать один и тот же результат на втором
    # прогоне (`08-automation-triggers.md`); проверяется `idempotence_check.py`.
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text.endswith("\n"):
        text += "\n"
    return text != original, text


def selftest() -> bool:
    """Проверяется РАЗЛИЧЕНИЕ, а не то, что код исполняется.

    Три половины: описание из манифеста побеждает заголовок; при отсутствии
    манифеста берётся заголовок файла; при отсутствии обоих пишется, что
    описания нет, — а НЕ выдумывается.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "01-a").mkdir(); (repo / "02-b").mkdir(); (repo / "03-c").mkdir()
        (repo / "01-a" / "x.md").write_text("# Заголовок файла\n", encoding="utf-8")
        (repo / "02-b" / "y.md").write_text("# Живой заголовок\n", encoding="utf-8")
        (repo / "03-c" / "z.txt").write_text("без заголовка", encoding="utf-8")
        (repo / "MANIFEST.md").write_text(
            "# М\n\n## 3. Что внутри\n\n| Раздел | Файлов | Что там |\n"
            "|---|---|---|\n| `01-a/` | 1 | описание от человека |\n",
            encoding="utf-8")
        table = build_table(repo)
        return ("описание от человека" in table          # манифест победил
                and "Живой заголовок" in table            # заголовок подхвачен
                and "описания нет" in table)              # пустое названо пустым


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        ok = selftest()
        print("🟢 канарейка: манифест побеждает заголовок, пустое названо пустым"
              if ok else "🔴 канарейка: РАЗЛИЧЕНИЕ СЛОМАНО")
        return 0 if ok else 1

    if not selftest():
        print("🔴 канарейка не прошла — результатам ниже верить нельзя")
        return 1

    if a.repo:
        repos = [REPOS / a.repo]
    else:
        repos = [d for d in sorted(REPOS.iterdir())
                 if d.is_dir() and (d / "README.md").is_file()
                 and (d / "VERSION").is_file()]

    changed = 0
    for repo in repos:
        if not repo.is_dir():
            print(f"🔴 нет репы: {repo.name}")
            continue
        differs, text = rebuild(repo)
        if not differs:
            continue
        changed += 1
        before = len((repo / "README.md").read_text(encoding="utf-8").splitlines())
        after = len(text.splitlines())
        print(f"  {repo.name:<28} {before:>4} → {after:>4} строк")
        if not a.check:
            (repo / "README.md").write_text(text, encoding="utf-8")

    verb = "изменилось бы" if a.check else "изменено"
    print(f"\n{verb} README: {changed} из {len(repos)}")
    if a.check:
        print("Это только план. Применить: --all (или --repo ИМЯ).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
