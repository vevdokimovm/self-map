#!/usr/bin/env python3
"""Единственный источник правды: в истории репы нет никого, кроме владельца.

🔴 ЗАЧЕМ. Требование владельца 04.09.2026, дословно: «не надо чтобы Клод был
как-то упомянут — это основное правило: ни в контрибьюторах гита, ни в
коммитах, ни в релизах, нигде». Повод не косметический: адрес
`noreply@anthropic.com` **не принадлежит Anthropic** — его зарегистрировал
на себя посторонний человек, и GitHub показывал его в контрибьюторах
приватных репозиториев владельца.

🔴 ПОЧЕМУ ОДИН ФАЙЛ, А НЕ ДВА. Правило нужно и хуку (в момент коммита),
и гейту (по всей истории). Записанное дважды, оно разъедется — это `PIT-G`,
21 повтор. Здесь шаблоны объявлены один раз, а хук и гейт их импортируют.

🔴 ЧЕГО ЭТА ПРОВЕРКА НЕ ЛОВИТ:
  · переписанную историю — если коммит уже отравлен и запушен, проверка
    скажет об этом, но чистить придётся `filter-repo` и force-push,
    а это необратимое действие вовне (стоп-класс `/auto` §5);
  · упоминания в теле релиза на GitHub — они живут не в git;
  · имя, не совпадающее с шаблонами (например латиница с юникод-омоглифами).

Применение:
    attribution_check.py --repo <путь>     всё сразу: конфиг + история
    attribution_check.py --ident           автор текущего коммита (для pre-commit)
    attribution_check.py --message <файл>  текст сообщения (для commit-msg)
    attribution_check.py --selftest        канарейка
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# 🔴 ДВА РАЗНЫХ НАБОРА, И РАЗДЕЛЕНИЕ ЗДЕСЬ — ГЛАВНОЕ В ЭТОМ ФАЙЛЕ.
#
# Первая редакция искала голое слово `claude` ВЕЗДЕ, включая текст сообщения.
# Проверка на живой истории 07.09.2026 нашла «8 упоминаний» — и все восемь
# оказались **предметом работы владельца**: «механика сессий Claude Code»,
# «справочник Claude Code», «claude-context kit», «лимиты claude.ai ≠ Claude
# Code». Автор везде владелец, атрибуции нет ни в одном.
#
# > **Защита блокировала бы законную работу:** коммит «справочник Claude Code»
# > не прошёл бы хук. Запрет упоминать инструмент в описании документов
# > об этом инструменте — не защита, а помеха.
#
# Поэтому:
#   АТРИБУЦИЯ — конструкции, которыми ассистент СЕБЯ ПРИПИСЫВАЕТ. Ищутся
#               везде: в авторе, коммиттере и в тексте сообщения.
#   ЛИЧНОСТЬ  — голые имена. Ищутся ТОЛЬКО в авторе и коммиттере, где
#               законной причины их упоминать не существует.

АТРИБУЦИЯ = [
    (re.compile(r"co-authored-by:.*(claude|anthropic)", re.I), "трейлер Co-Authored-By"),
    (re.compile(r"generated with .*claude", re.I), "подпись «Generated with Claude»"),
    (re.compile(r"claude\.ai/(code|share)/", re.I), "ссылка на сессию"),
    (re.compile(r"noreply@anthropic\.com", re.I), "чужой адрес noreply@anthropic.com"),
]

ЛИЧНОСТЬ = [
    (re.compile(r"\banthropic\b", re.I), "имя Anthropic в подписи"),
    (re.compile(r"\bclaude\b", re.I), "имя Claude в подписи"),
]


def найти(текст: str, подпись: bool = False) -> list[str]:
    """Запрещённое в куске текста.

    Args:
        текст: что проверяем.
        подпись: True для автора и коммиттера — там запрещены и голые имена.
    """
    шаблоны = АТРИБУЦИЯ + ЛИЧНОСТЬ if подпись else АТРИБУЦИЯ
    return [имя for шаблон, имя in шаблоны if шаблон.search(текст)]


def _git(репа: Path, *аргументы: str) -> str:
    res = subprocess.run(["git", "-C", str(репа), *аргументы],
                         capture_output=True, text=True, encoding="utf-8")
    return res.stdout if res.returncode == 0 else ""


def проверить_конфиг(репа: Path) -> list[str]:
    """Локальный git config не подписан кем-то, кроме владельца.

    🔴 ТОЛЬКО `--local`, И ЭТО НАЙДЕНО ПРОВЕРКОЙ НА СЕБЕ. Первая редакция
    звала `git config user.name` без `--local`: git тогда поднимается
    к глобальному конфигу, находит там владельца и возвращает его. Проверка
    печатала «атрибуция чистая» в репе, где `.git` не было вовсе, а
    локального конфига — тем более. Она проверяла не то, что называла:
    величина взята не оттуда (`PIT-197`).
    """
    if not (репа / ".git").exists():
        # Нет репозитория — нет и локального конфига; требовать его не от чего.
        return []
    беды = []
    for ключ in ("user.name", "user.email"):
        значение = _git(репа, "config", "--local", ключ).strip()
        # 🔴 ПУСТО — ЭТО ТОЖЕ БЕДА, а не «нечего проверять»: без локального
        # значения коммит подпишется чем угодно из глобального конфига или
        # окружения, и защита держится на том, чего в этой репе не записано.
        if not значение:
            беды.append(f"git config {ключ} не задан локально — подпись непредсказуема")
            continue
        for имя in найти(значение, подпись=True):
            беды.append(f"git config {ключ} = «{значение}»: {имя}")
    return беды


def проверить_историю(репа: Path) -> list[str]:
    """Ни один коммит не подписан и не упоминает ассистента."""
    if not (репа / ".git").exists():
        return []
    сырое = _git(репа, "log", "--all", "--format=%H%x01%an%x01%ae%x01%cn%x01%ce%x01%B%x02")
    беды = []
    for запись in сырое.split("\x02"):
        if not запись.strip():
            continue
        части = запись.strip().split("\x01")
        if len(части) < 6:
            continue
        sha, an, ae, cn, ce, тело = части[:6]
        for поле, значение, подпись in (("автор", f"{an} <{ae}>", True),
                                        ("коммиттер", f"{cn} <{ce}>", True),
                                        ("сообщение", тело, False)):
            for имя in найти(значение, подпись=подпись):
                беды.append(f"{sha[:8]} — {поле}: {имя}")
    return беды


def проверить_настройки() -> list[str]:
    """`attribution` в settings.json выключен всеми тремя полями."""
    путь = Path.home() / ".claude" / "settings.json"
    if not путь.is_file():
        return ["~/.claude/settings.json не найден — attribution не подтверждён"]
    текст = путь.read_text(encoding="utf-8", errors="replace")
    беды = []
    if '"attribution"' not in текст:
        return ["в settings.json нет блока attribution — трейлер ничем не выключен"]
    for ключ in ('"commit"', '"pr"'):
        совпадение = re.search(rf'{ключ}\s*:\s*"([^"]*)"', текст)
        if совпадение is None:
            беды.append(f"attribution.{ключ.strip(chr(34))} отсутствует")
        elif совпадение.group(1).strip():
            беды.append(f"attribution.{ключ.strip(chr(34))} не пуст: «{совпадение.group(1)}»")
    if re.search(r'"sessionUrl"\s*:\s*true', текст):
        беды.append("attribution.sessionUrl = true — ссылка на сессию попадёт в коммит")
    return беды


def selftest() -> bool:
    """Канарейка: проверка обязана отличать чистое от отравленного.

    🔴 Без неё «бед нет» неотличимо от «проверка сломана и молчит» — ровно
    тот отказ, против которого вся эта защита и заводится.
    """
    # Атрибуция — запрещена везде, включая текст сообщения.
    атрибуция = [
        "Co-Authored-By: Claude <noreply@anthropic.com>",
        "🤖 Generated with Claude Code",
        "См. https://claude.ai/code/abc123",
    ]
    # 🔴 ГЛАВНОЕ В КАНАРЕЙКЕ: голое имя в СООБЩЕНИИ законно, в ПОДПИСИ нет.
    # Без этой пары проверка снова начнёт блокировать коммиты вида
    # «справочник Claude Code» — восемь таких нашлось в живой истории.
    предмет = [
        "base-repo v4.45.0 — механика сессий Claude Code: разбор",
        "feat: v1.2.0 — infra docs 11-17 + claude-context kit",
        "Лимиты изображений: claude.ai ≠ Claude Code, точный ресёрч",
    ]
    подписи_плохие = ["Claude <noreply@anthropic.com>", "Anthropic Assistant <x@y.z>"]
    чистое = [
        "Vasilii Evdokimov <vevdokimovm@gmail.com>",
        "base-repo v4.189.0 — гейт проверяет паспорт работы",
        "fix: убрать лишний клод в переменной",  # 🔴 намеренно: «клод» кириллицей
    ]
    return (all(найти(т) for т in атрибуция)
            and not any(найти(т) for т in предмет)          # в сообщении — можно
            and all(найти(т, подпись=True) for т in предмет)  # в подписи — нельзя
            and all(найти(т, подпись=True) for т in подписи_плохие)
            and not any(найти(т, подпись=True) for т in чистое))


def main() -> int:
    р = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    р.add_argument("--repo", type=Path)
    р.add_argument("--ident", action="store_true")
    р.add_argument("--message", type=Path)
    р.add_argument("--selftest", action="store_true")
    a = р.parse_args()

    # 🔴 КАНАРЕЙКА ИДЁТ ПЕРВОЙ И БЕЗ УСЛОВИЙ. В `stitch_png.py` она стояла
    # после разбора аргументов и не запускалась никогда.
    if a.selftest:
        ок = selftest()
        print("🟢 канарейка: проверка различает чистое и отравленное" if ок
              else "🔴 КАНАРЕЙКА УПАЛА — проверка не работает")
        return 0 if ок else 1

    беды: list[str] = []

    if a.message:
        беды += [f"сообщение коммита: {и}"
                 for и in найти(a.message.read_text(encoding="utf-8", errors="replace"))]

    if a.ident:
        for поле in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
            значение = subprocess.run(["git", "var", поле], capture_output=True,
                                      text=True).stdout.strip()
            беды += [f"{поле}: {и}" for и in найти(значение, подпись=True)]

    if a.repo:
        беды += проверить_конфиг(a.repo)
        беды += проверить_историю(a.repo)
        беды += проверить_настройки()

    if not (a.message or a.ident or a.repo):
        р.error("нужен хотя бы один из --repo / --ident / --message / --selftest")

    if беды:
        print("🔴 АТРИБУЦИЯ НАРУШЕНА — в работе владельца упомянут ассистент\n")
        for беда in беды:
            print(f"   · {беда}")
        print("\n   Правило: ~/.claude/CLAUDE.md, требование владельца 04.09.2026.")
        print("   Повод: адрес noreply@anthropic.com принадлежит постороннему")
        print("   человеку и показывался в контрибьюторах приватных реп.\n")
        return 1

    print("🟢 атрибуция чистая: в истории и настройках только владелец")
    return 0


if __name__ == "__main__":
    sys.exit(main())
