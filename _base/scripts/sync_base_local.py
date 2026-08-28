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

🔴 ИСПРАВЛЕНО 27.08.2026 (найдено прямым вопросом владельца): `--all` раньше
обходил только репы, где `_base/` уже существовал — репа, которая никогда
её не получала (не отставание, а полное отсутствие), молча пропускалась
навсегда. Так `_base/` не заводился в `personal-finance-dss`,
`character-a-analysis`, `portrait-of-taste`, `mission-control` — 47 версий
канона подряд. `--all` теперь обходит **все приватные репы на диске**
(приватность — по `gh repo list`, один вызов на прогон, не по репе) и
заводит `_base/` там, где его ещё не было, а не только обновляет существующий.
Публичные репы по-прежнему не получают `_base/` никогда — правило ADR-004.
Офлайн/`gh` недоступен → громкий отказ с текстом ошибки `gh`, старое
поведение (только репы с уже существующим `_base/`) как ручной обходной путь
(`--repo` поштучно), не тихий фолбэк.

ЗАПУСК
    sync_base_local.py <репа>              одна репа (заводит _base/, если его не было)
    sync_base_local.py --all               все приватные репы на диске
    sync_base_local.py --check             только показать отставание, не трогать
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE_REPO = Path(__file__).resolve().parent.parent
REPOS = BASE_REPO.parent

JUNK_DIRS = {".git", "__MACOSX", "__pycache__", ".ipynb_checkpoints", ".pytest_cache"}
JUNK_NAMES = {".DS_Store", "Thumbs.db"}

# То же дерево, что раньше раздавал sync-base.sh LOCAL=1 (ADR-004 §1) — весь канон
# base-repo кроме собственно приватного маркера ротации (.repo-id репе не нужен,
# у неё свой) и уже отдельно копируемых top-level служебных файлов, идущих как есть.
# 🔴 28.08.2026: перечисление каталогов `NN-*` ЗАМЕНЕНО правилом.
# Список отстал дважды и молча: `08-systems-theory-lab` (заведён 22.08) и
# `09-automation-kit` (28.08) в него не попали — то есть новый кит физически
# не доезжал до реп, хотя `BASE_VERSION` бодро показывал свежую версию.
# Обнаружено гейтом: `_base/README.md` ссылался на `./09-automation-kit`,
# которого рядом нет.
# Это ровно `PIT-097` («список — намерение, свойство объекта — факт»):
# признак «это кит базы» — имя вида `NN-...`, а не членство в списке,
# который надо не забыть дополнить. Файлы по-прежнему перечислены явно:
# у них нет общего свойства, по которому их можно отобрать.
DISTRIBUTE_FILES = (
    ".claude", ".githooks", "reports", "scripts", "templates", "tests",
    "00-CLAUDE-STOP.md", "00-MANIFEST.md", "00-MANIFEST-attack-on-titan.md",
    "CHANGELOG.md", "README.md", "ROADMAP.md", "TASKS.md", "START-HERE.md",
    "DO-NOT-EDIT.md", "repos-map.md", "repos-map-CHANGELOG.md",
    ".gitignore", ".repo-class",
)


def _distribute() -> tuple[str, ...]:
    r"""Что раздаётся: все каталоги-киты `NN-*` + явный список файлов.

    Каталог-кит опознаётся по имени (`\d\d-`), а не по списку — иначе каждый
    новый кит нужно не забыть вписать, и его отсутствие видно только тогда,
    когда что-то на него сошлётся.
    """
    kits = sorted(d.name for d in BASE_REPO.iterdir()
                  if d.is_dir() and re.match(r"^\d\d-", d.name))
    return tuple(kits) + DISTRIBUTE_FILES


DISTRIBUTE = _distribute()


def _copytree_clean(src: Path, dst: Path) -> None:
    def ignore(dirpath: str, names: list[str]) -> set[str]:
        return {n for n in names if n in JUNK_DIRS or n in JUNK_NAMES}
    shutil.copytree(src, dst, ignore=ignore, dirs_exist_ok=True)


def private_repo_names(owner: str = "vevdokimovm") -> set[str]:
    """Один вызов `gh` за весь прогон — какие репы owner'а приватные.

    Громкий отказ, а не тихий фолбэк (`71-fail-loud-and-sourcing.md` §7ж):
    если `gh` недоступен/не авторизован, вызывающий код обязан показать
    текст ошибки и остановиться, а не молча вернуться к старому неполному
    поведению — иначе тот же класс бага (репа без `_base/` пропущена
    навсегда) повторится незаметно.
    """
    result = subprocess.run(
        ["gh", "repo", "list", owner, "--limit", "500",
         "--json", "name,isPrivate"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or "(пустой вывод)"
        raise RuntimeError(f"gh repo list {owner} → код {result.returncode}\n{detail}")
    data = json.loads(result.stdout)
    return {r["name"] for r in data if r.get("isPrivate")}


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
        try:
            private = private_repo_names()
        except Exception as e:
            print(f"✗ не удалось получить список приватных реп: {e}")
            print("  --all требует рабочий `gh` (fail loud, не тихий фолбэк — "
                  "71-fail-loud-and-sourcing.md §7ж). Обходной путь: "
                  "sync_base_local.py <репа> поштучно.")
            return 2
        targets = sorted(
            d for d in REPOS.iterdir()
            if d.is_dir() and d.name != "base-repo" and d.name in private
        )
    elif a.repo:
        # 26.08.2026: base-repo не бывает получателем самой себя — без этой
        # проверки одиночный запуск с "base-repo" пишет служебные маркеры
        # (BASE_VERSION/DO-NOT-EDIT.md) в канон, а не в чужой _base/.
        if a.repo == "base-repo":
            print("✗ base-repo не может быть целью синхронизации — это источник канона")
            return 2
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

    if a.all and not a.check:
        _record_liveness(f"канон v{canon_version}, {len(targets)} реп")
    return 0


def _record_liveness(summary: str) -> None:
    """Признак живости (`08-automation-triggers.md`) — не тихая автоматизация."""
    import datetime
    import re

    path = BASE_REPO / "reports" / "infra-liveness.md"
    if not path.is_file():
        return
    today = datetime.date.today().isoformat()
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(\| `scripts/sync_base_local\.py --all` \| )[^|]+( \| )[^|]+( \|)"
    )
    new_text, n = pattern.subn(rf"\g<1>{today}\g<2>{summary}\g<3>", text)
    if n:
        path.write_text(new_text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
