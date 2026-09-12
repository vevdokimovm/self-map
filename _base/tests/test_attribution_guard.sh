#!/usr/bin/env bash
# Защита атрибуции: ассистент не может попасть в contributors ни одним путём.
#
# 🔴 ЗАЧЕМ ТЕСТ, А НЕ ДОВЕРИЕ К КОДУ. Требование владельца 04.09.2026 —
# «ни в контрибьюторах гита, ни в commit_tryах, ни в релизах, нигде». Повод
# реальный: адрес `noreply@anthropic.com` зарегистрирован на постороннего
# человека и показывался в контрибьюторах приватных реп.
#
# Защита из трёх слоёв, и тест проверяет КАЖДЫЙ отдельно:
#   1. `commit-msg`  — блокирует трейлер и подписи в тексте сообщения;
#   2. `--ident`     — блокирует отравленного автора при чистом сообщении;
#   3. `--repo`      — находит грязь в УЖЕ существующей истории (постфактум).
#
# 🔴 Тест обязан проверять и обратное: чистый commit_try должен ПРОХОДИТЬ.
# Защита, которая блокирует всё, неотличима от сломанной.
#
# 🔴 ИМЕНА ПЕРЕМЕННЫХ — ТОЛЬКО ЛАТИНИЦА (`PIT-202`, ТРЕТИЙ повтор).
# Первая редакция ЭТОГО файла звала их по-русски и упала на
# `БАЗА=...: No such file or directory`. Bash разбирает такое присваивание
# как команду. Тот же промах уже стоил запуска `freeze_watch.sh`
# и `collectors.sh`. Третий повтор переводит класс в механическую
# проверку — она заведена: `scripts/shell_ascii_check.py`.
#
# Запуск:  bash tests/test_attribution_guard.sh
set -u

BASE="$(cd "$(dirname "$0")/.." && pwd)"
CHECK="$BASE/scripts/attribution_check.py"
STAND="$(mktemp -d "${TMPDIR:-/tmp}/attr_guard_XXXXXX")"
fails=0
n=0

verdict() {  # ожидание фактический_код имя
  n=$((n + 1))
  if [ "$1" = "$2" ]; then
    printf '  🟢 %d. %s\n' "$n" "$3"
  else
    printf '  🔴 %d. %s — ждали код %s, получили %s\n' "$n" "$3" "$1" "$2"
    fails=$((fails + 1))
  fi
}

commit_try() {  # сообщение -> код возврата (0 = commit_try прошёл)
  echo "$RANDOM" > "$STAND/f_$n.txt"
  git -C "$STAND" add -A >/dev/null 2>&1
  git -C "$STAND" commit -q -m "$1" >/dev/null 2>&1
  echo $?
}

echo "стенд: $STAND"
git -C "$STAND" init -q
git -C "$STAND" config user.name  "Vasilii Evdokimov"
git -C "$STAND" config user.email "vevdokimovm@gmail.com"
git -C "$STAND" config core.hooksPath "$BASE/.githooks"

echo
echo "=== СЛОЙ 1: сообщение коммита ==="
verdict 0 "$(commit_try 'feat: обычная работа владельца')"                    "чистый коммит ПРОХОДИТ"
verdict 1 "$(commit_try 'feat: x

Co-Authored-By: Claude <noreply@anthropic.com>')"                       "трейлер Co-Authored-By блокируется"
verdict 1 "$(commit_try 'feat: x

🤖 Generated with Claude Code')"                                        "подпись Generated with блокируется"
verdict 1 "$(commit_try 'feat: x

https://claude.ai/code/abc123')"                                        "ссылка на сессию блокируется"
# 🔴 ГОЛОЕ ИМЯ В СООБЩЕНИИ — ЗАКОННО И ОБЯЗАНО ПРОХОДИТЬ.
# Проверка живой истории 07.09.2026 нашла восемь таких коммитов, и все
# восемь — предмет работы владельца: «справочник Claude Code»,
# «claude-context kit», «лимиты claude.ai ≠ Claude Code». Защита, которая
# их блокирует, запрещает писать документы про инструмент — это помеха,
# а не безопасность.
verdict 0 "$(commit_try 'docs: справочник Claude Code и лимиты claude.ai')"     "имя в ТЕКСТЕ проходит — это предмет работы"

echo
echo "=== СЛОЙ 2: автор при ЧИСТОМ сообщении ==="
git -C "$STAND" config user.email "noreply@anthropic.com"
verdict 1 "$(commit_try 'feat: сообщение полностью чистое')"                  "отравленный автор блокируется"
git -C "$STAND" config user.email "vevdokimovm@gmail.com"
verdict 0 "$(commit_try 'feat: автор возвращён владельцу')"                   "после починки автора коммит ПРОХОДИТ"

echo
echo "=== СЛОЙ 3: грязь в УЖЕ существующей истории ==="
python3 "$CHECK" --repo "$STAND" >/dev/null 2>&1
verdict 0 "$?"                                                            "чистая история признаётся чистой"

# 🔴 --no-verify обходит хуки ПО ПОСТРОЕНИЮ, это свойство git, а не дыра
# нашей защиты. Именно поэтому нужен слой 3: он ловит то, что просочилось
# мимо хуков, при каждом закрытии батча.
git -C "$STAND" config user.email "claude@anthropic.com"
echo "obhod" > "$STAND/obhod.txt"
git -C "$STAND" add -A >/dev/null 2>&1
git -C "$STAND" commit -q --no-verify -m "feat: мимо хуков" >/dev/null 2>&1
python3 "$CHECK" --repo "$STAND" >/dev/null 2>&1
verdict 1 "$?"                                                            "коммит в обход --no-verify НАХОДИТСЯ постфактум"

echo
echo "=== КАНАРЕЙКА самой проверки ==="
python3 "$CHECK" --selftest >/dev/null 2>&1
verdict 0 "$?"                                                            "проверка различает чистое и отравленное"

rm -rf "$STAND"
echo
if [ "$fails" -eq 0 ]; then
  echo "🟢 ВСЕ $n ПРОВЕРОК ПРОШЛИ — ассистент не попадёт в contributors"
  exit 0
fi
echo "🔴 ПРОВАЛОВ: $fails из $n — ЗАЩИТА НЕ РАБОТАЕТ"
exit 1
