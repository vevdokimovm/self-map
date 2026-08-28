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

ЧТО ДЕЛАЕТ — три файла одной операцией, как того требует деплой:

  1. `VERSION` — новый номер;
  2. `CHANGELOG.md` — секция с заголовком и разрядом (MAJOR/MINOR/PATCH);
  3. `WATCHLOG.md` — строка `**Версия:** X.Y.Z`, которую читает `deploy.sh`
     (`sed -n 's/.*\\*\\*Версия:\\*\\*...'`). Нет строки — она создаётся.

🔴 ГРАНИЦА (`71` §7г-бис): содержание секции пишет вахта. Скрипт разносит готовый
текст по трём местам и следит, чтобы ни одно не отстало, — он не сочиняет changelog.

ЗАПУСК
    bump_repo.py career --minor --title "..." --body FILE
    bump_repo.py science --patch --title "..." --body-stdin
    bump_repo.py --check-all      только проверить расхождения по всем репам
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

BASE_REPO = Path(__file__).resolve().parent.parent
REPOS = BASE_REPO.parent
TODAY = date.today().isoformat()

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
    return {
        "vevdokimovm@gmail.com": "V",
        "finpilot.support@proton.me": "A",
    }.get(email, "?")


def bump(v: str, kind: str) -> str:
    a, b, c = (v.strip().split(".") + ["0", "0", "0"])[:3]
    if kind == "major":
        return f"{int(a)+1}.0.0"
    if kind == "patch":
        return f"{a}.{b}.{int(c)+1}"
    return f"{a}.{int(b)+1}.0"


def watchlog_version(repo: Path) -> str | None:
    wl = repo / "WATCHLOG.md"
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
    wl = repo / "WATCHLOG.md"
    if not wl.is_file():
        wl.write_text(f"# {repo.name} — Вахтенный журнал\n\n"
                      f"**Версия:** {new} · **Дата:** {TODAY} · **Вахта:** {current_watch()}\n",
                      encoding="utf-8")
        return "журнал создан"
    t = wl.read_text(encoding="utf-8")
    m = WL_VERSION.search(t)
    if m:
        wl.write_text(t[:m.start(1)] + new + t[m.end(1):], encoding="utf-8")
        return "строка обновлена"
    head = re.search(r"^#\s+.*$", t, re.M)
    i = t.index("\n", head.end()) if head else 0
    wl.write_text(t[:i] + f"\n\n**Версия:** {new} · **Дата:** {TODAY} · **Вахта:** {current_watch()}\n"
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
    wl = repo / "WATCHLOG.md"
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
    new_t, n = re.subn(
        r"(> \*\*Сейчас:\*\* )`v[\d.]+`( · )\d{4}-\d{2}-\d{2}( · ).*",
        rf"\g<1>`v{new}`\g<2>{TODAY}\g<3>{title}", t, count=1)
    if n:
        rm.write_text(new_t, encoding="utf-8")
        return "README-статус обновлён"
    return None


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
    section = f"## [{new}] — {TODAY} — {a.title} ({tag})\n\n{body.rstrip()}\n\n"
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
