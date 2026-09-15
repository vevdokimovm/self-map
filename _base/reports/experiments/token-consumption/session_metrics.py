#!/usr/bin/env python3
"""
session_metrics.py — вынимает эмпирику расхода токенов из ЛОГА сессии Claude Code.

Место в системе: `analyze.py` читает `measurements.csv` и пересобирает модель;
этот скрипт — шаг раньше, он **производит строку** для `measurements.csv` из сырого
`~/.claude/projects/<проект>/<сессия>.jsonl`.

Почему скриптом, а не промптом. Замер делался руками трижды (20.08, 21.08 ×2), каждый раз
заново, и каждый раз вахта переоткрывала одни и те же вопросы: где лог, как считать контекст,
что такое цена хода. Один раз записанный расчёт стоит одну команду и, главное, **даёт
сопоставимые числа между вахтами** — руками пересчитанное сравнивать нельзя.

Инструмент ПЕРЕЧИСЛЯЕТ И СЧИТАЕТ. Решения (что записать в `hypothesis.md`, какую строку
считать подтверждением, а какую опровержением) принимает вахта.

🔴 ПОТОЛОК, названный вслух (`71` §7г-бис):
  · Расход СУБАГЕНТОВ в лог родителя не попадает — записей `isSidechain=true` в логах
    вахт VI/VII ноль при потраченных 191 487 токенах. Скрипт честно печатает 0 и говорит,
    что это значит: считать делегирование по этому логу НЕЛЬЗЯ, нужны логи самих агентов
    либо парсинг task-уведомлений.
  · Падение контекста до нуля скрипт различить не умеет: `auto-compact` и рестарт сессии
    выглядят одинаково. Печатается факт падения и ход, вывод делает вахта.
  · «Цена хода» — условные единицы по формуле из `hypothesis.md`, не деньги и не проценты
    лимита. Сравнивать можно только с числами, посчитанными этой же формулой.

Запуск:
    python3 session_metrics.py                    # свежий лог проекта текущей папки
    python3 session_metrics.py --list             # какие логи вообще есть
    python3 session_metrics.py <path.jsonl>
    python3 session_metrics.py --csv              # только готовая строка для measurements.csv

Только стандартная библиотека.
"""
import json
import os
import sys
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
BUCKET = 25_000

# Формула условной цены хода — та же, что в hypothesis.md и в замерах 20–21.08.
# Менять её нельзя, не пересчитав все прошлые строки: иначе числа перестанут быть сравнимы.
COST = {"cache_read": 0.1, "cache_creation": 2.0, "input": 1.0, "output": 1.0}


def find_logs(cwd: Path) -> list[Path]:
    """Логи проекта текущей папки; если таких нет — все, по свежести."""
    if not PROJECTS.is_dir():
        return []
    slug = str(cwd).replace("/", "-")
    own = sorted(PROJECTS.glob(f"{slug}/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if own:
        return own
    return sorted(PROJECTS.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)


def pick_log(found: list[Path]) -> Path:
    """Выбрать лог текущей сессии — и сделать неоднозначность ВИДИМОЙ.

    🔴 PIT-118. Одна сессия может писаться в ДВА файла с разными `sessionId`
    (обёртка фонового джоба и сессия). Прежний выбор — «самый свежий по mtime» —
    молча взял не тот: срез показал 106 ходов вместо 126 и hit 98.7 % вместо 97.7 %,
    и числа успели уехать в `measurements.csv`.

    Канарейка `--selftest` при этом была зелёной: она проверяет **арифметику**
    свёртки задвоенных строк и про выбор источника не знает ничего. Измеритель
    доказывал, что правильно считает, и молчал о том, что считает не то.

    Два лечения, оба дешёвые:
    1. `$CLAUDE_JOB_DIR` даёт id текущего джоба — если лог с таким именем есть,
       он и есть источник, mtime тут не судья;
    2. если рядом лежит второй свежий лог, он **называется вслух** с числом строк.
       Неоднозначность, показанная в выводе, перестаёт быть тихой.
    """
    # CLAUDE_JOB_DIR указывает на сам каталог джоба (…/jobs/<id>), поэтому id —
    # это `.name`. Первая редакция брала `.parent.name` и получала «jobs»:
    # ветка не срабатывала никогда и молча падала в выбор по mtime — то есть
    # починка PIT-118 существовала только на бумаге, ровно как `21` §4г.
    job = os.environ.get("CLAUDE_JOB_DIR", "")
    job_id = Path(job).name if job else ""
    if job_id:
        for p in found:
            if p.stem.startswith(job_id):
                if len(found) > 1:
                    print(f"[выбор лога] по CLAUDE_JOB_DIR: {p.name}")
                return p

    chosen = found[0]
    rivals = [p for p in found[1:3]
              if abs(p.stat().st_mtime - chosen.stat().st_mtime) < 900]
    if rivals:
        print("🔴 РЯДОМ ЕЩЁ СВЕЖИЕ ЛОГИ — возможно, сессия пишется в несколько файлов.")
        print(f"   выбран:  {chosen.name}  ({chosen.stat().st_size // 1024} КБ)")
        for p in rivals:
            print(f"   рядом:   {p.name}  ({p.stat().st_size // 1024} КБ)")
        print("   Сверь числа по обоим (путь можно передать аргументом) — PIT-118.\n")
    return chosen


def read_turns(path: Path) -> tuple[list[dict], list[dict], dict]:
    """Возвращает (ходы главного треда, ходы субагентов, служебные факты)."""
    main, side = [], []
    seen_ids: set[str] = set()
    meta = {"models": {}, "efforts": {}, "attachments": 0, "versions": set(),
            "api_errors": 0, "lines": 0, "bad_lines": 0, "dup_records": 0}
    for line in path.open(encoding="utf-8", errors="replace"):
        meta["lines"] += 1
        try:
            d = json.loads(line)
        except Exception:
            meta["bad_lines"] += 1
            continue
        # ВНИМАНИЕ: считаются ВСЕ записи с полем attachment, включая служебные
        # напоминания среды, а не только присланные владельцем файлы. Это прокси,
        # а не счётчик вложений: для пункта backlog §5.4 нужен разбор по типам.
        # 🟢 Компакт НЕ надо угадывать по падению контекста: CLI пишет явный маркер.
        # Найдено 21.08.2026 — снимает неоднозначность «компакт или рестарт».
        if d.get("type") == "system" and d.get("subtype") == "compact_boundary":
            cm = d.get("compactMetadata") or {}
            meta.setdefault("compacts", []).append({
                "ts": d.get("timestamp", "")[:19],
                "trigger": cm.get("trigger"),
                "pre": cm.get("preTokens"),
                "post": cm.get("postTokens"),
                "dropped": cm.get("cumulativeDroppedTokens"),
                "sec": (cm.get("durationMs") or 0) / 1000,
                "kept": len((cm.get("preservedMessages") or {}).get("uuids") or []),
            })
        if d.get("attachment") is not None:
            meta["attachments"] += 1
        if d.get("version"):
            meta["versions"].add(d["version"])
        if d.get("isApiErrorMessage"):
            meta["api_errors"] += 1
        msg = d.get("message") or {}
        usage = msg.get("usage")
        if not usage or d.get("type") != "assistant":
            continue
        # Отказ по лимиту тоже приходит как assistant+usage (поле quotaLimits,
        # isApiErrorMessage=true). Это не ход: он ничего не сделал и портит
        # и счёт ходов, и среднюю цену. Найдено 21.08.2026 при сборке limits_watch.
        if d.get("isApiErrorMessage") or d.get("quotaLimits"):
            continue
        # 🔴 ОДНА реплика пишется в лог НЕСКОЛЬКИМИ строками (по строке на блок
        # содержимого: текст, каждый tool_use), и КАЖДАЯ несёт одинаковый usage.
        # Суммировать их — значит завысить и число ходов, и весь расход: замер
        # 21.08.2026 по шести логам дал коэффициент задвоения x1.64...x2.24.
        # Ключ дедупликации — message.id: он общий у строк одной реплики.
        mid = msg.get("id")
        if mid is not None:
            if mid in seen_ids:
                meta["dup_records"] += 1
                continue
            seen_ids.add(mid)

        model = msg.get("model") or "unknown"
        meta["models"][model] = meta["models"].get(model, 0) + 1
        if d.get("effort"):
            meta["efforts"][d["effort"]] = meta["efforts"].get(d["effort"], 0) + 1
        cc = usage.get("cache_creation") or {}
        turn = {
            "input": usage.get("input_tokens", 0) or 0,
            "read": usage.get("cache_read_input_tokens", 0) or 0,
            "create": usage.get("cache_creation_input_tokens", 0) or 0,
            "output": usage.get("output_tokens", 0) or 0,
            "thinking": (usage.get("output_tokens_details") or {}).get("thinking_tokens", 0) or 0,
            "ttl_1h": cc.get("ephemeral_1h_input_tokens", 0) or 0,
            "ttl_5m": cc.get("ephemeral_5m_input_tokens", 0) or 0,
            "model": model,
        }
        turn["context"] = turn["input"] + turn["read"] + turn["create"]
        turn["cost"] = (turn["read"] * COST["cache_read"] + turn["create"] * COST["cache_creation"]
                        + turn["input"] * COST["input"] + turn["output"] * COST["output"])
        (side if d.get("isSidechain") else main).append(turn)
    return main, side, meta


def slope(ys: list[float]) -> float:
    """МНК-наклон по номеру хода. Без numpy — формула в две строки."""
    n = len(ys)
    if n < 2:
        return 0.0
    mx = (n - 1) / 2
    my = sum(ys) / n
    num = sum((i - mx) * (y - my) for i, y in enumerate(ys))
    den = sum((i - mx) ** 2 for i in range(n))
    return num / den if den else 0.0


def drops(turns: list[dict], factor: float = 0.5) -> list[tuple[int, int, int]]:
    """Ходы, где контекст упал более чем вдвое: auto-compact ИЛИ рестарт — не различаем."""
    out = []
    for i in range(1, len(turns)):
        prev, cur = turns[i - 1]["context"], turns[i]["context"]
        if prev > 50_000 and cur < prev * factor:
            out.append((i + 1, prev, cur))
    return out


def buckets(turns: list[dict]) -> list[tuple[int, int, float, float]]:
    """(нижняя граница бакета, число ходов, средняя цена, средний cache_read)."""
    acc: dict[int, list[dict]] = {}
    for t in turns:
        acc.setdefault(t["context"] // BUCKET * BUCKET, []).append(t)
    return [(lo, len(v), sum(x["cost"] for x in v) / len(v), sum(x["read"] for x in v) / len(v))
            for lo, v in sorted(acc.items())]


def fmt(n: float) -> str:
    return f"{int(round(n)):,}".replace(",", " ")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}

    if "--list" in flags:
        for p in find_logs(Path.cwd())[:15]:
            print(f"{p.stat().st_size // 1024:>7} КБ  {p}")
        return 0

    if args:
        path = Path(args[0]).expanduser()
    else:
        found = find_logs(Path.cwd())
        if not found:
            print("Логов не найдено. Проверь ~/.claude/projects/ или укажи путь явно.",
                  file=sys.stderr)
            return 1
        path = pick_log(found)
    if not path.is_file():
        print(f"нет файла: {path}", file=sys.stderr)
        return 1

    main_turns, side_turns, meta = read_turns(path)
    if not main_turns:
        print(f"в {path.name} нет ходов с usage — это не лог сессии?", file=sys.stderr)
        return 1

    ctx = [t["context"] for t in main_turns]
    read = sum(t["read"] for t in main_turns)
    create = sum(t["create"] for t in main_turns)
    fresh = sum(t["input"] for t in main_turns)
    out_tok = sum(t["output"] for t in main_turns)
    think = sum(t["thinking"] for t in main_turns)
    ttl1h = sum(t["ttl_1h"] for t in main_turns)
    ttl5m = sum(t["ttl_5m"] for t in main_turns)
    hit = read / (read + create) * 100 if (read + create) else 0.0
    model = max(meta["models"], key=meta["models"].get).replace("claude-", "")
    effort = max(meta["efforts"], key=meta["efforts"].get) if meta["efforts"] else "unknown"
    bk = buckets(main_turns)
    falls = drops(main_turns)

    csv_note = (
        f"лог {path.name}: {len(main_turns)} ходов главного треда, макс. контекст {max(ctx)}, "
        f"cache_read/creation={read}/{create} -> hit {hit:.1f}%, "
        f"кэш 1h/5m={ttl1h}/{ttl5m}, прирост {slope([float(c) for c in ctx]):.0f} ток/ход, "
        f"цена хода {fmt(bk[0][2])} -> {fmt(bk[-1][2])} усл.ед. "
        f"на контексте {fmt(bk[0][0])}->{fmt(bk[-1][0])}, "
        f"падений контекста {len(falls)}, субагентских записей {len(side_turns)}"
    )
    csv_line = (f"<ДАТА>,code,{model},{effort},{read + create + fresh},{out_tok},,"
                f"{meta['attachments']},{len(main_turns)},warm,{max(ctx)},,,"
                f"<baseline_id>,\"{csv_note}\"")

    if "--csv" in flags:
        print(csv_line)
        return 0

    print(f"ЛОГ: {path}")
    print(f"     строк {meta['lines']}, нечитаемых {meta['bad_lines']}, "
          f"версии CLI: {', '.join(sorted(meta['versions'])) or '—'}")
    print(f"\nМОДЕЛЬ: {', '.join(f'{k} ×{v}' for k, v in sorted(meta['models'].items(), key=lambda x: -x[1]))}")
    print(f"EFFORT: {', '.join(f'{k} ×{v}' for k, v in meta['efforts'].items()) or 'в логе не размечен'}")
    dup = meta.get("dup_records", 0)
    if dup:
        tot_rec = len(main_turns) + len(side_turns) + dup
        print(f"\nЗАДВОЕНИЕ ЛОГА: {tot_rec} записей → {tot_rec - dup} реплик "
              f"(×{tot_rec / (tot_rec - dup):.2f}); {dup} повторных строк отброшено")

    print(f"\nХОДОВ главного треда: {len(main_turns)}   записей с attachment: {meta['attachments']}"
          f"   ошибок API: {meta['api_errors']}")
    print(f"КОНТЕКСТ: макс {fmt(max(ctx))}, медиана {fmt(sorted(ctx)[len(ctx)//2])}, "
          f"прирост {slope([float(c) for c in ctx]):.0f} ток/ход")
    if falls:
        print(f"  🔴 ПАДЕНИЙ КОНТЕКСТА: {len(falls)} — сверить с маркером компакта ниже")
        for turn_no, prev, cur in falls[:6]:
            print(f"     ход {turn_no}: {fmt(prev)} -> {fmt(cur)}")
    else:
        print("  ✅ падений контекста нет — потолок сессии не ниже максимума выше")

    comps = meta.get("compacts") or []
    if comps:
        print(f"\nКОМПАКТ: {len(comps)} — маркер compact_boundary, гадать по падению не нужно")
        for c in comps:
            print(f"  {c['ts']}  trigger={c['trigger']}  {c['pre']:,} -> {c['post']:,} ток. "
                  f"за {c['sec']:.0f} c, сохранено сообщений: {c['kept']}".replace(",", " "))
    else:
        print("\nКОМПАКТ: маркеров compact_boundary нет — падения контекста (если есть) "
              "это НЕ компакт")

    if falls and not comps:
        print("     ⚠️  Маркера compact_boundary нет → это НЕ компакция, а рестарт сессии")
    elif falls and comps:
        print("     ✅ Маркер компакта есть — падение объяснено, гадать не нужно")

    print(f"\nКЭШ: read {fmt(read)} · creation {fmt(create)} · hit rate {hit:.1f}%")
    print(f"     TTL записи: 1 час {fmt(ttl1h)} · 5 минут {fmt(ttl5m)}"
          + ("  (дешёвый режим)" if ttl1h >= ttl5m else "  🔴 короткий TTL — вероятен overage"))
    print(f"ВЫХОД: {fmt(out_tok)} токенов, из них thinking {fmt(think)} "
          f"({think / out_tok * 100:.0f}%)" if out_tok else "")
    print(f"НЕКЭШИРОВАННЫЙ вход за всю сессию: {fmt(fresh)}")

    print(f"\nЦЕНА ХОДА по бакетам {BUCKET // 1000}K (усл. ед. по формуле hypothesis.md):")
    print(f"  {'контекст':>12}  {'ходов':>6}  {'цена хода':>12}  {'cache_read':>12}")
    for lo, n, cost, rd in bk:
        print(f"  {fmt(lo):>12}  {n:>6}  {fmt(cost):>12}  {fmt(rd):>12}")
    if len(bk) > 1:
        # 🔴 Считать рост от первого НЕНУЛЕВОГО бакета. Прежняя редакция делила на
        # bk[0] и при нулевой цене печатала «×0.0» — арифметически невозможное число
        # при 10 083 → 72 829. Найдено 23.08.2026: рестарт сессии (`/login`) обнуляет
        # контекст, и создаётся бакет «0» с одним ходом и ценой 0. Он становится
        # первым, деление на него срывается в фолбэк — и фолбэк МОЛЧА выдаёт 0
        # вместо того, чтобы назвать причину.
        base = next(((lo, cost) for lo, _n, cost, _rd in bk if cost > 0), None)
        if base is None:
            print("  → рост цены хода не считается: во всех бакетах цена 0")
        else:
            k = bk[-1][2] / base[1]
            note = "" if base[0] == bk[0][0] else f"  (от первого ненулевого; бакет {fmt(bk[0][0])} пуст — рестарт сессии)"
            print(f"  → рост цены хода на диапазоне {fmt(base[0])}…{fmt(bk[-1][0])}: ×{k:.1f}{note}")
        print("    (форма зависимости действительна ТОЛЬКО на этом диапазоне — 28 §10б)")

    print(f"\nСУБАГЕНТЫ: записей isSidechain в этом логе — {len(side_turns)}")
    if not side_turns:
        print("  🔴 Ноль — это НЕ значит «субагентов не было». Их расход в лог родителя")
        print("     не попадает вовсе; мерить по этому файлу делегирование нельзя.")
    else:
        print(f"  собственный расход: {fmt(sum(t['cost'] for t in side_turns))} усл. ед., "
              f"контекст макс {fmt(max(t['context'] for t in side_turns))}")

    print("\nСТРОКА ДЛЯ measurements.csv (подставить дату и baseline_id):")
    print(csv_line)
    print("\nДальше — руками: сверить с hypothesis.md §3 и §5; подтверждённые 🟢-строки")
    print("без веской причины не переписывать; расхождение записать с датой и источником.")
    return 0


def selftest() -> int:
    """Канарейка: подсовываем заведомо задвоенный лог и требуем, чтобы счёт сошёлся.

    Проверка, которую нельзя провалить, — не проверка (`71` §7в). Поэтому здесь
    не «запускается ли парсер», а именно тот дефект, который был найден 21.08.2026:
    одна реплика в двух строках должна дать ОДИН ход, а не два.
    """
    import tempfile

    def rec(mid, read, create, out, extra=""):
        return ('{"type":"assistant","timestamp":"2026-01-01T00:00:00Z","message":'
                f'{{"id":"{mid}","model":"test","usage":{{"input_tokens":0,'
                f'"cache_read_input_tokens":{read},"cache_creation_input_tokens":{create},'
                f'"output_tokens":{out}}}}}{extra}}}\n')

    fixture = (
        rec("msg_A", 1000, 0, 10)      # реплика A, строка 1 (текст)
        + rec("msg_A", 1000, 0, 10)    # реплика A, строка 2 (tool_use) — ТОТ ЖЕ usage
        + rec("msg_A", 1000, 0, 10)    # реплика A, строка 3
        + rec("msg_B", 2000, 0, 20)    # реплика B
    )
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(fixture)
        tmp = Path(fh.name)
    try:
        turns, _, meta = read_turns(tmp)
    finally:
        tmp.unlink()

    fails = []
    if len(turns) != 2:
        fails.append(f"ходов должно быть 2 (A и B), получено {len(turns)}")
    if meta["dup_records"] != 2:
        fails.append(f"повторных записей должно быть 2, получено {meta['dup_records']}")
    total_read = sum(t["read"] for t in turns)
    if total_read != 3000:
        fails.append(f"cache_read должен быть 3000 (1000+2000), получено {total_read}")
    if meta["models"].get("test") != 2:
        fails.append(f"счётчик модели должен быть 2, получено {meta['models'].get('test')}")

    if fails:
        print("🔴 КАНАРЕЙКА УПАЛА — дедупликация по message.id не работает:")
        for f in fails:
            print(f"   · {f}")
        print("   Без неё замер завышает расход в 1.6–2.2 раза (см. hypothesis.md §3).")
        return 1
    print("✅ канарейка: задвоенный лог свёрнут верно (3 строки + 1 = 2 хода, read 3000)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
