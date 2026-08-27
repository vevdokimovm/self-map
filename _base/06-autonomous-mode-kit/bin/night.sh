#!/usr/bin/env bash
# =============================================================================
# night.sh — «ушёл спать» одной командой.
#
#   ~/repos/base-repo/06-autonomous-mode-kit/bin/night.sh
#
# Что делает сверх autonomous_loop.sh — то, что иначе владелец делает руками
# и однажды забудет:
#   · берёт бриф из 06-autonomous-mode-kit/runs/NIGHT-RUN-BRIEF.md, если не указан другой
#     (мандат живёт внутри репы, не в Downloads — исправлено 25.08.2026);
#   · оборачивает прогон в `caffeinate -i` — иначе ноутбук уснёт и прогон умрёт
#     на первой же паузе, а утром это выглядит как «агент ничего не сделал»;
#   · отвязывает от терминала (`nohup`) — закрытие окна больше не убивает прогон;
#   · печатает ОДНУ строку для остановки и одну для просмотра журнала.
#
# Почему отдельный файл, а не флаг: autonomous_loop.sh — механизм, он не должен
# знать про сон ноутбука и терминал. Здесь — сценарий владельца.
# =============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRIEF="${1:-$(dirname "$0")/../runs/NIGHT-RUN-BRIEF.md}"
HOURS="${2:-9}"

c(){ printf '\033[96m%s\033[0m\n' "$*"; }
y(){ printf '\033[93m%s\033[0m\n' "$*"; }
r(){ printf '\033[91m%s\033[0m\n' "$*"; }

if [ ! -f "$BRIEF" ]; then
  r "Нет брифа: $BRIEF"
  y "Шаблон — $HERE/../LAUNCH_BRIEF.md. Без письменного мандата прогон не запускается."
  exit 2
fi

RUN_DIR="$HOME/claude-autonomous-runs/$(date +%Y-%m-%d_%H%M%S)"

c "── Ночной прогон"
printf '  бриф:    %s\n' "$BRIEF"
printf '  часов:   %s\n' "$HOURS"
printf '  прогон:  %s\n' "$RUN_DIR"
echo

# Предполётный сухой прогон: если что-то не так с брифом или лимитами,
# лучше узнать сейчас, а не утром по пустому журналу.
if ! bash "$HERE/autonomous_loop.sh" --brief "$BRIEF" --hours "$HOURS" \
        --run-dir "$RUN_DIR" --dry >/dev/null 2>&1; then
  r "Сухой прогон не прошёл — запускаю его повторно, чтобы показать причину:"
  bash "$HERE/autonomous_loop.sh" --brief "$BRIEF" --hours "$HOURS" --dry
  exit 2
fi

nohup caffeinate -i bash "$HERE/autonomous_loop.sh" \
      --brief "$BRIEF" --hours "$HOURS" --run-dir "$RUN_DIR" \
      > "$RUN_DIR/nohup.out" 2>&1 &
PID=$!
sleep 2

if ! kill -0 "$PID" 2>/dev/null; then
  r "Прогон не стартовал. Последние строки:"
  tail -20 "$RUN_DIR/nohup.out" 2>/dev/null
  exit 1
fi

printf '\033[92m✓ прогон идёт, PID %s — терминал можно закрывать\033[0m\n\n' "$PID"
c "Остановить:"
printf '  touch %s/STOP\n\n' "$RUN_DIR"
c "Посмотреть утром:"
printf '  column -t -s"$(printf "\\t")" %s/journal.tsv\n' "$RUN_DIR"
printf '  tail -40 %s/nohup.out\n' "$RUN_DIR"
