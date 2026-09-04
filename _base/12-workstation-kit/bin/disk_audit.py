#!/usr/bin/env python3
"""disk_audit.py — ревизия всего диска: профили, папки, что где лежит.

ЗАКАЗ ВЛАДЕЛЬЦА 02.09.2026: «ревизию файлов всех профилей всего диска
Макинтош — там есть Guest, Shared, все папки, навести порядок».

🔴 СКРИПТ НИЧЕГО НЕ УДАЛЯЕТ И НЕ ПЕРЕМЕЩАЕТ. Он отвечает на вопрос
«что где лежит и почему это странно» — решение принимает владелец.
Раскладка чужих файлов по папкам необратима и требует понимания,
что это за файлы; такое не делается автоматически.

ПРЕДУСЛОВИЯ: macOS.

ПОСТУСЛОВИЯ: напечатана карта диска по уровням — профили, корень домашней
папки, общие каталоги — с пометкой у каждого, стандартный он или нет
и когда трогали последний раз.

ИНВАРИАНТ: только чтение.
"""
from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from datetime import date
from pathlib import Path

# Что macOS создаёт сама. Всё остальное в корне домашней папки завёл человек
# или установщик — и вот это и есть предмет ревизии.
STANDARD_HOME = {"Applications", "Desktop", "Documents", "Downloads", "Library",
                 "Movies", "Music", "Pictures", "Public"}

# Каталоги, чей размер меряется отдельно: они большие и растут сами.
NOISY = {"Library", "repos"}


def sh(cmd: list[str], timeout: int = 300) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def size_mb(p: Path) -> int:
    out = sh(["du", "-sk", str(p)], timeout=600)
    try:
        return int(out.split()[0]) // 1024
    except (ValueError, IndexError):
        return 0


def touched(p: Path) -> str:
    try:
        return date.fromtimestamp(p.stat().st_mtime).isoformat()
    except OSError:
        return "—"


def human(mb: int) -> str:
    return f"{mb/1024:.1f} ГБ" if mb >= 1024 else f"{mb} МБ"


def audit_profiles() -> list[dict]:
    rows = []
    users = Path("/Users")
    if not users.is_dir():
        return rows
    for p in sorted(users.iterdir()):
        if not p.is_dir() or p.name.startswith("."):
            continue
        mb = size_mb(p)
        # Guest и Shared — системные по назначению, но ведут себя по-разному:
        # Guest обязан быть пустым, Shared накапливает мусор от установщиков.
        kind = ("гостевой (должен быть пуст)" if p.name == "Guest"
                else "общий для всех учёток" if p.name == "Shared"
                else "профиль пользователя")
        rows.append({"имя": p.name, "мб": mb, "вид": kind, "изменён": touched(p)})
    return rows


def audit_home() -> list[dict]:
    rows = []
    for p in sorted(Path.home().iterdir()):
        if not p.is_dir() or p.name.startswith("."):
            continue
        std = p.name in STANDARD_HOME
        rows.append({
            "имя": p.name,
            "мб": size_mb(p) if p.name not in NOISY else size_mb(p),
            "стандартная": std,
            "изменён": touched(p),
        })
    return rows


def audit_shared() -> list[dict]:
    rows = []
    d = Path("/Users/Shared")
    if not d.is_dir():
        return rows
    for p in sorted(d.iterdir()):
        if p.name.startswith("."):
            continue
        rows.append({"имя": p.name, "мб": size_mb(p), "изменён": touched(p)})
    return rows


def audit_library() -> list[dict]:
    """Что внутри ~/Library — там обычно и прячется место.

    Каталог системный, но растёт от приложений: кэши, контейнеры,
    поддержка приложений. Владелец его не открывает, а он крупнейший.
    """
    rows = []
    d = Path.home() / "Library"
    if not d.is_dir():
        return rows
    for p in sorted(d.iterdir()):
        if p.name.startswith("."):
            continue
        mb = size_mb(p)
        if mb < 100:          # мелочь не показываем — её десятки
            continue
        rows.append({"имя": p.name, "мб": mb, "изменён": touched(p)})
    return sorted(rows, key=lambda r: -r["мб"])


def audit_naming(home: list[dict]) -> list[dict]:
    """🔴 Проверка именования — заказ владельца «правильный единый неминг».

    Правило системы (`76-repo-classes.md` §6): имена латиницей, строчными,
    слова через дефис. Кириллица в путях схлопывает слаги сессий
    (`99-claude-code-sessions.md` §1), пробелы ломают команды без кавычек.
    """
    bad = []
    for r in home:
        n = r["имя"]
        if r.get("стандартная"):
            continue          # системные папки трогать нельзя
        problems = []
        if any(ord(c) > 127 for c in n):
            problems.append("кириллица — схлопывает слаги сессий")
        if " " in n:
            problems.append("пробел — ломает команды без кавычек")
        if n != n.lower() and not n[0].isupper():
            problems.append("смешанный регистр")
        if "_" in n and "-" in n:
            problems.append("смесь дефисов и подчёркиваний")
        if problems:
            bad.append({"имя": n, "проблемы": problems})
    return bad


def render(profiles: list[dict], home: list[dict], shared: list[dict]) -> None:
    today = date.today()

    print("╭─ Ревизия диска\n│")
    print("│  ПРОФИЛИ В /Users")
    for r in profiles:
        note = ""
        if r["имя"] == "Guest" and r["мб"] > 0:
            note = "  🔴 гостевой не пуст"
        print(f"│    {human(r['мб']):>9}  {r['имя']:<20} {r['вид']}{note}")

    print("│\n│  КОРЕНЬ ДОМАШНЕЙ ПАПКИ")
    std = [r for r in home if r["стандартная"]]
    extra = [r for r in home if not r["стандартная"]]

    print(f"│    стандартных: {len(std)} · заведённых вручную: {len(extra)}")
    print("│")
    print("│    🔴 Нестандартные — предмет ревизии:")
    for r in sorted(extra, key=lambda x: -x["мб"]):
        age = (today - date.fromisoformat(r["изменён"])).days if r["изменён"] != "—" else 0
        mark = "  ⏳ не трогали {} дн".format(age) if age > 180 else ""
        print(f"│      {human(r['мб']):>9}  {r['имя']:<26} {r['изменён']}{mark}")

    if shared:
        print("│\n│  /Users/Shared — общий для всех учётных записей")
        for r in sorted(shared, key=lambda x: -x["мб"])[:10]:
            print(f"│      {human(r['мб']):>9}  {r['имя'][:40]:<42} {r['изменён']}")

    lib = audit_library()
    if lib:
        print("│\n│  ~/Library — крупнее 100 МБ (владелец сюда не заглядывает)")
        for r in lib[:10]:
            print(f"│      {human(r['мб']):>9}  {r['имя'][:36]:<38} {r['изменён']}")

    bad = audit_naming(home)
    print("│\n│  ИМЕНОВАНИЕ")
    if bad:
        print(f"│    🔴 нарушают правило: {len(bad)}")
        for r in bad:
            print(f"│      {r['имя'][:34]:<36} {'; '.join(r['проблемы'])}")
    else:
        print("│    🟢 все нестандартные папки названы по правилу")

    print("╰─")
    print("\n🔴 Скрипт ничего не удалил и не переместил — это карта, не действие.")
    print("   Раскладка файлов по смыслу требует знать, что это за файлы;")
    print("   автоматически такое не делается.")


def main() -> int:
    if platform.system() != "Darwin":
        print(f"🔴 Скрипт для macOS; здесь {platform.system()}.", file=sys.stderr)
        return 2
    argparse.ArgumentParser(description="Ревизия диска").parse_args()
    render(audit_profiles(), audit_home(), audit_shared())
    return 0


if __name__ == "__main__":
    sys.exit(main())
