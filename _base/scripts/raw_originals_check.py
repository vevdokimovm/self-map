#!/usr/bin/env python3
"""raw_originals_check.py — сверка служебок с оригиналами на диске (СТ-001 §6).

🔴 ЗАКАЗ ВЛАДЕЛЬЦА 15.09.2026: стандарт на сырые экспорты — «где хранить в системе
сырые экспорты, как обрабатывать, порядок».

ЧТО ЛОВИТ. Служебка обещает: «оригинал сейчас лежит там-то, sha256 такой-то».
Обещание устаревает молча — файл перенесли, а строку нет. 15.09.2026 первый
видеопрогон споткнулся ровно об это: путь из служебки вёл в пустоту.

Сверка идёт по sha256, а не по имени: если путь не существует, скрипт ищет файл
с тем же именем во всех известных хранилищах и признаёт находку только при
совпадении хэша. Одноимённый, но другой файл — это не находка.

СТАТУСЫ
    ok        путь существует, хэш совпал, хранилище по стандарту
    icloud    файл цел, но лежит в синкаемой iCloud папке — нарушение §3
    stale     по пути пусто, файл с тем же хэшем найден в другом месте
    changed   файл есть, но хэш другой
    lost      нигде не найден
    gone      утрата признана строкой `| утрачен | … |` в служебке — не ошибка
    deleted   удалён по основанию (`| удалён | … |`) при принятой выжимке — не ошибка
    premature удалён при непринятой выжимке — нарушение СТ-001.6
    missing   (--fast) по пути пусто; stale это или lost, покажет полная сверка

ЗАПУСК
    raw_originals_check.py                 сводка + проблемные строки
    raw_originals_check.py --all           все строки
    raw_originals_check.py --repo legal-knowledge-base
    raw_originals_check.py --fast          без хэшей: только путь — для гейта
    raw_originals_check.py --fix           переписать путь у stale, найденных в каноне
    raw_originals_check.py --selftest

Код выхода 1 при `lost`, `changed` или `missing` — это потеря, а не беспорядок.
Признанная утрата (`gone`) код не портит: иначе гейт краснел бы вечно из-за
файлов, которых уже не вернуть, и перестал бы что-либо сообщать.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path

HOME = Path.home()
REPOS = HOME / "repos"
CANON = HOME / "raw-originals"
ICLOUD_SYNCED = (HOME / "Documents", HOME / "Desktop")
LEGACY_STORES = (HOME / "Documents" / "_heavy-originals",)

PATH_ROW = re.compile(r"^\| оригинал сейчас \| `[^`]+` \|$", re.M)
ROW = re.compile(r"^\|\s*(оригинал сейчас|sha256|было по пути|утрачен|удалён|выжимка)\s*\|\s*`([^`]+)`", re.M)
BAD = ("lost", "changed", "missing", "premature")
ACCEPTED = "🟢"
SKIP_DIRS = {"_base", ".git", "node_modules"}


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def in_icloud(path: Path) -> bool:
    return any(path.is_relative_to(root) for root in ICLOUD_SYNCED)


class OriginalsCheck:
    """Сверка паспортов служебок с файлами во всех хранилищах."""

    def __init__(self, repos: Path, stores: list[Path]) -> None:
        self.repos = repos
        self.stores = stores
        self._by_name: dict[str, list[Path]] | None = None
        self._hash_cache: dict[Path, str] = {}

    def passports(self, only_repo: str = "") -> list[dict]:
        found = []
        for md in self.markdown(only_repo):
            rel = md.relative_to(self.repos)
            try:
                text = md.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "оригинал сейчас" not in text:
                continue
            fields = {k: v for k, v in ROW.findall(text)}
            if "оригинал сейчас" in fields and "sha256" in fields:
                found.append({"note": rel, "repo": rel.parts[0],
                              "path": Path(fields["оригинал сейчас"]),
                              "sha": fields["sha256"],
                              "gone": "утрачен" in fields,
                              "deleted": "удалён" in fields,
                              "extract": fields.get("выжимка", "")})
        return found

    def markdown(self, only_repo: str = ""):
        """Все .md реп, не заходя в `_base`, `.git` и `node_modules`.

        `glob("*/**/*.md")` отбрасывал их уже после обхода: 53 с на 67 репах
        при том, что хэши не считались. Отсечение на входе — ровно то, что дорого.
        """
        roots = [self.repos / only_repo] if only_repo else sorted(
            d for d in self.repos.iterdir() if d.is_dir())
        for root in roots:
            for dirpath, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for name in files:
                    if name.endswith(".md"):
                        yield Path(dirpath) / name

    def index(self) -> dict[str, list[Path]]:
        if self._by_name is None:
            self._by_name = {}
            for store in self.stores:
                if store.is_dir():
                    for p in store.rglob("*"):
                        if p.is_file():
                            self._by_name.setdefault(nfc(p.name), []).append(p)
        return self._by_name

    def digest(self, path: Path) -> str:
        if path not in self._hash_cache:
            self._hash_cache[path] = sha256(path)
        return self._hash_cache[path]

    def verify(self, item: dict, fast: bool = False) -> tuple[str, Path | None]:
        path = item["path"]
        if item.get("gone"):
            return "gone", None
        if item.get("deleted"):
            return ("deleted" if item.get("extract", "").startswith(ACCEPTED)
                    else "premature"), None
        if fast:
            if not path.is_file():
                return "missing", None
            return ("icloud" if in_icloud(path) else "ok"), path
        if path.is_file():
            if self.digest(path) != item["sha"]:
                return "changed", path
            return ("icloud" if in_icloud(path) else "ok"), path
        for cand in self.index().get(nfc(path.name), []):
            if self.digest(cand) == item["sha"]:
                return "stale", cand
        return "lost", None


def fix_path(note: Path, new: Path) -> None:
    """Переписать строку «оригинал сейчас» в служебке (СТ-001.5).

    Меняется ровно одна строка паспорта: упоминание пути в тексте выжимки не задевается.
    """
    text = note.read_text(encoding="utf-8")
    fixed, n = PATH_ROW.subn(f"| оригинал сейчас | `{new}` |", text, count=1)
    if n != 1:
        raise ValueError(f"строка паспорта не найдена: {note}")
    note.write_text(fixed, encoding="utf-8")


def default_stores(repos: Path) -> list[Path]:
    return [CANON, *LEGACY_STORES, *sorted(repos.glob("*/reports/imports/heavy-originals"))]


def selftest() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repos, store, other = root / "repos", root / "store", root / "other"
        for d in (repos / "r" / "notes", store, other):
            d.mkdir(parents=True)
        (store / "ок.mp4").write_bytes(b"A")
        (other / "уехал.mp4").write_bytes(b"B")
        (other / "двойник.mp4").write_bytes(b"not-the-same")
        sha_a = hashlib.sha256(b"A").hexdigest()
        sha_b = hashlib.sha256(b"B").hexdigest()

        def note(name: str, path: Path, sha: str) -> None:
            (repos / "r" / "notes" / f"{name}.md").write_text(
                f"| sha256 | `{sha}` |\n| оригинал сейчас | `{path}` |\n", encoding="utf-8")

        note("ok", store / "ок.mp4", sha_a)
        note("stale", store / "уехал.mp4", sha_b)
        note("changed", store / "ок.mp4", "0" * 64)
        note("lost", store / "двойник.mp4", sha_b.replace("a", "b", 1) + "")
        # имя в NFD, как отдаёт macOS: должно найтись
        note("nfd", store / unicodedata.normalize("NFD", "уехал.mp4"), sha_b)

        note("gone", store / "нет.mp4", "1" * 64)
        gone_note = repos / "r" / "notes" / "gone.md"
        gone_note.write_text(gone_note.read_text(encoding="utf-8")
                             + "| утрачен | `15.09.2026` — нигде |\n", encoding="utf-8")

        def row(name: str, line: str) -> None:
            f = repos / "r" / "notes" / f"{name}.md"
            f.write_text(f.read_text(encoding="utf-8") + line + "\n", encoding="utf-8")

        note("del_ok", store / "нет2.mp4", "2" * 64)
        row("del_ok", "| выжимка | `🟢 принята` |")
        row("del_ok", "| удалён | `15.09.2026` — канал воспроизводим |")
        note("del_bad", store / "нет3.mp4", "3" * 64)
        row("del_bad", "| выжимка | `🔴 не извлечена` |")
        row("del_bad", "| удалён | `15.09.2026` — место |")

        chk = OriginalsCheck(repos, [store, other])
        fast = {p["note"].stem: chk.verify(p, fast=True)[0] for p in chk.passports()}
        assert fast["ok"] == "ok" and fast["stale"] == "missing" and fast["gone"] == "gone", fast
        assert fast["del_ok"] == "deleted" and fast["del_bad"] == "premature", fast
        got = {p["note"].stem: chk.verify(p)[0] for p in chk.passports()}
        assert got == {"ok": "ok", "stale": "stale", "changed": "changed",
                       "lost": "lost", "nfd": "stale", "gone": "gone",
                       "del_ok": "deleted", "del_bad": "premature"}, got

        moved = repos / "r" / "notes" / "stale.md"
        old = store / "уехал.mp4"
        moved.write_text(moved.read_text(encoding="utf-8")
                         + f"\nВ выжимке упомянут `{old}`.\n", encoding="utf-8")
        fix_path(moved, other / "уехал.mp4")
        text = moved.read_text(encoding="utf-8")
        assert f"| оригинал сейчас | `{other / 'уехал.mp4'}` |" in text, text
        assert f"упомянут `{old}`" in text, "текст выжимки задет"
        again = OriginalsCheck(repos, [store, other])
        item = next(i for i in again.passports() if i["note"].stem == "stale")
        assert again.verify(item)[0] == "ok"
    print("🟢 selftest: ok/stale/changed/lost различаются, одноимённый двойник "
          "с чужим хэшем не засчитан, NFD-имя находится, --fix правит только строку паспорта, --fast и признанная утрата работают, удаление без выжимки ловится (СТ-001.6)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--fast", action="store_true", help="без хэшей, только путь")
    ap.add_argument("--fix", action="store_true",
                    help="переписать путь у stale, если файл найден в ~/raw-originals")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    chk = OriginalsCheck(REPOS, default_stores(REPOS))
    items = chk.passports(a.repo)
    counts: Counter[str] = Counter()
    fixed = 0
    for item in sorted(items, key=lambda i: str(i["note"])):
        status, where = chk.verify(item, fast=a.fast)
        if a.fix and status == "stale" and where is not None and where.is_relative_to(CANON):
            fix_path(REPOS / item["note"], where)
            status, fixed = "ok", fixed + 1
        counts[status] += 1
        if a.all or status != "ok":
            tail = f" → {where}" if status == "stale" else ""
            print(f"{status:8} {item['note']}{tail}")

    print(f"\nслужебок с паспортом: {len(items)}")
    for status in ("ok", "icloud", "stale", "changed", "lost", "gone", "missing",
                   "deleted", "premature"):
        print(f"  {status:8} {counts[status]}")
    if a.fix:
        print(f"  переписано путей: {fixed}")
    return 1 if any(counts[s] for s in BAD) else 0


if __name__ == "__main__":
    sys.exit(main())
