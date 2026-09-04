#!/usr/bin/env python3
"""quality_per_token.py — сколько находок приходится на 100K потраченных токенов.

🔴 ПОВОД — `ROADMAP` §P1.6b и `66` §3в. Заказ владельца 21.08.2026 дословно:
без показателя «оптимизация обсуждается на вкус». Определение было записано
тогда же, а снималось **вручную**, и роадмап ставил условие: собирать
в инструмент, «когда ручной подсчёт станет узким местом, не раньше».

**Условие наступило и проверяемо числом:** 04.09.2026 закрыто **28 батчей
за 4 часа 20 минут**. Ручной проход по каждому — уже не «несколько минут
раз в несколько батчей».

ЧТО СЧИТАЕТСЯ:

    находок на 100K = находки батча / (потрачено токенов / 100 000)

🔴 ЗНАМЕНАТЕЛЬ ИЗМЕНЁН ПРОТИВ ИСХОДНОГО ОПРЕДЕЛЕНИЯ, и это не описка.
`66` §3в говорил «прирост КОНТЕКСТА между двумя записями `batch`». Так
считать нельзя: при компакте контекст падает с миллиона до двадцати тысяч,
и прирост становится **отрицательным** — батч, попавший на компакт, получил
бы бесконечное качество. Замер этой сессии: два компакта на 1740 ходов.

Считается **потраченное**: `output + cache_creation + input` по ходам,
попавшим в окно батча. Кэш-чтение в знаменатель не входит — оно почти
бесплатно (`49` §4.4), и включать его значило бы наказывать за длинную
сессию, которая как раз и экономит.

🔴 ЧИСЛИТЕЛЬ — ПРОКСИ, И ЕГО УСЛОВИЕ НАЗВАНО (`28` §5в-бис).
Находка считается по секции `CHANGELOG` этого батча: блоки `🔴` плюс
уникальные ссылки на карточки `PIT-NNN`/`SYN-NNN`. Это работает, **пока
вахта помечает находки красным маркером** — соглашение, а не закон природы.
Перестанут помечать — числитель молча уедет в ноль, и по одному числу
это будет неотличимо от плохой работы.

ЧЕГО ИНСТРУМЕНТ НЕ ДЕЛАЕТ:
  · не судит о ВАЖНОСТИ находки — считается существование записи, как
    в реестрах `PIT`/`SYN`. Вес вручную не оценивается намеренно;
  · не сравнивает вахты между собой: у разных задач разная плотность
    находок по построению, и низкое число на механическом батче — норма;
  · не заменяет чтение. Число отвечает «где смотреть», а не «где плохо».

ЗАПУСК:
    python3 scripts/quality_per_token.py              # последние 15 батчей
    python3 scripts/quality_per_token.py --all        # все, что нашлись в логе
    python3 scripts/quality_per_token.py --selftest
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402

BASE_REPO, REPOS, _ = resolve_roots(__file__)
AUTO_LOG = BASE_REPO / "06-autonomous-mode-kit/runs/auto.log"
CHANGELOG = BASE_REPO / "CHANGELOG.md"
SESSIONS = Path.home() / ".claude/projects"

VER_RE = re.compile(r"^v?(\d+\.\d+\.\d+)")
CARD_RE = re.compile(r"\b(?:PIT|SYN)-\d+")


def batches(repo: str = "base-repo") -> list[tuple[datetime, str]]:
    """(время, версия) по строкам `batch` журнала прогона, по возрастанию."""
    out: list[tuple[datetime, str]] = []
    if not AUTO_LOG.is_file():
        return out
    for line in AUTO_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) != 4 or parts[1] != repo or parts[2] != "batch":
            continue
        m = VER_RE.match(parts[3])
        if not m:
            continue
        try:
            out.append((datetime.fromisoformat(parts[0]), m.group(1)))
        except ValueError:
            continue
    return out


def findings_by_version() -> dict[str, int]:
    """Находки по секциям `CHANGELOG`: блоки 🔴 плюс уникальные карточки."""
    out: dict[str, int] = {}
    if not CHANGELOG.is_file():
        return out
    text = CHANGELOG.read_text(encoding="utf-8", errors="replace")
    for chunk in re.split(r"^## \[", text, flags=re.M)[1:]:
        ver = chunk.split("]", 1)[0].strip()
        body = chunk
        out[ver] = body.count("🔴") + len(set(CARD_RE.findall(body)))
    return out


def spend_series() -> list[tuple[datetime, int]]:
    """(время хода, потрачено токенов) по логам всех сессий проекта.

    🔴 Задвоение строк лога — известное свойство (`session_metrics.py`):
    одна реплика пишется несколько раз. Дедуп по `message.id`, иначе
    знаменатель раздувается в 1.8 раза и качество занижается во столько же.
    """
    seen: set[str] = set()
    out: list[tuple[datetime, int]] = []
    if not SESSIONS.is_dir():
        return out
    for f in SESSIONS.rglob("*.jsonl"):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            if '"usage"' not in line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get("message") or {}
            usage = msg.get("usage") or {}
            mid = msg.get("id")
            if not usage or (mid and mid in seen):
                continue
            if mid:
                seen.add(mid)
            ts = rec.get("timestamp")
            if not ts:
                continue
            try:
                when = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                continue
            spent = (int(usage.get("output_tokens") or 0)
                     + int(usage.get("cache_creation_input_tokens") or 0)
                     + int(usage.get("input_tokens") or 0))
            if spent:
                out.append((when, spent))
    out.sort()
    return out


def rows(limit: int | None) -> list[dict]:
    bs = batches()
    if len(bs) < 2:
        return []
    finds = findings_by_version()
    series = spend_series()
    res: list[dict] = []
    for (t0, _), (t1, ver) in zip(bs, bs[1:]):
        spent = sum(v for w, v in series if t0 < w <= t1)
        mins = (t1 - t0).total_seconds() / 60
        n = finds.get(ver, 0)
        res.append({"ver": ver, "min": mins, "spent": spent, "find": n,
                    "per100k": (n / (spent / 100_000)) if spent else None})
    return res[-limit:] if limit else res


def selftest() -> int:
    """Канарейка на ОБА конца: и на разбор журнала, и на арифметику.

    🔴 Отдельный случай на компакт: прежнее определение (прирост контекста)
    дало бы отрицательный знаменатель, и проверка обязана показывать, что
    новое определение этого не делает.
    """
    ok = True
    cases = [
        ("находки считаются", "## [1.0.0]\n🔴 раз\n🔴 два\nсм. PIT-001\n", 3),
        ("одна карточка дважды — одна находка",
         "## [1.0.0]\nPIT-001 и снова PIT-001\n", 1),
        ("пустая секция — ноль", "## [1.0.0]\nпросто текст\n", 0),
    ]
    import tempfile
    global CHANGELOG
    real = CHANGELOG
    try:
        for name, text, expect in cases:
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "CHANGELOG.md"
                p.write_text(text, encoding="utf-8")
                CHANGELOG = p
                got = findings_by_version().get("1.0.0")
                mark = "✅" if got == expect else "🔴"
                print(f"   {mark} {name}: {got} (ждали {expect})")
                ok &= got == expect
    finally:
        CHANGELOG = real
    # Арифметика: 3 находки на 150 000 токенов = 2.0 на 100K
    got = 3 / (150_000 / 100_000)
    mark = "✅" if abs(got - 2.0) < 1e-9 else "🔴"
    print(f"   {mark} арифметика: {got:.2f} на 100K при 3 находках и 150K токенов")
    ok &= abs(got - 2.0) < 1e-9
    print("selftest OK" if ok else "🔴 selftest ПРОВАЛЕН")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="все батчи, не последние 15")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    data = rows(None if a.all else 15)
    if not data:
        print("Батчей в журнале меньше двух — считать нечего.")
        return 0

    print("═══ Находок на 100K потраченных токенов ═══\n")
    print(f"  {'версия':<12}{'мин':>6}{'потрачено':>12}{'находок':>9}{'на 100K':>10}")
    measured = [r for r in data if r["spent"]]
    for r in data:
        per = f"{r['per100k']:.1f}" if r["per100k"] is not None else "—"
        print(f"  {r['ver']:<12}{r['min']:>6.0f}{r['spent']:>12,}{r['find']:>9}{per:>10}"
              .replace(",", " "))
    if measured:
        vals = sorted(r["per100k"] for r in measured)
        med = vals[len(vals) // 2]
        print(f"\n  медиана: {med:.1f} находок на 100K · замеров {len(measured)}")
    if len(measured) < len(data):
        print(f"  🔴 без замера: {len(data) - len(measured)} — ходы вне логов сессий")
    print("\n🔴 Числитель — ПРОКСИ: считается пометка 🔴 и ссылка на карточку.")
    print("   Перестанут помечать — число уедет в ноль, и это будет")
    print("   неотличимо от плохой работы (`28` §5в-бис).")
    print("🔴 Число отвечает «где смотреть», а не «где плохо»: у механического")
    print("   батча низкая плотность находок — норма, а не провал.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
