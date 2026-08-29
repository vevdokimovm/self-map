#!/usr/bin/env python3
"""load_weight.py — сколько контекста съедает набор документов, если его загрузить.

🔴 КАНДИДАТ №5 ОЧЕРЕДИ ВНЕДРЕНИЯ: «счётчик токенов загружаемого набора
с порогом» (`08-systems-theory-lab/INDUSTRY_VS_US.md`).

ЗАЧЕМ. Правило «прочитай документ перед работой» бесплатно на бумаге и стоит
контекста на деле. Пока вес не назван числом, любое обсуждение «грузить весь
кит или выборочно» — спор об ощущениях.

🔴 ЭТО ОЦЕНКА, А НЕ ЗАМЕР, И ЭТО ГЛАВНОЕ, ЧТО НАДО ЗНАТЬ.
Настоящий токенизатор моделью здесь недоступен, поэтому считается вилка
по двум коэффициентам, и оба названы:

  · **3.5 символа на токен** — нижняя граница. Ближе к латинице, коду,
    разметке, повторяющимся служебным словам;
  · **2.2 символа на токен** — верхняя. Кириллица токенизируется дороже
    латиницы: русское слово чаще режется на 2-3 куска, а не берётся целиком.

Настоящее число лежит **между** ними и ближе к верхней границе для текста
на русском. Вилка приводится целиком, потому что одно число создало бы
ложную точность — а именно ложная точность и опаснее отсутствия числа:
на неё опираются как на замер.

🔴 ЧЕГО НЕ УМЕЕТ (`71` §7г-бис):
  · не знает **настоящего** словаря токенизатора — вилка может промахнуться
    на нетипичном материале (таблицы, длинные ссылки, эмодзи);
  · не учитывает, что **часть набора уже в кэше** — повторная загрузка того
    же документа стоит иначе;
  · считает вес **набора**, а не хода: системный префикс, история и вывод
    инструментов сюда не входят.

ЗАПУСК
    load_weight.py                    вес китов base-repo
    load_weight.py --path 00-infrastructure   один каталог
    load_weight.py --top 15           самые тяжёлые файлы
    load_weight.py --selftest         канарейка
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402
BASE_REPO, REPOS, FROM_KIT = resolve_roots(__file__)

SKIP = {".git", "__pycache__", ".venv", "node_modules", "_base", ".pytest_cache"}
CHARS_PER_TOKEN_LOW = 2.2      # кириллица режется мелко — дороже
CHARS_PER_TOKEN_HIGH = 3.5     # латиница, код, разметка — дешевле
# Порог: окно в 200 тыс. токенов — типичное для длинного контекста.
# Набор, съедающий больше четверти окна, вытесняет саму работу.
WARN_TOKENS = 50_000


def weigh(root: Path) -> list[tuple[Path, int]]:
    """(путь, символов) по каждому документу набора."""
    out = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        if any(part in SKIP for part in rel.parts):
            continue
        try:
            out.append((rel, len(path.read_text(encoding="utf-8", errors="replace"))))
        except OSError:
            continue
    return out


def tokens(chars: int) -> tuple[int, int]:
    """Вилка токенов: (нижняя оценка, верхняя)."""
    return int(chars / CHARS_PER_TOKEN_HIGH), int(chars / CHARS_PER_TOKEN_LOW)


def selftest() -> bool:
    """Проверяется РАЗЛИЧЕНИЕ: вилка обязана быть вилкой, а не точкой.

    Нижняя оценка строго меньше верхней, обе растут с размером, и пустой
    вход не даёт деления на ноль.
    """
    lo1, hi1 = tokens(10_000)
    lo2, hi2 = tokens(20_000)
    return (lo1 < hi1 and lo2 < hi2 and lo1 < lo2 and hi1 < hi2
            and tokens(0) == (0, 0))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--path", help="каталог внутри репы вместо всей")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        ok = selftest()
        print("🟢 канарейка: вилка остаётся вилкой и растёт с размером"
              if ok else "🔴 канарейка: РАЗЛИЧЕНИЕ СЛОМАНО")
        return 0 if ok else 1

    root = BASE_REPO / a.path if a.path else BASE_REPO
    if not root.is_dir():
        print(f"🔴 нет каталога: {root}")
        return 1

    items = weigh(root)
    total = sum(c for _, c in items)
    lo, hi = tokens(total)

    print(f"═══ Вес набора · {root.name} ═══\n")
    print(f"  документов : {len(items)}")
    print(f"  символов   : {total:,}".replace(",", " "))
    print(f"  токенов    : **{lo:,} … {hi:,}**".replace(",", " "))
    print(f"  доля окна 200K : {lo * 100 // 200000} … {hi * 100 // 200000} %")

    if hi >= WARN_TOKENS:
        print(f"\n  🔴 верхняя оценка выше порога {WARN_TOKENS:,}".replace(",", " "))
        print("     Набор такого веса вытесняет саму работу из окна.")

    print(f"\n── Самые тяжёлые ({a.top}):")
    for rel, chars in sorted(items, key=lambda kv: -kv[1])[:a.top]:
        l, h = tokens(chars)
        print(f"  {l:>6} … {h:>6} ток.  {rel}")

    print("\n🔴 ЭТО ОЦЕНКА, А НЕ ЗАМЕР. Вилка от двух коэффициентов:")
    print(f"   {CHARS_PER_TOKEN_HIGH} симв./токен (латиница, код, разметка) —")
    print(f"   {CHARS_PER_TOKEN_LOW} симв./токен (кириллица режется мельче).")
    print("   Настоящее число между ними, ближе к верхней границе для русского.")
    print("   Одно число создало бы ложную точность — на неё опираются как")
    print("   на замер, и это опаснее отсутствия числа.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
