#!/usr/bin/env python3
"""Верификация: сравнить локальные копии из sync_repos_zip.py с истиной на GitHub.

Не доверяет "ok"-статусу самого sync-скрипта — тянет полное дерево файлов default-ветки
через GitHub Git Trees API (путь + точный размер blob'а в байтах) и построчно сверяет с
тем, что реально лежит на диске: нет ли пропущенных файлов, лишних файлов, расхождений
по размеру (= разное содержимое).

Использование:
    python3 scripts/verify_repos_zip.py [--owner vevdokimovm] [--dest ~/repos]
    python3 scripts/verify_repos_zip.py --only base-repo,finpilot
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def gh_json(args: list[str]) -> object:
    """Вызов gh с сохранением НАСТОЯЩЕЙ причины отказа (71-fail-loud-and-sourcing.md §7г).

    `check=True` сообщил бы только код возврата; текст gh — «Invalid username or password»,
    «Could not resolve host», «429 Too Many Requests» — потерялся бы, а лечатся они
    по-разному.
    """
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or "(пустой вывод)"
        raise RuntimeError(f"gh {' '.join(args)} → код {result.returncode}\n{detail}")
    return json.loads(result.stdout)


def list_repos(owner: str) -> list[dict]:
    return gh_json(
        [
            "repo", "list", owner, "--limit", "500",
            "--json", "name,defaultBranchRef,isArchived",
        ]
    )


def remote_tree(owner: str, repo: str, branch: str) -> tuple[dict[str, int], bool]:
    """path -> size (bytes) для всех blob'ов дерева. Возвращает (карта, truncated?)."""
    data = gh_json(
        ["api", f"repos/{owner}/{repo}/git/trees/{branch}?recursive=1"]
    )
    tree = {}
    for entry in data.get("tree", []):
        if entry.get("type") == "blob":
            tree[entry["path"]] = entry.get("size", -1)
    return tree, bool(data.get("truncated", False))


IGNORE_LOCAL = {".DS_Store"}  # macOS Finder-артефакт, не часть содержимого репозитория


def local_tree(root: Path) -> dict[str, int]:
    tree = {}
    if not root.exists():
        return tree
    for p in root.rglob("*"):
        if p.is_file() and p.name not in IGNORE_LOCAL:
            rel = str(p.relative_to(root))
            tree[rel] = p.stat().st_size
    return tree


def compare(remote: dict[str, int], local: dict[str, int]) -> dict:
    remote_paths = set(remote)
    local_paths = set(local)
    missing = sorted(remote_paths - local_paths)          # есть на GitHub, нет локально
    extra = sorted(local_paths - remote_paths)             # есть локально, нет на GitHub
    common = remote_paths & local_paths
    size_mismatch = sorted(
        p for p in common if remote[p] >= 0 and remote[p] != local[p]
    )
    return {
        "remote_count": len(remote_paths),
        "local_count": len(local_paths),
        "missing": missing,
        "extra": extra,
        "size_mismatch": size_mismatch,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", default="vevdokimovm")
    parser.add_argument(
        "--dest", default=str(Path(__file__).resolve().parent.parent.parent)
    )
    parser.add_argument("--only", default="")
    parser.add_argument("--skip-archived", action="store_true")
    args = parser.parse_args()

    dest = Path(args.dest).expanduser()
    repos = list_repos(args.owner)
    if args.only:
        wanted = {n.strip() for n in args.only.split(",") if n.strip()}
        repos = [r for r in repos if r["name"] in wanted]
    if args.skip_archived:
        repos = [r for r in repos if not r.get("isArchived")]

    print(f"Верифицирую {len(repos)} репозиториев owner={args.owner} против {dest}\n")

    clean, dirty, api_failed = [], [], []
    for r in repos:
        name = r["name"]
        branch = (r.get("defaultBranchRef") or {}).get("name", "main")
        try:
            remote, truncated = remote_tree(args.owner, name, branch)
        except subprocess.CalledProcessError as e:
            api_failed.append((name, str(e)))
            print(f"  API-FAIL {name}: {e}")
            continue
        local = local_tree(dest / name)
        result = compare(remote, local)
        trunc_note = " [TRUNCATED — дерево >100k записей, GitHub API обрезал]" if truncated else ""

        if not result["missing"] and not result["extra"] and not result["size_mismatch"]:
            clean.append(name)
            print(f"  OK    {name}: {result['remote_count']} файлов, полное совпадение{trunc_note}")
        else:
            dirty.append((name, result))
            print(
                f"  DIFF  {name}: remote={result['remote_count']} local={result['local_count']} "
                f"missing={len(result['missing'])} extra={len(result['extra'])} "
                f"size_mismatch={len(result['size_mismatch'])}{trunc_note}"
            )
            for p in result["missing"][:5]:
                print(f"          missing: {p}")
            for p in result["size_mismatch"][:5]:
                print(f"          size differs: {p}")

    print(f"\nИтог: {len(clean)} полностью совпали, {len(dirty)} с расхождениями, "
          f"{len(api_failed)} не удалось проверить (API-ошибка)")
    if dirty or api_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
