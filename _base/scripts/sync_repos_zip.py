#!/usr/bin/env python3
"""Синхронизация всех репозиториев GitHub-аккаунта в локальную папку через zip-снапшот.

Не через `git clone`/`gh repo clone` (тянет полную историю, требует git-конфиг на каждую
репу) и не через GitHub Releases (тег/релиз ставится не на каждый коммит — правка пары
файлов без бампа версии осталась бы незамеченной). Вместо этого — то же, что делает кнопка
"Code -> Download ZIP" на странице репозитория: codeload.github.com отдаёт архив текущего
состояния default-ветки, всегда актуальный на момент запроса.

Использование:
    python3 scripts/sync_repos_zip.py [--owner vevdokimovm] [--dest ~/repos]
    python3 scripts/sync_repos_zip.py --only base-repo,finpilot   # только выбранные

Требует авторизованный `gh` (gh auth status) — используется для списка репозиториев
(включая приватные) и как источник токена для скачивания zip приватных репозиториев.

🔴 ГРАНИЦА ИНСТРУМЕНТА: в zip-снимке НЕТ `.git`.
Даты, авторство и эволюция кода существуют только на GitHub — проверено на 30 экспортах
старых реп, ни в одном архива истории не оказалось. Следствия:

  · локальная копия годится для чтения содержимого и сверки по хешам, но НЕ для ответа
    на вопросы «когда это появилось», «кто менял», «что было до»;
  · перенос файлов из такого снимка НЕ сохраняет историю — репу нельзя удалять после
    переноса, только архивировать;
  · нужна история локально — забирать `gh repo clone`, а не этим скриптом.
"""
import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path


def gh_json(args: list[str]) -> object:
    """Вызов gh с сохранением НАСТОЯЩЕЙ причины отказа.

    `check=True` поднял бы CalledProcessError, чей текст сообщает только код возврата:
    сам вывод gh («Invalid username or password», «Could not resolve host»,
    «429 Too Many Requests») остаётся в объекте исключения и в сообщение не попадает.
    Четыре разные причины выглядели бы одинаково, а лечатся по-разному —
    71-fail-loud-and-sourcing.md §7г.
    """
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or "(пустой вывод)"
        raise RuntimeError(f"gh {' '.join(args)} → код {result.returncode}\n{detail}")
    return json.loads(result.stdout)


def gh_token() -> str:
    result = subprocess.run(
        ["gh", "auth", "token"], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def list_repos(owner: str) -> list[dict]:
    return gh_json(
        [
            "repo",
            "list",
            owner,
            "--limit",
            "500",
            "--json",
            "name,defaultBranchRef,isArchived,isPrivate,updatedAt",
        ]
    )


def download_zip(owner: str, repo: str, branch: str, token: str, tmp_zip: Path) -> None:
    url = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{branch}"
    req = urllib.request.Request(url, headers={"Authorization": f"token {token}"})
    with urllib.request.urlopen(req) as resp, open(tmp_zip, "wb") as f:
        shutil.copyfileobj(resp, f)


def unpack(tmp_zip: Path, repo: str, dest: Path) -> None:
    target = dest / repo
    if target.exists():
        shutil.rmtree(target)
    with zipfile.ZipFile(tmp_zip) as zf:
        names = zf.namelist()
        # codeload заворачивает всё в один корневой каталог <repo>-<branch>/ — снимаем обёртку
        root = names[0].split("/")[0] + "/"
        zf.extractall(dest / f".{repo}-tmp-extract")
    extracted_root = dest / f".{repo}-tmp-extract" / root
    shutil.move(str(extracted_root), str(target))
    shutil.rmtree(dest / f".{repo}-tmp-extract", ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", default="vevdokimovm")
    parser.add_argument(
        "--dest",
        default=str(Path(__file__).resolve().parent.parent.parent),
    )
    parser.add_argument(
        "--only",
        default="",
        help="Список имён репозиториев через запятую — синхронизировать только их",
    )
    parser.add_argument(
        "--skip-archived", action="store_true", help="Пропускать заархивированные репозитории"
    )
    args = parser.parse_args()

    dest = Path(args.dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)

    repos = list_repos(args.owner)
    if args.only:
        wanted = {n.strip() for n in args.only.split(",") if n.strip()}
        repos = [r for r in repos if r["name"] in wanted]
    if args.skip_archived:
        repos = [r for r in repos if not r.get("isArchived")]

    token = gh_token()
    print(f"Синхронизирую {len(repos)} репозиториев owner={args.owner} → {dest}")

    ok, failed = [], []
    for r in repos:
        name = r["name"]
        branch = (r.get("defaultBranchRef") or {}).get("name", "main")
        tmp_zip = dest / f".{name}.zip.tmp"
        try:
            download_zip(args.owner, name, branch, token, tmp_zip)
            unpack(tmp_zip, name, dest)
            ok.append(name)
            print(f"  ok   {name} ({branch})")
        except Exception as e:  # noqa: BLE001 — сводка ошибок в конце, не падать на первой
            failed.append((name, str(e)))
            print(f"  FAIL {name}: {e}")
        finally:
            tmp_zip.unlink(missing_ok=True)

    print(f"\nГотово: {len(ok)} ok, {len(failed)} failed")
    if failed:
        for name, err in failed:
            print(f"  - {name}: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
