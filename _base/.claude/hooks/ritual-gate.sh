#!/bin/bash
# Stop-хук: артефакт правлен, обвязка отстала — не даём закончить ход.
#
# ЗАЧЕМ. Класс PIT-G из reports/incidents/PITFALLS.md — «артефакт правлен, его
# обвязка нет», **4 повтора**. Все четыре раза правило было записано и известно:
# отказывает не знание, а МОМЕНТ. Обвязка (копии, журнал, спека, число в прозе)
# правится последней, когда работа уже ощущается сделанной, и ровно тогда
# внимание кончается.
#
# Гейты для этого есть — deploy_version_gate.py, revision_check.py. Их надо
# ЗАПУСТИТЬ, и именно этот шаг пропускается. Хук запускается сам.
#
# ГРАНИЦА, названная вслух (71 §7г-бис): ловится только механическое расхождение
# версий и чисел. «Правку сделал плохо» хук не видит и видеть не может — это
# ревизия, а не гейт.
#
# stop_hook_active guard обязателен: без него Stop-хук порождает следующий Stop
# и блок зацикливается (та же причина, что в finpilot/tests-gate.sh).
set -uo pipefail

input=$(cat)
active=$(printf '%s' "$input" | python3 -c '
import json, sys
try: print(json.load(sys.stdin).get("stop_hook_active", False))
except Exception: print(False)
') || exit 0
{ [ "$active" = "True" ] || [ "$active" = "true" ]; } && exit 0

root="${CLAUDE_PROJECT_DIR:-.}"
cd "$root" 2>/dev/null || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
[ -f VERSION ] || exit 0

problems=""

# --- 1. Деплойер: версия против журнала, спеки и КОПИЙ на диске ---------------
# Копии — главное: владелец запускает ~/Downloads/deploy.sh, а не канон в репе.
# Именно так правка 4.17.1 не доехала до него 21.08.2026 (повтор №4 в PIT-G).
if [ -f scripts/deploy_version_gate.py ] && [ -f templates/deploy.sh ]; then
  if ! out=$(python3 scripts/deploy_version_gate.py 2>&1); then
    problems="${problems}
▸ ДЕПЛОЙЕР — версия, документация и копии разошлись:
$(printf '%s' "$out" | grep -E '^\s+FAIL' | head -6)

  Починить:  python3 scripts/deploy_version_gate.py --fix
             python3 scripts/deploy_version_gate.py --sync-copies"
  fi
fi

# --- 2. Ревизионный гейт: числа в прозе, дубли разделов, журнал кампании ------
if [ -f scripts/revision_check.py ]; then
  if ! out=$(python3 scripts/revision_check.py --root . 2>&1); then
    problems="${problems}
▸ РЕВИЗИОННЫЙ ГЕЙТ не CLEAN:
$(printf '%s' "$out" | grep -E '^\[FAIL\]' | head -6)

  Подробности:  python3 scripts/revision_check.py --root ."
  fi
fi

# --- 3. VERSION поднята, а архива для неё нет --------------------------------
# Правило владельца (память): каждый VERSION bump = zip в ~/Downloads.
version="$(tr -d ' \t\r\n' < VERSION 2>/dev/null)"
if [ -n "$version" ] && [ ! -f "$HOME/Downloads/base-repo-v${version}.zip" ]; then
  # Архив мог быть уже опубликован и удалён деплойером — тогда есть тег на GitHub.
  #
  # 🔴 Сетевой вызов внутри хука обязан иметь таймаут. Без него недоступная сеть
  # вешает `git ls-remote` до таймаута самого хука, хук убивается — и блок НЕ
  # выставляется. То есть гейт проходится фактом отсутствия интернета, молча.
  # Класс тот же, что в `personal-finance-dss/.claude/hooks/tests-gate.sh`:
  # тяжёлая проверка в хуке деградирует в fail-open (`71` §7в).
  # `timeout(1)` не используем — его нет на голом macOS; таймаут даёт python3.
  tag_found=$(python3 - "$version" <<'PY' 2>/dev/null
import subprocess, sys
ver = sys.argv[1]
try:
    r = subprocess.run(
        ["git", "ls-remote", "--tags",
         "https://github.com/vevdokimovm/base-repo.git", f"v{ver}"],
        capture_output=True, text=True, timeout=8,
    )
    print("yes" if f"v{ver}" in r.stdout else "no")
except Exception:
    print("unknown")   # сеть недоступна/висит — подтвердить тег НЕЛЬЗЯ
PY
)
  # "unknown" трактуется как "нет": отказ в пользу более дорогой ошибки —
  # лишний блок дешевле, чем пропущенный незакрытый батч.
  if [ "$tag_found" != "yes" ]; then
    problems="${problems}
▸ VERSION=${version}, но архива ~/Downloads/base-repo-v${version}.zip нет
  и тега v${version} на GitHub тоже нет.

  Собрать:  python3 scripts/pack_release.py"
  fi
fi

[ -z "$problems" ] && exit 0

reason="Обвязка отстала от правки — класс PIT-G (4 повтора, reports/incidents/PITFALLS.md).
${problems}

Почему это блок, а не предупреждение: все четыре прошлых раза правило было
записано и известно. Пропускается не знание, а запуск проверки — поэтому
проверка запускается сама.

Починил — увеличь счётчик PIT-G и допиши случай строкой. Счётчик про историю,
он не сбрасывается."

printf '%s' "$reason" | python3 -c '
import json, sys
print(json.dumps({"decision": "block", "reason": sys.stdin.read()}, ensure_ascii=False))
'
exit 0
