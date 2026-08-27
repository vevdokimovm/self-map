#!/usr/bin/env python3
"""import_dedup.py — снять дубли из `90-imported/` и растворить остаток по разделам.

ПОВОД. Кампания переноса 22.08.2026 клала материал в `<репа>/90-imported/` отдельным
разделом — правильно: перенесённое не проверено ревизией, и смешивать его с проверенным
нельзя (`21` §1). Но ревизия трёх реп подряд показала, что первый шаг разбора **всегда
один и тот же**, и он механический:

| Репа | импорт | дублировало уже лежащее |
|---|---|---|
| `health-vault` | 269 | **233** (87 %) |
| `family` | 40 | **25** (63 %) |

🔴 **Импорт по имени папки привозит и то, что в репе уже есть** (`PIT-124`). Пока дубли
не сняты, они читаются как состав репы и попадают в манифест — то есть врут о ней.

ЧТО ДЕЛАЕТ

  1. Считает sha256 всего, что лежит в репе **вне** `90-imported/` и `_base/`.
  2. Файл импорта, чей хеш уже есть, удаляет: это не потеря, а снятие копии.
  3. Остаток показывает поимённо — **раскладку по разделам скрипт не делает**.

🔴 ГРАНИЦА (`71` §7г-бис). Снять дубль — механика, разложить остаток — суждение:
куда пойдёт файл, зависит от предмета, а не от расширения. В `family` раскладка
по типам сработала (фото к фото), но это частный случай; общее правило —
`00-infrastructure/87-file-to-repo-routing.md`, и применяет его вахта.

ЗАПУСК
    import_dedup.py --repo family          показать, что дубль, а что нет
    import_dedup.py --repo family --apply  снять дубли
    import_dedup.py --all                  обзор по всем репам с импортом
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

BASE_REPO = Path(__file__).resolve().parent.parent
REPOS = BASE_REPO.parent
SKIP_NAMES = {".DS_Store", ".gitkeep"}

# 🔴 МУСОР, КОТОРЫЙ ПРИЕХАЛ С МАТЕРИАЛОМ. Word держит файл-замок `~$имя.docx` (162 байта,
# без содержания) пока документ открыт; при копировании папки он едет вместе с ним.
# За ревизию 23.08.2026 их набралось 41 по четырём репам.
JUNK_PREFIX = ("~$",)


def is_junk(p: Path) -> bool:
    return p.name in SKIP_NAMES or p.name.startswith(JUNK_PREFIX)


def audit(before: int, moved: int, junk: int, left: int) -> str:
    """Приёмка раскладки: одно множество с обеих сторон (`PIT-134`).

    🔴 Дефект, повторившийся дважды за один вечер: `before` считался БЕЗ `.DS_Store`,
    а `junk` его включал — баланс показывал «разницу» там, где потерь не было
    (`research-craft` дал −1, `legal-knowledge-base` дал +36).

    Пока формула считает разные множества, её результат приходится перепроверять
    вручную — то есть приёмки нет, есть её видимость.
    """
    # 🔴 Мусор — часть исходного множества: он БЫЛ в импорте и был удалён.
    # Первая редакция этой же функции считала `before - moved - left` и объявляла
    # расхождением ровно число удалённого мусора. То есть починка воспроизвела
    # тот самый дефект, который чинила: разные множества с двух сторон.
    diff = before - moved - junk - left
    if diff == 0:
        return f"было {before} · разложено {moved} · осталось {left} · мусора удалено {junk} · ✅ баланс сошёлся"
    return (f"было {before} · разложено {moved} · осталось {left} · мусора {junk} · "
            f"🔴 РАСХОЖДЕНИЕ {diff} — файлы не учтены, разобрать до продолжения")


def sha256(p: Path) -> str | None:
    h = hashlib.sha256()
    try:
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def own_hashes(repo: Path) -> set[str]:
    """Хеши того, что в репе УЖЕ есть — вне импорта и вне зеркала базы."""
    out = set()
    for p in repo.rglob("*"):
        if not p.is_file() or p.name in SKIP_NAMES:
            continue
        if "_base" in p.parts or "90-imported" in p.parts or ".git" in p.parts:
            continue
        h = sha256(p)
        if h:
            out.add(h)
    return out


def icloud_stubs(root: Path) -> tuple[int, int]:
    """Сколько файлов — заглушки iCloud (`st_blocks == 0`), то есть ещё не на диске.

    🔴 ЗАЧЕМ ПРОВЕРЯТЬ ДО РАБОТЫ. 23.08.2026 дедуп `misc-vault` прожил час и снял ноль
    файлов: `ps` показал 0.0 % CPU при 3.48 с процессорного времени — процесс не считал,
    а ждал сеть. Из 1 490 файлов импорта **451 оказались заглушками**, и хеширование
    каждой требует докачки.

    Заглушка неотличима от файла по `ls`, размеру и `stat().st_size` — только `st_blocks`
    говорит, лежит ли содержимое на диске (`PIT-120`).
    """
    total = stubs = 0
    for p in root.rglob("*"):
        if not p.is_file() or is_junk(p):
            continue
        total += 1
        try:
            if p.stat().st_blocks == 0:
                stubs += 1
        except OSError:
            pass
    return total, stubs


def process(repo: Path, apply: bool) -> tuple[int, int]:
    imp = repo / "90-imported"
    if not imp.is_dir():
        return 0, 0

    total, stubs = icloud_stubs(imp)
    if stubs:
        share = stubs / total * 100 if total else 0
        print(f"\n── {repo.name}: 🔴 {stubs} из {total} файлов ({share:.0f} %) — "
              f"заглушки iCloud, не на диске")
        print("      Хеширование потянет их из сети и встанет. Сначала материализовать:")
        print(f"      brctl download {imp}")
        print("      Проверить готовность: st_blocks > 0 у всех файлов.")
        if stubs > total * 0.1:
            print("      ⏭  ПРОПУСКАЮ репу — доля заглушек выше 10 %")
            return 0, 0
    own = own_hashes(repo)
    dupes, rest = [], []
    for p in imp.rglob("*"):
        if not p.is_file() or p.name in SKIP_NAMES:
            continue
        (dupes if sha256(p) in own else rest).append(p)

    print(f"\n── {repo.name}: импорт {len(dupes) + len(rest)} · "
          f"дублей {len(dupes)} · нового {len(rest)}")
    for p in rest[:12]:
        print(f"      новое: {p.relative_to(imp)}")
    if len(rest) > 12:
        print(f"      … и ещё {len(rest) - 12}")

    if apply and dupes:
        for p in dupes:
            p.unlink()
        # пустые каталоги за собой убрать, иначе останется скелет из папок
        for d in sorted(imp.rglob("*"), key=lambda x: -len(x.parts)):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        if imp.is_dir() and not any(imp.iterdir()):
            imp.rmdir()
            print("      ✓ `90-imported/` растворён полностью")
        print(f"      ✓ снято дублей: {len(dupes)}")
    return len(dupes), len(rest)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    targets = ([REPOS / a.repo] if a.repo
               else sorted(d for d in REPOS.iterdir() if d.is_dir()) if a.all else [])
    if not targets:
        ap.error("нужен --repo ИМЯ или --all")

    td = tr = 0
    for t in targets:
        if not t.is_dir() or not (t / "90-imported").is_dir():
            continue
        d, r = process(t, a.apply)
        td += d
        tr += r

    print(f"\n  дублей: {td} · остаётся к раскладке: {tr}")
    if not a.apply:
        print("  (сухой прогон; --apply чтобы снять дубли)")
    else:
        print("  Раскладку остатка делает вахта — `00-infrastructure/87-file-to-repo-routing.md`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
