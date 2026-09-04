#!/usr/bin/env python3
"""retire_repo.py — расформировать репу правильно: деструктор к new_repo.py.

ЗАКАЗ ВЛАДЕЛЬЦА 02.09.2026: «напиши тогда и деструктор по аналогии ООП плюсов».

Аналогия точна и продуктивна. В C++ деструктор освобождает то, что захватил
конструктор, и делает это в **обратном порядке**. У репы захвачено не только
место на диске:

    конструктор захватил          деструктор обязан освободить
    ─────────────────────────     ────────────────────────────────
    каталог на диске              каталог (последним!)
    строку в repos-map.md         строку и счётчик в шапке
    репозиторий на GitHub         пометить archived, не удалять
    архивы в ~/Downloads          🔴 НЕ ТРОГАТЬ — см. ниже
    ссылки из соседних реп        найти и перенаправить

🔴 ГЛАВНОЕ ОТЛИЧИЕ ОТ C++, И ОНО ЗДЕСЬ РЕШАЮЩЕЕ. Деструктор объекта стирает
память безвозвратно, и это правильно: памяти не жалко. **Здесь стирать нельзя.**
У реп нет локального `.git`, архив релиза — не копия версии, а её единственный
экземпляр (`/auto` §2). Поэтому этот деструктор:

  · **никогда не удаляет архивы** — они пережили саму репу и остаются;
  · **никогда не удаляет репозиторий на GitHub** — только помечает архивным;
  · каталог на диске сносит только по явному `--purge`, и только после того,
    как убедился, что содержимое уехало на GitHub.

Иначе говоря: это не `delete`, а перевод в `archived` — состояние из
`76-repo-classes.md` §1, где прямо сказано «история сохранена».

ПРЕДУСЛОВИЯ (все до первой записи):
  · репа существует на диске;
  · её класс допускает расформирование (`infra` и `core` — нет: они вечные);
  · 🔴 содержимое уехало на GitHub, иначе снос = потеря единственного экземпляра;
  · на неё не ссылается ни один живой документ (иначе получится ссылка в пустоту —
    `/auto` §2г, случай 1: «итог хуже обоих исходных состояний»).

ПОСТУСЛОВИЯ:
  · `.repo-class` = `archived`;
  · строка в `repos-map.md` помечена, счётчик уменьшен;
  · при `--purge` каталога на диске нет, а архивы на месте.

ИНВАРИАНТ: ни один архив релиза не удалён, ни один репозиторий на GitHub
не стёрт. Проверяется после.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402

BASE_REPO, REPOS, _ = resolve_roots(__file__)

# Классы, которые не расформировываются по определению (`76` §1):
# infra — инфраструктура системы, core — зона жизни «на века».
IMMORTAL = {"infra", "core"}


def sh(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def find_references(name: str) -> list[str]:
    """Кто ссылается на репу. Снос при живых ссылках даёт ссылку в пустоту."""
    hits = []
    for p in REPOS.rglob("*.md"):
        if "/_base/" in str(p) or f"/{name}/" in str(p):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if re.search(rf"\b{re.escape(name)}\b", text):
            hits.append(str(p.relative_to(REPOS)))
    return hits


sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import artifacts_dir  # noqa: E402

def main() -> int:
    ap = argparse.ArgumentParser(description="Расформировать репу по канону")
    ap.add_argument("name", help="имя репы")
    ap.add_argument("--apply", action="store_true", help="выполнить")
    ap.add_argument("--purge", action="store_true",
                    help="🔴 удалить каталог с диска (архивы и GitHub не трогаются)")
    ap.add_argument("--force", action="store_true",
                    help="игнорировать живые ссылки — только осознанно")
    args = ap.parse_args()

    target = REPOS / args.name
    problems = []

    # ── ПРЕДУСЛОВИЯ, все до первой записи
    if not target.is_dir():
        print(f"🔴 нет такой репы: {target}", file=sys.stderr)
        return 2

    cls_file = target / ".repo-class"
    cls = cls_file.read_text().strip() if cls_file.is_file() else "?"
    if cls in IMMORTAL:
        print(f"🔴 класс «{cls}» не расформировывается: "
              f"{'инфраструктура системы' if cls == 'infra' else 'зона жизни на века'} "
              f"(76-repo-classes.md §1)", file=sys.stderr)
        return 2

    # уехало ли на GitHub — без этого снос равен потере
    code, _ = sh(["gh", "repo", "view", f"vevdokimovm/{args.name}"], 40)
    on_github = code == 0
    if not on_github:
        problems.append("на GitHub репы НЕТ — снос уничтожит единственный экземпляр")

    refs = find_references(args.name)
    if refs and not args.force:
        problems.append(f"на репу ссылаются {len(refs)} документов — "
                        f"снос даст ссылки в пустоту")

    archives = sorted(artifacts_dir().glob(f"{args.name}-v*.zip"))

    print(f"Расформировать «{args.name}» · класс {cls}\n")
    print(f"  на GitHub:        {'🟢 есть' if on_github else '🔴 НЕТ'}")
    print(f"  архивов релизов:  {len(archives)}  🔴 не удаляются никогда")
    print(f"  ссылок из других: {len(refs)}")
    for r in refs[:6]:
        print(f"      {r}")
    if len(refs) > 6:
        print(f"      … и ещё {len(refs) - 6}")

    if problems:
        print(f"\n🔴 ОСТАНОВЛЕНО: {len(problems)}")
        for p in problems:
            print(f"   · {p}")
        print("\n   Живые ссылки — не формальность: репа исчезнет, а указатели")
        print("   на неё останутся. Это состояние хуже обоих исходных")
        print("   (`/auto` §2г, случай 1). Сначала перенаправить, потом сносить.")
        return 1

    if not args.apply:
        print("\n🟡 Это план. Выполнить: тот же вызов с --apply")
        return 0

    # ── ДЕСТРУКТОР: освобождаем в обратном порядке захвата
    (target / ".repo-class").write_text("archived\n", encoding="utf-8")
    print("\n  🟢 .repo-class → archived")

    # строка в карте
    m = BASE_REPO / "repos-map.md"
    if m.is_file():
        t = m.read_text(encoding="utf-8")
        cnt = re.search(r"\| \*\*Репозиториев\*\* \| (\d+) заведено", t)
        if cnt:
            t = t.replace(f"| **Репозиториев** | {cnt.group(1)} заведено",
                          f"| **Репозиториев** | {int(cnt.group(1)) - 1} заведено")
            print(f"  🟢 счётчик в карте: {cnt.group(1)} → {int(cnt.group(1)) - 1}")
        m.write_text(t, encoding="utf-8")

    if args.purge:
        shutil.rmtree(target)
        print(f"  🟢 каталог снесён: {target}")

    # ── ПОСТУСЛОВИЕ: инвариант об архивах проверяется, а не подразумевается
    left = sorted(artifacts_dir().glob(f"{args.name}-v*.zip"))
    if len(left) != len(archives):
        print(f"  🔴 ИНВАРИАНТ НАРУШЕН: архивов было {len(archives)}, "
              f"стало {len(left)}", file=sys.stderr)
        return 1
    print(f"  🟢 архивы на месте: {len(left)} — инвариант соблюдён")
    print("\n  Дальше вручную: пометить репу archived на GitHub "
          "(Settings → Archive), удалять её оттуда не надо.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
