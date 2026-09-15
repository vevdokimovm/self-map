#!/usr/bin/env python3
"""delivery_check.py — дошло ли до реп то, что система им отправляет.

🔴 ПОВОД, 15.09.2026. Механизм патчноутов завели 14.09 под заказ владельца
«все узнают об этом сразу при входе в игру обязательно». Файл не попал
в раздачу — и **0 из 58 реп** получили его за сутки. Хук при этом отрабатывал
с кодом 0 и молчал: читать было нечего, а пустой вход неотличим от «новостей
нет» (`PIT-G` случай 21).

🔴 УРОК, КОТОРЫЙ ИСПОЛНЯЕТ ЭТОТ СКРИПТ. «Механизм отработал» и «репа получила» —
разные утверждения. Второе проверяется только счётом НА СТОРОНЕ ПОЛУЧАТЕЛЯ,
и потому проверка идёт по репам, а не по каналу.

ЧЕТЫРЕ КАНАЛА, КОТОРЫМИ СИСТЕМА ГОВОРИТ С РЕПОЙ

    правила      `_base/` — версия и отпечаток набора (сверку делает
                 sync_base_local; здесь только факт наличия и свежести метки)
    новости      `_base/INFRA-UPDATES.md` + отметка `.infra-updates-read`
    вход         `_base/00-CLAUDE-STOP.md` — что читается до начала работы
    инструменты  глобальные: симлинк плагина в ~/.claude/skills, хук старта

🔴 ЧЕГО НЕ ЛОВИТ. Не проверяет, что вахта ПРОЧЛА и ПРИМЕНИЛА: доставленность
и применение — разные вещи, второе машиной не измеряется. Не проверяет
содержимое правил (это `revision_check`). Для публичных реп `_base/` не
раздаётся намеренно (ADR-004) — они исключаются, а не считаются провалом.

ЗАПУСК
    delivery_check.py              сводка + проблемные репы
    delivery_check.py --all        все строки
    delivery_check.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

HOME = Path.home()
BASE = Path(__file__).resolve().parent.parent
REPOS = BASE.parent
GLOBAL_SETTINGS = HOME / ".claude" / "settings.json"
PLUGIN_LINK = HOME / ".claude" / "skills" / "base-kit"
VER_RE = re.compile(r"^## v(\d+\.\d+\.\d+)", re.M)


def canon_version() -> str:
    return (BASE / "VERSION").read_text(encoding="utf-8").strip()


def latest_note(updates: Path) -> str:
    """Версия самого свежего патчноута в файле."""
    if not updates.is_file():
        return ""
    m = VER_RE.search(updates.read_text(encoding="utf-8"))
    return m.group(1) if m else ""


def repo_class(repo: Path) -> str:
    f = repo / ".repo-class"
    return f.read_text(encoding="utf-8").strip() if f.is_file() else ""


def expects_base(repo: Path, private: set[str] | None) -> bool:
    """`_base/` кладётся не всем: публичные и архивные репы его не получают.

    🔴 ИСТОЧНИК ПРАВДЫ О ПУБЛИЧНОСТИ — ТОТ ЖЕ, ЧТО У РАЗДАЧИ (`gh`), а не
    `.repo-meta`. Первая редакция смотрела метафайл, которого у продуктовых
    реп нет, и объявила «не доставлено» семь ПУБЛИЧНЫХ реп, куда база
    не кладётся намеренно (ADR-004). Проверка, у которой своя версия правды,
    выдаёт ложные тревоги — а они учат не читать отчёт (`sync_base_local` §план).
    """
    if repo_class(repo) in {"archived", "public-mirror"}:
        return False
    if private is not None:
        return repo.name in private
    meta = repo / ".repo-meta"
    if meta.is_file():
        try:
            if json.loads(meta.read_text(encoding="utf-8")).get("private") is False:
                return False
        except json.JSONDecodeError:
            pass
    return True


def private_names() -> set[str] | None:
    """Приватные репы владельца по `gh`. None — если спросить не удалось."""
    try:
        sys.path.insert(0, str(BASE / "scripts"))
        from sync_base_local import private_repo_names
        return private_repo_names()
    except Exception:  # noqa: BLE001 — недоступность gh не должна ронять проверку
        return None


class RepoDelivery:
    """Что из отправленного дошло до одной репы."""

    def __init__(self, repo: Path, canon: str, canon_note: str) -> None:
        self.repo = repo
        self.canon = canon
        self.canon_note = canon_note
        self.base = repo / "_base"

    @property
    def base_version(self) -> str:
        f = self.base / "BASE_VERSION"
        return f.read_text(encoding="utf-8").strip() if f.is_file() else ""

    def problems(self) -> list[str]:
        out: list[str] = []
        if not self.base.is_dir():
            return ["🔴 правила: нет `_base/` вовсе"]
        if not self.base_version:
            out.append("🔴 правила: нет отметки версии")
        elif self.base_version != self.canon:
            out.append(f"🟡 правила: {self.base_version}, канон {self.canon}")
        if not (self.base / "00-CLAUDE-STOP.md").is_file():
            out.append("🔴 вход: нет `00-CLAUDE-STOP.md`")

        updates = self.base / "INFRA-UPDATES.md"
        if not updates.is_file():
            out.append("🔴 новости: файла нет — канал не доставляет ничего")
        else:
            got = latest_note(updates)
            if got != self.canon_note:
                out.append(f"🟡 новости: свежая {got or '—'}, в каноне {self.canon_note}")
            else:
                read = self.repo / ".infra-updates-read"
                if not read.is_file():
                    out.append("⚪️ новости: доставлены, но ещё не прочитаны")
        return out


def global_channel() -> list[str]:
    """Каналы, общие для всех реп: плагин со скиллами и хук старта сессии."""
    out: list[str] = []
    if not PLUGIN_LINK.exists():
        out.append(f"🔴 инструменты: нет {PLUGIN_LINK} — скиллы недоступны вне базы")
    elif PLUGIN_LINK.is_symlink() and not PLUGIN_LINK.resolve().is_dir():
        out.append("🔴 инструменты: симлинк плагина висит в пустоту")
    else:
        for part in ("skills", "agents"):
            if not (PLUGIN_LINK / part).is_dir():
                out.append(f"🟡 инструменты: в плагине нет `{part}/`")
    try:
        settings = json.loads(GLOBAL_SETTINGS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return out + [f"🔴 новости: не читается {GLOBAL_SETTINGS}: {exc}"]
    hooks = json.dumps(settings.get("hooks", {}), ensure_ascii=False)
    if "patch_notes.py" not in hooks:
        out.append("🔴 новости: глобальный хук старта не зовёт patch_notes.py — "
                   "патчноуты не покажутся ни в одной репе")
    return out


def selftest() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repo = root / "r"
        (repo / "_base").mkdir(parents=True)
        d = RepoDelivery(repo, "1.0.0", "1.0.0")
        assert any("00-CLAUDE-STOP" in p for p in d.problems())
        assert any("новости: файла нет" in p for p in d.problems())

        (repo / "_base" / "BASE_VERSION").write_text("1.0.0\n", encoding="utf-8")
        (repo / "_base" / "00-CLAUDE-STOP.md").write_text("x", encoding="utf-8")
        (repo / "_base" / "INFRA-UPDATES.md").write_text(
            "# п\n\n## v1.0.0 — 15.09.2026 — тест\n\n- что-то\n", encoding="utf-8")
        probs = d.problems()
        assert len(probs) == 1 and "не прочитаны" in probs[0], probs
        (repo / ".infra-updates-read").write_text("1.0.0", encoding="utf-8")
        assert RepoDelivery(repo, "1.0.0", "1.0.0").problems() == []

        # отставшая версия ловится, устаревший патчноут — тоже
        old = RepoDelivery(repo, "2.0.0", "2.0.0").problems()
        assert any("правила: 1.0.0" in p for p in old), old
        assert any("новости: свежая 1.0.0" in p for p in old), old

        # публичная репа исключается, а не считается провалом
        pub = root / "p"
        pub.mkdir()
        (pub / ".repo-meta").write_text('{"private": false}', encoding="utf-8")
        assert not expects_base(pub, None)
        assert not expects_base(pub, {"other"}), "публичная по gh — не ждёт базы"
        assert expects_base(pub, {"p"}), "приватная по gh — ждёт базу"
        (pub / ".repo-class").write_text("archived", encoding="utf-8")
        assert not expects_base(pub, {"p"}), "архивная не ждёт базы даже приватной"
    print("🟢 selftest: отсутствие канала ловится, отставание версии и патчноута ловится, "
          "непрочитанное отличается от недоставленного, публичные репы исключаются")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    canon = canon_version()
    canon_note = latest_note(BASE / "INFRA-UPDATES.md")
    private = private_names()
    if private is None:
        print("🟡 gh недоступен — публичность определяется по .repo-meta, "
              "публичные репы могут попасть в отчёт ложно\n")
    rows: list[tuple[Path, list[str]]] = []
    skipped = 0
    for repo in sorted(p for p in REPOS.iterdir() if p.is_dir() and p.name != BASE.name):
        if not (repo / ".repo-id").is_file():
            continue
        if not expects_base(repo, private):
            skipped += 1
            continue
        rows.append((repo, RepoDelivery(repo, canon, canon_note).problems()))

    # 🔴 ТРИ СОСТОЯНИЯ, А НЕ ДВА. «Доставлено, но не прочитано» — НОРМА: вахта
    # в эту репу просто ещё не заходила, и новость ждёт её на входе. Считать
    # это замечанием значит красить 57 реп из 57 в жёлтый после каждого
    # патчноута — отчёт, где всё жёлтое, читать перестают.
    bad = [(r, p) for r, p in rows if any(x.startswith("🔴") for x in p)]
    warn = [(r, p) for r, p in rows
            if any(x.startswith("🟡") for x in p) and (r, p) not in bad]
    unread = [r for r, p in rows if any(x.startswith("⚪️") for x in p)]
    for repo, probs in (rows if a.all else bad + warn):
        if probs or a.all:
            print(f"{repo.name}")
            for p in probs or ["🟢 всё доставлено"]:
                print(f"   {p}")

    glob = global_channel()
    if glob:
        print("\nобщие каналы:")
        for g in glob:
            print(f"   {g}")

    print(f"\nреп под доставкой: {len(rows)} · 🟢 доставлено полностью: "
          f"{len(rows) - len(bad) - len(warn)} · 🟡 отстают: {len(warn)}"
          f" · 🔴 не доставлено: {len(bad)}"
          f" · вне доставки (публичные/архивные): {skipped}")
    if unread:
        print(f"⚪️ ждут прочтения на входе в репу: {len(unread)} — это норма, "
              "а не замечание: вахта туда ещё не заходила")
    print(f"канон: v{canon} · свежий патчноут: v{canon_note or '—'}")
    return 1 if bad or any(g.startswith("🔴") for g in glob) else 0


if __name__ == "__main__":
    sys.exit(main())
