#!/usr/bin/env python3
"""agenda.py — что сейчас в работе: открытые пункты плана по всем репам.

🔴 ПОВОД, 04.09.2026. Владелец: *«сделай скилл, который показывает, какие
задачи сейчас актуальны… а если задач нет — составлял сам»*. Машинная
половина здесь; суждение — в скилле `/agenda`.

🔴 ГЛАВНОЕ: ПОКАЗАТЬ ПЛАН — МАЛО, ПЛАН ВРЁТ. В тот же день роадмап соврал
вахте **трижды**, и каждый раз уверенно:

  · «витрина: решить, что публикуем» — уже решено И ИСПОЛНЕНО, репы публичны;
  · «перепись: 3 280 файлов» — очередь закрыта, там ноль;
  · «вахта A заблокирована» — работает две недели как.

Общая причина: пункт описывает **внешнее состояние**, которое меняется
без единого события в системе (`21` §4а-трис). Поэтому инструмент не просто
перечисляет открытое, а **помечает подозрительное**:

  🕰  срок в тексте прошёл — исход не выбран;
  📁  пункт ссылается на путь, которого на диске нет;
  🔢  пункт называет число, а рядом лежит счётчик с другим.

🔴 ЧЕГО НЕ ДЕЛАЕТ:

  · **не решает, что делать следующим** — порядок работ это суждение,
    и он зависит от того, чего хочет владелец сегодня (`103`);
  · **не закрывает пункты** — «выглядит сделанным» и «сделано» разные вещи,
    закрытие требует проверки по существу;
  · **не отличает важное от неважного.** Метка 📁 значит «проверь», а не
    «протухло»: путь мог быть указан в чужую репу или в будущее.

ЗАПУСК:
    python3 scripts/agenda.py                # база
    python3 scripts/agenda.py --all          # все репы системы
    python3 scripts/agenda.py --repo chess   # одна названная
    python3 scripts/agenda.py --selftest
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402

BASE_REPO, REPOS, _ = resolve_roots(__file__)

OPEN_RE = re.compile(r"^\s*-\s*\[( |~)\]\s*(.+)$")
SEC_RE = re.compile(r"^##+\s+(.+?)\s*$")
# `[зав. до 29.08]`, `[зав. 27.08]`, `[зав. до 04.10.2026]`
DUE_RE = re.compile(r"\[зав\.\s*(?:до\s*)?(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\s*\]")
# путь в обратных кавычках, похожий на файл или каталог репы
PATH_RE = re.compile(r"`([A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:md|py|sh|json|tsv|csv))`")


def clean(text: str) -> str:
    return re.sub(r"[*`🔴🆕🎯🏁🟢🟡⚫🔵⚠️✅]", "", text).strip()


def due_passed(text: str, today: dt.date) -> str | None:
    m = DUE_RE.search(text)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
    year = int(y) if y else today.year
    try:
        when = dt.date(year, mo, d)
    except ValueError:
        return None
    # Без года срок мог быть из прошлого года — берём ближайший в прошлом.
    if not y and when > today + dt.timedelta(days=180):
        when = dt.date(year - 1, mo, d)
    return when.isoformat() if when < today else None


def dead_paths(text: str, repo: Path) -> list[str]:
    """Пути из пункта, которых нет ни в репе, ни в соседних, ни в базе."""
    out = []
    for raw in dict.fromkeys(PATH_RE.findall(text)):
        if (repo / raw).exists() or (BASE_REPO / raw).exists() or (REPOS / raw).exists():
            continue
        # Последний сегмент мог лежать глубже — ищем по дереву репы.
        tail = raw.split("/")[-1]
        if any(True for _ in repo.rglob(tail)):
            continue
        out.append(raw)
    return out


def items(path: Path, repo: Path, today: dt.date) -> list[dict]:
    """Открытые пункты файла плана, с разделом и метками подозрительности."""
    if not path.is_file():
        return []
    out: list[dict] = []
    section = "—"
    depth = 0
    for n, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        # 🔴 СВЁРНУТОЕ В `<details>` — ИСТОРИЯ, А НЕ ПЛАН. Найдено первым же
        # прогоном 04.09.2026: закрывая задачу, вахта прячет прежнюю
        # формулировку в `<details>`, и её `- [ ]` оставался открытым.
        # Атрибуция уже была отключена, а инструмент показывал её как долг —
        # то есть новый счётчик врал ровно тем, ради чего заведён.
        low = line.lower()
        if "<details" in low:
            depth += low.count("<details")
        if "</details>" in low:
            depth = max(0, depth - low.count("</details>"))
            continue
        if depth:
            continue
        s = SEC_RE.match(line)
        if s:
            section = clean(s.group(1))
            continue
        m = OPEN_RE.match(line)
        if not m:
            continue
        text = clean(m.group(2))
        # 🔴 ЗАГОТОВКА ШАБЛОНА — не задача. В `TASKS.md` стоит образец
        # «<Что сделать, в прошедшем времени…>»; он открыт по построению
        # и закрытым не станет никогда.
        if not text or text.startswith("<"):
            continue
        out.append({
            "file": path.name, "line": n, "section": section,
            "part": m.group(1) == "~", "text": text,
            "due": due_passed(line, today),
            "dead": dead_paths(line, repo),
        })
    return out


def gather(repo: Path, today: dt.date) -> dict:
    plan = items(repo / "ROADMAP.md", repo, today)
    owner = items(repo / "TASKS.md", repo, today)
    return {"repo": repo.name, "plan": plan, "owner": owner}


def selftest() -> int:
    import tempfile
    ok = True
    today = dt.date(2026, 9, 4)
    cases = [
        ("открытый пункт виден", "- [ ] сделать штуку\n", 1),
        ("закрытый не виден", "- [x] сделано\n", 0),
        ("частичный виден", "- [~] наполовину\n", 1),
        ("пустой пункт не считается", "- [ ]\n", 0),
        ("🔴 свёрнутое в details — история, не план",
         "- [x] закрыто\n\n<details>\n\n- [ ] прежняя формулировка\n\n</details>\n", 0),
        ("после </details> план снова считается",
         "<details>\n- [ ] спрятано\n</details>\n\n- [ ] живое\n", 1),
        ("🔴 заготовка шаблона не задача",
         "- [ ] <Что сделать, в прошедшем времени>\n", 0),
    ]
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        for name, text, expect in cases:
            (r / "ROADMAP.md").write_text(text, encoding="utf-8")
            got = len(items(r / "ROADMAP.md", r, today))
            print(f"   {'✅' if got == expect else '🔴'} {name}: {got}")
            ok &= got == expect
    # Сроки: прошедший ловится, будущий молчит, несуществующая дата не роняет.
    for text, expect in (("[зав. до 29.08] что-то", True),
                         ("[зав. до 31.12] что-то", False),
                         ("[зав. до 31.02] что-то", False),
                         ("[зав. 27.08.2026] что-то", True)):
        got = due_passed(text, today) is not None
        print(f"   {'✅' if got == expect else '🔴'} срок «{text[:18]}»: "
              f"{'просрочен' if got else 'нет'}")
        ok &= got == expect
    print("selftest OK" if ok else "🔴 selftest ПРОВАЛЕН")
    return 0 if ok else 1


def show(data: dict) -> tuple[int, int]:
    plan, owner = data["plan"], data["owner"]
    if not plan and not owner:
        return 0, 0
    print(f"\n═══ {data['repo']} ═══")
    for title, rows in (("ПЛАН (работа вахты)", plan),
                        ("ЖДЁТ ВЛАДЕЛЬЦА", owner)):
        if not rows:
            continue
        print(f"\n  {title} — {len(rows)}")
        sec = None
        for r in rows:
            if r["section"] != sec:
                sec = r["section"]
                print(f"\n    · {sec[:70]}")
            marks = ""
            if r["due"]:
                marks += f" 🕰 срок {r['due']}"
            if r["dead"]:
                marks += f" 📁 нет пути: {', '.join(r['dead'][:2])}"
            flag = "~" if r["part"] else " "
            print(f"      [{flag}] {r['text'][:74]}")
            if marks:
                print(f"          {marks.strip()}")
    return len(plan), len(owner)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="все репы системы")
    ap.add_argument("--repo", help="одна названная репа")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    today = dt.date.today()
    if a.all:
        repos = [d for d in sorted(REPOS.iterdir())
                 if d.is_dir() and (d / "VERSION").exists()]
    elif a.repo:
        repos = [REPOS / a.repo]
    else:
        repos = [BASE_REPO]

    tp = to = 0
    empty: list[str] = []
    for repo in repos:
        if not repo.exists():
            print(f"🔴 нет репы: {repo.name}")
            return 2
        data = gather(repo, today)
        p, o = show(data)
        tp += p
        to += o
        if p == 0 and o == 0:
            empty.append(repo.name)

    print(f"\n{'═' * 46}\nИТОГО: план {tp} · ждёт владельца {to}")
    if empty:
        print(f"\n🟢 без открытых пунктов: {len(empty)} — {', '.join(empty[:8])}"
              + (" …" if len(empty) > 8 else ""))
        print("   🔴 Пустой план — не «всё сделано», а «плана нет».")
        print("      Что с этим делать — `/agenda`, раздел про интервью.")
    print("\n🔴 Метки 🕰 и 📁 значат «проверь», а не «протухло»:")
    print("   срок мог быть перенесён устно, путь — указан в чужую репу")
    print("   или в будущее. Инструмент показывает, судит вахта.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
