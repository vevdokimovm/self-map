#!/usr/bin/env python3
"""close_batch.py — закрыть батч одной командой.

ЗАКАЗ ВЛАДЕЛЬЦА 28.08.2026: *«автоматизировать все процессы, что захардкожены
и часто приходится делать вручную, но почему-то до сих пор не автоматизированы»*.

ПОВОД — ЗАМЕР, А НЕ ОЩУЩЕНИЕ. Ритуал закрытия батча (`06-autonomous-mode-kit/
STANDARD.md` §2) — **семь шагов**, и за одну сессию 28.08.2026 он выполнялся
**больше двадцати раз** руками. Из семи автоматизированы были четыре
(`bump_repo.py`), остальные три вызывались отдельными командами, и порядок
приходилось помнить. Забытый шаг не виден сразу: версия поднята, а архива нет —
батч выглядит закрытым, но не пережил бы обрыв.

ЧТО ДЕЛАЕТ — весь ритуал, в правильном порядке, с остановкой на первом отказе:

    1. revision_check.py     — гейт обязан дать CLEAN (иначе стоп)
    2. bump_repo.py          — VERSION + CHANGELOG + WATCHLOG §0 +
                               «Текущая точка» + README-статус
    3. pack_release.py       — архив в ~/Downloads (старые НЕ удаляются)
    4. auto_log.py           — строка в журнал прогона

ЧЕГО НЕ ДЕЛАЕТ И ПОЧЕМУ:
  · **не пишет за вахту тело CHANGELOG** — это содержание работы, не ритуал;
    текст передаётся аргументом или файлом, иначе батч закрывается пустым
    описанием, и через месяц непонятно, что в нём было;
  · **не решает, какой это подъём** (major/minor/patch) — суждение;
  · **не гасит и не ставит сторожа** — им управляет авто-режим, у которого
    свои основания (`/auto` §0).

🔴 ГЕЙТ ПЕРВЫМ, НЕ ПОСЛЕДНИМ. Если проверка падает — версия не поднимается
вовсе. Обратный порядок (сначала поднять, потом проверить) оставляет репу
в состоянии «версия новая, содержание сломано», которое чинится сложнее,
чем не начатый батч.

ЗАПУСК
    close_batch.py <репа> --patch --title "…" --body-stdin < body.md
    close_batch.py <репа> --minor --title "…" --body-file body.md
    close_batch.py <репа> --patch --title "…" --dry-run
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BASE_REPO = Path(__file__).resolve().parent.parent
REPOS = BASE_REPO.parent


def run(cmd: list[str], stdin_text: str | None = None) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, input=stdin_text)
    return p.returncode, (p.stdout + p.stderr)


def step(n: int, total: int, title: str) -> None:
    print(f"\n[{n}/{total}] {title}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--title", required=True, help="тезис батча одной строкой")
    ap.add_argument("--body-stdin", action="store_true")
    ap.add_argument("--body-file")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--major", action="store_true")
    g.add_argument("--minor", action="store_true")
    g.add_argument("--patch", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="показать план, ничего не выполняя")
    ap.add_argument("--skip-gate", action="store_true",
                    help="🔴 только когда падение гейта уже разобрано и признано "
                         "предсуществующим — иначе батч закроется поверх дефекта")
    a = ap.parse_args()

    repo = REPOS / a.repo
    if not (repo / "VERSION").is_file():
        return print(f"🔴 {a.repo}: нет VERSION — это не версионируемая репа") or 1

    body = ""
    if a.body_stdin:
        body = sys.stdin.read()
    elif a.body_file:
        body = Path(a.body_file).read_text(encoding="utf-8")

    bump_flag = "--major" if a.major else "--minor" if a.minor else "--patch"
    total = 4

    if a.dry_run:
        print(f"ПЛАН для {a.repo} ({bump_flag}):")
        print("  1. revision_check.py --root … → обязан CLEAN")
        print(f"  2. bump_repo.py {bump_flag} --title {a.title!r}")
        print("  3. pack_release.py → архив в ~/Downloads")
        print("  4. auto_log.py --type batch")
        return 0

    # --- 1. гейт -------------------------------------------------------------
    step(1, total, "гейт ревизии")
    if a.skip_gate:
        print("  ⚠ пропущен по --skip-gate (падение признано предсуществующим)")
    else:
        rc, out = run(["python3", str(BASE_REPO / "scripts/revision_check.py"),
                       "--root", str(repo)])
        last = [l for l in out.strip().split("\n") if l.strip()][-1:]
        print("  " + (last[0] if last else "нет вывода"))
        if "CLEAN" not in out:
            print("\n🔴 ОСТАНОВЛЕНО: гейт не CLEAN — версия НЕ поднята.")
            print("   Починить и повторить, либо --skip-gate, если падение")
            print("   предсуществующее и это разобрано.")
            return 1

    # --- 2. версия и живые документы ----------------------------------------
    step(2, total, "версия · CHANGELOG · WATCHLOG · README")
    rc, out = run(["python3", str(BASE_REPO / "scripts/bump_repo.py"), a.repo,
                   bump_flag, "--title", a.title, "--body-stdin"], stdin_text=body)
    print("\n".join("  " + l for l in out.strip().split("\n")[:8]))
    if rc != 0:
        print("\n🔴 ОСТАНОВЛЕНО на подъёме версии.")
        return 1

    new_version = (repo / "VERSION").read_text(encoding="utf-8").strip()

    # --- 3. архив ------------------------------------------------------------
    step(3, total, "архив релиза")
    rc, out = run(["python3", str(BASE_REPO / "scripts/pack_release.py"), str(repo)])
    print("\n".join("  " + l for l in out.strip().split("\n")[-3:]))
    if rc != 0:
        print("\n🔴 архив не собран — батч НЕ закрыт (версия уже поднята,")
        print("   собрать вручную: pack_release.py " + str(repo))
        return 1

    # --- 4. журнал прогона ---------------------------------------------------
    step(4, total, "журнал авто-режима")
    rc, out = run(["python3", str(BASE_REPO / "06-autonomous-mode-kit/bin/auto_log.py"),
                   "--repo", a.repo, "--type", "batch",
                   "--note", f"v{new_version}: {a.title}"])
    print("  " + out.strip().split("\n")[-1])

    print(f"\n✅ батч закрыт: {a.repo} v{new_version}")
    print("   Сторож авто-режима переставляется отдельно — им управляет /auto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
