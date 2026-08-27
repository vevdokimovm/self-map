#!/usr/bin/env python3
"""Собрать все различающиеся версии базопоставляемого файла по всем репам.

Вход: имя файла (basename). Выход: сколько разных версий, кто где, размеры,
и путь к каждой версии для последующего сравнения по измерениям.
"""
import hashlib
import os
import sys
from collections import defaultdict
from pathlib import Path

# 🔴 Путь к базе — одной строкой и через окружение (`ROADMAP.md` §P0 п. 6).
# Замер 22.08.2026: `/Users/vasyaevdokimov/Documents/base-repo` был вписан строкой
# в 15 файлов, и это единственное, что мешало перенести базу в каталог системы:
# перенос обрывал собственный инструмент исполнения, включая сессию, которая его делает.
# Падение на путь скрипта, а не на константу: скрипт лежит В базе и знает, где он.
BASE_ENV = os.environ.get("BASE_REPO")
CANON = Path(BASE_ENV).expanduser() if BASE_ENV else Path(__file__).resolve().parent.parent
ROOT = CANON.parent
SKIP = {".git", "__MACOSX", "__pycache__", ".ipynb_checkpoints"}


def sha1(p):
    try:
        return hashlib.sha1(p.read_bytes()).hexdigest()
    except OSError:
        return None


def find(name, include_base=False):
    hits = []
    for repo in sorted(ROOT.iterdir()):
        if not repo.is_dir():
            continue
        for dp, dn, fns in os.walk(repo):
            dn[:] = [d for d in dn if d not in SKIP]
            rel = Path(dp).relative_to(repo)
            if not include_base and rel.parts and rel.parts[0] == "_base":
                continue
            if name in fns:
                hits.append(Path(dp) / name)
    return hits


def main():
    name = sys.argv[1]
    include_base = "--with-base" in sys.argv
    hits = find(name, include_base)

    canon = None
    for dp, dn, fns in os.walk(CANON):
        dn[:] = [d for d in dn if d not in SKIP]
        if name in fns:
            canon = Path(dp) / name
            break

    groups = defaultdict(list)
    for p in hits:
        groups[sha1(p)].append(p)

    ch = sha1(canon) if canon else None
    print(f"=== {name}")
    print(f"канон: {canon.relative_to(CANON) if canon else '— НЕТ В БАЗЕ'}"
          f"  {canon.stat().st_size if canon else 0} байт  sha {ch[:12] if ch else '—'}")
    print(f"копий в репах: {len(hits)} · различных версий: {len(groups)}\n")

    for i, (h, paths) in enumerate(
        sorted(groups.items(), key=lambda kv: -len(kv[1])), 1
    ):
        mark = "  ← СОВПАДАЕТ С КАНОНОМ" if h == ch else ""
        size = paths[0].stat().st_size
        print(f"--- версия {i}: sha {h[:12]}  {size} байт  копий {len(paths)}{mark}")
        for p in sorted(paths)[:20]:
            print(f"      {p.relative_to(ROOT)}")
        if len(paths) > 20:
            print(f"      … ещё {len(paths)-20}")
        print()


if __name__ == "__main__":
    main()
