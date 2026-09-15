#!/usr/bin/env bash
# Периодическая самопроверка инфры без участия владельца — по заказу 27.08.2026:
# «система должна помнить сама и делать», не календарное напоминание человеку.
#
# ПОЧЕМУ launchd, А НЕ create_trigger (`34-cowork-scheduled-tasks.md`):
# create_trigger стартует свежую сессию НА СЕРВЕРЕ Anthropic — без доступа к
# ~/repos/ на этой конкретной машине. owner_blockers.py и sync_base_local.py
# читают локальный диск, значит задача обязана идти локально
# (`51-autonomous-agent-loop.md` §9, строка «Задача обязана идти локально»).
#
# ЛОГИКА: launchd будит этот скрипт часто (раз в неделю) и дёшево — сам скрипт
# сначала смотрит на recorded-даты в infra-liveness.md БЕЗ вызова Claude. Только
# если прошло >=14 дней с последнего прогона — зовёт `claude -p` по-настоящему.
# Так частый будильник не означает частую (дорогую) сессию.
set -Eeuo pipefail

BASE_REPO="$HOME/repos/base-repo"
LIVENESS="$BASE_REPO/reports/infra-liveness.md"
THRESHOLD_DAYS=14
LOG="/tmp/infra-liveness-check.log"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

if [ ! -f "$LIVENESS" ]; then
  log "нет $LIVENESS — пропуск (ждёт первого ручного прогона)"
  exit 0
fi

oldest_days=0
while IFS= read -r date_str; do
  [ -z "$date_str" ] && continue
  run_epoch=$(date -j -f "%Y-%m-%d" "$date_str" "+%s" 2>/dev/null) || continue
  now_epoch=$(date "+%s")
  days=$(( (now_epoch - run_epoch) / 86400 ))
  [ "$days" -gt "$oldest_days" ] && oldest_days=$days
done < <(grep -oE '\| [0-9]{4}-[0-9]{2}-[0-9]{2} \|' "$LIVENESS" | tr -d '| ')

log "самый старый прогон: $oldest_days дней назад (порог $THRESHOLD_DAYS)"

if [ "$oldest_days" -lt "$THRESHOLD_DAYS" ]; then
  log "всё свежо, Claude не зовём"
  exit 0
fi

log "порог превышен — зову claude -p"

PROMPT='Работай в base-repo (~/repos/base-repo). Задача периодической самопроверки
инфры, без диалога, без вопросов: (1) прогони `python3 scripts/owner_blockers.py`,
(2) прогони `python3 scripts/sync_base_local.py --all` (требует gh; если недоступен —
не молчать, вывести ошибку в конце и остановиться на этом шаге). Оба скрипта сами
пишут дату в reports/infra-liveness.md при штатном прогоне — отдельно ничего не
записывать. Если owner_blockers.py покажет группы устаревших блокировок (репа
поднята до v1.0.0+, а TASKS.md всё ещё просит материалы) — закрой их тем же
способом, что использован 27.08.2026 (перенос закрытого пункта в TASKS_HISTORY.md
с датой и причиной "репа наполнена волной, пункт устарел"), но НЕ трогай репы
ниже v1.0.0 — там блокировка настоящая. Если что-то в base-repo изменилось —
обычный цикл: revision_check.py -> VERSION/CHANGELOG/WATCHLOG -> pack_release.py.
Ничего не спрашивай, отчёт не нужен — это фоновый прогон без владельца у экрана.'

cd "$BASE_REPO"
claude -p "$PROMPT" --dangerously-skip-permissions --output-format json \
  > /tmp/infra-liveness-claude-out.json 2>>"$LOG" || log "claude -p вернул ошибку, см. $LOG"

log "прогон завершён"
