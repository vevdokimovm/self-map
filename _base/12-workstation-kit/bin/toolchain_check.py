#!/usr/bin/env python3
"""toolchain_check.py — что устарело в инструментарии и чего не хватает.

ЗАКАЗ ВЛАДЕЛЬЦА 02.09.2026: «может, заодно заведём какой-то механизм обновления
тулинга… обновлять устаревшее, чекать что есть на рынке; и что-то, что не было
установлено, но очень полезно — есть ли, стоит скачать».

🔴 ЧТО ЭТОТ СКРИПТ ДЕЛАЕТ И ЧЕГО НЕ ДЕЛАЕТ.
Он **сравнивает установленное с эталоном** и печатает расхождения. Эталон —
список ниже, написанный людьми: «что должно стоять на машине разработчика
и почему». Скрипт не ходит в интернет за рейтингами и не решает, что модно.

Причина простая: «что есть на рынке» — вопрос суждения, а не команды.
Ответ на него живёт в `12-workstation-kit/STATE.md` и пересматривается
руками, когда есть повод. Скрипт же отвечает на проверяемое:
**совпадает ли машина с тем, что мы решили.**

ПРЕДУСЛОВИЯ:
  · macOS, `brew` в PATH (иначе часть проверок отвалится, и это будет сказано).

ПОСТУСЛОВИЯ:
  · напечатано три списка: устарело · отсутствует из эталона · лишнее;
  · пустой список печатается словами, а не пропускается: «ничего не устарело» —
    это ответ, а молчание — нет.

ИНВАРИАНТ: скрипт ничего не устанавливает и не обновляет. Он только
СРАВНИВАЕТ и печатает команды, которые владелец выполнит сам.
🔴 Обновление тулчейна — необратимое действие вовне (`/auto` §5), и решать
его должен человек.
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys

# ── ЭТАЛОН: что должно стоять и почему ────────────────────────────────
#
# Каждая строка — решение, а не список желаний. «Зачем» пишется здесь же,
# чтобы через полгода не гадать, нужен ли инструмент до сих пор.
#
# `способ` важен: 02.09.2026 выяснено дважды, что тулчейны на Rust и Go
# ставятся официальным бинарником, а не brew — сборка из исходников на Intel
# занимает часы (`STATE.md` §3).
BASELINE = {
    # ── ядро, без чего не работает ничего
    "git":      {"зачем": "версионирование", "способ": "Apple CLT", "класс": "ядро"},
    "python3":  {"зачем": "основной язык системы", "способ": "uv", "класс": "ядро"},
    "uv":       {"зачем": "версии Python и окружения — вместо pyenv+venv+pip",
                 "способ": "бинарник astral.sh", "класс": "ядро"},
    "node":     {"зачем": "фронтенд, инструменты сборки",
                 "способ": "бинарник nodejs.org", "класс": "ядро"},
    "gh":       {"зачем": "релизы и PR из терминала", "способ": "brew", "класс": "ядро"},

    # ── диагностика: без них нельзя ответить «что с машиной»
    "smartctl": {"зачем": "износ SSD; без него SMART говорит лишь Verified/Failing",
                 "способ": "brew install smartmontools", "класс": "диагностика"},

    # ── повседневное, уже стоит
    "rg":       {"зачем": "поиск по коду, на порядок быстрее grep",
                 "способ": "brew install ripgrep", "класс": "удобство"},
    "jq":       {"зачем": "разбор JSON в конвейерах", "способ": "brew install jq",
                 "класс": "удобство"},
    "fzf":      {"зачем": "интерактивный поиск", "способ": "brew", "класс": "удобство"},
    "bat":      {"зачем": "просмотр файлов с подсветкой", "способ": "brew", "класс": "удобство"},
    "eza":      {"зачем": "замена ls", "способ": "brew", "класс": "удобство"},
    "zoxide":   {"зачем": "переход по каталогам по частям имени", "способ": "brew",
                 "класс": "удобство"},
}

# Инструменты, которые часто оказываются лишними: их ставят под задачу
# и забывают. Не «удалить», а «спросить себя, нужен ли».
SUSPECTS = {
    "pyenv": "заменён uv — версиями Python управляет он",
    "conda": "тяжёлый менеджер окружений; для наших задач хватает uv",
    "nvm": "версиями Node управляет бинарник в ~/.local/opt",
}


def sh(cmd: list[str], timeout: int = 30) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def version_of(tool: str) -> str:
    """Версия инструмента. Пустая строка = не установлен."""
    if not shutil.which(tool):
        return ""
    for flag in ("--version", "-V", "version"):
        out = sh([tool, flag], 15)
        m = re.search(r"(\d+\.\d+(?:\.\d+)?)", out)
        if m:
            return m.group(1)
    return "?"


def brew_outdated() -> list[dict]:
    """Что устарело по мнению brew. Формат --json стабильнее текстового."""
    if not shutil.which("brew"):
        return []
    out = sh(["brew", "outdated", "--json=v2"], 120)
    try:
        data = json.loads(out or "{}")
    except ValueError:
        return []
    rows = []
    for f in data.get("formulae", []):
        rows.append({"имя": f.get("name"),
                     "стоит": ", ".join(f.get("installed_versions", [])),
                     "доступно": f.get("current_version", "?")})
    for c in data.get("casks", []):
        rows.append({"имя": c.get("name", [c.get("token")])[0],
                     "стоит": c.get("installed_version", "?"),
                     "доступно": c.get("current_version", "?"),
                     "приложение": True})
    return rows


def check() -> dict:
    installed, missing = {}, []
    for tool, meta in BASELINE.items():
        v = version_of(tool)
        if v:
            installed[tool] = {**meta, "версия": v}
        else:
            missing.append({"инструмент": tool, **meta})
    suspects = [{"инструмент": t, "почему": why}
                for t, why in SUSPECTS.items() if shutil.which(t)]
    return {
        "эталон_выполнен": len(installed),
        "эталон_всего": len(BASELINE),
        "установлено": installed,
        "не_хватает": missing,
        "под_вопросом": suspects,
        "устарело_в_brew": brew_outdated(),
    }


def render(r: dict) -> None:
    print(f"╭─ Инструментарий: {r['эталон_выполнен']} из {r['эталон_всего']} по эталону")
    print("╰─")

    by_class: dict[str, list] = {}
    for tool, meta in r["установлено"].items():
        by_class.setdefault(meta["класс"], []).append((tool, meta))
    for cls in ("ядро", "диагностика", "удобство"):
        items = by_class.get(cls, [])
        if not items:
            continue
        print(f"\n{cls.upper()}")
        for tool, meta in sorted(items):
            print(f"   🟢 {tool:<10} {meta['версия']:<10} {meta['зачем'][:52]}")

    if r["не_хватает"]:
        print(f"\n🔴 НЕ ХВАТАЕТ ПО ЭТАЛОНУ: {len(r['не_хватает'])}")
        for m in r["не_хватает"]:
            print(f"   {m['инструмент']:<12} {m['зачем']}")
            print(f"   {'':<12} поставить: {m['способ']}")
    else:
        print("\n🟢 Эталон выполнен полностью — ничего не отсутствует.")

    if r["под_вопросом"]:
        print(f"\n⚠️  СТОИТ, НО, ВОЗМОЖНО, УЖЕ НЕ НУЖНО: {len(r['под_вопросом'])}")
        for s in r["под_вопросом"]:
            print(f"   {s['инструмент']:<12} {s['почему']}")
        print("   🔴 Это НЕ команда удалить — это повод спросить себя.")

    old = r["устарело_в_brew"]
    if old:
        print(f"\nУСТАРЕЛО В BREW: {len(old)}")
        for o in old[:12]:
            mark = "📦" if o.get("приложение") else "  "
            print(f"   {mark} {o['имя'][:24]:<26} {o['стоит'][:14]:<16} → {o['доступно']}")
        if len(old) > 12:
            print(f"      … и ещё {len(old) - 12}")
        print("\n   Обновить всё:        brew upgrade")
        print("   Только приложения:   brew upgrade --cask")
        print("   🔴 НЕ обновлять вслепую тулчейны на Rust/Go: brew соберёт")
        print("      их из исходников, и на Intel это часы (STATE.md §3).")
    else:
        print("\n🟢 В brew ничего не устарело.")

    print("\n🔴 Скрипт НИЧЕГО не обновляет — только сравнивает и печатает команды.")
    print("   Обновление тулчейна необратимо и решается человеком.")


def main() -> int:
    if platform.system() != "Darwin":
        print(f"🔴 Скрипт для macOS; здесь {platform.system()}.", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(description="Состояние инструментария против эталона")
    ap.add_argument("--json", action="store_true", help="выдать JSON")
    args = ap.parse_args()
    r = check()
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        render(r)
    return 1 if (r["не_хватает"] or r["устарело_в_brew"]) else 0


if __name__ == "__main__":
    sys.exit(main())
