#!/usr/bin/env python3
"""rename_readiness.py — готова ли машина к переименованию учётной записи.

ЗАКАЗ ВЛАДЕЛЬЦА 02.09.2026: «подготовь всё, чтобы потом всё легко сделать».

🔴 СКРИПТ НИЧЕГО НЕ МЕНЯЕТ. Он отвечает на один вопрос: можно ли начинать,
и что мешает. Само переименование делается вручную по инструкции
`it-base/05-tech-guides/macos-username-change.md` — из терминала текущей
сессии оно невозможно технически: нельзя переименовать домашнюю папку
пользователя, под которым идёт процесс.

ПРЕДУСЛОВИЯ: macOS; штатные `dscl`, `tmutil`, `df`.

ПОСТУСЛОВИЯ: напечатан список проверок с вердиктом по каждой и общий ответ
«можно / нельзя / можно с оговорками». Ни одна проверка не молчит: непройденная
называет, что именно сделать.

ИНВАРИАНТ: только чтение. Ни одной команды, меняющей состояние системы.
"""
from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path

OLD = "vasyaevdokimov"
NEW = "vasiliievdokimov"


def sh(cmd: list[str], timeout: int = 30) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def check_already_renamed() -> tuple[bool, str, str]:
    cur = sh(["whoami"]).strip()
    if cur == NEW:
        return True, f"имя уже {NEW}", "переименование выполнено — запускать rename_user_paths.py"
    return False, f"текущее имя: {cur}", ""


def check_second_admin() -> tuple[bool, str, str]:
    """🔴 Ключевая проверка. Без второго администратора шаги 2-4 невыполнимы:
    выйти из единственной учётной записи некуда."""
    out = sh(["dscl", ".", "-read", "/Groups/admin", "GroupMembership"])
    admins = [a for a in out.replace("GroupMembership:", "").split()
              if a and a != "root"]
    if len(admins) >= 2:
        return True, f"администраторов: {len(admins)} ({', '.join(admins)})", ""
    return False, f"администратор один: {', '.join(admins) or '?'}", \
        "создать временного: Настройки → Пользователи и группы → Добавить, роль «Администратор»"


def check_backup() -> tuple[bool, str, str]:
    """Переименование — процедура, после которой обычно что-то чинят.
    Делать её без копии значит принимать два риска сразу вместо одного."""
    listing = sh(["tmutil", "listbackups"], 40)
    if "No machine directory" in listing or not listing.strip():
        return False, "резервных копий НЕТ ни одной", \
            "скопировать ~/Documents и ~/repos на внешний носитель — это минимум"
    return True, f"копии есть: {len(listing.strip().splitlines())}", ""


def check_disk_space() -> tuple[bool, str, str]:
    out = sh(["df", "-k", "/System/Volumes/Data"]).splitlines()
    if len(out) < 2:
        return False, "не удалось замерить", "проверить вручную: df -h"
    free_gb = int(out[1].split()[3]) / 1024 / 1024
    if free_gb >= 20:
        return True, f"свободно {free_gb:.0f} ГБ", ""

    # 🔴 Мало места — не всегда мусор. Прежде чем советовать «почистить»,
    # надо посмотреть, чем оно занято: снимки APFS освобождаются сами,
    # а игра занимает место по назначению, и чистить её никто не просил.
    snaps = len([l for l in sh(["tmutil", "listlocalsnapshots", "/"], 20).splitlines()
                 if "com.apple" in l])
    hint = "освободить хотя бы 20 ГБ — переименование создаёт временные копии"
    if snaps:
        hint = (f"снимков APFS: {snaps} — они держат удалённое и освобождаются "
                f"сами при нужде; снять вручную: sudo tmutil deletelocalsnapshots /")
    return False, f"свободно всего {free_gb:.0f} ГБ", hint


def check_paths_scale() -> tuple[bool, str, str]:
    """Сколько правок ждёт после. Не блокирует, но полезно знать заранее."""
    root = Path.home() / "repos"
    if not root.is_dir():
        return True, "каталог repos не найден", ""
    n = 0
    for p in root.rglob("*.md"):
        if "/_base/" in str(p):
            continue
        try:
            n += p.read_text(encoding="utf-8").count(OLD)
        except (OSError, UnicodeDecodeError):
            continue
    return True, f"вхождений старого пути в документации: {n}", \
        "правится одной командой ПОСЛЕ переименования: scripts/rename_user_paths.py --apply"


def check_running_apps() -> tuple[bool, str, str]:
    """Приложения, которые держат файлы в домашней папке и мешают
    переименованию, — их лучше закрыть заранее."""
    heavy = ("Docker", "VirtualBox", "Google Chrome", "Firefox", "Code")
    out = sh(["ps", "-Ao", "comm"], 20)
    running = [h for h in heavy if h in out]
    if not running:
        return True, "тяжёлых приложений не запущено", ""
    return False, f"запущены: {', '.join(running)}", \
        "закрыть перед началом — они держат файлы в домашней папке"


CHECKS = (
    ("имя уже сменено", check_already_renamed),
    ("второй администратор", check_second_admin),
    ("резервная копия", check_backup),
    ("место на диске", check_disk_space),
    ("масштаб правок после", check_paths_scale),
    ("тяжёлые приложения закрыты", check_running_apps),
)


def main() -> int:
    if platform.system() != "Darwin":
        print(f"🔴 Скрипт для macOS; здесь {platform.system()}.", file=sys.stderr)
        return 2
    argparse.ArgumentParser(description="Готовность к переименованию").parse_args()

    print(f"Готовность к переименованию: {OLD} → {NEW}\n")
    blockers = []
    for label, probe in CHECKS:
        ok, state, fix = probe()
        mark = "🟢" if ok else "🔴"
        print(f"  {mark} {label:<28} {state}")
        if fix:
            print(f"     {'':<28} → {fix}")
        if not ok and label != "имя уже сменено":
            blockers.append(label)

    print()
    if not blockers:
        print("🟢 Можно начинать. Порядок шагов —")
        print("   it-base/05-tech-guides/macos-username-change.md, «Вариант B-факт».")
        return 0
    print(f"🔴 Мешает: {len(blockers)} — {', '.join(blockers)}")
    print("   Каждое закрывается строкой «→» выше. Ни одно не требует много времени,")
    print("   кроме резервной копии — но она здесь и есть главная защита.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
