#!/usr/bin/env bash
# watch-identity.sh — определить, под какой вахтой идёт сессия, и сказать это вслух.
#
# Версия: 1.0.0 (2026-08-28)
#
# ЗАЧЕМ ХУК, А НЕ ПРАВИЛО В ТЕКСТЕ.
# Требование владельца 28.08.2026: «внеси правило чекать вахту автоматически
# каждый раз, когда видишь команду login успешно завершившуюся» — и сразу
# следом: «не правило, а автоматическое что-то», «не просто теорию, а рабочий
# механизм».
#
# Он прав по существу, и это подтверждено официально (внешний ресёрч 28.08.2026,
# `reports/research/claude-official-practice-vs-internal-2026-08-28.md` §1.1):
#   «Claude treats them as context, NOT enforced configuration. To block an
#    action regardless of what Claude decides, use a PreToolUse hook instead.»
#   «Unlike CLAUDE.md instructions which are advisory, hooks are deterministic.»
#
# Правило «проверяй вахту после /login» существовало и **не сработало дважды**:
# PIT-156 (буква записана по шаблону) и 28.08.2026 (владелец: «ты забываешь
# чекать вахту автоматически, она снова сменилась»). Оба раза — не забывчивость,
# а отсутствие механизма: у Claude НЕТ доступа к своей почте (credentials в
# Keychain), после /login личность меняется МОЛЧА, ни одного сигнала в контексте.
# Текст, который надо вспомнить, против события, которое происходит само, —
# проигрывает всегда.
#
# ЧТО ДЕЛАЕТ. Читает `~/.claude.json` (тот же источник, что panel_probe.py), сопоставляет
# email с буквой вахты и печатает строку в контекст. Ничего не блокирует:
# это информирование, не запрет — неверная буква не повод останавливать работу,
# повод её знать.
#
# УСТАНОВКА: событие SessionStart в .claude/settings.json (плюс UserPromptSubmit,
# если нужна проверка чаще — но это дороже, а личность за один промпт не меняется).

set -Eeuo pipefail

MAP_FILE="${CLAUDE_PROJECT_DIR:-$PWD}/../mission-control/ACCOUNTS.md"
STATE_DIR="${TMPDIR:-/tmp}/claude-watch-identity"
mkdir -p "$STATE_DIR" 2>/dev/null || true
STATE_FILE="$STATE_DIR/last-email"

# --- достать email ------------------------------------------------------------
# Источник — `~/.claude.json`, поле `oauthAccount.emailAddress`. Тот же, что
# у `panel_probe.py` (проверено 28.08.2026: keychain держит ТОКЕН, а email —
# здесь; первая редакция хука полезла в keychain и молча вернула пустое —
# ровно тот отказ, который PIT-016 велит ловить проверкой вывода).
# Пусто или ошибка — молчим: хук, роняющий сессию, хуже отсутствующего.
email=""
CLAUDE_JSON="$HOME/.claude.json"
if [ -f "$CLAUDE_JSON" ]; then
  email="$(python3 -c '
import json, sys, pathlib
try:
    d = json.loads(pathlib.Path(sys.argv[1]).read_text())
    print((d.get("oauthAccount") or {}).get("emailAddress") or "")
except Exception:
    print("")' "$CLAUDE_JSON" 2>/dev/null)"
fi

[ -n "$email" ] || exit 0

# --- сопоставить с буквой вахты ------------------------------------------------
# Источник соответствия — ACCOUNTS.md планировщика. Хардкод здесь был бы
# четвёртой копией правды (PIT-097: список — намерение, свойство — факт).
letter=""
case "$email" in
  vevdokimovm@gmail.com)        letter="V" ;;
  finpilot.support@proton.me)   letter="A" ;;
  *)
    # не захардкожено — ищем в таблице ACCOUNTS.md по email
    if [ -f "$MAP_FILE" ]; then
      letter="$(grep -oE '\*\*[VJMSA]\*\*[^|]*\|[^|]*'"${email//./\\.}" "$MAP_FILE" 2>/dev/null \
                | grep -oE '\*\*[VJMSA]\*\*' | head -1 | tr -d '*')"
    fi
    ;;
esac

prev=""
[ -f "$STATE_FILE" ] && prev="$(cat "$STATE_FILE" 2>/dev/null || true)"
printf '%s' "$email" > "$STATE_FILE" 2>/dev/null || true

if [ -n "$letter" ]; then
  msg="Вахта этой сессии: ${letter} (${email})."
else
  msg="🔴 Вахта НЕ ОПОЗНАНА: ${email} — нет в таблице ACCOUNTS.md. Не угадывать букву, спросить владельца."
fi

if [ -n "$prev" ] && [ "$prev" != "$email" ]; then
  msg="$msg 🔴 ЛИЧНОСТЬ СМЕНИЛАСЬ (было: ${prev}) — записи в WATCHLOG под прежней буквой перепроверить."
fi

echo "$msg"
exit 0
