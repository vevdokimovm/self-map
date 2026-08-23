#!/usr/bin/env python3
"""Есть ли сигнал нагрузки в собственных логах: задержка ответа по часам суток.

ЧТО МЕРИМ. Цена хода в токенах — арифметика, от нагрузки зависеть не может.
Зависеть может ЗАДЕРЖКА. Если она гуляет по часам — фактор существует и наблюдаем.

КАК. По каждой реплике ассистента берём её timestamp и timestamp предыдущей записи
пользователя/инструмента; разница = время ответа. Дедуп по message.id (PIT-H).
Группируем по часу UTC. Считаем медиану, а не среднее: один тяжёлый ход перекосит среднее.
"""
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

LOGDIR = Path.home() / ".claude" / "projects"


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def probe(path):
    seen, rows, prev_ts = set(), [], None
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = r.get("timestamp")
            if not ts:
                continue
            role = (r.get("message") or {}).get("role")
            mid = (r.get("message") or {}).get("id")
            if role == "assistant" and mid:
                if mid in seen:
                    continue
                seen.add(mid)
                if prev_ts:
                    dt = (parse(ts) - prev_ts).total_seconds()
                    usage = (r.get("message") or {}).get("usage") or {}
                    out = usage.get("output_tokens", 0)
                    if 0 < dt < 600:                      # отсекаем паузы владельца
                        rows.append((parse(ts), dt, out))
            prev_ts = parse(ts)
    return rows


logs = sorted(LOGDIR.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:6]
allrows = []
print("ЛОГИ:")
for p in logs:
    r = probe(p)
    if r:
        print(f"  {len(r):5} реплик  {r[0][0]:%m-%d %H:%M}…{r[-1][0]:%m-%d %H:%M}  {p.parent.name[-28:]}/{p.name[:8]}")
        allrows += r

print(f"\nВСЕГО реплик с задержкой: {len(allrows)}")
if not allrows:
    raise SystemExit("нет данных")

byhour = defaultdict(list)
for ts, dt, out in allrows:
    byhour[ts.hour].append((dt, out))

print("\nЗАДЕРЖКА ПО ЧАСАМ (UTC). с/ток — нормировано на объём выхода:")
print(f"{'час':>4} {'реплик':>7} {'медиана с':>10} {'медиана с/1к ток':>18}")
norm = {}
for h in sorted(byhour):
    v = byhour[h]
    if len(v) < 8:
        continue
    med = statistics.median(d for d, _ in v)
    per = [d / (o / 1000) for d, o in v if o > 50]
    medper = statistics.median(per) if per else float("nan")
    norm[h] = medper
    print(f"{h:>4} {len(v):>7} {med:>10.1f} {medper:>18.1f}")

if len(norm) >= 3:
    lo, hi = min(norm, key=norm.get), max(norm, key=norm.get)
    print(f"\nразмах нормированной задержки: час {lo} = {norm[lo]:.1f} с/1к  ·  "
          f"час {hi} = {norm[hi]:.1f} с/1к  ·  отношение ×{norm[hi]/norm[lo]:.2f}")
    print("🔴 отношение близко к 1 — сигнала нагрузки в этих данных нет;")
    print("   отношение заметно больше 1 — фактор есть, но подтверждать надо на большем ряде.")
