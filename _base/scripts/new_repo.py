#!/usr/bin/env python3
"""Golden path — один шаг, а не ручное копирование 8-10 файлов с образца.

ПОЧЕМУ ЭТОТ СКРИПТ ПОЯВИЛСЯ (27.08.2026, найдено ресёрчем индустрии —
platform engineering: golden path = «инстанцировал шаблон, платформа сама
завела реестрацию/пайплайн», а не «списал с соседнего сервиса руками»).
Ручное копирование уже реально разъезжалось со стандартом: `finpilot` не имел
`.repo-meta` до сегодняшнего дня, 12 реп несли description-«эссе» на 200-344
символа. Скелет здесь собран по факту диска трёх недавно заведённых
сателлитов (`business`, `quick-answers`, `independent-expert`), не по
абстрактному минимуму `76-repo-classes.md` §1 — практика шире таблицы.

ЧТО НЕ ДЕЛАЕТ. Не пишет содержательный текст (MANIFEST §1, README-абзац) —
это синтез, не подстановка; оставляет TODO с явной пометкой, кто и когда
должен заполнить. Не трогает `repos-map.md` — тот всё равно проверяется
`revision_check.py::check_repos_map_sync()` при следующей ревизии base-repo,
писать туда одной строкой без описания зоны — то же самое, что не писать
вообще (`76-repo-classes.md` §4.1, «упоминание не считается записью»).

ЗАПУСК
    new_repo.py <имя> --class satellite --description "..." [--topics a,b,c]
    new_repo.py <имя> --class temp --parent it-base --description "..."
    new_repo.py <имя> --class infra --description "..."   (минимальный набор)
"""
from __future__ import annotations

import argparse
import datetime
from pathlib import Path

REPOS_DIR = Path.home() / "repos"
GITIGNORE = """.DS_Store
*.swp
*~
.idea/
.vscode/
__pycache__/
*.pyc
.env
*.zip
_local/
"""

FULL_CLASSES = {"core", "satellite", "temp", "product"}


def render_full(name: str, klass: str, desc: str, topics: str, today: str, parent: str | None) -> dict[str, str]:
    class_line = f"temp:{parent}" if klass == "temp" and parent else klass

    readme = f"""# {name} — Vasilii Evdokimov

{desc}

> Most documents are in Russian.

## Status

Скелет заведён {today} — см. `MANIFEST.md` для полного описания зоны
ответственности и границ с соседними репами. Наполнение не начато.

## Data & privacy note

Приватный личный репозиторий. Секреты — пароли, ключи, токены, данные карт —
сюда не попадают ни при каких условиях.

---

**Contact:** vevdokimovm@gmail.com · GitHub: [@vevdokimovm](https://github.com/vevdokimovm)
"""

    start_here = f"""# START HERE — `{name}`

**Класс:** `{klass}`
**Состояние:** скелет, наполнение не начато

## Что это

TODO — одно-два предложения, что за репа и чем НЕ является. Заполнить при
первом реальном наполнении, не оставлять как заглушку дольше одной сессии.

## Порядок входа в сессию

1. `WATCHLOG.md` §0 — где остановились
2. `ROADMAP.md` — что дальше
3. `_base/` — общие правила системы (зеркало `base-repo`, **не редактировать здесь**)

## Правила

Общесистемные правила наследуются из `_base/` — раздаётся `sync_base_local.py`.
Планирование верхнего уровня — репа `mission-control`.
"""

    manifest = f"""# Манифест репы `{name}`

## 1. Что это за репа — в трёх предложениях

TODO — заполнить при первом реальном наполнении. Golden path генерирует
только скелет; синтез смысла репы — работа человека/Claude на месте, не шаблона.

**Класс:** `{klass}`
**Видимость:** приватная
**Версия на момент манифеста:** 0.1.0

## 2. Описание для `.repo-meta` и GitHub

```
{desc}
```

**Теги:** `{topics}`

## 3. Что внутри — по предмету, а не по каталогам

TODO — таблица «раздел / файлов / что по существу» после первого наполнения.

## 4. Классификация: что сюда идёт, а что нет

TODO — граница с соседними репами, парой через «↔» (`76-repo-classes.md` §5).

## 5. Тяжёлое: эталоны и выжимки

TODO — если появятся медиа/сканы: эталон или расходное (`METHOD_IMAGES.md` §9).

## 6. Связи с другими репами

TODO.

## 7. Состояние на момент манифеста

| | |
|---|---|
| ревизия пройдена | нет — репа только заведена |
| открытых задач | нет |
| секреты | не проверено — репа пуста |
"""

    roadmap = f"""# ROADMAP — {name}

> Только будущее и только открытое. Приоритеты, не вехи.
> Основание: `_base/00-infrastructure/45-roadmap-and-tasks.md`.

**СЛЕДУЮЩАЯ ЗАДАЧА:** ждёт первого реального наполнения.

## P1

- [ ] _(появится по мере работы)_
"""

    tasks = f"""# TASKS — {name}

> Действия, которые может совершить только владелец: найти, скачать, прислать, решить.
> Работа внутри песочницы — в `ROADMAP.md`.
> Статус несёт чекбокс, не время глагола.

_пока пусто — репа только заведена._
"""

    changelog = f"""# CHANGELOG — {name}

## [0.1.0] — {today} — MINOR: скелет репозитория

Заведена через `scripts/new_repo.py` (golden path, `76-repo-classes.md`).

Формат: [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/) · SemVer.

### Добавлено

- Служебные файлы: `.repo-id`, `.repo-class`, `.repo-meta`, `VERSION`, `.gitignore`
- Каркас: `README.md`, `START-HERE.md`, `ROADMAP.md`, `TASKS.md`, `WATCHLOG.md`, `MANIFEST.md`
"""

    vahta_note = "Вахта передаётся между аккаунтами V / J / M / S / A."
    watchlog = f"""# WATCHLOG — {name}

> {vahta_note} Принял вахту — сначала сюда,
> потом эмпирическая сверка файлов, потом работа.

## §0. Где стоим

**Версия:** 0.1.0 · **Дата:** {today} · **Вахта:** —

**Состояние:** скелет заведён через golden path (`new_repo.py`), наполнение
не начато.

**СЛЕДУЮЩАЯ ЗАДАЧА:** первое реальное наполнение — начать с `MANIFEST.md` §1
(TODO там же).

## §1. История вахт

| Версия | Дата | Вахта | Что сделано |
|---|---|---|---|
| 0.1.0 | {today} | — | Скелет по стандарту через `new_repo.py`. |
"""

    files = {
        ".repo-class": class_line + "\n",
        ".repo-id": f"vevdokimovm/{name}\n",
        ".repo-meta": f"description={desc}\ntopics={topics}\nprivate=true\n",
        ".gitignore": GITIGNORE,
        "VERSION": "0.1.0\n",
        "README.md": readme,
        "START-HERE.md": start_here,
        "MANIFEST.md": manifest,
        "ROADMAP.md": roadmap,
        "TASKS.md": tasks,
        "CHANGELOG.md": changelog,
        "WATCHLOG.md": watchlog,
    }
    return files


def render_infra(name: str, desc: str, topics: str, today: str) -> dict[str, str]:
    return {
        ".repo-class": "infra\n",
        ".repo-id": f"vevdokimovm/{name}\n",
        ".repo-meta": f"description={desc}\ntopics={topics}\nprivate=true\n",
        ".gitignore": GITIGNORE,
        "VERSION": "0.1.0\n",
        "README.md": f"# {name} — Vasilii Evdokimov\n\n{desc}\n\n> Most documents are in Russian.\n",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--class", dest="klass", required=True,
                     choices=["infra", "core", "satellite", "temp", "product"])
    ap.add_argument("--description", required=True)
    ap.add_argument("--topics", default="")
    ap.add_argument("--parent", help="обязателен для --class temp")
    a = ap.parse_args()

    if a.klass == "temp" and not a.parent:
        print("--class temp требует --parent <родительская-репа> (76-repo-classes.md §2)")
        return 2

    target = REPOS_DIR / a.name
    if target.exists():
        print(f"уже существует: {target} — new_repo.py не для повторного применения")
        return 2

    today = datetime.date.today().isoformat()

    if a.klass == "infra":
        files = render_infra(a.name, a.description, a.topics, today)
    else:
        files = render_full(a.name, a.klass, a.description, a.topics, today, a.parent)

    target.mkdir(parents=True)
    for fname, content in files.items():
        (target / fname).write_text(content, encoding="utf-8")

    print(f"скелет собран: {target} ({len(files)} файлов, класс {a.klass})")
    print("дальше вручную:")
    print(f"  1. заполнить TODO в MANIFEST.md/START-HERE.md (если полный класс)")
    print(f"  2. добавить запись в base-repo/repos-map.md (76-repo-classes.md §4.1 — "
          f"обязательна, revision_check.py проверит при следующем релизе base-repo)")
    print(f"  3. первый деплой — деплой.sh заведёт репо на GitHub")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
