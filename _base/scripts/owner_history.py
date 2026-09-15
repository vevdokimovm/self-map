#!/usr/bin/env python3
"""owner_history.py — пробовал ли владелец это раньше? Ищет в его записях.

🔴 ПОВОД, 04.09.2026. Владелец заказал приложение «EPUB и PDF в аудиокнигу».
Перед разбором рынка сделан дешёвый шаг — поиск темы в его собственных
дневниках. Нашлось: **аудиокниги он уже слушал и бросил**, и причину назвал
сам — «пересказать я нихуя особо не смогу».

Приложение, которое просто озвучивает EPUB, воспроизвело бы тот же исход.
Находка изменила предмет репы **до написания первой строки кода**.

ЧЕМ ЭТО ОТЛИЧАЕТСЯ ОТ ДРУГИХ ПРОВЕРОК — три разных корпуса:

    /auto §1.3   «не решено ли уже»   → база, реестры    → делала ли СИСТЕМА
    /options     «мы это пробовали?»  → реестр ловушек   → эти ли ГРАБЛИ
    этот скрипт  «пробовал ли он»     → self-map и др.   → делал ли ВЛАДЕЛЕЦ

🔴 ГРАНИЦА, НАЗВАННАЯ ВСЛУХ. Скрипт находит **упоминания**, а не выводы.
«Бросил аудиокниги» может значить три разных вещи, и какая верна — знает
только владелец. Найденное идёт в `TASKS.md` вопросом, а не в решение.

ГДЕ ИЩЕТ. Репы, куда владелец пишет о себе: `self-map` (дневник, разборы),
`edu-base`, `health-vault`, `christ-walk`, `character-a-analysis`.
🔴 Список — по свойству «здесь владелец пишет О СЕБЕ», а не по алфавиту.

ЗАПУСК:
    python3 scripts/owner_history.py аудиокниг
    python3 scripts/owner_history.py "аудиокниг|audiobook|tts" --context 2
    python3 scripts/owner_history.py --selftest
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402

# Репы, где владелец пишет о себе. Свойство, а не алфавит.
PERSONAL = ("self-map", "edu-base", "health-vault", "christ-walk",
            "character-a-analysis", "portrait-of-taste", "misc-vault")
SKIP_PARTS = ("_base", ".git", "__pycache__", "node_modules", ".venv")
# Журналы системы — не записи владельца о себе.
SKIP_NAMES = ("CHANGELOG", "WATCHLOG", "ROADMAP", "TASKS", "MANIFEST",
              "PITFALLS", "pitfalls")


def search(root: Path, pattern: str, context: int) -> list[tuple[str, int, str]]:
    rx = re.compile(pattern, re.I)
    hits: list[tuple[str, int, str]] = []
    for name in PERSONAL:
        repo = root / name
        if not repo.is_dir():
            continue
        for f in sorted(repo.rglob("*.md")):
            rel = f.relative_to(root)
            if any(p in rel.parts for p in SKIP_PARTS):
                continue
            if any(n in f.name for n in SKIP_NAMES):
                continue
            try:
                lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines):
                if not rx.search(line):
                    continue
                lo, hi = max(0, i - context), min(len(lines), i + context + 1)
                chunk = " ".join(l.strip() for l in lines[lo:hi] if l.strip())
                hits.append((rel.as_posix(), i + 1, chunk))
    return hits


def selftest() -> int:
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        sm = root / "self-map" / "notes"
        sm.mkdir(parents=True)
        (sm / "diary.md").write_text(
            "обычная строка\nслушал аудиокниги и бросил\nещё строка\n",
            encoding="utf-8")
        # Журнал системы — не должен попадать в выдачу
        (root / "self-map" / "CHANGELOG.md").write_text(
            "аудиокниги упомянуты тут\n", encoding="utf-8")
        # Репа не из личных — тоже не должна
        other = root / "it-base"
        other.mkdir()
        (other / "x.md").write_text("аудиокниги\n", encoding="utf-8")

        hits = search(root, "аудиокниг", 0)
        found_diary = any("diary.md" in h[0] for h in hits)
        no_chlog = not any("CHANGELOG" in h[0] for h in hits)
        no_other = not any("it-base" in h[0] for h in hits)
        for name, good in (("находит в дневнике", found_diary),
                           ("пропускает CHANGELOG", no_chlog),
                           ("не лезет в неличные репы", no_other)):
            print(f"   {'✅' if good else '🔴'} {name}")
            ok &= good
        # Контекст: соседние строки склеиваются
        wide = search(root, "аудиокниг", 1)
        has_ctx = any("обычная строка" in h[2] for h in wide)
        print(f"   {'✅' if has_ctx else '🔴'} --context берёт соседние строки")
        ok &= has_ctx
    print("selftest OK" if ok else "🔴 selftest ПРОВАЛЕН")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pattern", nargs="?", help="слово или регулярка темы")
    ap.add_argument("--context", type=int, default=1,
                    help="сколько строк вокруг показывать (по умолчанию 1)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if not a.pattern:
        ap.error("нужен pattern (или --selftest)")

    _base, root, _ = resolve_roots(__file__)
    hits = search(root, a.pattern, a.context)

    if not hits:
        print(f"🟡 «{a.pattern}» в записях владельца не встречается.")
        print("   Это НЕ значит «не пробовал» — значит «не записал».")
        print("   Искали в: " + ", ".join(PERSONAL))
        return 0

    print(f"🔴 Найдено упоминаний: {len(hits)} — владелец об этом уже писал\n")
    for rel, ln, chunk in hits[:20]:
        print(f"  {rel}:{ln}")
        print(f"     {chunk[:200]}\n")
    if len(hits) > 20:
        print(f"  … и ещё {len(hits) - 20}")
    print("🔴 Найденное — МАТЕРИАЛ ДЛЯ ВОПРОСА, а не готовый вывод.")
    print("   Что это значило, знает только владелец: спросить в TASKS.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
