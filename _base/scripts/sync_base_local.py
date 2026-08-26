#!/usr/bin/env python3
"""sync_base_local.py — обновить `_base/` внутри репы до текущего канона base-repo.

🔴 ПОВОД (`PIT-141`). `ADR-004` называет механизм раздачи `_base/` как
`deploy.sh --sync-base` — этого флага нет в коде. `base_coverage.py --adr004`
подтвердил: 51 репа отстала на `_base/BASE_VERSION` v2.92.0 при каноне v3.22+.
Постоянного исполнителя решения так и не появилось (`21-revision-protocol.md` §4г:
«правило без исполнителя есть обещание»).

ЧТО ДЕЛАЕТ. Заменяет `<репа>/_base/` копией канона base-repo целиком (кроме .git
и мусора сборки), пишет `_base/BASE_VERSION` = текущий `VERSION` канона. Отдельный
скрипт, не режим `deploy.sh` — та же логика, что развела `pack_release.py` и
`bump_repo.py`: узкий инструмент безопаснее правки живого 1800-строчного деплойера
без долгого тестирования.

Побочно чинит артефакт iCloud-конфликтов: каталоги с суффиксом ` 2`, `` (2)`` и т.п.
внутри `_base/` — заменяются с нуля, поэтому переживший мусор просто не копируется.

ЗАПУСК
    sync_base_local.py <репа>              одна репа
    sync_base_local.py --all               все репы с существующим _base/
    sync_base_local.py --check             только показать отставание, не трогать
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

BASE_REPO = Path(__file__).resolve().parent.parent
REPOS = Path.home() / "Documents" / "система_репозиториев"

JUNK_DIRS = {".git", "__MACOSX", "__pycache__", ".ipynb_checkpoints", ".pytest_cache"}
JUNK_NAMES = {".DS_Store", "Thumbs.db"}

# То же дерево, что раньше раздавал sync-base.sh LOCAL=1 (ADR-004 §1) — весь канон
# base-repo кроме собственно приватного маркера ротации (.repo-id репе не нужен,
# у неё свой) и уже отдельно копируемых top-level служебных файлов, идущих как есть.
DISTRIBUTE = (
    "00-infrastructure", "00-manifest-aot", "01-claude-context",
    "02-methodology-library", "03-role-kit", "04-product-dev-kit",
    "05-infra-synthesis-lab", "06-autonomous-mode-kit", "07-media-to-text-lab",
    "reports", "scripts", "templates", "tests", ".claude", ".githooks",
    "00-CLAUDE-STOP.md", "00-MANIFEST.md", "00-MANIFEST-attack-on-titan.md",
    "CHANGELOG.md", "README.md", "ROADMAP.md", "TASKS.md", "START-HERE.md",
    "DO-NOT-EDIT.md", "repos-map.md", "repos-map-CHANGELOG.md",
    ".gitignore", ".repo-class",
)


def _copytree_clean(src: Path, dst: Path) -> None:
    def ignore(dirpath: str, names: list[str]) -> set[str]:
        return {n for n in names if n in JUNK_DIRS or n in JUNK_NAMES}
    shutil.copytree(src, dst, ignore=ignore, dirs_exist_ok=True)


def sync_one(repo: Path, canon_version: str, check_only: bool) -> tuple[str, str]:
    base_dir = repo / "_base"
    stamp = base_dir / "BASE_VERSION"
    old = stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else "(нет штампа)"
    if old == canon_version:
        return (old, "уже актуальна")
    if check_only:
        return (old, "ОТСТАЛА")

    if base_dir.exists():
        shutil.rmtree(base_dir)
    base_dir.mkdir(parents=True)

    for name in DISTRIBUTE:
        src = BASE_REPO / name
        if not src.exists():
            continue
        dst = base_dir / name
        if src.is_dir():
            _copytree_clean(src, dst)
        else:
            shutil.copy2(src, dst)

    (base_dir / "DO-NOT-EDIT.md").write_text(
        "# Не редактировать вручную\n\n"
        f"Это зеркало `base-repo` (канон), обновлено `sync_base_local.py` из версии "
        f"`{canon_version}`. Правки сюда теряются при следующей синхронизации — своё "
        "пишется в `00-infrastructure/` уровнем выше, не здесь.\n",
        encoding="utf-8",
    )
    stamp.write_text(canon_version + "\n", encoding="utf-8")
    return (old, f"→ {canon_version}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    canon_version = (BASE_REPO / "VERSION").read_text(encoding="utf-8").strip()

    if a.all:
        targets = sorted(d for d in REPOS.iterdir() if d.is_dir() and (d / "_base").is_dir())
    elif a.repo:
        targets = [REPOS / a.repo]
    else:
        ap.error("нужно имя репы или --all")
        return 2

    print(f"канон: v{canon_version}\n")
    for repo in targets:
        if not repo.is_dir():
            print(f"  нет репы: {repo.name}")
            continue
        old, verdict = sync_one(repo, canon_version, a.check)
        print(f"  {repo.name:<26} {old:<10} {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
