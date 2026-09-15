#!/usr/bin/env python3
"""
limits_watch.py — лимиты как ДАННЫЕ: когда сброс, как часто упираемся, сколько ждать.

Закрывает `ROADMAP.md` §P1.6b («файл, который знает, когда восстанавливаются лимиты»)
и питает §P1.6a (автопродолжение после сброса: чтобы досылать «продолжай», нужно машинное
время сброса, а не строка на экране).

🔴 ГЛАВНОЕ, ЧЕМ ЭТО ОТЛИЧАЕТСЯ ОТ ЗАПИСАННОГО В РОАДМАПЕ.
Роадмап называл источником `/usage` — интерактивную слэш-команду. В headless её нет,
и это делало бы автопродолжение неавтоматизируемым. Фактический источник лучше:
**Claude Code пишет отказ по лимиту прямо в лог сессии**, полем `quotaLimits`:

    {"status":"rejected","resetsAt":1787332200,"rateLimitType":"five_hour",
     "overageStatus":"rejected","overageDisabledReason":"org_level_disabled",
     "unifiedRateLimitFallbackAvailable":false,"isUsingOverage":false,
     "upgradePaths":["upgrade_plan"]}

`resetsAt` — **unix-таймстамп**. Ни парсинга «resets 3:45pm», ни догадок о таймзоне
и переходе на летнее время, ни зависимости от языка интерфейса. Найдено 21.08.2026
вахтой VII при сборке автономного контура.

🔴 ПОТОЛОК, названный вслух (`71` §7г-бис):
  · Запись появляется ТОЛЬКО в момент отказа. Пока лимит не упёрт, свежих данных нет —
    скрипт честно говорит «упора не было с <дата>», а не выдумывает остаток.
  · 🔴 **Отказ НЕ означает блокировку до `resetsAt`.** Первая редакция этого скрипта
    печатала «🔴 ИДЁТ · ждать 1 ч 54 мин» — и была неправа: в том же логе после отказа
    шли **149 успешных ходов**, а `resetsAt` ещё не наступил. То есть отказ бывает
    преодолимым (ретрай, окно освободилось), и вывод «мы заблокированы» из одной записи
    не следует. Поэтому блокировка определяется НЕ временем, а фактом: есть ли в том же
    логе успешный ход ПОСЛЕ отказа. Поймано сверкой вывода скрипта с тем, что скрипт
    писался работающей сессией.
  · Остаток лимита в процентах здесь НЕ считается: его в логе нет. Расход в токенах
    меряет `reports/experiments/token-consumption/session_metrics.py` — это другая
    величина, и смешивать их нельзя.
  · Типы окон видны только те, в которые реально упирались: сейчас `five_hour`
    и `seven_day`. Появится третий — появится в выводе сам, списка из головы тут нет.

Запуск:
    python3 limits_watch.py                # человеку: сводка
    python3 limits_watch.py --json         # машине: состояние в stdout
    python3 limits_watch.py --write        # записать limits.json рядом с китом
    python3 limits_watch.py --wait-seconds # СКОЛЬКО СЕКУНД ЖДАТЬ до сброса (0 = не ждать)

Только стандартная библиотека.
"""
import datetime
import glob
import json
import os
import sys
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
OUT = Path(__file__).resolve().parent.parent / "limits.json"
WINDOW_HINT = {"five_hour": "5 часов", "seven_day": "неделя"}


def collect() -> list[dict]:
    """Записи об упоре + факт: был ли успешный ход ПОСЛЕ отказа в том же логе.

    Второе и решает, заблокированы ли мы. Время сброса говорит только, когда окно
    обновится, — но отказ мог быть преодолён раньше (см. потолок в шапке).
    """
    out = []
    for f in glob.glob(str(PROJECTS / "*" / "*.jsonl")):
        hits, last_ok = [], None
        try:
            fh = open(f, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                has_quota = '"quotaLimits"' in line
                if not has_quota and '"usage"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                ts = d.get("timestamp")
                q = d.get("quotaLimits")
                # 🔴 Порядок важен: запись об отказе НЕСЁТ type="assistant" И message.usage,
                # то есть выглядит успешным ходом. Первая редакция проверяла успех раньше
                # квоты и теряла ВСЕ 40 записей об упоре, печатая «упоров не было».
                if not (isinstance(q, dict) and q.get("resetsAt")):
                    ok = (d.get("type") == "assistant"
                          and (d.get("message") or {}).get("usage")
                          and not d.get("isApiErrorMessage"))
                    if ok and ts and (last_ok is None or ts > last_ok):
                        last_ok = ts
                    continue
                hits.append({
                    "hit_at": ts,
                    "session": Path(f).stem,
                    "project": Path(f).parent.name,
                    "type": q.get("rateLimitType", "unknown"),
                    "resets_at": int(q["resetsAt"]),
                    "status": q.get("status"),
                    "overage": q.get("overageStatus"),
                    "overage_off_because": q.get("overageDisabledReason"),
                    "fallback": bool(q.get("unifiedRateLimitFallbackAvailable")),
                })
        for h in hits:
            h["преодолён"] = bool(last_ok and h["hit_at"] and last_ok > h["hit_at"])
            h["последний_успешный_ход"] = last_ok
            out.append(h)
    out.sort(key=lambda r: r["hit_at"] or "")
    return out


def state(recs: list[dict], now: float | None = None) -> dict:
    now = now if now is not None else datetime.datetime.now().timestamp()
    by_type: dict[str, dict] = {}
    for r in recs:
        cur = by_type.get(r["type"])
        if cur is None or r["resets_at"] > cur["resets_at"]:
            by_type[r["type"]] = r

    windows = {}
    for t, r in by_type.items():
        left = r["resets_at"] - now
        windows[t] = {
            "окно": WINDOW_HINT.get(t, t),
            "последний упор": r["hit_at"],
            "сброс_unix": r["resets_at"],
            "сброс_локально": datetime.datetime.fromtimestamp(r["resets_at"]).isoformat(timespec="minutes"),
            "сброс_ещё_не_наступил": left > 0,
            "до_сброса_сек": int(left) if left > 0 else 0,
            # Блокировка определяется ФАКТОМ, а не временем: если после отказа
            # в том же логе был успешный ход — отказ преодолён.
            "отказ_преодолён": r.get("преодолён", False),
            "последний_успешный_ход": r.get("последний_успешный_ход"),
        }
    active = [w for w in windows.values()
              if w["сброс_ещё_не_наступил"] and not w["отказ_преодолён"]]
    return {
        "снято": datetime.datetime.now().isoformat(timespec="seconds"),
        "всего_упоров_в_логах": len(recs),
        "окна": windows,
        "ждать_секунд": max((w["до_сброса_сек"] for w in active), default=0),
        "оверейдж": {
            "статус": by_type[max(by_type, key=lambda t: by_type[t]["resets_at"])]["overage"] if by_type else None,
            "почему_выключен": by_type[max(by_type, key=lambda t: by_type[t]["resets_at"])]["overage_off_because"] if by_type else None,
        } if by_type else {},
        "потолок": "Данные появляются ТОЛЬКО в момент отказа. Остаток лимита в логе "
                   "отсутствует и здесь не оценивается; расход в токенах меряет "
                   "reports/experiments/token-consumption/session_metrics.py.",
    }


def human(recs: list[dict], st: dict) -> None:
    print(f"ЛИМИТЫ · снято {st['снято']}")
    if not recs:
        print("\nВ логах нет ни одной записи об упоре в лимит.")
        print("Это НЕ значит «лимит не близко» — значит, отказа ещё не было.")
        return

    print(f"Записей об упоре во всех логах: {st['всего_упоров_в_логах']}")
    for t, w in sorted(st["окна"].items()):
        if w["отказ_преодолён"]:
            mark = "✅ отказ преодолён — после него были успешные ходы"
        elif w["сброс_ещё_не_наступил"]:
            m = w["до_сброса_сек"] // 60
            mark = f"🔴 ВОЗМОЖНА БЛОКИРОВКА · до сброса {m // 60} ч {m % 60} мин"
        else:
            mark = "✅ окно сброшено по времени"
        print(f"\n  {t} ({w['окно']}) — {mark}")
        print(f"     последний упор:  {w['последний упор']}")
        print(f"     сброс окна:      {w['сброс_локально']}")
        if w["последний_успешный_ход"]:
            print(f"     последний ход:   {w['последний_успешный_ход']}")

    if st.get("оверейдж", {}).get("статус"):
        o = st["оверейдж"]
        print(f"\n  Оверейдж: {o['статус']}"
              + (f" (выключен: {o['почему_выключен']})" if o["почему_выключен"] else ""))
        if o["статус"] == "rejected":
            print("     → при упоре работа ОСТАНАВЛИВАЕТСЯ, а не продолжается платно.")
            print("       Для автономного прогона это главное: ждать сброса, а не надеяться.")

    # Ритм упоров — чтобы планировать батчи, а не гадать
    by_hour: dict[int, int] = {}
    for r in recs:
        if not r["hit_at"]:
            continue
        try:
            h = datetime.datetime.fromisoformat(r["hit_at"].replace("Z", "+00:00")).astimezone().hour
        except ValueError:
            continue
        by_hour[h] = by_hour.get(h, 0) + 1
    if by_hour:
        top = sorted(by_hour.items(), key=lambda x: -x[1])[:5]
        print("\n  Когда упираемся чаще всего (локальный час : сколько раз):")
        print("     " + " · ".join(f"{h:02d}:00 ×{n}" for h, n in top))

    print(f"\n  ЖДАТЬ СЕКУНД: {st['ждать_секунд']}   (0 = можно работать)")
    print("  Это ВЕРХНЯЯ оценка: отказ бывает преодолимым раньше сброса окна.")
    print("  Автономному циклу правильнее пробовать с backoff, а не спать всё время целиком.")
    print(f"\n  Потолок: {st['потолок']}")


def main() -> int:
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    recs = collect()
    st = state(recs)

    if "--wait-seconds" in flags:
        print(st["ждать_секунд"])
        return 0
    if "--json" in flags:
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0
    if "--write" in flags:
        payload = dict(st, история=recs[-40:])
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"записано: {OUT}  ({len(recs)} упоров, ждать {st['ждать_секунд']} с)")
        return 0

    human(recs, st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
