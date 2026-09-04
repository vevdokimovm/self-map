#!/usr/bin/env python3
"""refcount.py — счётчик ссылок на артефакт: кто на него смотрит и достижим ли он.

🔴 ЗАКАЗ ВЛАДЕЛЬЦА 03.09.2026, дословно: *«раз мы начали давно с ООП в плюсах,
конструктор деструктор покрыли гейтами — какие ещё механизмы внести… типо там
есть всякий счетчик памяти»*.

Прямой аналог — **подсчёт ссылок** (`shared_ptr`, ARC, refcounting GC). Объект
живёт, пока на него кто-то ссылается; удалять объект с ненулевым счётчиком —
получить висячую ссылку, удалять недостижимый — незаметная утечка.

ДВА ВОПРОСА, ОДИН ИНДЕКС (`refs_index.py`):

    refcount.py <путь>      кто ссылается на этот артефакт — ПЕРЕД удалением,
                            переносом, переименованием
    refcount.py --orphans   что во всей базе недостижимо: ноль входящих ссылок

🔴 ПОВОД НЕ УМОЗРИТЕЛЬНЫЙ — ОБА ВОПРОСА УЖЕ ЗАДАВАЛИСЬ РУКАМИ 03.09.2026.
Приводя файлы мака к единому неймингу, вахта вручную грепала, кто ссылается
на переименовываемые пути, — и нашла два `@`-импорта в `~/.claude/CLAUDE.md`.
Не проверь она их, инструкции владельца перестали бы грузиться в каждой сессии.
Ручная проверка сработала, потому что вахта о ней вспомнила; в этом и дефект.

## Чем это НЕ является

**`--orphans` не список на удаление.** В программе недостижимый объект — мусор.
Здесь — документ, который **никто не найдёт**, и лечение обратное: не удалить,
а связать, дописав ссылку из навигатора. Ровно `PIT-176`: невидимое не станет
красным, оно перестанет существовать для того, кто ищет.

**Соседние инструменты и почему они остаются:**

| Инструмент | Вопрос | Отношение |
|---|---|---|
| `kit_weight.py` | что не нужно **раздавать** | тот же индекс, вопрос об экономии раздачи |
| `check_incoming_refs.py` | безопасен ли перенос **каталога** | абсолютные пути в конфигах, до операции |
| `check_dangling_registry_refs` | ссылка есть, объекта **нет** | обратное направление: висячая ссылка |

Здесь — «объект есть, ссылок нет» и «сколько ссылок у объекта».

🔴 ЧЕГО НЕ ЛОВИТ: ссылки по номеру («см. `71` §7ж» не содержит имени файла),
ложные совпадения частых имён (`README.md`), и смысл — упоминание не есть
польза. Полный разбор границ — в докстроке `refs_index.py`; здесь они
не пересказываются, чтобы не разойтись с ней.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import refs_index  # noqa: E402
from _roots import resolve_roots  # noqa: E402

BASE_REPO, REPOS, FROM_KIT = resolve_roots(__file__)

# Корни достижимости: точки входа, на которые ссылаться некому по построению.
# Аналог GC roots — глобальные объекты, живые вне зависимости от ссылок.
ROOTS = {"START-HERE.md", "README.md", "00-CLAUDE-STOP.md", "WATCHLOG.md",
         "CHANGELOG.md", "ROADMAP.md", "TASKS.md", "VERSION"}


def count_one(target: Path) -> int:
    """Кто ссылается на артефакт. Печатает разбор, возвращает код возврата."""
    if not target.exists():
        print(f"🔴 нет такого пути: {target}")
        return 2
    name = target.name
    corpus = refs_index.build(BASE_REPO)
    try:
        rel_self = target.resolve().relative_to(BASE_REPO)
    except ValueError:
        rel_self = None                      # артефакт вне базы — считаем все
    inside = refs_index.referrers(name, corpus, exclude=rel_self)
    outside = refs_index.external_referrers(name)

    print(f"артефакт: {name}")
    print(f"  ссылок внутри базы : {len(inside)}")
    for r in inside[:12]:
        print(f"     · {r}")
    if len(inside) > 12:
        print(f"     … и ещё {len(inside) - 12}")
    print(f"  ссылок из конфигов : {len(outside)}")
    for r in outside:
        print(f"     🔴 {r} — обрыв сломает СРЕДУ, а не документ (PIT-126)")

    total = len(inside) + len(outside)
    if total == 0:
        print("\n  счётчик 0 — удаление/перенос никого не обрывает.")
        print("  🔴 Но ноль означает и то, что артефакт НЕДОСТИЖИМ: его")
        print("     не найдут по ссылке. Если он нужен — связать, а не удалить.")
        return 0
    print(f"\n  🔴 счётчик {total} — удаление оставит висячие ссылки.")
    print("     Перед операцией: поправить ссылки, потом трогать артефакт.")
    return 1


def orphans() -> int:
    """Что недостижимо во всей базе. Корни исключены по построению."""
    corpus = refs_index.build(BASE_REPO)
    candidates = [rel for rel, _ in corpus if rel.name not in ROOTS]
    found = refs_index.unreferenced(candidates, corpus)

    print(f"файлов в корпусе базы: {len(corpus)} · корней: {len(ROOTS)}")
    print(f"🔴 недостижимо (ноль входящих ссылок): {len(found)}")
    by_dir: dict[str, list[Path]] = {}
    for rel in found:
        by_dir.setdefault(str(rel.parent), []).append(rel)
    for d in sorted(by_dir):
        print(f"\n  {d}/")
        for rel in sorted(by_dir[d]):
            print(f"     · {rel.name}")
    if found:
        print("\n  🔴 Это НЕ список на удаление. Недостижимый документ — тот,")
        print("     которого не найдут по ссылке (`PIT-176`). Лечение обычно")
        print("     обратное: дописать ссылку из навигатора или README раздела.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="счётчик ссылок на артефакт")
    ap.add_argument("target", nargs="?", help="путь к артефакту")
    ap.add_argument("--orphans", action="store_true",
                    help="показать всё недостижимое в базе")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        ok = refs_index.selftest()
        print("канарейка: " + ("🟢 зелёная" if ok else "🔴 красная"))
        return 0 if ok else 1
    if a.orphans:
        return orphans()
    if not a.target:
        ap.error("нужен путь к артефакту, или --orphans, или --selftest")
    return count_one(Path(a.target).expanduser())


if __name__ == "__main__":
    raise SystemExit(main())
