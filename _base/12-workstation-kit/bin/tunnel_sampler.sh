#!/bin/bash
# Пассивный сбор счётчиков туннеля и игры во время матча.
# 🔴 -t wifi ОБЯЗАТЕЛЕН: без него nettop складывает loopback с сетью
#    и объём завышается в разы (PIT-197).
# Ничего в сеть не шлёт — только читает снимок nettop.
# Применение: tunnel_sampler.sh [секунд_всего] [шаг_секунд]
set -u
DUR="${1:-1800}"
STEP="${2:-10}"
OUT="$(cd "$(dirname "$0")/.." && pwd)/observations/tunnel-samples.tsv"
[ -s "$OUT" ] || printf 'время\tпроцесс\tвниз_Б\tвверх_Б\tдубли\tне_в_срок\tповторы\n' > "$OUT"

END=$(( $(date +%s) + DUR ))
while [ "$(date +%s)" -lt "$END" ]; do
  nettop -P -x -t wifi -l 1 2>/dev/null | awk -v ts="$(date +%H:%M:%S)" '
    $2 ~ /^(Tunnel|dota2|steam_osx)\./ {
      split($2, a, "."); print ts "\t" a[1] "\t" $3 "\t" $4 "\t" $5 "\t" $6 "\t" $7
    }' >> "$OUT"
  sleep "$STEP"
done
