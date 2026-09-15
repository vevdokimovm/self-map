#!/usr/bin/env python3
"""refs_index.py — ЕДИНСТВЕННОЕ место, где записано, что считается ссылкой.

🔴 ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ, А НЕ ФУНКЦИЯ В КАЖДОМ СКРИПТЕ. Кандидат №14 очереди
внедрения нашёл **пять независимых определений карточки реестра**, два из которых
расходились с тремя. На живых данных оба давали одно число, поэтому расхождение
было невидимо; проявилось бы на первой карточке с двойным пробелом.

Со ссылками то же самое и уже началось: `kit_weight.py` считал упоминания сам,
`check_incoming_refs.py` — сам, `check_dangling_registry_refs` — сам. Три
определения. Здесь они сводятся к одному ДО того, как разойдутся.

ЧТО СЧИТАЕТСЯ ССЫЛКОЙ: упоминание **имени файла** в тексте любого другого файла
базы. Не путь, не markdown-ссылка — просто имя. Выбор мягкий сознательно:
в этой системе на документы ссылаются и `[текст](путь)`, и «см. `71` §7ж»,
и просто «`pitfalls.md`». Строгий разбор markdown-ссылок пропустил бы
большинство настоящих связей.

🔴 ЧЕГО ЭТО НЕ ЛОВИТ (`71` §7г-бис) — названо здесь, а не оставлено читателю:
  · **ссылку по номеру**: «см. `71` §7ж» не содержит имени файла
    `71-fail-loud-and-sourcing.md`. Такие связи индекс не видит;
  · **обратное — ложное совпадение**: файл `README.md` упоминается всюду,
    и почти любой `README.md` будет выглядеть достижимым;
  · **смысл**: упоминание ≠ польза. Файл могут упоминать и не открывать,
    а неупомянутый может быть самым читаемым (`START-HERE.md`).

Поэтому индекс отвечает на вопрос «**на что не ссылаются**», а не «что не нужно».
Решение о судьбе артефакта — суждение вахты (`71` §7г-бис).
"""
from __future__ import annotations

from pathlib import Path

# Каталоги, которые не являются содержанием базы: копии кита в наследниках,
# кэш, служебное. `_base` исключён по существу: это КОПИЯ канона, и упоминание
# внутри неё не делает файл достижимым — оно и есть тот же самый текст.
SKIP = {".git", "__pycache__", ".pytest_cache", ".venv", "node_modules", "_base"}

# Расширения, в которых ищем упоминания. Двоичные не читаем.
TEXT_SUFFIXES = {".md", ".py", ".sh", ".json", ".tsv", ".txt", ".yml", ".yaml"}

# Конфиг-точки входа ВНЕ базы. Аналог внешней ссылки на объект: их обрыв
# ломает не документ, а среду. `PIT-126`: перенос папки оборвал `@`-импорт
# в `~/.claude/CLAUDE.md`, и регистр (`Claude`/`claude`) спрятал совпадение.
EXTERNAL = (
    Path.home() / ".claude" / "CLAUDE.md",
    Path.home() / ".claude" / "settings.json",
    Path.home() / ".zshrc",
    Path.home() / ".zprofile",
)


def is_indexable(path: Path) -> bool:
    """Входит ли файл в корпус. Одно условие на всех потребителей."""
    return (path.is_file()
            and path.suffix in TEXT_SUFFIXES
            and not any(s in path.parts for s in SKIP))


def build(base: Path) -> list[tuple[Path, str]]:
    """Корпус базы: (путь относительно базы, текст). Один обход диска.

    🔴 Обход стоит времени, поэтому строится ОДИН раз и передаётся дальше.
    `sync_base_local` уже платил за обратное: отпечаток пересчитывался
    на каждую из 54 реп — 0.12 с × 54 за прогон на одних и тех же файлах.
    """
    out = []
    for p in base.rglob("*"):
        if not is_indexable(p):
            continue
        try:
            out.append((p.relative_to(base), p.read_text(encoding="utf-8",
                                                         errors="replace")))
        except OSError:
            continue
    return out


def referrers(name: str, corpus: list[tuple[Path, str]],
              exclude: Path | None = None) -> list[Path]:
    """Кто упоминает это имя. `exclude` — сам артефакт, он себя не считает."""
    return [rel for rel, text in corpus
            if rel != exclude and name in text]


def external_referrers(name: str) -> list[Path]:
    """Кто ссылается на имя из конфигов ВНЕ базы.

    🔴 Сравнение регистронезависимое: ФС macOS регистр не различает, и
    `Claude` против `claude` однажды уже спрятал живую ссылку (`PIT-126`).
    """
    low = name.lower()
    out = []
    for cfg in EXTERNAL:
        try:
            if cfg.is_file() and low in cfg.read_text(encoding="utf-8",
                                                      errors="replace").lower():
                out.append(cfg)
        except OSError:
            continue
    return out


def unreferenced(candidates: list[Path], corpus: list[tuple[Path, str]]) -> list[Path]:
    """Из кандидатов — те, на кого не ссылается никто. Порядок сохраняется."""
    return [rel for rel in candidates if not referrers(rel.name, corpus, exclude=rel)]


def selftest() -> bool:
    """Различение, а не исполнение: упомянутый и неупомянутый не сливаются.

    Проверяются оба направления И самоупоминание: файл, называющий сам себя
    (а так делает почти каждый скрипт в шапке), обязан остаться сиротой,
    иначе сирот не будет никогда и проверка станет тождеством.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / "док.md").write_text("смотри живой.md подробнее", encoding="utf-8")
        (base / "живой.md").write_text("я упомянут", encoding="utf-8")
        (base / "сирота.md").write_text("сирота.md — я зову только себя",
                                        encoding="utf-8")
        (base / "_base").mkdir()
        (base / "_base" / "копия.md").write_text("сирота.md", encoding="utf-8")

        corpus = build(base)
        if any(rel.parts and rel.parts[0] == "_base" for rel, _ in corpus):
            return False                      # копия кита не входит в корпус
        found = unreferenced([Path("живой.md"), Path("сирота.md")], corpus)
        if found != [Path("сирота.md")]:
            return False                      # 🔴 самоупоминание не спасает
        if referrers("живой.md", corpus) != [Path("док.md")]:
            return False
        return True


if __name__ == "__main__":
    import sys
    ok = selftest()
    print("канарейка индекса ссылок: " + ("🟢 зелёная" if ok else "🔴 красная"))
    sys.exit(0 if ok else 1)
