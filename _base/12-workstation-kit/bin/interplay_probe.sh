#!/bin/bash
# Совместный ряд: кадр с экрана Dota + состояние машины В ТОТ ЖЕ МОМЕНТ.
#
# 🔴 ЗАЧЕМ ОТДЕЛЬНО ОТ fps_probe.sh. Тот отвечает «сколько кадров».
# Этот отвечает на другой вопрос — «что происходило вокруг, когда их стало
# меньше». Два ряда, снятых порознь, связать нельзя: между ними неизвестный
# сдвиг, а просадка живёт секунды. Поэтому снимок экрана и строка показаний
# берутся в одном витке цикла, с одной меткой времени.
#
# Ничего в сеть не шлёт: только ps, vm_stat, sysctl и снимок nettop.
#
# Применение: interplay_probe.sh [кадров] [шаг_секунд] [каталог]
set -u
N="${1:-12}"
STEP="${2:-6}"
DIR="${3:-${TMPDIR:-/tmp}/interplay}"
RECT="${FPS_RECT:-1050,0,180,20}"
# 🔴 SHOTS=0 — ряд БЕЗ снимков экрана. Замерено 05.09.2026: в витке со снимком
# `WindowServer` подскакивал до 52 %, а `dota2` проседала с 252 до 128 %.
# Наблюдение не бесплатно, и на длинном ряду его цена накапливается.
# Показания машины стоят копейки, поэтому копить их можно часами;
# кадры снимаются короткими сериями, когда они действительно нужны.
SHOTS="${SHOTS:-1}"
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
WATCHED="dota2|Tunnel|claude|iTerm2|WindowServer|steam_osx"

mkdir -p "$DIR"
rm -f "$DIR"/f_*.png "$DIR"/strip.png
printf 'кадр\tвремя\tload1\tсвоб_МБ\tсвоп_МБ\tdota_cpu\tdota_МБ\tтун_cpu\tвахта_cpu\twinsrv_cpu\ten0_вниз\ten0_вверх\tповторы\tне_в_срок\tстраниц_с_диска\tиз_свопа\n' > "$DIR/rows.tsv"

read_en0() { netstat -ib | awk '$1=="en0" && $4 ~ /:/ {print $7" "$10; exit}'; }
read_tun() {
  nettop -P -x -t wifi -l 1 2>/dev/null \
    | awk '$2 ~ /^Tunnel/ {print $7" "$6; exit}'
}

# 🔴 ЗАНЯТОСТЬ СВОПА И РАБОТА СО СВОПОМ — РАЗНЫЕ ВЕЛИЧИНЫ. Замер 05.09.2026:
# занято 1.7 ГБ, а записей в своп за полминуты — НОЛЬ, чтения 1.3 МБ.
# Вывод «машина непрерывно свопит» был сделан по занятости и оказался неверен.
# Поэтому в ряду теперь обе: `своп_МБ` — сколько занято, `из_свопа` — сколько
# реально поднято за интервал. Вторая и есть то, чем нехватка памяти
# превращается в рывок.
read_vm() { vm_stat | awk '/Pageins/{gsub(/\./,"",$NF); p=$NF} /Swapins/{gsub(/\./,"",$NF); s=$NF} END{print p" "s}'; }

prev_en0="$(read_en0)"; prev_tun="$(read_tun)"; prev_vm="$(read_vm)"
i=0
while [ "$i" -lt "$N" ]; do
  i=$((i + 1))
  printf -v tag "%03d" "$i"
  [ "$SHOTS" = "1" ] && screencapture -x -R "$RECT" "$DIR/f_$tag.png" 2>/dev/null

  now="$(date +%H:%M:%S)"
  load="$(sysctl -n vm.loadavg | awk '{print $2}')"
  free_mb="$(vm_stat | awk '/Pages free/{gsub(/\./,"",$3); f=$3} /Pages speculative/{gsub(/\./,"",$3); s=$3} END{printf "%d", (f+s)*4096/1048576}')"
  swap_mb="$(sysctl -n vm.swapusage | sed -n 's/.*used = \([0-9.]*\)M.*/\1/p')"
  # 🔴 ИМЯ БЕРЁТСЯ ИЗ ХВОСТА СТРОКИ, А НЕ ИЗ $3. Пути на этой машине содержат
  # пробелы («…/Application Support/…»), awk режет их по пробелу, и $3 выходит
  # обрывком: у dota2 получался ноль при 300 % занятости. Поймано первым же
  # прогоном — правка проверяется запуском, а не перечитыванием (§2г, правило 3).
  procs="$(ps -Ao pcpu,rss,comm | awk '
    {
      path = ""
      for (j = 3; j <= NF; j++) path = path (j > 3 ? " " : "") $j
      n = path; sub(/.*\//, "", n)
      cpu[n] += $1; mem[n] += $2
    }
    END {
      printf "%.0f\t%.0f\t%.0f\t%.0f\t%.0f",
        cpu["dota2"], mem["dota2"]/1024, cpu["Tunnel"], cpu["claude"], cpu["WindowServer"]
    }')"

  cur_en0="$(read_en0)"; cur_tun="$(read_tun)"
  d_en0="$(awk -v a="$prev_en0" -v b="$cur_en0" 'BEGIN{split(a,p," ");split(b,c," ");
            printf "%d\t%d", c[1]-p[1], c[2]-p[2]}')"
  d_tun="$(awk -v a="$prev_tun" -v b="$cur_tun" 'BEGIN{split(a,p," ");split(b,c," ");
            r=c[1]-p[1]; o=c[2]-p[2]; if(r<0)r=0; if(o<0)o=0; printf "%d\t%d", r, o}')"
  prev_en0="$cur_en0"; prev_tun="$cur_tun"

  cur_vm="$(read_vm)"
  d_vm="$(awk -v a="$prev_vm" -v b="$cur_vm" 'BEGIN{split(a,p," ");split(b,c," ");
           printf "%d\t%d", c[1]-p[1], c[2]-p[2]}')"
  prev_vm="$cur_vm"

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$tag" "$now" "$load" "$free_mb" "${swap_mb:-0}" "$procs" "$d_en0" "$d_tun" "$d_vm" >> "$DIR/rows.tsv"

  [ "$i" -lt "$N" ] && sleep "$STEP"
done

if [ "$SHOTS" = "1" ]; then
  python3 "$SELF_DIR/stitch_png.py" "$DIR/strip.png" "$DIR"/f_*.png
  echo "показания: $DIR/rows.tsv — строки в том же порядке, что полосы сверху вниз"
else
  echo "показания: $DIR/rows.tsv (без снимков, SHOTS=0)"
fi
