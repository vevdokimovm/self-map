#!/usr/bin/env python3
"""bump_repo.py — поднять версию ЧУЖОЙ репы одной операцией.

🔴 ПОВОД — `PIT-136`, найденный владельцем на живом деплое:

    ТРЕБУЕТ РЕШЕНИЯ: career v0.2.0 — WATCHLOG §0 стоит на 0.1.0,
    точка входа в вахту отстала. Обнови §0 и перезапусти

Репа была пропущена и не опубликована. Проверка нашла **шесть** таких.

**Почему так вышло.** У базы ритуал закрытия встроен в `close_batch.py` и потому
исполняется всегда. Для чужих реп версия поднималась вручную — тремя строками питона, —
и ритуал сократился до того, что помнилось: `VERSION` и `CHANGELOG`, без `WATCHLOG` §0.

> **Правило существовало, исполнителя у него не было** (`PIT-116`).
> Ручной подъём версии воспроизводит дефект каждый раз, когда шагов больше одного.

ЧТО ДЕЛАЕТ — три файла одной операцией, как того требует деплой,
и четвёртым действием оставляет след о закрытом батче:

  1. `VERSION` — новый номер;
  2. `CHANGELOG.md` — секция с заголовком и разрядом (MAJOR/MINOR/PATCH);
  3. `WATCHLOG.md` — строка `**Версия:** X.Y.Z`, которую читает `deploy.sh`
     (`sed -n 's/.*\\*\\*Версия:\\*\\*...'`). Нет строки — она создаётся.
  4. `06-autonomous-mode-kit/runs/auto.log` — строка `batch` о закрытии.

🔴 ПОЧЕМУ ЧЕТВЁРТЫЙ ШАГ ЗДЕСЬ — решение `ROADMAP` §P0-1 от 03.09.2026,
повод `PIT-174` (`ADR-007`).

Признак жизни для watchdog `system_status.batch_silence()` — строка `batch`
в журнале прогона. Писал её только ритуал `close_batch.py` шагом 5. Вахта,
закрывавшая батчи поштучно (`bump_repo` → `pack_release` → `sync_base_local`),
журнал не трогала — и watchdog девять часов показывал «минут тишины: 580»
посреди самой плотной работы за вахту. Обойдя ритуал, вахта **выключила
единственную проверку на собственное залипание** и узнать об этом не могла:
залипание как раз и значит, что никто не смотрит.

**Событие излучает тот, кто его производит.** Факт «версия поднята, батч
закрыт» знает этот скрипт и только он; ритуал — потребитель события, а не
его источник. Пока объявлял потребитель, событие терялось при любом другом
вызывающем. Через `bump_repo` проходит КАЖДЫЙ подъём версии — и ритуальный,
и ручной, — то есть это самое узкое горло, через которое течёт весь класс.

🔴 ЭТО НЕ ЗНАНИЕ ПРО АВТО-РЕЖИМ. Скрипт журналирует собственное действие;
то, что журнал лежит в ките `06-*`, — свойство размещения файла, а не
зависимость от режима. Связь — одна константа `AUTO_LOG` и вызов соседнего
CLI, без импорта: переедет журнал — поменяется строка.

ЗАПИСЬ НЕ ФАТАЛЬНА. Журнал — след, а не предусловие: нет `auto_log.py`,
отказал, недоступен — подъём версии всё равно состоялся и код возврата
остаётся нулевым. Обратное означало бы, что репу нельзя поднять из копии
кита, где журнала нет вовсе.

🔴 ГРАНИЦА (`71` §7г-бис): содержание секции пишет вахта. Скрипт разносит готовый
текст по трём местам и следит, чтобы ни одно не отстало, — он не сочиняет changelog.

ЗАПУСК
    bump_repo.py career --minor --title "..." --body FILE
    bump_repo.py science --patch --title "..." --body-stdin
    bump_repo.py --check-all      только проверить расхождения по всем репам
ПРЕДУСЛОВИЯ (проверяются до первой записи):
  · репа существует и у неё есть `VERSION` — иначе поднимать нечего;
  · `VERSION` разбирается как `X.Y.Z`; мусор в файле не «поднимается»,
    а останавливает работу;
  · задан разряд (`--major`/`--minor`/`--patch`) и заголовок секции.

ПОСТУСЛОВИЯ (проверяются после — ради них скрипт и заведён):
  · `VERSION` выросла ровно на одну ступень заданного разряда;
  · в `CHANGELOG.md` есть секция ровно этой версии;
  · 🔴 `WATCHLOG` §0 назвал ЭТУ версию — тот самый шаг, который выпадал
    при ручном подъёме и оставил шесть реп неопубликованными (`PIT-136`);
  · «Текущая точка» и блок статуса README согласованы с `VERSION`.

ИНВАРИАНТ: `VERSION` == версия в `CHANGELOG` == версия в `WATCHLOG` §0.
Расхождение любых двух означает, что подъём оборвался посередине, и репа
выглядит закрытой, не будучи ею.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

# Корень определяется общим модулем: скрипт может быть запущен и из базы,
# и из копии кита в репе-наследнике (`_base/scripts/`). См. `_roots.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402
BASE_REPO, REPOS, FROM_KIT = resolve_roots(__file__)
# Единственная точка связи с китом авто-режима: переедет журнал — правится здесь.
AUTO_LOG = BASE_REPO / "06-autonomous-mode-kit" / "bin" / "auto_log.py"
TODAY = date.today().isoformat()
# 🔴 ВРЕМЯ, А НЕ ТОЛЬКО ДАТА — заказ владельца 03.09.2026 21:29.
# За сутки система закрывает до десяти версий; по одной дате порядок событий
# внутри дня восстанавливается только по номеру версии, а у отчётов и разборов
# номера нет вовсе. Время — часть показания (`00-infrastructure/94` §3).
# Минуты без секунд: секундная точность в заголовке ничего не различает,
# а глазу мешает. В журналах СОБЫТИЙ секунды остаются — там их пишет машина.
NOW = datetime.now().strftime("%H:%M")
STAMP = f"{TODAY} {NOW}"

# Как читает версию сам deploy.sh — сверяемся ровно этим выражением, а не похожим.
WL_VERSION = re.compile(r"\*\*Версия:\*\*\s*([0-9][0-9.]*)")



def current_watch() -> str:
    """Буква вахты — из `~/.claude.json`, а НЕ константой.

    🔴 Найдено 28.08.2026: здесь стояло литеральное «V». Это и был **корень
    `PIT-156`** — правило «проверяй вахту перед записью» физически не могло
    помочь, потому что писала не вахта, а скрипт, и он писал V всегда.
    Один прогон `--all` разложил неверную букву по 45 репам.

    Тот же класс, что `PIT-160`: массовый инструмент умножает свой неверный
    допуск на охват. И та же развилка «правило против механизма»: сколько ни
    напоминай себе проверять, источник числа не в памяти агента.

    Не определилась — возвращаем `?`, а не подставляем ближайшую: неизвестная
    буква честнее неверной (`71` §7ж).
    """
    import json
    from pathlib import Path as _P
    try:
        d = json.loads((_P.home() / ".claude.json").read_text(encoding="utf-8"))
        email = (d.get("oauthAccount") or {}).get("emailAddress") or ""
    except Exception:
        return "?"
    if not email:
        return "?"
    # 🔴 29.08.2026: здесь стоял ПЕРЕЧЕНЬ из двух вахт — тот же дефект, что
    # литеральное «V» до него, только мягче: две вахты работали, три молча
    # получали «?». Поймано на вахте S (`gertab95@gmail.com`) сразу после
    # `/login`. Перечень покрывает ровно то, что кто-то однажды вписал;
    # правило читает реестр, который и так обязан быть верным.
    registry = _P(__file__).resolve().parent.parent / "00-infrastructure" / "84-claude-accounts.md"
    if registry.is_file():
        for line in registry.read_text(encoding="utf-8", errors="replace").splitlines():
            if email in line:
                m = re.search(r"\*\*([VJMSA])\*\*", line)
                if m:
                    return m.group(1)
    return "?"


def bump(v: str, kind: str) -> str:
    a, b, c = (v.strip().split(".") + ["0", "0", "0"])[:3]
    if kind == "major":
        return f"{int(a)+1}.0.0"
    if kind == "patch":
        return f"{a}.{b}.{int(c)+1}"
    return f"{a}.{int(b)+1}.0"


# Указатель — короткий файл, чьё содержание: «настоящий лежит там».
# 🔴 29.08.2026: `bump_repo.py` вписал `**Версия:**` прямо в файл-указатель
# `personal-finance-dss/WATCHLOG.md` — и **восстановил тот самый третий источник
# правды о состоянии**, который в том же батче был оттуда убран. Инструмент,
# не различающий документ и указатель на документ, отменяет работу по разведению
# источников молча и на каждом подъёме версии.
POINTER_MAX_LINES = 40


def follow_pointer(path: Path) -> Path:
    """Настоящий файл, если этот — указатель; иначе он сам."""
    if not path.is_file():
        return path
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text.splitlines()) > POINTER_MAX_LINES:
        return path
    for m in re.finditer(r"\[[^\]]*\]\(([^)]+)\)|`([^`]+)`", text):
        target = (m.group(1) or m.group(2) or "").strip()
        if not target or target.startswith(("http", "#")):
            continue
        if Path(target).name != path.name:
            continue
        candidate = (path.parent / target).resolve()
        if candidate.is_file() and candidate != path.resolve():
            return candidate
    return path


def watchlog_version(repo: Path) -> str | None:
    # Идём по указателю, как write_watchlog и sync_resume_point: иначе сверка
    # читает заглушку, не находит версии и валит батч на ровном месте.
    wl = follow_pointer(repo / "WATCHLOG.md")
    if not wl.is_file():
        return None
    m = WL_VERSION.search(wl.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else None


def check_all() -> int:
    bad = 0
    for d in sorted(REPOS.iterdir()):
        if not d.is_dir():
            continue
        vf = d / "VERSION"
        if not vf.is_file():
            continue
        # 🔴 Отсутствие журнала — тоже расхождение, а не повод пропустить репу.
        # Первая редакция проверки требовала наличия WATCHLOG.md и молча пропускала
        # реп без него — 25 из 61. Деплой на такой репе отказывает при первом же
        # подъёме версии: «в WATCHLOG.md нет строки **Версия:**» (`PIT-136`).
        # Проверка, пропускающая случай, ради которого заведена, бесполезна.
        if not (d / "WATCHLOG.md").is_file():
            print(f"  🔴 {d.name:<26} VERSION {vf.read_text(encoding='utf-8').strip():<10} "
                  f"WATCHLOG.md ОТСУТСТВУЕТ")
            bad += 1
            continue
        v = vf.read_text(encoding="utf-8").strip()
        w = watchlog_version(d)
        if v != w:
            print(f"  🔴 {d.name:<26} VERSION {v:<10} §0 {w or 'НЕТ СТРОКИ'}")
            bad += 1
    print(f"\n  расхождений: {bad}")
    if bad:
        print("  Деплой такие репы ПРОПУСКАЕТ, не публикуя (PIT-136).")
    else:
        print("  ИТОГ: точка входа каждой репы совпадает с её VERSION")
    return 1 if bad else 0


def write_watchlog(repo: Path, new: str) -> str:
    """Строка `**Версия:**` — то, что читает деплой. Нет её — создаём."""
    wl = follow_pointer(repo / "WATCHLOG.md")
    if not wl.is_file():
        wl.write_text(f"# {repo.name} — Вахтенный журнал\n\n"
                      f"**Версия:** {new} · **Дата:** {STAMP} · **Вахта:** {current_watch()}\n",
                      encoding="utf-8")
        return "журнал создан"
    t = wl.read_text(encoding="utf-8")
    m = WL_VERSION.search(t)
    if m:
        t = t[:m.start(1)] + new + t[m.end(1):]
        # 🔴 ДАТА ОБНОВЛЯЕТСЯ ВМЕСТЕ С ВЕРСИЕЙ — найдено тестом V7 03.09.2026.
        # Здесь менялась ТОЛЬКО версия, и §0 нёс дату первого подъёма навсегда.
        # Замер на живых репах в день находки: `science` — §0 «2026-08-04»
        # при верхней записи CHANGELOG от 2026-09-03, расхождение в МЕСЯЦ;
        # `chess`, `war`, `style` — по два дня.
        #
        # Дефект тихий и того же класса, что весь этот батч: точка входа
        # выглядит заполненной и врёт о том, когда репу трогали в последний раз.
        # Правило §3 WATCHLOG требует «в любой момент отражать текущую точку» —
        # исполнителя у него не было.
        #
        # Поля `**Дата:**` может не быть — тогда НЕ выдумываем: строка написана
        # не нами, и дописывать в неё поле значит менять чужой формат.
        t = re.sub(r"(\*\*Дата:\*\*\s*)\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?",
                   rf"\g<1>{STAMP}", t, count=1)
        wl.write_text(t, encoding="utf-8")
        return "строка обновлена"
    head = re.search(r"^#\s+.*$", t, re.M)
    i = t.index("\n", head.end()) if head else 0
    wl.write_text(t[:i] + f"\n\n**Версия:** {new} · **Дата:** {STAMP} · **Вахта:** {current_watch()}\n"
                  + t[i:], encoding="utf-8")
    return "строка добавлена"



def sync_resume_point(repo: Path, new: str) -> str | None:
    """Строка «Текущая точка: vX.Y.Z» в §0 — её читает гейт (`PIT-094`).

    🔴 28.08.2026: `bump_repo.py` обновлял только `**Версия:**`, а «Текущая
    точка» оставалась прежней — то есть **сам инструмент подъёма версии
    создавал расхождение**, которое гейт потом честно ловил. Обнаружено после
    массового прогона по 45 репам: каждая получила `PIT-094` от своего же
    подъёма.
    """
    wl = follow_pointer(repo / "WATCHLOG.md")
    if not wl.is_file():
        return None
    t = wl.read_text(encoding="utf-8")
    new_t, n = re.subn(r"([Тт]екущая точка:\s*\**v?)\d+\.\d+\.\d+", rf"\g<1>{new}", t)
    if n:
        wl.write_text(new_t, encoding="utf-8")
        return f"«Текущая точка» → v{new}"
    return None


def sync_readme_status(repo: Path, new: str, title: str) -> str | None:
    """Блок `<!-- STATUS -->` в README — витрина репы (`75` §1).

    Та же дыра, тот же заход: подъём версии оставлял README отставшим.
    """
    rm = repo / "README.md"
    if not rm.is_file():
        return None
    t = rm.read_text(encoding="utf-8")
    if "<!-- STATUS -->" not in t:
        return None
    # 🔴 Старая дата съедается ВМЕСТЕ с возможным временем: иначе при повторном
    # подъёме `\d{4}-\d{2}-\d{2}` совпал бы с датой, а `( · )` упёрся бы
    # в ` 21:38 · ` — замена не сработала бы, и гейт нашёл бы отставший README
    # ПОСЛЕ подъёма версии, то есть в состоянии «версия новая, витрина старая».
    new_t, n = re.subn(
        r"(> \*\*Сейчас:\*\* )`v[\d.]+`( · )\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?( · ).*",
        rf"\g<1>`v{new}`\g<2>{STAMP}\g<3>{title}", t, count=1)
    if n:
        rm.write_text(new_t, encoding="utf-8")
        return "README-статус обновлён"
    return None


def journal_batch(repo_name: str, new: str, title: str) -> str:
    """Оставить след о закрытом батче. Возвращает строку для вывода.

    🔴 НЕ ПАДАЕТ НИКОГДА (см. шапку): журнал — след, а не предусловие.
    Отказ сообщается словом `⚠` в выводе и не трогает код возврата.
    Молчать об отказе нельзя — молчащий признак жизни хуже отсутствующего
    (`71` §7ж): он выглядит работающим.

    Формат заметки — `vX.Y.Z: заголовок` — дословно тот же, что у ритуала:
    совпадение не косметическое, на нём держится защита от двойной записи
    в `auto_log.py`. Разойдутся форматы — вернётся дубль.
    """
    if not AUTO_LOG.is_file():
        return f"⚠ журнал прогона не найден ({AUTO_LOG}) — строка не записана"
    try:
        out = subprocess.run(
            ["python3", str(AUTO_LOG), "--repo", repo_name, "--type", "batch",
             "--note", f"v{new}: {title}"],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"⚠ журнал прогона не записан: {exc}"
    if out.returncode != 0:
        tail = (out.stderr or out.stdout or "").strip().splitlines()
        return (f"⚠ журнал прогона отказал (код {out.returncode}): "
                f"{tail[-1][:80] if tail else 'без вывода'}")
    said = out.stdout.strip().splitlines()
    return f"журнал прогона — {said[-1] if said else 'записано'}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", nargs="?")
    ap.add_argument("--check-all", action="store_true")
    ap.add_argument("--title")
    ap.add_argument("--body")
    ap.add_argument("--body-stdin", action="store_true")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--minor", action="store_true")
    g.add_argument("--patch", action="store_true")
    g.add_argument("--major", action="store_true")
    a = ap.parse_args()

    if a.check_all:
        return check_all()
    if not a.repo or not a.title:
        ap.error("нужны имя репы и --title (или --check-all)")

    repo = REPOS / a.repo
    if not repo.is_dir():
        sys.exit(f"нет репы: {repo}")
    vf = repo / "VERSION"
    if vf.is_file():
        cur = vf.read_text(encoding="utf-8").strip()
        # 🔴 НАЙДЕНО ТЕСТОМ `tests/test_version_bump.sh` 03.09.2026.
        # Шапка обещала: «мусор в файле не поднимается, а останавливает работу».
        # Обещание не исполнялось: `bump()` дополняет недостающие части нулями
        # (`["мусор"] + ["0","0","0"]`), и `VERSION` с содержимым `мусор`
        # превращалась в `мусор.0.1` — записанную во ВСЕ ТРИ файла разом.
        #
        # Это худший исход из возможных для этого скрипта: он заведён как
        # лекарство от полузакрытых реп (`PIT-136`), а сам приводил репу
        # в состояние, из которого её не поднимет уже ничто — версия
        # не разбирается ни одним инструментом системы.
        #
        # Проверка стоит здесь, а не внутри `bump()`, потому что шапка обещает
        # отказ ДО ПЕРВОЙ ЗАПИСИ: провалиться в середине трёх файлов хуже,
        # чем не начать.
        if not re.fullmatch(r"\d+\.\d+\.\d+", cur):
            sys.exit(f"🔴 {a.repo}/VERSION не разбирается как X.Y.Z: {cur!r}\n"
                     f"   Поднимать нечего: сначала привести файл в порядок вручную.\n"
                     f"   Ни один файл не тронут.")
    else:
        # 🔴 PIT-143: «нет локального VERSION» ≠ «репа не публиковалась». exam-kit
        # вёл 21 релиз собственным процессом (без local VERSION) — подъём с 0.0.0
        # оказался НИЖЕ уже опубликованного v1.21.1, деплой отказал, а объяснение
        # владельцу («это разный счётчик») было домыслом до проверки факта.
        # Раз файла нет — спросить GitHub, а не молчать про 0.0.0.
        cur = "0.0.0"
        rid = repo / ".repo-id"
        if rid.is_file():
            slug = rid.read_text(encoding="utf-8").strip()
            try:
                out = subprocess.run(
                    ["gh", "api", f"repos/{slug}/tags", "--jq", ".[0].name"],
                    capture_output=True, text=True, timeout=15)
                latest = out.stdout.strip().lstrip("v")
                if latest and re.match(r"^\d+\.\d+\.\d+$", latest):
                    print(f"  🔴 локального VERSION нет, но на GitHub уже есть тег v{latest} "
                          f"({slug}) — считаю от него, не от 0.0.0", file=sys.stderr)
                    cur = latest
            except Exception:
                pass  # gh недоступен/репа ещё не создана — 0.0.0 остаётся законным умолчанием
    kind = "major" if a.major else "patch" if a.patch else "minor"
    new = bump(cur, kind)
    tag = {"major": "MAJOR", "patch": "PATCH"}.get(kind, "MINOR")

    body = sys.stdin.read() if a.body_stdin else (
        Path(a.body).read_text(encoding="utf-8") if a.body else "")
    if not body.strip():
        sys.exit("пустое тело секции — нечего писать в CHANGELOG")

    # 1. CHANGELOG
    cf = repo / "CHANGELOG.md"
    section = f"## [{new}] — {STAMP} — {a.title} ({tag})\n\n{body.rstrip()}\n\n"
    if cf.is_file():
        t = cf.read_text(encoding="utf-8")
        m = re.search(r"^#\s+.*$", t, re.M)
        i = m.end() if m else 0
        cf.write_text(t[:i] + "\n\n" + section + t[i:].lstrip("\n"), encoding="utf-8")
    else:
        cf.write_text(f"# {a.repo} — CHANGELOG\n\n{section}", encoding="utf-8")

    # 2. VERSION
    vf.write_text(new + "\n", encoding="utf-8")

    # 3. WATCHLOG §0 — то, из-за чего деплой отказывал
    how = write_watchlog(repo, new)

    # 4. Всё остальное, что обязано двигаться ВМЕСТЕ с версией.
    # 🔴 28.08.2026: без этих двух шагов сам подъём версии создавал дрейф —
    # «Текущая точка» и README-статус оставались прежними, и гейт честно
    # ловил `PIT-094`/`PIT-116` у 45 реп подряд. Версия репы поднимается
    # ОДНОЙ операцией, включающей всё живое (`PIT-136` — тот же принцип).
    resume = sync_resume_point(repo, new)
    readme = sync_readme_status(repo, new, a.title or "версия поднята")

    print(f"✓ {a.repo}: {cur} → {new}")
    print(f"  · CHANGELOG — секция [{new}]")
    print(f"  · VERSION")
    print(f"  · WATCHLOG §0 — {how}")
    if resume:
        print(f"  · {resume}")
    if readme:
        print(f"  · {readme}")

    check = watchlog_version(repo)
    if check != new:
        sys.exit(f"🔴 сверка не прошла: §0 читается как {check}, а VERSION {new}")
    print("  · сверка: точка входа совпадает с VERSION ✅")

    # 🔴 Шаг 4 — ПОСЛЕ сверки. Признак жизни означает «батч закрыт», а батч,
    # не прошедший сверку, не закрыт: сверка выходит выше по коду и сюда
    # не доходит. Журналировать до неё значило бы отчитаться о том, чего нет.
    print(f"  · {journal_batch(a.repo, new, a.title)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
