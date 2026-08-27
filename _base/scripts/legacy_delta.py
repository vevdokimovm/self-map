#!/usr/bin/env python3
"""Есть ли в плоских legacy-копиях базы что-то, чего нет в актуальной базе?

Для каждой репы с плоской копией (`00-infrastructure/` = старая база):
  * файл байт-в-байт совпал с каноном         -> дубль, снимать
  * имя есть в каноне, содержимое иное        -> старая версия, снимать (канон новее)
  * имени в каноне НЕТ                        -> ⚠ проверить руками
"""
import hashlib
import os
from collections import defaultdict
from pathlib import Path

CANON = Path(__file__).resolve().parent.parent
ROOT = CANON.parent
SKIP = {".git", "__MACOSX", "__pycache__", ".ipynb_checkpoints"}

# репы, где 00-infrastructure/ — это плоская копия базы, а не свои протоколы
LEGACY = [
    "academic-portfolio", "character-a-analysis", "christ-walk", "edu-base",
    "family", "health-vault", "it-base", "legal-knowledge-base", "misc-vault",
    "portrait-of-taste", "self-map", "truth-seeking",
]

# маркер плоской копии: наличие этого файла в 00-infrastructure/
MARKER = "01-repo-standard.md"


def sha1(p):
    try:
        return hashlib.sha1(p.read_bytes()).hexdigest()
    except OSError:
        return None


def index(root):
    by_hash, by_name = set(), defaultdict(list)
    for dp, dn, fns in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP]
        for fn in fns:
            if fn == ".DS_Store":
                continue
            p = Path(dp) / fn
            h = sha1(p)
            if h:
                by_hash.add(h)
                by_name[fn].append(p)
    return by_hash, by_name


canon_hash, canon_name = index(CANON)
print(f"канон: {len(canon_hash)} уникальных blob'ов, {len(canon_name)} имён\n")

total = defaultdict(int)
unknown = defaultdict(list)

for repo in LEGACY:
    inf = ROOT / repo / "00-infrastructure"
    if not (inf / MARKER).exists():
        print(f"{repo:<24} — плоской копии нет, пропуск")
        continue
    dup = old = new = 0
    for dp, dn, fns in os.walk(inf):
        dn[:] = [d for d in dn if d not in SKIP]
        for fn in fns:
            if fn == ".DS_Store":
                continue
            p = Path(dp) / fn
            h = sha1(p)
            if h in canon_hash:
                dup += 1
            elif fn in canon_name:
                old += 1
            else:
                new += 1
                unknown[fn].append(str(p.relative_to(ROOT)))
    total["dup"] += dup
    total["old"] += old
    total["new"] += new
    print(f"{repo:<24} дубль {dup:>4} · старая версия {old:>4} · ⚠ имени нет в базе {new:>4}")

print(f"\nИТОГО: дублей {total['dup']} · старых версий {total['old']} · "
      f"⚠ неизвестных {total['new']}")

print("\n=== ⚠ ИМЕНА, КОТОРЫХ НЕТ В АКТУАЛЬНОЙ БАЗЕ ===")
for fn, paths in sorted(unknown.items(), key=lambda kv: -len(kv[1])):
    print(f"\n{fn}  ({len(paths)} копий)")
    for p in sorted(paths)[:4]:
        print(f"    {p}")
    if len(paths) > 4:
        print(f"    … ещё {len(paths)-4}")
