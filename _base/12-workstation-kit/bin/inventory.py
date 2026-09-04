#!/usr/bin/env python3
"""inventory.py — индекс приложений и крупных файлов на машине, с историей.

ЗАКАЗ ВЛАДЕЛЬЦА 02.09.2026: «сделай индекс файлов на моём маке, приложений,
чтобы была история… чтобы скилл machine тоже показывал это всё — что где и тд».

🔴 ЗАЧЕМ ИСТОРИЯ, А НЕ ПРОСТО СПИСОК. Список отвечает «что стоит сейчас»;
на этот вопрос и `ls /Applications` ответит. История отвечает на другое:
**что появилось, что исчезло и когда** — а это единственный способ заметить,
что программа установилась сама, или что нужное пропало при чистке.

Снимок кладётся в `snapshots/YYYY-MM-DD.json` рядом с этим скриптом. Каждый
запуск сравнивается с предыдущим и печатает разницу.

ПРЕДУСЛОВИЯ:
  · macOS — иначе отказ, а не догадка;
  · каталог `snapshots/` создаётся сам при первом запуске.

ПОСТУСЛОВИЯ:
  · файл снимка за сегодня существует и содержит валидный JSON;
  · при наличии прошлого снимка напечатана разница, даже если она пустая
    («ничего не изменилось» — тоже ответ, а не молчание).

ИНВАРИАНТ: скрипт только читает файловую систему и пишет СВОЙ снимок.
Ничего в системе не меняет.
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SNAP_DIR = HERE.parent / "snapshots"

# Где искать приложения. `~/Applications` — пользовательские, их часто забывают.
APP_ROOTS = (Path("/Applications"), Path.home() / "Applications")

# Признаки ИИ-инструмента в имени. 🔴 Список ЗАВЕДОМО неполон: имя не обязано
# говорить о назначении (Granola, Attio, Pencil — по имени не догадаться).
# Поэтому он лишь подсказка к разбору, а не классификатор.
AI_HINTS = ("ai", "gpt", "claude", "llm", "copilot", "cursor", "ollama",
            "gemini", "perplexity", "devin", "antigravity", "windsurf",
            "wispr", "granola", "notion", "raycast", "warp")


def sh(cmd: list[str], timeout: int = 30) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def app_size_mb(p: Path) -> int:
    out = sh(["du", "-sk", str(p)], timeout=60)
    try:
        return int(out.split()[0]) // 1024
    except (ValueError, IndexError):
        return 0


def app_version(p: Path) -> str:
    """Версия из Info.plist. Отсутствие — законное состояние, не ошибка."""
    plist = p / "Contents" / "Info.plist"
    if not plist.is_file():
        return "—"
    out = sh(["defaults", "read", str(plist), "CFBundleShortVersionString"], 10)
    return out.strip() or "—"


# Где приложения держат рабочие данные. Проверяется по имени приложения
# и по типовым скрытым каталогам — точного соответствия нет, поэтому
# отсутствие данных означает «не нашли», а не «не используется».
DATA_ROOTS = (
    Path.home() / "Library" / "Application Support",
    Path.home() / "Library" / "Containers",
    Path.home(),
)


def last_activity(app_name: str) -> tuple[str, int]:
    """Когда приложение последний раз ПИСАЛО свои данные, и сколько их (МБ).

    🔴 Почему не дата самого `.app`: она меняется при ОБНОВЛЕНИИ, а не при
    запуске. Замер 02.09.2026 показал разницу в месяцы: половина инструментов
    «обновлена недавно» и при этом не открывалась с весны.

    🔴 Почему не `kMDItemLastUsedDate`: у восьми проверенных приложений
    из девяти это поле пустое — Spotlight его не заполняет. Проверка,
    молча возвращающая пустоту, хуже отсутствующей.

    Возвращает ("—", 0), если каталог данных не найден. Это законный исход:
    приложение может хранить их не там, где мы ищем.
    """
    candidates = [app_name, app_name.replace(" ", ""), f".{app_name.lower()}"]
    for root in DATA_ROOTS:
        for cand in candidates:
            d = root / cand
            if not d.is_dir():
                continue
            try:
                when = date.fromtimestamp(d.stat().st_mtime).isoformat()
            except OSError:
                continue
            out = sh(["du", "-sk", str(d)], timeout=60)
            try:
                mb = int(out.split()[0]) // 1024
            except (ValueError, IndexError):
                mb = 0
            return when, mb
    return "—", 0


def scan_apps() -> list[dict]:
    apps = []
    for root in APP_ROOTS:
        if not root.is_dir():
            continue
        # maxdepth 3: приложения разложены по тематическим папкам
        for p in sorted(root.rglob("*.app")):
            # вложенные .app внутри других .app — часть родителя, не отдельные
            if any(part.endswith(".app") for part in p.relative_to(root).parts[:-1]):
                continue
            try:
                mtime = date.fromtimestamp(p.stat().st_mtime).isoformat()
            except OSError:
                continue
            name = p.stem
            act_date, act_mb = last_activity(name)
            apps.append({
                "имя": name,
                "данные_писались": act_date,
                "данных_мб": act_mb,
                "путь": str(p),
                "папка": str(p.parent.relative_to(root)) if p.parent != root else "—",
                "мб": app_size_mb(p),
                "версия": app_version(p),
                "изменён": mtime,
                "похоже_на_ии": any(h in name.lower() for h in AI_HINTS),
            })
    return apps


def scan_big_dirs(limit_mb: int = 500) -> list[dict]:
    """Крупные каталоги в домашней папке — где лежит место."""
    rows = []
    targets = [Path.home() / n for n in
               ("Documents", "Downloads", "Desktop", "Pictures", "Movies",
                "Music", "repos", "Library")]
    for t in targets:
        if not t.is_dir():
            continue
        out = sh(["du", "-sk", str(t)], timeout=300)
        try:
            mb = int(out.split()[0]) // 1024
        except (ValueError, IndexError):
            continue
        if mb >= limit_mb:
            rows.append({"путь": str(t), "мб": mb})
    return sorted(rows, key=lambda r: -r["мб"])


def collect() -> dict:
    apps = scan_apps()
    return {
        "снято": date.today().isoformat(),
        "приложений": len(apps),
        "приложения": apps,
        "крупные_каталоги": scan_big_dirs(),
        "brew_формул": len([x for x in sh(["brew", "list", "--formula"], 60).split()]),
        "brew_приложений": len([x for x in sh(["brew", "list", "--cask"], 60).split()]),
    }


def previous_snapshot(today: str) -> tuple[str, dict] | tuple[None, None]:
    if not SNAP_DIR.is_dir():
        return None, None
    files = sorted(p for p in SNAP_DIR.glob("*.json") if p.stem != today)
    if not files:
        return None, None
    try:
        return files[-1].stem, json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None


def diff(old: dict, new: dict) -> dict:
    """Что появилось, что исчезло, что сменило версию."""
    o = {a["путь"]: a for a in old.get("приложения", [])}
    n = {a["путь"]: a for a in new.get("приложения", [])}
    added = [n[k] for k in n.keys() - o.keys()]
    gone = [o[k] for k in o.keys() - n.keys()]
    changed = [
        {"имя": n[k]["имя"], "было": o[k]["версия"], "стало": n[k]["версия"]}
        for k in o.keys() & n.keys()
        if o[k]["версия"] != n[k]["версия"] and n[k]["версия"] != "—"
    ]
    return {"появились": added, "исчезли": gone, "сменили_версию": changed}


def render(snap: dict, prev_date: str | None, delta: dict | None) -> None:
    print(f"╭─ Индекс машины · {snap['снято']}")
    print(f"│  приложений: {snap['приложений']} · "
          f"brew: {snap['brew_формул']} формул, {snap['brew_приложений']} приложений")
    print("╰─")

    by_folder: dict[str, list] = {}
    for a in snap["приложения"]:
        by_folder.setdefault(a["папка"], []).append(a)

    print("\nПРИЛОЖЕНИЯ ПО ПАПКАМ")
    for folder, items in sorted(by_folder.items(), key=lambda kv: -sum(a["мб"] for a in kv[1])):
        total = sum(a["мб"] for a in items)
        print(f"\n  {folder}  —  {len(items)} шт, {total} МБ")
        for a in sorted(items, key=lambda x: -x["мб"])[:8]:
            mark = " 🤖" if a["похоже_на_ии"] else ""
            print(f"      {a['мб']:>5} МБ  {a['имя'][:34]:<36} {a['версия'][:12]:<14}"
                  f"{a['изменён']}{mark}")
        if len(items) > 8:
            print(f"      … и ещё {len(items) - 8}")

    ai = [a for a in snap["приложения"] if a["похоже_на_ии"]]
    if ai:
        print(f"\nПОХОЖЕ НА ИИ-ИНСТРУМЕНТЫ: {len(ai)}")
        print(f"   {'размер':>7} {'обновлён':<12} {'данные писались':<16} имя")
        for a in sorted(ai, key=lambda x: -x["мб"]):
            # 🔴 Две даты рядом намеренно: расхождение между ними и есть ответ
            # на вопрос «пользуются ли». «Обновлён вчера, данные писались
            # в мае» означает, что приложение обновляется само, а не работает.
            act = a.get("данные_писались", "—")
            stale = act != "—" and act < a["изменён"]
            mark = "  🔴 не в работе" if stale else ""
            print(f"   {a['мб']:>5} МБ {a['изменён']:<12} {act:<16} "
                  f"{a['имя'][:24]}{mark}")
        print("   🔴 Отбор по ИМЕНИ — заведомо неполон: назначение из имени")
        print("      не следует. Разбор по существу — в 13-ai-tools-lab/.")

    print("\nКРУПНЫЕ КАТАЛОГИ")
    for d in snap["крупные_каталоги"]:
        print(f"   {d['мб']:>7} МБ  {d['путь']}")

    if delta is None:
        print(f"\n🟢 Первый снимок — сравнивать не с чем. "
              f"Следующий запуск покажет разницу.")
        return
    print(f"\nИЗМЕНЕНИЯ С {prev_date}")
    if not any(delta.values()):
        print("   ничего не менялось")
        return
    for a in delta["появились"]:
        print(f"   + появилось: {a['имя']} ({a['мб']} МБ)")
    for a in delta["исчезли"]:
        print(f"   − исчезло:   {a['имя']} ({a['мб']} МБ)")
    for c in delta["сменили_версию"]:
        print(f"   ↑ {c['имя']}: {c['было']} → {c['стало']}")


def main() -> int:
    if platform.system() != "Darwin":
        print(f"🔴 Скрипт для macOS; здесь {platform.system()}.", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(description="Индекс приложений и файлов машины")
    ap.add_argument("--json", action="store_true", help="выдать JSON")
    ap.add_argument("--no-save", action="store_true",
                    help="не записывать снимок (только показать)")
    args = ap.parse_args()

    snap = collect()
    today = snap["снято"]
    prev_date, prev = previous_snapshot(today)
    delta = diff(prev, snap) if prev else None

    if not args.no_save:
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        (SNAP_DIR / f"{today}.json").write_text(
            json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")

    if args.json:
        print(json.dumps({"снимок": snap, "изменения": delta},
                         ensure_ascii=False, indent=2))
    else:
        render(snap, prev_date, delta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
