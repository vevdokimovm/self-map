#!/usr/bin/env python3
"""distribute_claude_kit.py — раздать базовый набор `.claude/` дочерним репам.

ЗАЧЕМ (ROADMAP.md: «Раздать `.claude/` дочерним репам»). До этой правки хуки/агенты
были только у `base-repo` и `personal-finance-dss` — у остальных ~57 репозиториев не
было НИЧЕГО, то есть хук защиты `_base/` (`protect-base-mirror.sh`, ROADMAP «Хук на
`_base/`») действовал только в сессиях, где корень проекта — `base-repo`. Сессия,
открытая в любой другой репе, ту же правку внутри её собственного `_base/` не ловила.

ЧТО ВХОДИТ В БАЗОВЫЙ НАБОР v1 — решение этой правки, узкое и намеренно:
    только `.claude/hooks/protect-base-mirror.sh` + `settings.json` с PreToolUse на него.
Агенты (`repo-inventory`, `base-coverage-probe`) и скиллы НЕ входят — они кампанейские
инструменты синтеза, не универсальная защита; расширение набора — решение будущей
правки, не эта. Узкий набор снижает риск конфликта с продуктовыми `.claude/` (если
такой появится у репы позже) до почти нуля: один файл, одно поведение, без побочных
эффектов на остальную работу агента.

КОГО ПРОПУСКАЕМ:
    - у репы уже есть `.claude/settings.json` — не трогаем, это продуктовая настройка
      (`personal-finance-dss`) или уже раздано (`base-repo`);
    - нет `.repo-id` — не похоже на заведённую репу системы, а не то, что можно
      определить надёжно.

ЗАПУСК
    python3 scripts/distribute_claude_kit.py            # сухой прогон, только список
    python3 scripts/distribute_claude_kit.py --apply     # реально пишет файлы
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

BASE_REPO = Path(__file__).resolve().parent.parent
REPOS_DIR = BASE_REPO.parent
HOOK_SRC = BASE_REPO / ".claude" / "hooks" / "protect-base-mirror.sh"

SETTINGS_JSON = """{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "\\"$CLAUDE_PROJECT_DIR/.claude/hooks/protect-base-mirror.sh\\"",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if not HOOK_SRC.is_file():
        print(f"✗ нет исходного хука: {HOOK_SRC}")
        return 1

    skipped_has_settings = []
    skipped_not_repo = []
    targets = []

    for d in sorted(REPOS_DIR.iterdir()):
        if not d.is_dir():
            continue
        if d.name == "base-repo":
            continue
        if (d / ".claude" / "settings.json").is_file():
            skipped_has_settings.append(d.name)
            continue
        if not (d / ".repo-id").is_file():
            skipped_not_repo.append(d.name)
            continue
        targets.append(d)

    print(f"репов к раздаче: {len(targets)}")
    print(f"уже имеют .claude/settings.json (пропущены): {len(skipped_has_settings)}")
    if skipped_has_settings:
        print("  " + ", ".join(skipped_has_settings))
    print(f"без .repo-id, не похоже на репу (пропущены): {len(skipped_not_repo)}")
    if skipped_not_repo:
        print("  " + ", ".join(skipped_not_repo))
    print()

    if not a.apply:
        print("сухой прогон — ничего не записано. Реально раздать: --apply")
        for d in targets:
            print(f"  {d.name}")
        return 0

    done = 0
    for d in targets:
        hooks_dir = d / ".claude" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HOOK_SRC, hooks_dir / "protect-base-mirror.sh")
        (hooks_dir / "protect-base-mirror.sh").chmod(0o755)
        (d / ".claude" / "settings.json").write_text(SETTINGS_JSON, encoding="utf-8")
        print(f"  ✓ {d.name}")
        done += 1

    print(f"\nроздано: {done}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
