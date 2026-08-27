#!/usr/bin/env python3
"""Фактическое покрытие раздачи базы по репам системы.

ЗАЧЕМ. Утверждение «база раздаётся в 57 реп» использовалось как основание для выводов
(«каждый дубль в базе едет во все 57», оценка стоимости правки базы). 22.08.2026 при
закрытии `master-admission` нашлась репа с НУЛЁМ совпадений и без каталога инфраструктуры
вовсе, следом ещё три. Значит покрытие — величина, которую надо измерить, а не предположить.

ЧТО СЧИТАЕТ. Для каждой репы:
  · есть ли каталог `00-infrastructure/` (или `_base/`) и сколько в нём файлов;
  · сколько файлов репы совпадают с файлами базы БАЙТ-В-БАЙТ (sha256);
  · сколько документов базы `NN-*.md` присутствуют по имени (пусть и другой редакции).

Три разных числа намеренно: побайтовое совпадение говорит «раздача свежая»,
совпадение по имени — «раздача была когда-то», отсутствие каталога — «не было никогда».

Запуск:  python3 scripts/base_coverage.py [--csv]
"""

import hashlib
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE.parent
SKIP = {"base-repo", "Добавить ", "Old (before Claude)"}


def sha(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def files(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            yield p


def main() -> None:
    base_files = list(files(BASE))
    base_hashes = {sha(p) for p in base_files}
    base_docnames = {p.name for p in base_files
                     if p.suffix == ".md" and p.parent.name == "00-infrastructure"}

    rows = []
    for d in sorted(ROOT.iterdir()):
        if not d.is_dir() or d.name in SKIP:
            continue
        try:
            repo_files = list(files(d))
        except OSError:
            continue
        if not repo_files:
            continue

        infra = d / "00-infrastructure"
        nested = d / "_base"
        infra_n = sum(1 for _ in files(infra)) if infra.is_dir() else 0
        nested_n = sum(1 for _ in files(nested)) if nested.is_dir() else 0

        exact = sum(1 for p in repo_files if sha(p) in base_hashes)
        byname = len({p.name for p in repo_files} & base_docnames)

        if infra_n == 0 and nested_n == 0 and exact == 0:
            status = "НЕТ"
        elif exact >= 40:
            status = "полная"
        elif exact > 0:
            status = "частичная"
        else:
            status = "только каталог"

        rows.append((d.name, len(repo_files), infra_n, nested_n, exact, byname, status))

    if "--csv" in sys.argv:
        print("repo,files,infra_files,nested_base,exact_match,by_name,status")
        for r in rows:
            print(",".join(str(x) for x in r))
        return

    print(f"БАЗА: {len(base_files)} файлов · документов 00-infrastructure/*.md: {len(base_docnames)}")
    print(f"РЕП В СИСТЕМЕ: {len(rows)}\n")
    print(f"{'репа':<26}{'файлов':>8}{'infra':>7}{'_base':>7}{'байт-в-байт':>13}{'по имени':>10}  статус")
    print("-" * 86)
    for name, n, infra_n, nested_n, exact, byname, status in rows:
        print(f"{name:<26}{n:>8}{infra_n:>7}{nested_n:>7}{exact:>13}{byname:>10}  {status}")

    print("\n--- СВОДКА ---")
    tally = {}
    for *_, status in rows:
        tally[status] = tally.get(status, 0) + 1
    for k in ("полная", "частичная", "только каталог", "НЕТ"):
        if k in tally:
            print(f"  {tally[k]:>3}  {k}")
    covered = sum(v for k, v in tally.items() if k != "НЕТ")
    print(f"\n  ПОКРЫТО ХОТЬ КАК-ТО: {covered} из {len(rows)}")
    print(f"  БЕЗ РАЗДАЧИ ВООБЩЕ:  {tally.get('НЕТ', 0)} из {len(rows)}")


# =========================================================================== #
# РЕЖИМ --adr004: четыре правила модели раздачи базы
# =========================================================================== #
def check_adr004() -> int:
    """Проверка правил `reports/adr/adr_004_base_distribution_model.md` §5.

    🔴 ЗАЧЕМ ЗДЕСЬ, А НЕ ОТДЕЛЬНЫМ СКРИПТОМ. ADR-004 §5 правило 4 прямо говорит:
    «`base_coverage.py` уже считает покрытие тремя числами — сделать его ГЕЙТОМ
    деплоя, а не отчётом по требованию». Заводить рядом второй измеритель значило бы
    повторить историю восьми скриптов деплоя (`templates/README.md`): каждый раз
    кажется проще написать новый, чем разобраться в старом.

    ЧТО ПРОВЕРЯЕТСЯ:

    · Правило 1 — на зеркале `_base/` стоит штамп `BASE_VERSION`, и он не отстал.
      Без штампа v1.36.0 прожила рядом с v2.42.0 незамеченной.
    · Правило 2 — в СОБСТВЕННОЙ `00-infrastructure/` репы нет копий канона.
      Две проверки, потому что одной мало: хеш ловит точную копию, ИМЯ — отставшую
      редакцию. В `misc-vault` из 109 файлов 77 ловились хешем, а 32 — только именем,
      и именно они опаснее: выглядят авторской правкой, а являются устаревшим каноном.
    · Правило 3 — шапка локальной инфраструктуры объявляет приоритет строкой.
    """
    base_ver = (BASE / "VERSION").read_text(encoding="utf-8").strip()
    binf = BASE / "00-infrastructure"
    canon = {p.name: sha(p) for p in binf.rglob("*") if p.is_file()}

    stale_stamp, no_stamp, rule2, rule3 = [], [], [], []

    for d in sorted(ROOT.iterdir()):
        if not d.is_dir() or d.name in SKIP:
            continue

        # --- Правило 1: штамп версии на зеркале
        mirror = d / "_base"
        if mirror.is_dir():
            stamp = mirror / "BASE_VERSION"
            if not stamp.is_file():
                no_stamp.append(d.name)
            else:
                v = stamp.read_text(encoding="utf-8").strip()
                # 🔴 Порог, а не равенство — `ADR-004` §5 правило 1 так и предписывал.
                # Строгое сравнение делало метрику вечно красной: база проходит
                # по несколько минорных версий за сессию, и все зеркала становились
                # «отставшими» после каждого батча (измерено 22.08.2026).
                try:
                    mv = [int(x) for x in v.split(".")[:2]]
                    cv = [int(x) for x in base_ver.split(".")[:2]]
                    lag = 999 if mv[0] != cv[0] else cv[1] - mv[1]
                except ValueError:
                    lag = 999
                if lag > 5:
                    stale_stamp.append((d.name, f"{v} (−{lag})"))

        # --- Правило 2: копии канона в своей инфраструктуре
        own = d / "00-infrastructure"
        if own.is_dir():
            exact = stale = 0
            for f in own.rglob("*"):
                if not f.is_file() or ".git" in f.parts:
                    continue
                # Только документы канона вида `NN-*`: README есть у всех и совпадение
                # его имени ни о чём не говорит (ложное срабатывание, проверено 22.08).
                if f.name in canon and f.name[:2].isdigit():
                    if sha(f) == canon[f.name]:
                        exact += 1
                    else:
                        stale += 1
            if exact or stale:
                rule2.append((d.name, exact, stale))

            # --- Правило 3: приоритет объявлен строкой
            readme = own / "README.md"
            declared = False
            if readme.is_file():
                head = readme.read_text(encoding="utf-8", errors="replace")[:1500].lower()
                declared = "_base" in head and ("источник" in head or "отлич" in head)
            if not declared:
                rule3.append(d.name)

    print(f"── ADR-004: модель раздачи базы · канон v{base_ver}\n")
    print(f"ПРАВИЛО 1 — штамп версии на зеркале")
    print(f"  зеркал без BASE_VERSION:        {len(no_stamp):>4}"
          + (f"  ({', '.join(no_stamp[:5])})" if no_stamp else ""))
    print(f"  зеркал с отставшим штампом:     {len(stale_stamp):>4}")
    if stale_stamp:
        from collections import Counter
        for v, n in Counter(v for _, v in stale_stamp).most_common():
            print(f"      v{v:<10} {n} реп")

    print(f"\nПРАВИЛО 2 — копии канона в СОБСТВЕННОЙ инфраструктуре репы")
    print(f"  реп с нарушением:               {len(rule2):>4}")
    te = sum(e for _, e, _ in rule2)
    ts = sum(s for _, _, s in rule2)
    print(f"  точных копий (ловит хеш):       {te:>4}")
    print(f"  отставших редакций (ловит имя): {ts:>4}   ← опаснее")
    for name, e, s in sorted(rule2, key=lambda r: -(r[1] + r[2]))[:12]:
        print(f"      {name:<26} копий {e:>3} · отстало {s:>3}")

    print(f"\nПРАВИЛО 3 — приоритет объявлен строкой в шапке")
    print(f"  реп без объявления:             {len(rule3):>4}"
          + (f"  ({', '.join(rule3[:5])}…)" if rule3 else ""))

    problems = len(no_stamp) + len(stale_stamp) + len(rule2) + len(rule3)
    print(f"\n  ИТОГ: {'CLEAN' if not problems else f'DRIFT — {problems} расхождений'}")
    return 1 if problems else 0


if __name__ == "__main__":
    if "--adr004" in sys.argv:
        raise SystemExit(check_adr004())
    main()
