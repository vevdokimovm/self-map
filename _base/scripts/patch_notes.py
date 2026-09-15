#!/usr/bin/env python3
"""patch_notes.py — патчноуты инфраструктуры: показать при входе в репу, как в игре.

🔴 ЗАКАЗ ВЛАДЕЛЬЦА 14.09.2026, дословно: «как знаешь в доте или любой игре
рил выходят патч логи и всем видно можно почитать все узнают об этом сразу
при входе в игру обязательно».

КАК УСТРОЕНО
    INFRA-UPDATES.md      — патчноуты в каноне base-repo; в наследниках лежит
                            как `_base/INFRA-UPDATES.md` (раздаётся каждым батчем).
    .infra-updates-read   — отметка в корне репы: до какой версии прочитано.
    SessionStart-хук      — глобальный (`~/.claude/settings.json`), зовёт `--session`
                            при входе в ЛЮБУЮ репу; непрочитанное уходит в контекст
                            с требованием показать владельцу первым сообщением.

РЕЖИМЫ
    --session             непрочитанные записи для репы $CLAUDE_PROJECT_DIR (молчит,
                          если читать нечего или репа не из системы)
    --ack                 отметить прочитанным до последней версии
    --digest [--days N]   сводка владельцу по git всех реп: версии и коммиты за N дней
    --selftest            канарейка
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

NOTES_NAME = "INFRA-UPDATES.md"
MARK_NAME = ".infra-updates-read"
HEAD_RE = re.compile(r"^## v(\d+)\.(\d+)\.(\d+)\b.*$", re.M)
REPOS = Path(__file__).resolve().parent.parent.parent
MAX_FULL = 5


class PatchNotes:
    """Разбор INFRA-UPDATES.md и отметки прочитанного для одной репы."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.notes = self._find_notes()
        self.mark = repo / MARK_NAME

    def _find_notes(self) -> Path | None:
        for cand in (self.repo / NOTES_NAME, self.repo / "_base" / NOTES_NAME):
            if cand.is_file():
                return cand
        return None

    def entries(self) -> list[tuple[tuple[int, int, int], str]]:
        if not self.notes:
            return []
        text = self.notes.read_text(encoding="utf-8")
        heads = list(HEAD_RE.finditer(text))
        out = []
        for i, m in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            ver = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            out.append((ver, text[m.start():end].strip()))
        return sorted(out, key=lambda e: e[0], reverse=True)

    def read_upto(self) -> tuple[int, int, int]:
        if not self.mark.is_file():
            return (0, 0, 0)
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", self.mark.read_text())
        return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 0, 0)

    def unread(self) -> list[tuple[tuple[int, int, int], str]]:
        seen = self.read_upto()
        return [e for e in self.entries() if e[0] > seen]

    def ack(self) -> str | None:
        ents = self.entries()
        if not ents:
            return None
        ver = ".".join(map(str, ents[0][0]))
        self.mark.write_text(ver + "\n", encoding="utf-8")
        return ver


def session(repo: Path) -> int:
    pn = PatchNotes(repo)
    new = pn.unread()
    if not new:
        return 0
    first_run = not pn.mark.is_file()
    shown = new[:MAX_FULL]
    print("🔔 ПАТЧНОУТЫ ИНФРАСТРУКТУРЫ — непрочитано: "
          f"{len(new)} (репа {repo.name})")
    print("🔴 Покажи их владельцу ПЕРВЫМ сообщением сессии, коротко, своими словами,"
          " до ответа на его вопрос. После показа отметь прочитанным:")
    print(f"   python3 {Path(__file__).resolve()} --ack --repo \"{repo}\"")
    if first_run and len(new) > MAX_FULL:
        print(f"(первый вход: показаны {MAX_FULL} свежих, старые отмечаются вместе с ними)")
    print()
    for _, body in shown:
        print(body)
        print()
    rest = new[MAX_FULL:]
    if rest:
        print("Ещё непрочитано, только заголовки:")
        for _, body in rest:
            print("  " + body.splitlines()[0].lstrip("# "))
    return 0


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def digest(days: int) -> int:
    since = f"{days}.days.ago"
    rows = []
    for repo in sorted(REPOS.iterdir()):
        if not (repo / ".git").exists():
            continue
        log = git(repo, "log", f"--since={since}", "--format=%s", "origin/main")
        if not log:
            continue
        subjects = log.splitlines()
        versions = [s for s in subjects if re.search(r"\bv\d+\.\d+\.\d+", s)]
        top = versions[0] if versions else subjects[0]
        rows.append((len(subjects), repo.name, top))
    if not rows:
        print(f"за {days} дн. изменений на GitHub нет")
        return 0
    print(f"📰 ДАЙДЖЕСТ за {days} дн. — реп с изменениями: {len(rows)}\n")
    for n, name, top in sorted(rows, reverse=True):
        print(f"  {name:28} коммитов {n:3}  · {top[:90]}")
    base = PatchNotes(REPOS / "base-repo")
    if base.entries():
        print("\nПоследний патчноут базы:")
        print(base.entries()[0][1].splitlines()[0])
    return 0


def selftest() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "_base").mkdir()
        (repo / "_base" / NOTES_NAME).write_text(
            "# Патчноуты\n\n## v1.2.0 — новое\n- пункт Б\n\n## v1.10.0 — свежее\n- пункт В\n"
            "\n## v1.1.0 — старое\n- пункт А\n", encoding="utf-8")
        pn = PatchNotes(repo)
        vers = [e[0] for e in pn.entries()]
        assert vers == [(1, 10, 0), (1, 2, 0), (1, 1, 0)], vers
        assert len(pn.unread()) == 3
        assert pn.ack() == "1.10.0"
        assert pn.unread() == []
        pn.mark.write_text("1.1.0\n")
        assert [e[0] for e in pn.unread()] == [(1, 10, 0), (1, 2, 0)]
        (Path(tmp) / "empty").mkdir()
        empty = PatchNotes(Path(tmp) / "empty")
        assert empty.unread() == []
    print("🟢 selftest: разбор версий (1.10 > 1.2), отметка, молчание без файла")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", action="store_true")
    ap.add_argument("--ack", action="store_true")
    ap.add_argument("--digest", action="store_true")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--repo", type=Path)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    repo = (a.repo or Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())).resolve()
    if a.selftest:
        return selftest()
    if a.digest:
        return digest(a.days)
    if a.ack:
        ver = PatchNotes(repo).ack()
        print(f"🟢 {repo.name}: прочитано до v{ver}" if ver else "патчноутов нет")
        return 0
    try:
        return session(repo)
    except Exception as exc:  # хук старта не должен ломать вход в сессию
        print(f"patch_notes: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
