#!/bin/sh
# Состояние сборщиков наблюдения — живы ли и сколько им осталось.
#
# 🔴 ЗАЧЕМ ОТДЕЛЬНЫЙ ИНСТРУМЕНТ (`PIT-201`). Сборщики живут заданное число
# секунд и умирают МОЛЧА. 05.09.2026 `freeze_watch.sh` кончился посреди
# игры владельца, и шесть минут остались без наблюдения — заметилось
# случайно. Разбор потом кричит о дыре, но кричит ПОСЛЕ. Здесь — до.
#
# 🔴 ИМЕНА ПЕРЕМЕННЫХ — ТОЛЬКО ЛАТИНИЦА. Первая редакция ЭТОГО файла звала
# их по-русски и упала на `КИТ=...: No such file or directory` — ровно так
# же, как `freeze_watch.sh` неделей раньше, и красный блок про это стоит
# у него в шапке. Повтор при живом предупреждении: соседний файл читают
# не тогда, когда пишут похожий, а когда он сломался.
#
#   collectors.sh          состояние
#   collectors.sh start    поднять то, что лежит
set -u
KIT="$(cd "$(dirname "$0")/.." && pwd)"

status() {
  for name in freeze_watch conn_sampler dns_probe; do
    pid="$(pgrep -f "$name.sh" | head -1)"
    if [ -z "$pid" ]; then
      printf '🔴 %-14s НЕ РАБОТАЕТ\n' "$name"
      continue
    fi
    age="$(ps -o etime= -p "$pid" | tr -d ' ')"
    dur="$(ps -o args= -p "$pid" | awk '{print $3}')"
    # 🔴 ОТВЕЧАТЬ НАДО НА «СКОЛЬКО ОСТАЛОСЬ», а не «сколько задано»:
    # первая редакция печатала срок из аргументов, и «срок 5400 с»
    # выглядело благополучно у процесса, которому жить 17 минут.
    left="$(awk -v a="$age" -v d="${dur:-0}" 'BEGIN{
      n=split(a,p,":"); s=0; for(i=1;i<=n;i++) s=s*60+p[i];
      r=d-s; if(d+0==0){print "?"} else if(r<=0){print "истёк"}
      else printf "%d:%02d", int(r/60), r%60 }')"
    mark="🟢"
    case "$left" in истёк) mark="🔴";; esac
    printf '%s %-14s pid %-6s живёт %-9s осталось %s\n' "$mark" "$name" "$pid" "$age" "$left"
  done
}

# 🔴 ПОРОГ ДОСРОЧНОЙ СМЕНЫ. Первая редакция поднимала только МЁРТВЫХ,
# и этого мало: сборщик с остатком в 10 минут переживёт запуск, умрёт
# через десять минут — и дыра появится всё равно. Инструмент ловил смерть,
# но не предотвращал разрыв, ради которого заводился (`PIT-201`).
# Поэтому сборщик с остатком меньше порога СМЕНЯЕТСЯ ЗАРАНЕЕ: старый
# гасится, новый встаёт сразу. Гасить обязательно — два сборщика пишут
# в один файл и перемешали бы ряд.
# Порог перекрывается извне — иначе ветку досрочной смены нельзя
# проверить, не дожидаясь конца срока сборщика.
RENEW="${RENEW:-420}"

left_seconds() {
  pid="$1"
  age="$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')"
  dur="$(ps -o args= -p "$pid" 2>/dev/null | awk '{print $3}')"
  [ -n "$age" ] && [ -n "$dur" ] || { echo 0; return; }
  awk -v a="$age" -v d="$dur" 'BEGIN{
    n=split(a,p,":"); s=0; for(i=1;i<=n;i++) s=s*60+p[i];
    r=d-s; print (r>0 ? int(r) : 0) }'
}

ensure() {
  name="$1"; shift
  pid="$(pgrep -f "$name.sh" | head -1)"
  if [ -n "$pid" ]; then
    rest="$(left_seconds "$pid")"
    if [ "$rest" -gt "$RENEW" ]; then
      return
    fi
    printf 'смена заранее: %s (осталось %s с)\n' "$name" "$rest"
    kill "$pid" 2>/dev/null
    sleep 1
  fi
  nohup bash "$KIT/bin/$name.sh" "$@" >/dev/null 2>&1 &
}

case "${1:-status}" in
  start)
    ensure freeze_watch 3600
    ensure conn_sampler 5400 15
    ensure dns_probe 3600 5
    sleep 2
    status
    ;;
  *) status ;;
esac
