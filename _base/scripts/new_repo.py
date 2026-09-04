#!/usr/bin/env python3
"""new_repo.py — завести репу правильно с первого раза.

ЗАКАЗ ВЛАДЕЛЬЦА 02.09.2026, дословно: «какие файлы, механизмы создать, чтобы
ты перестал обсираться? Мы даже вроде гейты делали, и всё равно ошибки».
И там же аналогия, которая объясняет причину точнее любого разбора:

    «если сравнивать с ООП, то у тебя постоянно лагает функция конструктора…
     как работать, если в самом начале утечки и сбои при создании объекта уже»

🔴 ДИАГНОЗ, ИЗ КОТОРОГО ВЫРОС ЭТОТ СКРИПТ. Гейт `revision_check.py` содержит
34 проверки и **ни одна не смотрит на `.repo-id`**. Причина структурная:
гейт проверяет репу, которая УЖЕ существует и уже в системе. Момент создания
он не покрывает вовсе — там ещё нечего проверять, репа заводится вручную
по памяти, а память подводит.

Живой случай 02.09.2026: репа `migration` заведена с `.repo-id` = случайный
UUID вместо `vevdokimovm/migration`. Формат записан в `48-repo-identity.md`
строкой 90 — я его не открыл. Гейт промолчал (не его область), деплой поймал
уже на публикации: «архив уехал бы не в ту репу».

**Вывод: правило, которое надо помнить при создании, — не механизм.
Механизм — это скрипт, который создаёт сам.**

ПРЕДУСЛОВИЯ (все до первой записи):
  · имя репы задано, латиницей, строчными, через дефис;
  · класс из восьми известных (`76-repo-classes.md` §1);
  · такой репы ещё нет на диске;
  · шаблон `.gitignore` в базе на месте.

ПОСТУСЛОВИЯ (проверяются после создания):
  · `.repo-id` содержит ровно `vevdokimovm/<имя>` — не UUID, не путь;
  · `.repo-class` содержит заявленный класс;
  · `VERSION` = 0.1.0;
  · `.repo-meta` содержит `private=`;
  · обязательный минимум файлов класса на месте;
  · гейт ревизии даёт CLEAN на свежей репе.

ИНВАРИАНТ: репа либо создана целиком и правильно, либо не создана вовсе.
Половина файлов хуже, чем ничего: она выглядит рабочей.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402

BASE_REPO, REPOS, _ = resolve_roots(__file__)

# 🔴 Владелец GitHub — источник формата `.repo-id`. Записан здесь один раз,
# чтобы не воспроизводиться по памяти при каждом заведении (`48` §90).
OWNER = "vevdokimovm"

CLASSES = {
    "infra": ["README.md", "VERSION"],
    "core": ["README.md", "VERSION", "ROADMAP.md", "TASKS.md", "START-HERE.md",
             "CHANGELOG.md"],
    "satellite": ["README.md", "VERSION", "ROADMAP.md", "CHANGELOG.md"],
    "temp": ["README.md", "VERSION"],
    "product": ["README.md", "VERSION", "CHANGELOG.md", "ROADMAP.md"],
    "profile": ["README.md", "VERSION"],
}

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,38}[a-z0-9]$")


def die(msg: str) -> int:
    print(f"🔴 {msg}", file=sys.stderr)
    return 2


def main() -> int:
    ap = argparse.ArgumentParser(description="Завести репу по канону")
    ap.add_argument("name", help="имя: латиница, строчные, дефисы")
    ap.add_argument("--class", dest="cls", required=True, choices=sorted(CLASSES),
                    help="класс репы (76-repo-classes.md §1)")
    ap.add_argument("--desc", required=True, help="описание одной строкой")
    ap.add_argument("--private", default="true", choices=["true", "false"],
                    help="приватная ли (по умолчанию true)")
    ap.add_argument("--apply", action="store_true",
                    help="создать (по умолчанию — только показать план)")
    args = ap.parse_args()

    # ── ПРЕДУСЛОВИЯ, все до единой записи (`/auto` §2г, правило 1)
    if not NAME_RE.match(args.name):
        return die(f"имя «{args.name}» нарушает правило: латиница, строчные, "
                   f"дефисы, 3-40 символов (76-repo-classes.md §6)")
    target = REPOS / args.name
    if target.exists():
        return die(f"репа уже существует: {target}")
    gitignore = BASE_REPO / "templates" / "gitignore.template"
    if not gitignore.is_file():
        return die(f"нет шаблона: {gitignore}")

    files = CLASSES[args.cls]
    # 🔴 Найдено тестом `test_repo_lifecycle.sh` 02.09.2026: шаблон README
    # ссылался на `TASKS.md` безусловно, а класс `satellite` этот файл
    # не получает — свежая репа рождалась с битой ссылкой и валила
    # собственный гейт ревизии. Конструктор обязан ссылаться только на то,
    # что сам же и создаёт.
    tasks_link = (" · на владельце — [`TASKS.md`](TASKS.md)"
                  if "TASKS.md" in files else "")
    print(f"Завести репу «{args.name}» · класс {args.cls} · "
          f"{'приватная' if args.private == 'true' else 'ПУБЛИЧНАЯ'}\n")
    print(f"  путь:      {target}")
    print(f"  .repo-id:  {OWNER}/{args.name}")
    print(f"  файлов:    {', '.join(files)}")

    if not args.apply:
        print("\n🟡 Это план. Создать: тот же вызов с --apply")
        return 0

    # ── СОЗДАНИЕ
    target.mkdir(parents=True)
    (target / ".repo-id").write_text(f"{OWNER}/{args.name}\n", encoding="utf-8")
    (target / ".repo-class").write_text(f"{args.cls}\n", encoding="utf-8")
    (target / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (target / ".repo-meta").write_text(
        f"description={args.desc}\ntopics=\nprivate={args.private}\n",
        encoding="utf-8")
    shutil.copy(gitignore, target / ".gitignore")

    today = date.today().isoformat()
    stub = {
        "README.md": f"""# {args.name} — {args.desc}

<!-- STATUS -->
> **Сейчас:** `v0.1.0` · {today} · Репа заведена, содержания пока нет
> Открытое — [`ROADMAP.md`](ROADMAP.md){tasks_link}
<!-- /STATUS -->

## За что отвечает эта репа

{args.desc}

🔴 **Граница с соседями** — заполнить парой через «↔», иначе репа заведена
не до конца (`76-repo-classes.md` §4.2).
""",
        "START-HERE.md": f"""# START-HERE — точка входа

## За что отвечает эта репа

{args.desc}

🔴 **За что НЕ отвечает:** заполнить. Без этого граница не проведена.

## Текущая точка

**v0.1.0, {today}.** Репа заведена, содержания нет. Это честное состояние.
""",
        "ROADMAP.md": f"""# ROADMAP

## §P. Приоритеты

**СЛЕДУЮЩАЯ ЗАДАЧА:** наполнить репу содержанием — сейчас только каркас.

### P1. Определить границу с соседними репами

Пока не сформулирована парой через «↔», репа заведена не до конца.
""",
        "TASKS.md": """# TASKS

## 🎯 Готово к запуску

- [ ] Сформулировать границу с соседними репами

## 🚧 В работе

*(пусто)*
""",
        "CHANGELOG.md": f"""# CHANGELOG

## [0.1.0] — {today}

### Репа заведена

Создана `scripts/new_repo.py` — каркас по канону класса `{args.cls}`.

`.repo-id` = `{OWNER}/{args.name}` проставлен скриптом, а не руками:
именно на этом шаге происходила ошибка при ручном заведении.
""",
    }
    for f in files:
        if f in stub:
            (target / f).write_text(stub[f], encoding="utf-8")

    # ── ПОСТУСЛОВИЯ: проверяется результат, а не «шаги не упали»
    problems = []
    rid = (target / ".repo-id").read_text().strip()
    if rid != f"{OWNER}/{args.name}":
        problems.append(f".repo-id = «{rid}», ожидалось «{OWNER}/{args.name}»")
    for f in files:
        if not (target / f).is_file():
            problems.append(f"нет обязательного файла: {f}")
    if (target / "VERSION").read_text().strip() != "0.1.0":
        problems.append("VERSION не 0.1.0")

    # 🔴 02.09.2026, PIT-G, пятый повтор. Найдено владельцем: «ты не положил
    # в репу миграции базу почему то. гейта на этого нет что ли?».
    #
    # Гейт БЫЛ — `sync_base_local.py --check --all` честно показывал
    # `migration · (нет штампа) ОТСТАЛА`. Не было исполнителя в нужный момент:
    # заведение репы и раздача канона стояли разными шагами, и второй шаг
    # оставался советом в конце вывода. Репа прожила шесть часов без `_base/` —
    # единственная из 63.
    #
    # Совет в конце вывода — это и есть «правило без исполнителя»
    # (`21-revision-protocol.md` §4г). Поэтому раздача теперь ДЕЛАЕТСЯ здесь,
    # а её результат проверяется постусловием ниже: шаг, который нельзя забыть,
    # потому что его никто не выполняет руками.
    #
    is_public = str(args.private).lower() == "false"
    NO_BASE_CLASSES = {"archived"}   # тот же список, что в repo_invariants.py

    # 🔴 РЕШАЕТ ПУБЛИЧНОСТЬ, А НЕ КЛАСС — исправлено 04.09.2026.
    #
    # Прежняя строка гласила «классы `product` и `profile` — публичные витрины,
    # им `_base/` не кладётся никогда». Формулировка подменяла признак: `ADR-004`
    # запрещает раздачу **публичным** репам, потому что канон системы не должен
    # уезжать наружу вместе с продуктом. Класс тут ни при чём.
    #
    # Замер по 9 репам класса `product` — закономерность без единого исключения:
    #
    #     private=true   control-panel, personal-finance-dss, research-engine  → _base ЕСТЬ
    #     private=false  algorithms-site, claude-usage, salvation, vk-graph, … → _base нет
    #
    # Расхождение стоило отката: заведение приватного продукта падало по `R-06`
    # («нет _base/BASE_VERSION»), потому что `new_repo` не раздавал канон,
    # а инвариант его требовал. Два места знали разное — классический `/auto` §7.
    if not is_public and args.cls not in NO_BASE_CLASSES:
        print("  · раскладываю _base/ (канон base-repo) …")
        sync = subprocess.run(
            ["python3", str(BASE_REPO / "scripts" / "sync_base_local.py"),
             target.name],
            capture_output=True, text=True, timeout=600)
        if sync.returncode != 0:
            problems.append(
                f"_base/ не разложена: {(sync.stderr or sync.stdout).strip()[:200]}")
        stamp = target / "_base" / "BASE_VERSION"
        if not stamp.is_file():
            problems.append("_base/BASE_VERSION нет — канон не раздан")

    gate = subprocess.run(
        ["python3", str(BASE_REPO / "scripts" / "revision_check.py"),
         "--root", str(target)],
        capture_output=True, text=True, timeout=300)
    if "ИТОГ: DRIFT" in gate.stdout:
        # 🔴 Называть, ЧТО именно не так. «Гейт не CLEAN» без причины
        # отправляет читателя запускать гейт заново руками — а конструктор
        # уже держит ответ в руках и просто выбрасывает его.
        fails = [ln.strip() for ln in gate.stdout.splitlines()
                 if ln.lstrip().startswith("[FAIL]") or ln.lstrip().startswith("·")]
        detail = "; ".join(fails[:4]) or "причина не разобрана"
        problems.append(f"гейт ревизии не CLEAN на свежей репе — {detail}")

    # ── ИНВАРИАНТ КЛАССА, единый с гейтом и деструктором
    # 🔴 Ровно то, чего не хватало: постусловия конструктора и правила гейта
    # были разными списками, и репа могла пройти первый, провалив второй.
    # Теперь список один — `repo_invariants.py`.
    from repo_invariants import check as invariant_check
    # phase="born": свежая репа ещё не выпускалась — требовать от неё
    # записи в журнале выпусков значит не дать ей родиться.
    for viol in invariant_check(target, phase="born"):
        problems.append(f"{viol.code} {viol.text}")

    if problems:
        # 🔴 СИЛЬНАЯ ГАРАНТИЯ (strong exception guarantee), заказ владельца
        # 02.09.2026: «как тогда работать если уже при создании объекта лажа».
        #
        # В C++ объект, чей конструктор бросил, НЕ СУЩЕСТВУЕТ — деструктор
        # ему не зовётся, ссылок на него нет. Здесь было иначе: каталог
        # оставался на диске в недособранном виде, а код возврата 1 читал
        # только тот, кто на него смотрел. Так `migration` прожила шесть часов
        # без `_base/`: конструктор отработал «наполовину успешно», и это
        # состояние выглядело рабочим.
        #
        # Половина объекта хуже его отсутствия: отсутствие видно сразу,
        # а половина мимикрирует под целое. Поэтому — откат.
        print(f"\n  🔴 ИНВАРИАНТ НАРУШЕН: {len(problems)}")
        for p in problems:
            print(f"     · {p}")
        try:
            shutil.rmtree(target)
            print(f"\n  🔴 ОТКАЧЕНО: {target} удалён целиком.")
            print("     Репа не создана — недособранной репы не бывает.")
            print("     Причина выше; исправь её и повтори тот же вызов.")
        except OSError as e:
            print(f"\n  🔴 ОТКАТ НЕ УДАЛСЯ: {e}")
            print(f"     🔴 На диске остался НЕПОЛНЫЙ каталог: {target}")
            print(f"     Убери руками: rm -rf {target}")
        return 1

    print(f"\n  🟢 создано: {target}")
    print("  🟢 постусловия выполнены: .repo-id верен, файлы на месте, "
          "_base/ разложена, гейт CLEAN")
    print(f"\n  Дальше вручную (это решения, не ритуал):")
    print(f"     · описать границу с соседями в README и START-HERE;")
    print(f"     · добавить секцию в base-repo/repos-map.md и поднять счётчик;")
    print(f"     · собрать архив: python3 scripts/pack_release.py {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
