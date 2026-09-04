#!/usr/bin/env bash
# =============================================================================
# autonomous_loop.sh — локальный контур автономной работы.
#
# Закрывает `ROADMAP.md` §P1.6a: «уехать на неделю, один раз сказать „продолжай"».
# Ресёрч под ним УЖЕ был (`00-infrastructure/51-autonomous-agent-loop.md` §5–§9,
# `06-autonomous-mode-kit/`) — здесь его сборка. Ничего не исследуется заново (PIT-072).
#
# ЧТО ЭТО ДЕЛАЕТ
#   1. Читает бриф (заполненный `LAUNCH_BRIEF.md`) — он и есть промпт.
#   2. Запускает `claude -p`, сохраняет `session_id`, дальше продолжает `--resume`.
#   3. Перед каждой попыткой спрашивает `limits_watch.py`, не упёрты ли лимиты,
#      и ждёт ровно столько, сколько тот назвал (машинный `resetsAt`, не парсинг экрана).
#   4. На сбое — backoff 30/60/120/240/300 с джиттером ±15% (`51` §5).
#   5. Пишет журнал: одна строка на попытку (закон 5 кита — записано по ходу, иначе не было).
#   6. Останавливается по стоп-файлу, дедлайну или пределу итераций.
#
# ЧЕГО ЭТО НЕ ДЕЛАЕТ НАМЕРЕННО
#   · Не решает, ЧТО делать — это в брифе (закон 1 кита).
#   · Не публикует, не удаляет, не деплоит — стоп-классы описаны в STOP_CONDITIONS.md
#     и обязаны стоять в самом брифе: скрипт их не навязывает и навязать не может.
#   · Не переживает выключение ноутбука. Нужна независимость от машины — Routines
#     (`51` §7, §9), а не этот файл.
#
# ЗАПУСК
#   ./autonomous_loop.sh --brief ~/runs/2026-08-22/BRIEF.md --hours 24
#   ./autonomous_loop.sh --brief BRIEF.md --dry            # план, ноль вызовов
#   touch "$RUN_DIR/STOP"                                  # мягкая остановка
#
# ПРИЁМКА (`ROADMAP.md` §P1.6a): не «скрипт написан», а прогон длиннее суток
# с искусственным обрывом сети посередине. До такого прогона контур считается несобранным.
# =============================================================================
set -uo pipefail          # без -e намеренно: падение вызова — штатное событие цикла

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

BRIEF=""
HOURS=24
MAX_ITER=0                # 0 = без предела по числу итераций
DRY=0
RUN_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --brief)     BRIEF="${2:-}"; shift 2 ;;
    --hours)     HOURS="${2:-}"; shift 2 ;;
    --max-iter)  MAX_ITER="${2:-}"; shift 2 ;;
    --run-dir)   RUN_DIR="${2:-}"; shift 2 ;;
    --dry)       DRY=1; shift ;;
    -h|--help)   sed -n '2,40p' "$0"; exit 0 ;;
    *) printf '\033[91mнеизвестный ключ: %s\033[0m\n' "$1" >&2; exit 2 ;;
  esac
done

# --- Предусловия. Отказ громкий: молчаливый старт без брифа хуже, чем не старт ---
if [ -z "$BRIEF" ] || [ ! -f "$BRIEF" ]; then
  printf '\033[91mНЕТ БРИФА.\033[0m Автономный прогон без письменного мандата не запускается.\n' >&2
  printf 'Шаблон: %s/LAUNCH_BRIEF.md — заполнить и передать через --brief\n' "$KIT_DIR" >&2
  exit 2
fi
if ! grep -q "СТОП" "$BRIEF" 2>/dev/null; then
  printf '\033[91mВ БРИФЕ НЕТ РАЗДЕЛА СТОП-УСЛОВИЙ.\033[0m\n' >&2
  printf 'Закон 2 кита: стоп-условия сильнее продуктивности и пишутся ДО запуска.\n' >&2
  printf 'Образец — %s/STOP_CONDITIONS.md\n' "$KIT_DIR" >&2
  exit 2
fi
command -v claude >/dev/null 2>&1 || { printf '\033[91mclaude не найден в PATH\033[0m\n' >&2; exit 2; }

[ -n "$RUN_DIR" ] || RUN_DIR="$HOME/claude-autonomous-runs/$(date +%Y-%m-%d_%H%M%S)"
mkdir -p "$RUN_DIR"
SESSION_FILE="$RUN_DIR/session_id"
JOURNAL="$RUN_DIR/journal.tsv"
LAST_OUT="$RUN_DIR/last_output.json"
STOP_FILE="$RUN_DIR/STOP"
DEADLINE=$(( $(date +%s) + HOURS * 3600 ))

# --- Настройки устойчивости из `51` §5. Задаются здесь, а не в глобальном settings.json:
#     глобальная правка мешает обычным сессиям (память про /auto-mode-setup).
export CLAUDE_CODE_MAX_RETRIES="${CLAUDE_CODE_MAX_RETRIES:-15}"
export CLAUDE_CODE_RETRY_WATCHDOG="${CLAUDE_CODE_RETRY_WATCHDOG:-1}"
export API_TIMEOUT_MS="${API_TIMEOUT_MS:-1800000}"      # 30 мин: VPN и мобильная сеть

[ -f "$JOURNAL" ] || printf 'время\tитерация\tсобытие\tкод\tдлительность_с\tзаметка\n' > "$JOURNAL"

log() {  # время · итерация · событие · код · длительность · заметка
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" "$3" "$4" "$5" >> "$JOURNAL"
}

say() { printf '\033[96m%s\033[0m\n' "$*"; }   # только яркие коды: тёмные не видны

BACKOFF="30 60 120 240 300"
backoff_at() {   # bash 3.2 не знает массивов по-человечески — берём словом из строки.
  # `awk`, не `for v in $BACKOFF` — тот полагался на word splitting, которого
  # zsh без setopt sh_word_split не делает (PIT-017, найдено check_shell_
  # antipatterns.py 28.08.2026). awk с here-string безопасен в bash и zsh одинаково.
  local i=$1
  awk -v n="$i" '{ print (n>=1 && n<=NF) ? $n : 300 }' <<< "$BACKOFF"
}

say "прогон:  $RUN_DIR"
say "бриф:    $BRIEF"
say "дедлайн: $(date -r "$DEADLINE" '+%Y-%m-%d %H:%M') (через ${HOURS} ч)"
say "остановить мягко:  touch $STOP_FILE"
# 🔴 ОБЕЩАНИЕ НАЗЫВАЕТСЯ ЧИСЛОМ, А НЕ СЛОВОМ «мягко». Замер
# `test_stop_latency.sh` 04.09.2026: между итерациями выход за 0 с,
# ВО ВРЕМЯ работы — только после её конца (27 с при стабе 25 с).
# Слово «мягко» без числа читается как «сейчас», и владелец,
# нажавший на тормоз, не понимает, почему цикл ещё идёт.
say "  ↑ остановится ПОСЛЕ текущей итерации, не мгновенно"
say "    длительность живой итерации пока не измерена — прогонов не было"
say "  🔴 мягко = ПОСЛЕ текущей итерации, не мгновенно (замер: до 20 мин)"

if [ "$DRY" -eq 1 ]; then
  say "--dry: ни одного вызова не делается"
  printf 'env: MAX_RETRIES=%s WATCHDOG=%s TIMEOUT_MS=%s\n' \
    "$CLAUDE_CODE_MAX_RETRIES" "$CLAUDE_CODE_RETRY_WATCHDOG" "$API_TIMEOUT_MS"
  python3 "$SCRIPT_DIR/limits_watch.py" || true
  log 0 "dry-run" 0 0 "план показан, вызовов нет"
  exit 0
fi

iter=0
fails=0
while true; do
  iter=$((iter+1))

  # --- стоп-условия проверяются ПЕРЕД работой, а не после ---
  if [ -f "$STOP_FILE" ]; then
    say "СТОП-файл найден — останавливаюсь"; log "$iter" "stop-file" 0 0 "$(cat "$STOP_FILE" 2>/dev/null | head -1)"; break
  fi
  now=$(date +%s)
  if [ "$now" -ge "$DEADLINE" ]; then
    say "дедлайн ${HOURS} ч исчерпан"; log "$iter" "deadline" 0 0 "прогон завершён по времени"; break
  fi
  if [ "$MAX_ITER" -gt 0 ] && [ "$iter" -gt "$MAX_ITER" ]; then
    say "предел итераций $MAX_ITER"; log "$iter" "max-iter" 0 0 ""; break
  fi

  # --- лимиты: ждём ровно столько, сколько назвал resetsAt, но не дольше дедлайна ---
  wait_s="$(python3 "$SCRIPT_DIR/limits_watch.py" --wait-seconds 2>/dev/null || echo 0)"
  case "$wait_s" in (*[!0-9]*) wait_s=0 ;; esac
  if [ "$wait_s" -gt 0 ]; then
    left=$(( DEADLINE - $(date +%s) ))
    [ "$wait_s" -gt "$left" ] && wait_s="$left"
    # Спим порциями: отказ бывает преодолим раньше сброса окна (см. потолок limits_watch).
    # 🔴 Обещание «стоп в течение минуты» верно ТОЛЬКО ЗДЕСЬ — в паузе по лимиту,
    # где мы сами спим кусками по 60 с. В рабочей фазе стоп ждёт конца итерации
    # (замер: `test_stop_latency.sh`, случай S2). Уточнено 04.09.2026: прежняя
    # формулировка звучала как общее свойство цикла и вводила в заблуждение.
    say "лимит: жду до $wait_s с, проверяя стоп каждые 60 с"
    log "$iter" "limit-wait" 0 "$wait_s" "resetsAt из лога сессии"
    slept=0
    while [ "$slept" -lt "$wait_s" ]; do
      [ -f "$STOP_FILE" ] && break
      sleep 60; slept=$((slept+60))
    done
    continue
  fi

  started=$(date +%s)
  if [ -s "$SESSION_FILE" ]; then
    sid="$(cat "$SESSION_FILE")"
    claude -p --resume "$sid" "продолжай" \
      --dangerously-skip-permissions --output-format json > "$LAST_OUT" 2>"$RUN_DIR/last_error.txt"
    rc=$?
    mode="resume"
  else
    claude -p "$(cat "$BRIEF")" \
      --dangerously-skip-permissions --output-format json > "$LAST_OUT" 2>"$RUN_DIR/last_error.txt"
    rc=$?
    mode="start"
    if [ "$rc" -eq 0 ]; then
      python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("session_id",""))' \
        "$LAST_OUT" 2>/dev/null > "$SESSION_FILE"
      [ -s "$SESSION_FILE" ] || rm -f "$SESSION_FILE"
    fi
  fi
  took=$(( $(date +%s) - started ))
  cp "$LAST_OUT" "$RUN_DIR/out_$(printf '%04d' "$iter").json" 2>/dev/null

  if [ "$rc" -eq 0 ]; then
    fails=0
    log "$iter" "$mode" "$rc" "$took" "ok"
    say "итерация $iter · $mode · ${took}с · ok"
  else
    fails=$((fails+1))
    note="$(head -c 200 "$RUN_DIR/last_error.txt" 2>/dev/null | tr '\t\n' '  ')"
    log "$iter" "$mode" "$rc" "$took" "$note"
    b="$(backoff_at "$fails")"
    say "итерация $iter · сбой rc=$rc · подряд $fails · пауза ${b}с"
    # джиттер ±15%: одновременные ретраи нескольких вахт не должны складываться
    j=$(( b * (85 + RANDOM % 31) / 100 ))
    sleep "$j"
  fi
done

say "журнал: $JOURNAL"
tail -5 "$JOURNAL"
