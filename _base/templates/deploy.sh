#!/usr/bin/env bash
# =============================================================================
# deploy.sh v4.27.1 — ЕДИНЫЙ деплойер репозиториев. Один скрипт на всю систему.
#
# ┌───────────────────────────────────────────────────────────────────────────┐
# │ ЖЕЛЕЗНОЕ ПРАВИЛО: ВТОРОГО СКРИПТА НЕ ЗАВОДИТСЯ. НИКОГДА.                   │
# │                                                                           │
# │ Понадобилась новая возможность — она становится РЕЖИМОМ (env-флагом)       │
# │ внутри этого файла, и на неё пишется тест в tests/test_deploy.sh.          │
# │ Не «быстренько отдельный скриптик рядом» — именно сюда.                    │
# │                                                                           │
# │ Почему это правило существует: восемь скриптов-предшественников появились  │
# │ ровно так — каждый раз казалось, что проще написать новый, чем разобраться │
# │ в старом. Итог: у каждой репы свой вариант деплоя, релизы в разных         │
# │ форматах, никто не помнит, что запускать. Разгребали это неделю.           │
# │                                                                           │
# │ Рецидив был уже ПОСЛЕ консолидации: для починки старых релизов завели      │
# │ отдельный fix_releases.sh — и тут же получили два скрипта вместо одного.   │
# │ Слит обратно режимом. Если рука тянется создать файл рядом — читай         │
# │ templates/README.md, там разобрано, почему это тупик.                      │
# └───────────────────────────────────────────────────────────────────────────┘
#
# Заменяет собой все прежние вариации (publish.sh, deploy_all.sh, deploy_from_zip.sh,
# deploy_all_versions.sh, commit_to_main.sh, commit_all_versions.sh, push_archives.sh,
# push_base_repo.sh, fix_releases.sh). Каждая из них умела свой кусок; здесь собран
# объединённый рабочий процесс + починка того, что прежние версии делали не по стандарту.
# Разбор консолидации: reports/merges/scripts_consolidation_report.md
# ПЕРЕД ПРАВКОЙ ПОВЕДЕНИЯ: reports/incidents/PITFALLS.md — лидерборд повторяющихся
#   дефектов со счётчиками. Класс с 3+ повторами лечится проверкой, не заплаткой.
# Контракт (что гарантируется на выходе): templates/deploy-SPEC.md
# Все режимы и ключи: templates/deploy-MODES.md
#
# ЧТО ДЕЛАЕТ (полный цикл, идемпотентно):
#   находит все версионные архивы в папке -> группирует по репам -> сортирует по SemVer
#   -> создаёт репу, если её нет -> клонирует -> чисто заменяет дерево -> коммит -> тег
#   -> push -> GitHub Release с ЗАГОЛОВКОМ и ОПИСАНИЕМ по стандарту -> канонический ассет
#   -> чинит уже существующие релизы, сделанные не по стандарту -> обновляет repos-map.
#
# ЗАПУСК:
#   zsh deploy.sh                      # папка по умолчанию ~/Developer
#   zsh deploy.sh ~/Desktop/archives   # другая папка
#   DRY=1 zsh deploy.sh                # ПЛАН без единого изменения (запускай первым!)
#
# ПЕРЕКЛЮЧАТЕЛИ (env):
#   DRY=1          показать план и выйти. Ничего не меняет ни локально, ни на GitHub
#   ONLY="a b"     обработать только эти репы
#   MIRRORS_ONLY=1 обработать ВСЕ зеркала из MIRRORS одной командой.
#                  Массовый прогон зеркала пропускает намеренно (иначе туда уедет
#                  лишнее), и перечислять их руками каждый раз — прямой путь
#                  к тому, что однажды забудешь одно. Ключ раскрывается в ONLY
#                  со списком MIRRORS, дальше работает та же проверенная ветка.
#                  ONLY=1 сделать нельзя: ONLY — это СПИСОК ИМЁН, и "1" будет
#                  понято как репа с именем 1.
#   SKIP="a b"     не трогать эти репы вообще
#   LAST=N         в починке смотреть только N САМЫХ СВЕЖИХ тегов (по SemVer), а не все
#   REPAIR=1       ТОЛЬКО починка: пройтись по существующим тегам/релизам и привести
#                  к стандарту (заголовок, описание из CHANGELOG, недостающий ассет).
#                  Новые версии не публикуются. Осмысленные описания не перезаписываются
#   FORCE=1        разрешить перезапись ОСМЫСЛЕННЫХ описаний релизов (по умолчанию нет:
#                  тег и релиз заморожены, 21-revision-protocol)
#   ASSETS_ONLY=1  только дозалить недостающие канонические ассеты
#   BACKFILL=1     разрешить публикацию версий НИЖЕ старшего существующего тега
#   PRIVATE=0      создавать публичные репы (по умолчанию приватные)
#   ASSET=0        не прикладывать zip к релизу (боевой прогон так НЕ запускать: §4 стандарта)
#   OWNER=...      владелец (по умолчанию vevdokimovm)
#   BRANCH=...     ветка (по умолчанию main)
#   BASE_REPO=...  путь к клону base-repo для авто-обновления repos-map
#                  (по умолчанию ищется рядом: ./base-repo, ~/base-repo, ~/repos/base-repo)
#
# ИМЕНА АРХИВОВ (понимает все три конвенции):
#   <repo>-vX_Y_Z.zip · <repo>_vX.Y.Z.zip · <repo>-vX.Y.Z.zip
#   Версия сверяется с файлом VERSION в дереве: расхождение -> версия пропускается.
#
# ЗАЩИТЫ (вшитые уроки, не трогать):
#   PIT-004 чистка-кроме-.git (чистая замена != долив) · PIT-006 git add -A -f ·
#   PIT-007 разворот wrapper-обёртки · маркеры корня ДО деструктива · автопроверка
#   «файлов в коммите == файлов в дереве» · ретраи под РФ-TLS · CHANGELOG парсится
#   ПИТОНОМ в --notes-file (пайп рвёт UTF-8 кириллицу) · сбой на одной версии НЕ роняет
#   батч · на падении рабочая папка сохраняется.
# =============================================================================

set -u
# zsh по умолчанию считает несовпавший шаблон фатальной ошибкой и обрывает скрипт
# (bash оставляет шаблон строкой). Скрипт запускают в zsh, тесты идут в bash —
# различие того же класса, что BSD/GNU. Снимаем фатальность сразу на входе.
if [ -n "${ZSH_VERSION:-}" ]; then
  setopt no_nomatch 2>/dev/null || true
  setopt sh_word_split 2>/dev/null || true
fi
if [ -n "${ZSH_VERSION:-}" ]; then setopt shwordsplit 2>/dev/null || true; fi

SELF_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
# 🔴 03.09.2026 (v4.24.0): по умолчанию — `~/Developer`, не папка скрипта.
# Заказ владельца: артефакты системы отдельно от всего скачанного.
#
# Почему `SELF_DIR` убран из цепочки: он давал сюрприз. Запуск КАНОНА
# (`templates/deploy.sh`) искал архивы в `templates/` и честно отвечал
# «публиковать нечего» — при полной папке архивов рядом. Копия в `~/Downloads`
# работала лишь потому, что случайно лежала там же, где архивы.
# Умолчание, верное по совпадению, ломается при первом переносе файла.
#
# `BASE_ARTIFACTS` — та же переменная, что у скриптов Python (`_roots.py`):
# один способ переопределить путь, а не два расходящихся.
DIR="${1:-${BASE_ARTIFACTS:-$HOME/Developer}}"
OWNER="${OWNER:-vevdokimovm}"
BRANCH="${BRANCH:-main}"
RETRIES="${RETRIES:-5}"; RETRY_SLEEP="${RETRY_SLEEP:-4}"
REMOTE_BASE="${REMOTE_BASE:-https://github.com/$OWNER}"   # переопределяется только для локальных тестов
MIN_FILES="${MIN_FILES:-5}"
PRIVATE="${PRIVATE:-1}"
ASSET="${ASSET:-1}"
# 🔴 ПРОСЕДАНИЕ СЕТИ ≠ ОБРЫВ. Найдено владельцем 27.08.2026: на нестабильном канале
# (в т.ч. при переключении VPN на лету) скорость может упасть с ~10 МБ/с до долей
# кбит/с, но соединение при этом НЕ рвётся — git виснет на TCP-уровне и ждёт молча,
# иногда десятками минут, вообще не доходя до кода ошибки, который ловит retry().
# Единственный способ это увидеть — не ждать, а измерять: git/curl умеют сами
# оборвать передачу, если средняя скорость держится ниже порога дольше заданного
# времени (`http.lowSpeedLimit`/`http.lowSpeedTime`, скоуп -c — только на эту
# команду, глобальный git.config не трогаем). Обрыв — это уже код ошибки, и retry()
# подхватывает его штатно: ждёт, повторяет — и переключить VPN в это окно безопасно.
#
# 🔴 ПОРОГ БЫЛ ОШИБОЧНО КАЛИБРОВАН — найдено владельцем в тот же день, в первом же
# реальном прогоне на живой VPN-нестабильности (batch 27.08.2026, деплой волны из
# 40 реп). `1024` байт/с (1 КБ/с) — это порог «соединение почти мертво», а реальный
# симптом — «соединение живо, но еле ползёт»: лог показал устойчивые 46–150 КБ/с
# на протяжении минут, что технически ВЫШЕ старого порога и потому НИКОГДА не
# срабатывало. Владелец наблюдал зависшую строку прогресса и ждал вручную Ctrl+C —
# ровно то, что должен был предотвратить этот механизм. Новый порог — на порядок
# выше: 50 КБ/с всё ещё оставляет запас для нормального, но не блещущего канала, и
# ловит именно «мучительно медленно» — ту зону, где ждать бессмысленнее, чем
# оборвать и попробовать заново. Время реакции сокращено (30с → 15с) — меньше
# висеть перед тем, как механизм вообще успеет заметить проблему.
CLONE_LOW_SPEED_LIMIT="${CLONE_LOW_SPEED_LIMIT:-51200}"  # байт/с — ниже считаем зависанием
CLONE_LOW_SPEED_TIME="${CLONE_LOW_SPEED_TIME:-15}"        # столько секунд подряд ниже лимита → обрыв
SCRIPT_VERSION="4.27.1"
# Накопители по релизам. Объявлены здесь, а не в блоке 2Б: ветка REPAIR (шаг 2А)
# вызывает ensure_release раньше, и под `set -u` обращение к необъявленной ASSET_OK
# роняло весь прогон уже ПОСЛЕ создания релиза — работа сделана, а код возврата ошибка.
ASSET_OK=""
NOREL=""
MIRROR_SKIPPED=""
DRY="${DRY:-0}"
AUDIT="${AUDIT:-0}"          # 1 = полная ревизия ВСЕХ релизов (долго)
VERIFY="${VERIFY:-0}"        # 1 = только проверка «что можно удалять локально»
ALL_REPOS="${ALL_REPOS:-0}"  # 1 = взять ВСЕ репы из repos-map, а не только те, где есть архивы
# Дубль под старым именем — нарушение §42 (ассетов должно быть ровно 3), поэтому
# снимается при обычном приведении к стандарту. Это НЕ отдельный флаг: владелец не
# обязан помнить спецкоманду, чтобы получить релиз по стандарту.
# Архив, полностью уехавший на GitHub (тег + релиз + ассет), — это дубликат того,
# что уже лежит в репе. Держать его на диске незачем, поэтому удаление опубликованных
# архивов включено ПО УМОЛЧАНИЮ. Отключается KEEP_ARCHIVES=1.
KEEP_ARCHIVES="${KEEP_ARCHIVES:-0}"
DELETE_AFTER="${DELETE_AFTER:-1}"
[ "$KEEP_ARCHIVES" = "1" ] && DELETE_AFTER=0
CHLOG_FILL="${CHLOG_FILL:-0}"  # 1 = дописать секции и разряды в CHANGELOG по данным git
# Публичные зеркала не трогаются массовыми режимами: служебные файлы в витрине
# посторонним не нужны (08.08.2026 в публичную finpilot так уехала вся _base/).
# Назвал репу явно через ONLY — значит осознанно, тогда работаем.
# Витрина по mission-control::ADR-009: КАЖДОЕ зеркало вносится сюда в момент создания, а не после
# первого инцидента. 15.08.2026 три зеркала были заведены и открыты в public раньше,
# чем попали в этот список, — окно, в котором sync-base.sh залил бы в них _base/.
# 🔴 Список ПУБЛИЧНЫХ реп: массовые режимы их пропускают, база в них не раздаётся.
# Обновлён 21.08.2026 — четыре репы были опубликованы в тот же день и в список
# не попали: algorithms-site, game-analytics-engine, claude-usage, salvation.
# Это ровно PIT-097 («список — намерение, свойство объекта — факт»): держать список
# в синхроне с GitHub руками невозможно, поэтому ниже стоит предохранитель по факту.
# 🔴 СВЕРЯЕТСЯ ИНСТРУМЕНТОМ, А НЕ ГЛАЗАМИ (с 04.09.2026):
#     python3 scripts/visibility_check.py
# Он спрашивает GitHub и сравнивает с этим списком и с `repos-map.md`.
# Первый же прогон нашёл ДВЕ публичные репы вне списка — `vevdokimovm`
# и `vevdokimovm.github.io`, профиль и сайт. Массовый режим считал бы их
# обычными и залил бы туда `_base/`; ровно это случилось 08.08.2026
# с публичной `finpilot`.
#
# Сверить список с реальностью вручную:
#   gh repo list vevdokimovm --limit 200 --json name,visibility \
#     --jq '.[]|select(.visibility=="PUBLIC")|.name'
# ── deploy-repos.conf — список зеркал БЕЗ выпуска новой версии скрипта ───────
# Заказ: `ROADMAP` §P2, «списки в теле deploy.sh». Исходная формулировка
# («перенести списки в данные») отвергнута: файл данных сломал бы главное
# свойство деплойера — самодостаточность. Он лежит в ПЯТИ местах, владелец
# запускает копию из `~/Developer`, и внешний конфиг туда бы не поехал —
# копия молча осталась бы без зеркал, то есть начала считать зеркало
# обычной репой и залила бы в витрину `_base/`.
#
# 🔴 Поэтому конфиг НЕОБЯЗАТЕЛЕН и лежит РЯДОМ со скриптом. Нет файла —
# работает ровно как раньше, на встроенном умолчании. Порядок старшинства:
#
#     переменная окружения  >  deploy-repos.conf  >  встроенное умолчание
#
# Окружение старше конфига намеренно: разовый прогон `MIRRORS="a b" ./deploy.sh`
# обязан перебивать постоянную настройку, а не наоборот.
#
# Формат — по одному `КЛЮЧ=значение` в строке, `#` в начале строки — комментарий.
# Единственный ключ сейчас — `MIRRORS`. Файл НЕ исполняется: он разбирается
# построчно, поэтому положить в него команду нельзя.
CONF_MIRRORS=""
DEPLOY_CONF="${DEPLOY_CONF:-$SELF_DIR/deploy-repos.conf}"
if [ -f "$DEPLOY_CONF" ]; then
  while IFS= read -r _cline || [ -n "$_cline" ]; do
    case "$_cline" in ''|'#'*) continue ;; esac
    case "$_cline" in *=*) : ;; *) continue ;; esac
    _ckey="${_cline%%=*}"
    _cval="${_cline#*=}"
    _ckey="$(printf '%s' "$_ckey" | tr -d ' \t')"
    _cval="$(printf '%s' "$_cval" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
                                        -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/")"
    case "$_ckey" in
      MIRRORS) CONF_MIRRORS="$_cval" ;;
      *) echo "⚠ ${DEPLOY_CONF}: неизвестный ключ «${_ckey}» — пропущен" >&2 ;;
    esac
  done < "$DEPLOY_CONF"
  [ -n "$CONF_MIRRORS" ] && echo "· зеркала взяты из $DEPLOY_CONF"
fi
MIRRORS="${MIRRORS:-${CONF_MIRRORS:-finpilot finpilot-mirror finpilot-public-mirror vk-graph health-report-generator bron-kerbosch algorithms-site game-analytics-engine claude-usage salvation vevdokimovm vevdokimovm.github.io}}"
MIRRORS_ONLY="${MIRRORS_ONLY:-0}"
if [ "$MIRRORS_ONLY" = "1" ]; then
  if [ -n "${ONLY:-}" ]; then
    echo "MIRRORS_ONLY=1 и ONLY заданы вместе — выбери одно" >&2; exit 2
  fi
  ONLY="$MIRRORS"
  export ONLY
fi
MIN_FREE_MB="${MIN_FREE_MB:-2048}"  # ниже этого порога свободного места прогон не начинается
KEEP_LEGACY_ASSETS="${KEEP_LEGACY_ASSETS:-0}"   # 1 = НЕ снимать дубли (страховка)
DROP_LEGACY_ASSETS="${DROP_LEGACY_ASSETS:-1}"   # оставлен для совместимости
GH_TIMEOUT="${GH_TIMEOUT:-120}"   # секунд на один вызов gh — чтобы не висеть
# 🔴 Найдено владельцем 27.08.2026: заливка ассета (`gh release create/upload`)
# раньше делила общий GH_TIMEOUT=120с с лёгкими API-вызовами (list/view/edit).
# 140 МБ на медленной VPN (40-60 КБ/с) не успевают залиться и на 10% за 120с —
# гарантированный таймаут, 3 молчаливые попытки (gh_try буферизует весь вывод
# через `$(...)`, поэтому во время загрузки не видно НИЧЕГО), затем явный отказ:
# релиз создаётся БЕЗ канонического ассета. Отдельный, больший таймаут именно
# для заливки — лёгкие вызовы (создание релиза без файла, список, правка) им не
# затронуты.
GH_UPLOAD_TIMEOUT="${GH_UPLOAD_TIMEOUT:-1800}"  # 30 минут — специально для заливки ассета
REPAIR="${REPAIR:-0}"
# 🔴 СКОЛЬКО ПОСЛЕДНИХ ВЕРСИЙ СМОТРЕТЬ В ПОЧИНКЕ. Заказ владельца 04.09.2026,
# дословно: «он проходит ВСЕ релизы вообще, а их уже очень много и реп много.
# Сделай функцию, чтобы он смотрел последние 5, или 10, или 2 — чтобы можно
# было назначить, и смотрел не с начала, а последние».
#
# Пустая строка = без ограничения, прежнее поведение. Число N = взять N САМЫХ
# СВЕЖИХ тегов по SemVer и чинить только их, от старшего к младшему.
#
# 🔴 Отбор идёт ПО ВЕРСИИ, а не по порядку `git tag -l`: тот сортирует
# лексикографически, и v2.10.0 у него младше v2.9.0. «Последние пять»
# по такому порядку — это пять случайных.
LAST="${LAST:-}"
# 🔴 `${LAST}` В СКОБКАХ ОБЯЗАТЕЛЬНО — см. кейс `I5` в тестах: переменная
# вплотную к «» под `set -u` убивает прогон в самой диагностической строке.
case "$LAST" in ''|*[!0-9]*) [ -n "$LAST" ] && { echo "LAST должен быть числом, получено «${LAST}»" >&2; exit 2; } ;; esac
[ "${LAST:-0}" = "0" ] && [ -n "$LAST" ] && { echo "LAST=0 не имеет смысла — это «не чинить ничего»" >&2; exit 2; }
FORCE="${FORCE:-0}"
ASSETS_ONLY="${ASSETS_ONLY:-0}"
BACKFILL="${BACKFILL:-0}"
# служебные архивы (загрузки из чата, системные) — молча мимо, репу для них не заводим
SERVICE_RE="${SERVICE_RE:-^([0-9]+|files([ _-][0-9]+)?|[Aa]rchive([ _-][0-9]+)?|Downloads?)$}"
# репы, у которых бывает вариантный постфикс в имени архива (finpilot_v6_20_1_intl)
VARIANT_REPOS="${VARIANT_REPOS:-finpilot}"
# имя архива != имя репы. Историческое: архивы finpilot_* принадлежат personal-finance-dss
# (finpilot — публичное зеркало). Формат: "имя-в-архиве=имя-репы имя2=репа2"
# finpilot-public-mirror=finpilot (2026-08-13, personal-finance-dss v8.19.3): владелец
# ЯВНО решил — репозиторий на GitHub остаётся называться просто `finpilot` (переименование
# туда-обратно проверено в этой же сессии), а АРХИВ санитизированного публичного среза
# называется finpilot-public-mirror-vX.Y.Z.zip — так понятнее у него на диске, не
# finpilot-vX.Y.Z.zip (то имя занято старой историей выше и уже участвует в сравнении с
# .repo-id). Санитайзер (tools/publish/finpilot_publish_public.sh) не пишет .repo-id в
# собранное дерево, так что здесь ИМЕННО карта — единственный способ довести архив до
# реальной репы finpilot, а не дать деплойеру завести пустую репу-сироту
# finpilot-public-mirror. finpilot-mirror=finpilot — более старое имя архива из той же
# сессии, оставлено для совместимости с уже лежащим в Downloads finpilot-mirror-v8.19.2.zip.
# Оба алиаса уже в MIRRORS ниже (защита от массовых режимов) — без строк карты они туда
# не доезжали вообще, только пропускались.
REPO_MAP="${REPO_MAP:-finpilot=personal-finance-dss finpilot-mirror=finpilot finpilot-public-mirror=finpilot}"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  # ТОЛЬКО ЯРКИЕ ЦВЕТА (91-97). Фон у владельца чёрный, поэтому запрещены:
  #   30m  — чёрный,           90m — «яркий чёрный» (серый),
  #   2m   — тусклый,          31-37m — тусклые варианты палитры,
  #   голая жирность 1m и печать без кода — это цвет терминала по умолчанию,
  #   он в тёмной теме тоже тёмный. Каждая строка обязана нести свой яркий код.
  C_RED=$'\033[91m'; C_GRN=$'\033[92m'; C_YLW=$'\033[93m'; C_CYN=$'\033[96m'
  C_MAG=$'\033[95m'; C_BLD=$'\033[1;97m'; C_TXT=$'\033[97m'; C_OFF=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YLW=""; C_CYN=""; C_MAG=""; C_BLD=""; C_TXT=""; C_OFF=""
fi
red(){ printf '%s%s%s\n' "$C_RED" "$*" "$C_OFF"; }
grn(){ printf '%s%s%s\n' "$C_GRN" "$*" "$C_OFF"; }
ylw(){ printf '%s%s%s\n' "$C_YLW" "$*" "$C_OFF"; }
cyn(){ printf '%s%s%s\n' "$C_CYN" "$*" "$C_OFF"; }
plain(){ printf '%s%s%s\n' "$C_TXT" "$*" "$C_OFF"; }   # ярко-белый, не цвет терминала
mag(){ printf '%s%s%s\n' "$C_MAG" "$*" "$C_OFF"; }
bld(){ printf '%s%s%s\n' "$C_BLD" "$*" "$C_OFF"; }
# fail loud: то, что скрипт чинить НЕ станет — человек решает сам
LOUD=""
# PIT-016: печать шла в stdout. Любая функция, вызвавшая loud внутри `$( )`,
# отдавала наверх не результат, а раскрашенную строку «ТРЕБУЕТ РЕШЕНИЯ:».
# Так родился заголовок релиза finpilot, начинающийся с \033[1;97m\033[95m.
# Диагностика всегда идёт в stderr — stdout принадлежит результату функции.
loud(){ LOUD="$LOUD
  $1"; printf '%s%s  ТРЕБУЕТ РЕШЕНИЯ: %s%s\n' "$C_BLD" "$C_MAG" "$1" "$C_OFF" >&2; }

# v4.17.1: сводка карты снимается, когда шаг 3 её же и починил.
# Сверка repos-map идёт ДО регистрации новых реп, поэтому её вердикт к моменту
# печати финального блока устаревает. Боевой прогон 21.08.2026 напечатал подряд:
#   "algorithms-site — repos-map добавлена (требует описания)"
#   "ТРЕБУЕТ ТВОЕГО РЕШЕНИЯ: repos-map: нет в карте вовсе — algorithms-site ..."
# Две строки, вторая опровергает первую. Владелец справедливо спросил, не сломан ли
# скрипт: публикация-то отработала верно. Молчаливое противоречие в итоговом блоке
# хуже отсутствия блока — читающий перестаёт доверять ВСЕМУ списку, включая
# настоящие пункты. Здесь имена, зарегистрированные шагом 3, вычёркиваются
# из строки MISSING; если вычеркнулись все — строка уходит целиком.
map_resolve(){
  [ -n "$LOUD" ] && [ -n "${1:-}" ] || return 0
  _new="$(LOUD_IN="$LOUD" RESOLVED="$1" python3 - <<'PYRES'
import os, re
loud = os.environ.get("LOUD_IN", "")
done = set(os.environ.get("RESOLVED", "").split())
out = []
for line in loud.split("\n"):
    if "нет в карте вовсе" in line and done:
        m = re.search(r"—\s*([^.]*?)\.", line)
        if m:
            names = [n for n in m.group(1).split() if n not in done]
            if not names:
                continue
            line = line[:m.start(1)] + " ".join(names) + line[m.end(1):]
    out.append(line)
print("\n".join(out))
PYRES
)" || return 0
  LOUD="$_new"
}

# PIT-016 (вторая половина): заголовок релиза не может содержать управляющих
# символов, чем бы ни закончилась его сборка. Санитайзер — последний рубеж,
# он ловит и будущие протечки, а не только известную.
safe_title(){
  _t="$(printf '%s' "$1" | LC_ALL=C sed $'s/\033\\[[0-9;]*[A-Za-z]//g' | tr -d '\001-\037\177')"
  _t="${_t#"${_t%%[![:space:]]*}"}"; _t="${_t%"${_t##*[![:space:]]}"}"
  case "$_t" in ''|*"ТРЕБУЕТ РЕШЕНИЯ"*) printf '%s v%s' "$2" "$3" ;; *) printf '%s' "$_t" ;; esac
}
die(){ red "ОШИБКА: $*"; [ -n "${WORK:-}" ] && [ -d "${WORK:-}" ] && red "Рабочая папка сохранена: $WORK"; exit 1; }

# 🔴 ДЕТЕРМИНИРОВАННЫЙ ОТКАЗ НЕ РЕТРАИТСЯ. Найдено владельцем 22.08.2026.
# `git push` в edu-base отклонялся `pre-receive` хуком: файл 207.75 МБ при жёстком
# лимите GitHub 100 МБ. Ретрай счёл это сетевым сбоем и повторил ПЯТЬ раз, каждый раз
# заливая 549 МБ по ~1.5 МБ/с — около получаса впустую. Отказ был окончательным:
# он не прошёл бы никогда, сколько ни жди.
#
# Ретрай осмыслен только для ВРЕМЕННОГО отказа (сеть, таймаут, 5xx). Отказ по
# содержанию — лимит размера, отклонение хуком, отсутствие прав — повторять нельзя:
# ожидание ничего не меняет, а стоит времени и трафика.
FATAL_PATTERNS='GH001|exceeds GitHub.s file size limit|pre-receive hook declined|Large files detected|remote rejected|Permission denied|403 Forbidden|authentication failed|repository not found'

retry(){ d="$1"; shift; a=1; s="$RETRY_SLEEP"
  while [ "$a" -le "$RETRIES" ]; do
    _out="$("$@" 2>&1)"; _rc=$?
    printf '%s\n' "$_out"
    [ "$_rc" -eq 0 ] && return 0
    if printf '%s' "$_out" | grep -qE "$FATAL_PATTERNS"; then
      red "  ✗ $d — отказ ОКОНЧАТЕЛЬНЫЙ, ретрай не поможет:"
      printf '%s' "$_out" | grep -oE "$FATAL_PATTERNS" | sort -u | sed 's/^/      /'
      red "  Причина в содержании, а не в сети. Чинить, а не ждать."
      red "  Файлы >100 МБ: python3 base-repo/07-media-to-text-lab/tools/heavy_media_to_note.py --all"
      return 1
    fi
    ylw "  попытка $a/$RETRIES ($d) не удалась — жду ${s}s (обычно TLS-таймаут к GitHub)"
    ylw "  сейчас безопасно переключить VPN: следующая попытка откроет соединение заново"
    sleep "$s"; a=$((a+1)); s=$((s*2)); done; return 1; }

# сводка прогона: строки «репа|версия|действие|статус»
SUMMARY=""
note(){ SUMMARY="$SUMMARY
$1"; }

# --- ШАГ 0. Preflight -----------------------------------------------------------
command -v git >/dev/null 2>&1 || die "git не найден"
command -v python3 >/dev/null 2>&1 || die "python3 не найден (нужен для разбора CHANGELOG)"
HAVE_GH=0; command -v gh >/dev/null 2>&1 && HAVE_GH=1
[ "$HAVE_GH" -eq 1 ] || ylw "⚠ gh не найден: пуш и теги пройдут, релизы придётся создать вручную"
[ -d "$DIR" ] || die "папка не найдена: $DIR"
[ "$ASSET" = "0" ] && ylw "⚠ ASSET=0 — релизы будут без канонического zip (нарушение §4 стандарта)"

# --- восстановление пропущенных секций CHANGELOG (режим CHLOG_FILL) --------------
# Отдельного скрипта не заводим (§иронное правило файла): это РЕЖИМ внутри deploy.sh.
CHFILL="$(mktemp -d)/chlog_fill.py"
cat > "$CHFILL" <<'FILLEOF'
#!/usr/bin/env python3
"""Restores missing CHANGELOG sections for tags that never got one.

Reads everything from git — tag date, commit subject, diff stat — and invents
nothing. Called by deploy.sh in CHLOG_FILL mode.

    chlog_fill.py <clone-dir> <repo-name>

Prints the versions it added, one per line. Exit 1 when nothing was missing.
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import date
from pathlib import Path

HEAD_RE = re.compile(r"^##\s+\[?v?(\d+)\.(\d+)\.(\d+)\]?")
BUMP_TAIL = re.compile(r"\((MAJOR|MINOR|PATCH)\)\s*$")
BUMP_HEAD = re.compile(r"(MAJOR|MINOR|PATCH)\s*[:\u2014\u2013-]")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
DASHES = "\u2014\u2013-"


def git(clone: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(clone), *args], capture_output=True, text=True, encoding="utf-8"
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def parse(version: str) -> tuple[int, int, int]:
    parts = (version.split(".") + ["0", "0"])[:3]
    return tuple(int(re.sub(r"\D", "", p) or 0) for p in parts)


def bump_of(current: str, previous: str | None) -> str:
    if previous is None:
        return "MAJOR"
    cur, prev = parse(current), parse(previous)
    if cur[0] != prev[0]:
        return "MAJOR"
    return "MINOR" if cur[1] != prev[1] else "PATCH"


def thesis_of(subject: str, repo: str, version: str) -> str:
    text = re.sub(rf"^{re.escape(repo)}\s+v?{re.escape(version)}\s*", "", subject or "")
    text = text.lstrip(DASHES + " ").strip()
    return text or "восстановлено по журналу git"


def touched_dirs(clone: Path, previous: str | None, version: str) -> str:
    if previous is None:
        names = git(clone, "show", "--pretty=", "--name-only", f"v{version}")
    else:
        names = git(clone, "diff", "--name-only", f"v{previous}", f"v{version}")
    dirs = []
    for line in names.splitlines():
        line = line.strip()
        if not line:
            continue
        dirs.append(line.rsplit("/", 1)[0] + "/" if "/" in line else "(корень)")
    ordered = sorted(set(dirs))
    shown = ", ".join(ordered[:6])
    return shown + (f" и ещё {len(ordered) - 6}" if len(ordered) > 6 else "")


def stat_of(clone: Path, previous: str | None, version: str) -> str:
    if previous is None:
        raw = git(clone, "show", "--shortstat", "--pretty=", f"v{version}")
    else:
        raw = git(clone, "diff", "--shortstat", f"v{previous}", f"v{version}")
    raw = raw.strip().splitlines()
    return raw[-1].strip() if raw else "объём изменений не определён"


def build_section(clone: Path, repo: str, version: str, previous: str | None) -> str:
    when = git(clone, "log", "-1", "--format=%ad", "--date=short", f"v{version}") or str(date.today())
    subject = git(clone, "log", "-1", "--format=%s", f"v{version}")
    lines = [
        f"## [{version}] — {when} — {thesis_of(subject, repo, version)} ({bump_of(version, previous)})",
        "",
        "Секция восстановлена по данным git: релиз выпускался без записи в журнале,",
        "а архив к этому моменту уже удалён. Ниже только то, что читается из репозитория.",
        "",
        f"- {stat_of(clone, previous, version)}",
    ]
    dirs = touched_dirs(clone, previous, version)
    if dirs:
        lines.append(f"- затронуты: {dirs}")
    lines.append("")
    return "\n".join(lines)


def normalize(clone: Path, repo: str, lines: list[str], tags: list[str]) -> tuple[list[str], list[str]]:
    """Дописывает разряд в заголовки, где его нет. Разряд считается по номерам версий,
    поэтому ничего не выдумывается — он и так однозначно следует из SemVer.

    Предшественник берётся из списка ТЕГОВ, а не из порядка в журнале: журнал может
    пропускать версии, и тогда сосед по файлу — не тот, с кем надо сравнивать.
    """
    before = {v: (tags[i - 1] if i else None) for i, v in enumerate(tags)}

    fixed: list[str] = []
    changed: list[str] = []
    for line in lines:
        match = HEAD_RE.match(line)
        if not match:
            fixed.append(line)
            continue
        version = ".".join(match.groups())
        if BUMP_TAIL.search(line) or BUMP_HEAD.search(line):
            fixed.append(line)
            continue
        earlier = before.get(version)
        head = line.rstrip()
        tail = re.sub(r"^##\s+\[?v?" + re.escape(version) + r"\]?\s*", "", head)
        tail = tail.lstrip(DASHES + " ").strip()
        when = DATE_RE.search(tail)
        rest = DATE_RE.sub("", tail, count=1).lstrip(DASHES + " ").strip() if when else tail
        if not rest:
            rest = thesis_of(git(clone, "log", "-1", "--format=%s", f"v{version}"), repo, version)
        parts = [f"## [{version}]"]
        if when:
            parts.append(when.group(0))
        parts.append(f"{rest} ({bump_of(version, earlier)})")
        fixed.append(" — ".join(parts))
        changed.append(version)
    return fixed, changed


def main() -> int:
    clone, repo = Path(sys.argv[1]), sys.argv[2]
    changelog = clone / "CHANGELOG.md"
    if not changelog.exists():
        changelog.write_text(
            f"# CHANGELOG — {repo}\n\nФормат: Keep a Changelog · версии по SemVer.\n",
            encoding="utf-8",
        )

    tags = sorted(
        (t[1:] for t in git(clone, "tag", "-l", "v*").splitlines() if t.strip()),
        key=parse,
    )
    if not tags:
        return 1

    text = changelog.read_text(encoding="utf-8")
    lines, normalized = normalize(clone, repo, text.splitlines(), tags)
    if normalized:
        text = "\n".join(lines) + "\n"
        changelog.write_text(text, encoding="utf-8")
        print("норм:" + ",".join(normalized), file=sys.stderr)
    have = {".".join(m.groups()) for m in (HEAD_RE.match(ln) for ln in text.splitlines()) if m}

    sections: list[tuple[str, str]] = []
    previous: str | None = None
    for version in tags:
        if version not in have:
            sections.append((version, build_section(clone, repo, version, previous)))
        previous = version

    if not sections:
        return 0 if normalized else 1

    # Пересобираем журнал: преамбула, затем ВСЕ секции по убыванию версии.
    # Простая вставка новых секций перед первой существующей ставила версию
    # из середины истории наверх — порядок обязан считаться по номерам, не по месту.
    lines = text.splitlines()
    heads = [i for i, ln in enumerate(lines) if HEAD_RE.match(ln)]
    preamble = "\n".join(lines[: heads[0]]).rstrip() if heads else text.rstrip()

    blocks: list[tuple[str, str]] = []
    for pos, start in enumerate(heads):
        end = heads[pos + 1] if pos + 1 < len(heads) else len(lines)
        version = ".".join(HEAD_RE.match(lines[start]).groups())
        blocks.append((version, "\n".join(lines[start:end]).rstrip()))
    blocks.extend((version, body.rstrip()) for version, body in sections)
    blocks.sort(key=lambda b: parse(b[0]), reverse=True)

    merged = preamble + "\n\n" + "\n\n".join(body for _, body in blocks) + "\n"
    changelog.write_text(merged, encoding="utf-8")

    print("\n".join(version for version, _ in sections))
    return 0


if __name__ == "__main__":
    sys.exit(main())
FILLEOF

# --- парсер CHANGELOG (питон: UTF-8, кириллица, тире) ---------------------------
PARSER="$(mktemp -d)/chlog.py"
cat > "$PARSER" <<'PYEOF'
"""Достаёт из CHANGELOG секцию версии: тело релиза + тезис для заголовка.

Понимает диалекты заголовков:
    ## [1.2.3] — 2026-07-22 — Тезис (MINOR)
    ## v1.2.3 — 2026-07-22 — Тезис
    ## [1.2.3] - 2026-07-22
Печатает тезис в stdout, тело пишет в файл. Пустой stdout = тезиса нет.
"""

import re
import sys
from pathlib import Path

changelog, version, out_path = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
vre = re.escape(version)
head_re = re.compile(r"^##\s+\[?v?" + vre + r"\]?(?![0-9])")
any_head_re = re.compile(r"^##\s+\[?v?\d+\.\d+\.\d+")

lines, body, started = changelog.read_text(encoding="utf-8").splitlines(), [], False
heading = ""
for line in lines:
    if not started and head_re.match(line):
        started, heading = True, line
        continue
    if started and any_head_re.match(line):
        break
    if started:
        body.append(line)

if not started:
    sys.exit(3)

tail = re.sub(r"^##\s+", "", heading)
tail = re.sub(r"^\[?v?\d+\.\d+\.\d+\]?\s*", "", tail)
tail = re.sub(r"^[—\-–]\s*", "", tail)
tail = re.sub(r"^\d{4}-\d{2}-\d{2}\s*", "", tail)
tail = re.sub(r"^[—\-–]\s*", "", tail)
# Канон §2 — разряд в скобках в конце: «— тезис (MINOR)».
# Но генератор скелетов с самого начала писал «— MINOR: тезис», и в этом диалекте
# сейчас живут журналы почти всех реп. Раз файлов больше, чем правил, парсер обязан
# понимать оба и приводить к канону сам, а не сыпать предупреждением на каждой версии.
bump = re.search(r"\((MAJOR|MINOR|PATCH)\)\s*$", tail)
if bump:
    thesis = re.sub(r"\s*\((MAJOR|MINOR|PATCH)\)\s*$", "", tail).strip()
else:
    bump = re.match(r"^(MAJOR|MINOR|PATCH)\s*[:\u2014\u2013-]\s*", tail)
    thesis = tail[bump.end():].strip() if bump else tail.strip()

text = "\n".join(body).strip("\n")
while text.startswith("---"):
    text = text.split("\n", 1)[1].lstrip("\n") if "\n" in text else ""
# Нормализуем шапку секции к канону §42: «## [X.Y.Z] — ДАТА — тезис (BUMP)».
# Часть реп исторически пишет «## vX.Y.Z — ...» без скобок — тело релиза из-за
# этого выглядело иначе, чем у остальных. Содержимое секции не трогаем.
_d = re.search(r"\d{4}-\d{2}-\d{2}", heading)
_h = "## [" + version + "]"
if _d:
    _h += " — " + _d.group(0)
if thesis:
    _h += " — " + thesis
if bump:
    _h += " (" + bump.group(1) + ")"
out_path.write_text((_h + "\n\n" + text).strip() + "\n", encoding="utf-8")

print(thesis)
if not bump:
    print("NOBUMP", file=sys.stderr)
if not thesis:
    print("NOTHESIS", file=sys.stderr)
PYEOF

# =============================================================================
# ФУНКЦИИ. Объявлены ДО всех шагов: режимы вроде VERIFY выходят из скрипта
# раньше, чем дошли бы до определений ниже по файлу — и падали с
# «command not found». Все функции живут здесь и только здесь.
# =============================================================================
# --- gh с таймаутом и ретраями --------------------------------------------------
# Раньше вызовы шли голыми: одна просадка сети — и версия помечалась провальной,
# а на зависшем соединении прогон мог стоять десятками минут.
gh_try(){
  _n=0
  while :; do
    if command -v timeout >/dev/null 2>&1; then
      _o="$(timeout "$GH_TIMEOUT" gh "$@" 2>&1)"; _rc=$?
    else
      _o="$(gh "$@" 2>&1)"; _rc=$?
    fi
    [ "$_rc" -eq 0 ] && { printf '%s' "$_o"; return 0; }
    # Ретраим ТОЛЬКО похожее на сбой связи. «Не найдено» и отказы прав —
    # это ответ сервера, повтор их не изменит и только тормозит прогон.
    case "$_rc:$_o" in
      124:*|*timeout*|*"connection reset"*|*"could not resolve"*|*"TLS handshake"*|\
      *"i/o timeout"*|*"EOF"*|*"502"*|*"503"*|*"504"*|*"rate limit"*|*"try again"*) : ;;
      *) printf '%s' "$_o"; return "$_rc" ;;
    esac
    _n=$((_n+1))
    [ "$_n" -ge 3 ] && { printf '%s' "$_o"; return "$_rc"; }
    sleep $((_n * 5))
  done
}

# gh_try_upload <таймаут-с> <gh-подкоманда...> — как gh_try, но для заливки
# ассета: больший таймаут (GH_UPLOAD_TIMEOUT, не GH_TIMEOUT) и живой heartbeat,
# пока идёт заливка. 🔴 Найдено владельцем 27.08.2026: `gh` печатает процент
# заливки, только когда stderr — реальный терминал; в перенаправленный поток
# (как здесь, ради ретраев) он не пишет НИЧЕГО до самого конца — отсюда полная
# тишина на несколько минут, неотличимая от зависания. Побайтовый процент так
# не получить (gh не отдаёт его наружу через файл), но живой отсчёт времени —
# доказательство, что процесс не завис, а работает.
gh_try_upload(){
  _ut="$1"; shift
  _n=0
  while :; do
    _ulog="$(mktemp)"
    if command -v timeout >/dev/null 2>&1; then
      timeout "$_ut" gh "$@" >"$_ulog" 2>&1 &
    else
      gh "$@" >"$_ulog" 2>&1 &
    fi
    _up_pid=$!
    ACTIVE_CHILD_PID="$_up_pid"
    _up_t0=$(date +%s)
    while kill -0 "$_up_pid" 2>/dev/null; do
      _up_el=$(( $(date +%s) - _up_t0 ))
      printf '\r    заливаю... %sс (может занять долго на медленном канале)' "$_up_el" >&2
      sleep 2
    done
    _rc=0; wait "$_up_pid" || _rc=$?
    ACTIVE_CHILD_PID=""
    printf '\r%-70s\r' " " >&2
    _o="$(cat "$_ulog")"; rm -f "$_ulog"
    [ "$_rc" -eq 0 ] && { printf '%s' "$_o"; return 0; }
    case "$_rc:$_o" in
      124:*|*timeout*|*"connection reset"*|*"could not resolve"*|*"TLS handshake"*|\
      *"i/o timeout"*|*"EOF"*|*"502"*|*"503"*|*"504"*|*"rate limit"*|*"try again"*)
        ylw "    заливка не удалась — похоже на сетевой сбой, повторяю" ;;
      *) printf '%s' "$_o"; return "$_rc" ;;
    esac
    _n=$((_n+1))
    [ "$_n" -ge 3 ] && { printf '%s' "$_o"; return "$_rc"; }
    sleep $((_n * 5))
  done
}

# Существует ли релиз. Отличает «нет релиза» (rc=1, ответ получен) от
# «запрос не прошёл» (сеть/таймаут) — во втором случае возвращает 2 и версия
# не считается отсутствующей. Раньше оба случая выглядели одинаково, и скрипт
# пытался создать уже существующий релиз.
# Возвращает: 0 — релиз есть · 1 — релиза нет · 2 — ответить невозможно (сеть/API).
# Текст ошибки кладётся в RELEASE_STATE_ERR, чтобы вызывающий МОГ ЕГО ПОКАЗАТЬ.
# Раньше он молча терялся, и на экран уходила зашитая фраза «GitHub недоступен» —
# то есть догадка вместо факта. Причин у кода 2 минимум шесть (502/503/504, таймаут,
# сброс соединения, DNS), лечатся они по-разному: 71-fail-loud-and-sourcing.md §7г.
RELEASE_STATE_ERR=""
release_state(){
  RELEASE_STATE_ERR=""
  _out="$(gh_try release view "v$2" --repo "$OWNER/$1" --json name 2>&1)"; _rc=$?
  [ "$_rc" -eq 0 ] && return 0
  case "$_out" in
    *timeout*|*"connection reset"*|*"could not resolve"*|*"TLS handshake"*|\
    *"i/o timeout"*|*"502"*|*"503"*|*"504"*|*"429"*|*"rate limit"*|*"secondary rate"*)
      RELEASE_STATE_ERR="$(printf '%s' "$_out" | tr '\n' ' ' | cut -c1-200)"
      return 2 ;;
  esac
  return 1
}

# Уборка рабочей папки. Объявлена здесь, как и все функции: ссылки на $WORK
# разрешаются в момент вызова, а не объявления, поэтому порядок безопасен.
#
# 🔴 Найдено владельцем 27.08.2026: Ctrl+C на фоновом `git clone &` (см.
# ACTIVE_CHILD_PID ниже) не делал ВООБЩЕ НИЧЕГО — не гонка, а поведение по
# умолчанию: неинтерактивный shell (job control выключен) ставит асинхронным
# командам `cmd &` игнорирование SIGINT намеренно, чтобы Ctrl+C переднего плана
# случайно не убивал фоновые задачи. Владелец жал Ctrl+C раз за разом без всякой
# реакции и был вынужден закрывать всё окно терминала (SIGHUP при закрытии — то,
# что фоновый процесс уже не игнорирует). Раз сигнал сам не долетает — трап обязан
# убить ребёнка ЯВНО: сначала мягко (TERM), с коротким ожиданием, и добить (KILL),
# если завис на блокирующем сетевом вызове и не отреагировал вовремя.
cleanup_work(){
  _rc=$?
  if [ -n "${ACTIVE_CHILD_PID:-}" ] && kill -0 "$ACTIVE_CHILD_PID" 2>/dev/null; then
    kill -TERM "$ACTIVE_CHILD_PID" 2>/dev/null
    _wait_n=0
    while [ "$_wait_n" -lt 3 ] && kill -0 "$ACTIVE_CHILD_PID" 2>/dev/null; do
      sleep 1; _wait_n=$((_wait_n+1))
    done
    kill -0 "$ACTIVE_CHILD_PID" 2>/dev/null && kill -KILL "$ACTIVE_CHILD_PID" 2>/dev/null
    wait "$ACTIVE_CHILD_PID" 2>/dev/null
  fi
  if [ "${KEEP_WORK:-0}" = "1" ]; then
    printf '%s\n' "рабочая папка оставлена: $WORK"
  else
    cd "$HOME" 2>/dev/null || cd /
    rm -rf "$WORK" 2>/dev/null
  fi
  rm -f "${INDEX:-}" "${REPOLIST:-}" "${PARSER:-}" 2>/dev/null
  exit "$_rc"
}

# Опознавательный знак репы: файл .repo-id со строкой `owner/repo`.
# Ищется на глубине 1..3 — распаковщики macOS добавляют уровни обёрток, и угадывать
# структуру по именам каталогов бессмысленно. Возвращает имя репы или пусто.
find_repo_id(){
  # По уровням сверху вниз: маркер вложенной репы не должен выигрывать у корневого.
  _rid=""
  for _d in 1 2 3; do
    _rid="$(find "$1" -mindepth "$_d" -maxdepth "$_d" -name '.repo-id' -type f -print 2>/dev/null | head -1)"
    [ -n "$_rid" ] && break
  done
  [ -n "$_rid" ] || return 1
  _line="$(head -1 "$_rid" | tr -d ' \t\r\n')"
  case "$_line" in */*) printf '%s' "${_line#*/}" ;; *) printf '%s' "$_line" ;; esac
}

# Версия из дерева: VERSION на глубине 1..3 по той же причине.
find_version_file(){
  _vf=""
  for _d in 1 2 3; do
    _vf="$(find "$1" -mindepth "$_d" -maxdepth "$_d" -name 'VERSION' -type f -print 2>/dev/null | head -1)"
    [ -n "$_vf" ] && break
  done
  [ -n "$_vf" ] || return 1
  tr -d ' \t\r\n' < "$_vf"
}

# Полностью ли версия опубликована: тег на remote + релиз + канонический ассет.
# Одна функция на VERIFY и на DELETE_AFTER — иначе они разъедутся.
# Печатает список недостающего; пусто = всё на месте.
missing_parts(){
  _mr="$1"; _mv="$2"; _miss=""
  git ls-remote --tags "$REMOTE_BASE/$_mr.git" "refs/tags/v$_mv" 2>/dev/null | grep -q . \
    || _miss="$_miss тег"
  release_state "$_mr" "$_mv"; _ms=$?
  if [ "$_ms" -ne 0 ]; then
    _miss="$_miss релиз"
  else
    gh_try release view "v$_mv" --repo "$OWNER/$_mr" --json assets --jq '.assets[].name' 2>/dev/null \
      | grep -Fxq "$_mr-v$_mv.zip" || _miss="$_miss ассет"
  fi
  printf '%s' "$_miss"
}

# Уборка распакованных зеркал. Вынесена в функцию, потому что нужна на ДВУХ путях:
# обычный прогон и ранний выход «архивов нет» — во втором случае зеркала всё равно
# могут лежать на диске, и их надо убрать.
cleanup_mirrors(){
  [ "$DELETE_AFTER" = "1" ] && [ "$HAVE_GH" -eq 1 ] || return 0
  # Распакованные зеркала. Каталоги ищем В ПАПКЕ НАПРЯМУЮ, а не по списку архивов
  # этого прогона: архив мог быть удалён раньше, а распакованная копия осталась.
  # Удаляем только доказуемую копию — все условия обязательны:
  #   1) имя разбирается как <repo>-vX.Y.Z (точки или подчёркивания, постфикс сборки);
  #   2) внутри есть VERSION и он совпадает с версией из имени;
  #   3) внутри НЕТ .git — иначе это рабочий клон, а не распакованный архив;
  #   4) версия полностью на GitHub (тег + релиз + ассет).
  # Каталог без версии в имени (`personal-finance-dss`) не рассматривается вовсе.
  # find вместо glob: в zsh несовпавший шаблон роняет скрипт целиком
  find "$DIR" -mindepth 1 -maxdepth 1 -type d -print 2>/dev/null | while IFS= read -r _cand; do
    [ -d "$_cand" ] || continue
    _cb="$(basename "$_cand")"
    _cp="$(printf '%s' "$_cb" | sed -E 's/[-_](intl|international|ru|en)$//' \
           | sed -nE 's/^(.+)[-_. ]v?([0-9]+)[._-]([0-9]+)[._-]([0-9]+)$/\1\t\2.\3.\4/p')"
    [ -n "$_cp" ] || continue
    _cr="$(printf '%s' "$_cp" | cut -f1)"; _cv="$(printf '%s' "$_cp" | cut -f2)"
    case " $VARIANT_REPOS " in *" $_cr "*) : ;; esac
    for _m in $REPO_MAP; do
      case "$_m" in "$_cr="*) _cr="${_m#*=}" ;; esac
    done
    [ -d "$_cand/.git" ] && { ylw "  ~ $_cb/ — git-клон, не трогаю"; continue; }
    # VERSION ищем в корне И на уровень глубже: macOS распаковывает foo.zip в папку
    # foo/, а внутри архива уже есть обёртка — VERSION оказывается на глубине 2.
    # .repo-id — надёжное опознание: не зависит ни от имени каталога, ни от глубины
    _rid_repo="$(find_repo_id "$_cand" || true)"
    [ -n "$_rid_repo" ] && _cr="$_rid_repo"
    _cver="$(find_version_file "$_cand" || true)"
    [ -n "$_cver" ] || { ylw "  ~ $_cb/ — нет ни .repo-id, ни VERSION (до 3 уровней) — не трогаю"; continue; }
    [ "$_cver" = "$_cv" ] || { ylw "  ~ $_cb/ — VERSION=$_cver ≠ $_cv, не трогаю"; continue; }
    # .git может быть тоже на уровень глубже
    if [ -e "$_cand/.git" ] \
       || [ -n "$(find "$_cand" -mindepth 2 -maxdepth 2 -name .git -print 2>/dev/null | head -1)" ]; then
      ylw "  ~ $_cb/ — git-клон внутри, не трогаю"; continue
    fi
    _mm="$(missing_parts "$_cr" "$_cv")"
    [ -z "$_mm" ] || { ylw "  ~ $_cb/ — на GitHub не хватает:$_mm — не трогаю"; continue; }
    rm -rf "$_cand" && { grn "  − $_cb/ (распакованное зеркало)"
                         note "$_cr|v$_cv|папка|удалена локально"
                         # тело while в пайпе — сабшелл, счётчик наружу не выходит
                         echo x >> "$WORK/.mirdel"; }
  done
  [ -f "$WORK/.mirdel" ] && MIR_DEL=$(grep -c . "$WORK/.mirdel")
  return 0
}

# --- поиск CHANGELOG где угодно в дереве ----------------------------------------
# Канон — корень репы (§46), но исторически файл живёт и в docs/, и в
# 00-infrastructure/, и глубже. Ищем везде и выбираем тот, где ЕСТЬ секция версии:
# наличие секции — единственный надёжный признак «это наш журнал».
# RELEASES.md — признанный альтернативный формат (найдено 2026-08-13 на репе finpilot,
# синк из архива finpilot-public-mirror-v8.19.2.zip: приватный монорепо намеренно НЕ
# публикует CHANGELOG.md — 300+ КБ внутренней кухни процесса — и вместо него держит
# отдельный RELEASES.md, переписанный с нуля под публичную историю версий; без этой
# строки поиск ничего не находил, релиз создавался без описания). Приоритет —
# CHANGELOG*, RELEASES только если чейнджлога нет вовсе, чтобы не подменять более
# подробный источник.
# find_changelog <корень> <версия> -> путь или пусто
find_changelog(){
  _root="$1"; _fv="$2"
  # 1) приоритетные места по порядку
  for _c in "$_root/CHANGELOG.md" "$_root/docs/CHANGELOG.md" \
            "$_root/00-infrastructure/CHANGELOG.md" "$_root/CHANGELOG" "$_root/Changelog.md" \
            "$_root/RELEASES.md" "$_root/docs/RELEASES.md"; do
    [ -f "$_c" ] && LC_ALL=C grep -qE "^#+ *\\[?$_fv\\]?( |\$|—|-)" "$_c" 2>/dev/null && { printf '%s' "$_c"; return 0; }
  done
  # 2) поиск по всему дереву — сначала тот, где есть секция версии
  _found="$(find "$_root" -maxdepth 4 \( -iname 'CHANGELOG*.md' -o -iname 'RELEASES.md' \) \
              ! -path '*/node_modules/*' ! -path '*/.git/*' ! -path '*/_archive/*' \
              ! -iname '*TEMPLATE*' ! -iname '*repos-map*' 2>/dev/null)"
  for _c in $_found; do
    LC_ALL=C grep -qE "^#+ *\\[?$_fv\\]?( |\$|—|-)" "$_c" 2>/dev/null && { printf '%s' "$_c"; return 0; }
  done
  # 3) секции нет нигде — вернём хоть какой-то журнал (приоритет корню, CHANGELOG
  #    приоритетнее RELEASES — если оба есть без секции, вероятнее не хватает
  #    записи в основном журнале, а не то, что нужно переключаться на запасной)
  for _c in "$_root/CHANGELOG.md" "$_root/docs/CHANGELOG.md" "$_root/00-infrastructure/CHANGELOG.md" \
            "$_root/RELEASES.md" "$_root/docs/RELEASES.md"; do
    [ -f "$_c" ] && { printf '%s' "$_c"; return 0; }
  done
  for _c in $_found; do [ -f "$_c" ] && { printf '%s' "$_c"; return 0; }; done
  return 1
}

# --- вспомогательное: заголовок + описание релиза по стандарту -------------------
# build_notes <корень-дерева> <ver> <repo> <out.md>  -> печатает заголовок релиза
build_notes(){
  _clroot="$1"; _v="$2"; _r="$3"; _out="$4"
  _thesis=""
  # принимаем и готовый путь к файлу, и корень дерева
  if [ -f "$_clroot" ]; then _cl="$_clroot"; else _cl="$(find_changelog "$_clroot" "$_v" || true)"; fi
  if [ -n "$_cl" ] && [ -f "$_cl" ]; then
    case "$_cl" in "$_clroot/CHANGELOG.md") : ;; *) plain "    CHANGELOG: ${_cl#$_clroot/}" >&2 ;; esac
    _thesis="$(python3 "$PARSER" "$_cl" "$_v" "$_out" 2>"$WORK/parse_err.txt")"
    if [ $? -ne 0 ]; then
      ylw "    CHANGELOG: секции [$_v] нет — описание будет техническим" >&2
      note "$_r|v$_v|описание|⚠ нет секции в CHANGELOG"
      _thesis=""
    else
      grep -q NOBUMP   "$WORK/parse_err.txt" 2>/dev/null && \
        { ylw "    CHANGELOG: в заголовке нет (MAJOR/MINOR/PATCH) — §2 стандарта" >&2; note "$_r|v$_v|формат|⚠ нет BUMP-маркера"; }
      grep -q NOTHESIS "$WORK/parse_err.txt" 2>/dev/null && \
        { ylw "    CHANGELOG: в заголовке нет тезиса — §2 стандарта" >&2; note "$_r|v$_v|формат|⚠ нет тезиса"; }
    fi
  else
    red "    ✗ CHANGELOG не найден нигде в дереве" >&2
    note "$_r|v$_v|описание|✗ CHANGELOG не найден"
    loud "$_r v$_v: CHANGELOG не найден — релиз без описания НЕ создаю"
    printf '' > "$_out"; return 1
  fi
  if [ ! -s "$_out" ]; then
    red "    ✗ в CHANGELOG нет секции [$_v] — релиз без описания не создаю" >&2
    loud "$_r v$_v: в CHANGELOG нет секции — добавь её и перезапусти с REPAIR=1"
    return 1
  fi
  if [ -n "$_thesis" ]; then printf '%s v%s — %s\n' "$_r" "$_v" "$_thesis"
  else printf '%s v%s\n' "$_r" "$_v"; fi
}

# release_is_stub <repo> <ver> -> 0 если описание пустое/заглушка (можно перезаписать)
release_is_stub(){
  _body="$(gh release view "v$2" --repo "$OWNER/$1" --json body --jq '.body' 2>/dev/null)"
  [ -z "$_body" ] && return 0
  printf '%s' "$_body" | grep -qE '^(Release |Синхронизация дерева)' && return 0
  [ "$(printf '%s' "$_body" | wc -c | tr -d ' ')" -lt 40 ] && return 0
  return 1
}

# ensure_release <repo> <ver> <notes.md> <title> <zip|"">
ensure_release(){
  _r="$1"; _v="$2"; _n="$3"; _t="$4"; _z="${5:-}"; _cl="${6:-}"
  [ "$HAVE_GH" -eq 1 ] || { ylw "    gh нет — релиз v$_v вручную"; return 0; }
  _aname="$_r-v$_v.zip"
  _top="$(git tag -l 'v*' 2>/dev/null | sed 's/^v//' | sort -t. -k1,1n -k2,2n -k3,3n | tail -1)"
  _lat="--latest=false"; [ -z "$_top" ] || [ "$_v" = "$_top" ] && _lat="--latest=true"

  if gh release view "v$_v" --repo "$OWNER/$_r" >/dev/null 2>&1; then
    # ---- АУДИТ существующего релиза (идёт всегда, а не по флагу) ----------------
    _ct="$(gh_try release view "v$_v" --repo "$OWNER/$_r" --json name --jq '.name' 2>/dev/null)"
    _cb="$(gh_try release view "v$_v" --repo "$OWNER/$_r" --json body --jq '.body' 2>/dev/null)"
    _fixt=0; _fixb=0
    [ -n "$_t" ] || _t="$_ct"                       # нет эталона — сохраняем текущий
    # заголовок: чиним, если расходится с эталоном из CHANGELOG
    [ -n "$_t" ] && [ "$_ct" != "$_t" ] && _fixt=1
    # тело: чиним заглушки; осмысленное, но расходящееся — только с FORCE
    # Тело правим ТОЛЬКО когда есть чем: пустой notes-файл (нет секции в CHANGELOG)
    # уходил в `gh release edit --notes-file <пусто>` и валил версию. Это и была
    # причина всех «не удалось обновить» в прогоне с FORCE.
    if [ ! -s "$_n" ]; then
      _fixb=0
      ylw "    ~ v$_v: нет секции в CHANGELOG — описание не трогаю"
      note "$_r|v$_v|описание|~ нет секции"
    elif release_is_stub "$_r" "$_v"; then _fixb=1
    elif [ "$FORCE" = "1" ]; then _fixb=1
    elif [ -s "$_n" ] && [ -n "$_cb" ]; then
      if [ "$(printf '%s' "$_cb" | tr -d ' \n\r')" != "$(cat "$_n" | tr -d ' \n\r')" ]; then
        ylw "    ~ v$_v: описание отличается от CHANGELOG — не трогаю (FORCE=1 чтобы синхронизировать)"
        note "$_r|v$_v|описание|~ расходится с CHANGELOG"
      fi
    fi
    if [ "$_fixt" = "1" ] || [ "$_fixb" = "1" ]; then
      if [ "$_fixb" = "1" ]; then
        # пустой заголовок НИКОГДА не отправляем — затрёт существующий
        _targ=""; [ -n "$_t" ] && _targ="--title"
        gh_try release edit "v$_v" --repo "$OWNER/$_r" ${_targ:+$_targ "$_t"} --notes-file "$_n" >/dev/null 2>&1 \
          && { grn "    ✓ v$_v: заголовок и описание по стандарту"; note "$_r|v$_v|релиз|починен"; } \
          || { red "    ✗ v$_v: не удалось обновить"; note "$_r|v$_v|релиз|✗ ошибка"; }
      else
        gh_try release edit "v$_v" --repo "$OWNER/$_r" --title "$_t" >/dev/null 2>&1 \
          && { grn "    ✓ v$_v: заголовок → $_t"; note "$_r|v$_v|заголовок|починен"; } \
          || { red "    ✗ v$_v: заголовок не обновлён"; note "$_r|v$_v|заголовок|✗ ошибка"; }
      fi
    fi
  else
    if [ "$ASSET" = "1" ] && [ -n "$_z" ]; then
      cp "$_z" "$WORK/$_aname"
      _asz="$(du -m "$WORK/$_aname" 2>/dev/null | cut -f1)"
      ylw "    → заливаю ассет $_aname${_asz:+ (~${_asz} МБ)}"
      gh_try_upload "$GH_UPLOAD_TIMEOUT" release create "v$_v" "$WORK/$_aname" --repo "$OWNER/$_r" --title "$_t" --notes-file "$_n" $_lat >/dev/null \
        && { grn "    ✓ релиз v$_v (+ассет $_aname)"; note "$_r|v$_v|релиз|создан"
             # помечаем ассет подтверждённым: иначе автоудаление архива не сработает
             # для только что созданных релизов (эта ветка выходит из функции раньше)
             ASSET_OK="${ASSET_OK:-} $_v"; } \
        || { red "    ✗ релиз v$_v не создан"; note "$_r|v$_v|релиз|✗ ошибка"; }
      rm -f "$WORK/$_aname"; return 0
    fi
    gh_try release create "v$_v" --repo "$OWNER/$_r" --title "$_t" --notes-file "$_n" $_lat >/dev/null 2>&1 \
      && { grn "    ✓ релиз v$_v"; note "$_r|v$_v|релиз|создан"; } \
      || { red "    ✗ релиз v$_v не создан"; note "$_r|v$_v|релиз|✗ ошибка"; }
  fi

  # ---- канонический ассет (§4: ровно 3 ассета) ---------------------------------
  if [ "$ASSET" = "1" ]; then
    _have="$(gh_try release view "v$_v" --repo "$OWNER/$_r" --json assets --jq '.assets[].name' 2>/dev/null)"
    if ! printf '%s\n' "$_have" | grep -Fxq "$_aname"; then
      _src=""
      if [ -n "$_z" ] && [ -f "$_z" ]; then
        # cp без проверки уже привёл к заливке недокопированного файла при полном диске
        if cp "$_z" "$WORK/$_aname" 2>/dev/null; then _src="архив"; else
          red "    ✗ v$_v: не удалось скопировать архив (место на диске?) — ассет не трогаю"
          note "$_r|v$_v|ассет|✗ копирование"; _src=""
        fi
      elif [ -n "$_cl" ] && git -C "$_cl" rev-parse "v$_v" >/dev/null 2>&1; then
        # Архива под рукой нет (старая версия) — собираем канонический zip из тега.
        # Содержимое то же дерево, обёртка по §43.
        git -C "$_cl" archive --format=zip --prefix="$_r-v$_v/" "v$_v" -o "$WORK/$_aname" 2>/dev/null && _src="тег"
      fi
      if [ -n "$_src" ] && [ -f "$WORK/$_aname" ]; then
        _lsz="$(wc -c < "$WORK/$_aname" | tr -d ' ')"
        _lmb=$(( (_lsz + 524288) / 1048576 ))
        ylw "    → заливаю ассет $_aname (~${_lmb} МБ, из $_src)"
        if gh_try_upload "$GH_UPLOAD_TIMEOUT" release upload "v$_v" "$WORK/$_aname" --repo "$OWNER/$_r" --clobber >/dev/null; then
          # Сверяем РАЗМЕР на GitHub с локальным: обрыв связи или нехватка места
          # дают частичный файл, который выглядит как успешная загрузка.
          _rsz="$(gh_try release view "v$_v" --repo "$OWNER/$_r" --json assets \
                  --jq ".assets[] | select(.name==\"$_aname\") | .size" 2>/dev/null | head -1)"
          # Сверяем, только если размер пришёл числом. Не смогли узнать — не выдумываем
          # отказ: ложная тревога хуже отсутствия проверки.
          case "$_rsz" in ''|*[!0-9]*) _rsz="" ;; esac
          if [ -n "$_rsz" ] && [ "$_rsz" != "$_lsz" ]; then
            red "    ✗ v$_v: ассет залился частично ($_rsz из $_lsz байт) — перезапусти"
            note "$_r|v$_v|ассет|✗ размер не сошёлся"
          else
            grn "    ✓ v$_v: ассет $_aname догружен (из: $_src)"; note "$_r|v$_v|ассет|догружен ($_src)"
            ASSET_OK="${ASSET_OK:-} $_v"
          fi
        else
          red "    ✗ v$_v: ассет не загрузился"; note "$_r|v$_v|ассет|✗ ошибка"
        fi
        rm -f "$WORK/$_aname"
      fi
    fi

    # ---- чистка дублей под старым именем (необратимо, только по флагу) ---------
    # ВАЖНО: отдельным блоком ПОСЛЕ загрузки и только если канонический ассет
    # реально лежит на релизе. Иначе при сбое сети можно снести единственную копию
    # и не суметь положить замену.
    if [ "$KEEP_LEGACY_ASSETS" != "1" ] && [ "$DROP_LEGACY_ASSETS" = "1" ]; then
      _now="$(gh_try release view "v$_v" --repo "$OWNER/$_r" --json assets --jq '.assets[].name' 2>/dev/null)"
      if printf '%s\n' "$_now" | grep -Fxq "$_aname"; then
        _vd="$(printf '%s' "$_v" | tr '.' '_')"
        printf '%s\n' "$_now" | while IFS= read -r _old; do
          [ -n "$_old" ] || continue
          [ "$_old" = "$_aname" ] && continue
          # Сносим ТОЛЬКО zip той же версии под старым именем — это дубль
          # канонического. Всё остальное (pdf, отчёты, архивы других версий)
          # не трогаем: удаление ассета необратимо.
          case "$_old" in *.zip) : ;; *) continue ;; esac
          case "$_old" in
            *"$_v"*|*"$_vd"*)
              if [ "$DRY" = "1" ]; then
                ylw "    − v$_v: снял бы дубль $_old (DRY)"
              else
                gh_try release delete-asset "v$_v" "$_old" --repo "$OWNER/$_r" --yes >/dev/null 2>&1 \
                  && { ylw "    − v$_v: снят дубль под старым именем — $_old"; note "$_r|v$_v|ассет|снят дубль $_old"; } \
                  || { red "    ✗ v$_v: не удалось снять $_old"; note "$_r|v$_v|ассет|✗ снятие"; }
              fi ;;
          esac
        done
      else
        ylw "    ~ v$_v: канонического ассета нет — чистку дублей пропускаю"
      fi
    fi
  fi

}


# Рабочая папка — во ВРЕМЕННОЙ директории, не в Downloads: сюда клонируются все репы,
# и один прогон легко даёт несколько гигабайт. Раньше лежала в Downloads и оставалась
# после каждого Ctrl+C — так и кончилось место на диске.
WORK="$(mktemp -d "${TMPDIR:-/tmp}/repo_deploy_XXXXXX")"
# Уборка при ЛЮБОМ выходе: нормальном, по ошибке, по Ctrl+C. Раньше стояла последней
# строкой скрипта, и до неё просто не доходило.
trap cleanup_work EXIT INT TERM

# --- ШАГ 1. Инвентаризация архивов ----------------------------------------------
_free_mb="$(df -Pm "${TMPDIR:-/tmp}" 2>/dev/null | awk 'NR==2{print $4}')"
if [ -n "$_free_mb" ] && [ "$_free_mb" -lt "$MIN_FREE_MB" ]; then
  die "свободно всего ${_free_mb} МБ (нужно ≥ ${MIN_FREE_MB}). Освободи место: прогон на
     переполненном диске обрывает копирование и может залить недокачанный ассет.
     Порог меняется через MIN_FREE_MB."
fi
bld "── deploy.sh v$SCRIPT_VERSION · Шаг 1. Ищу версионные архивы в $DIR"
# 🔴 Прогресс обязателен: шаг молча читает каждый архив, и на полусотне это десятки
# секунд. Молчание неотличимо от зависания — владелец прерывал прогон дважды.
_ntotal="$(ls -1 "$DIR"/*.zip 2>/dev/null | wc -l | tr -d " ")"
[ "${_ntotal:-0}" -gt 0 ] && ylw "   архивов к разбору: $_ntotal"
_nseen=0
INDEX="$(mktemp)"
NONCANON=""; DUPES=""; VARIANTS=""; MAPPED=""; UNKNOWN=""; N_SERVICE=0
for z in "$DIR"/*.zip; do
  [ -f "$z" ] || continue
  base="$(basename "$z" .zip)"
  _nseen=$((_nseen+1))
  printf '\r   [%s/%s] %-46.46s' "$_nseen" "${_ntotal:-?}" "$base" >&2

  # (A) служебные архивы из чата (files 3.zip, 16.zip) — не наши артефакты, молча мимо
  if printf '%s' "$base" | LC_ALL=C grep -qE "$SERVICE_RE"; then
    N_SERVICE=$((N_SERVICE+1)); continue
  fi
  if [ -n "${IGNORE:-}" ] && printf '%s' "$base" | LC_ALL=C grep -qE "$IGNORE"; then
    N_SERVICE=$((N_SERVICE+1)); continue
  fi

  # (B) рабочие копии и дубликаты — НИКОГДА не публикуем: это дубль, а не поставка
  if printf '%s' "$base" | LC_ALL=C grep -qiE '(^|[^a-zA-Z])copy([^a-zA-Z]|$)|\([0-9]+\)$|[0-9]+[._-][0-9]+[._-][0-9]+ [0-9]+$'; then
    DUPES="$DUPES
  $base.zip"; continue
  fi
  # macOS/браузер лепят хвосты: " copy", "-copy", "__copy_", " (1)", "(2)". Срезаем их,
  # иначе валидный архив просто не находится и человек думает, что скрипт сломан.
  clean="$(printf '%s' "$base" | sed -E 's/([ _-]*[Cc]opy[ _-]*)+$//; s/[ _-]*\([0-9]+\)$//; s/[ _-]+$//')"
  # ИСТОРИЧЕСКИЙ НЕЙМИНГ (§43): принимаем всё, что реально встречалось, чтобы старые архивы
  # не выпадали из системы. Разделитель имя↔версия: - _ . или пробел; префикс v необязателен;
  # разделитель внутри версии: . _ или -. Канон при этом один — точки, о нём говорим ниже.
  parsed="$(printf '%s' "$clean" | sed -nE 's/^(.+)[-_. ]v?([0-9]+)[._-]([0-9]+)[._-]([0-9]+)$/\1 \2.\3.\4/p')"
  if [ -z "$parsed" ]; then
    # двухчастная версия (v1.2) — тоже историческая ошибка: достраиваем до X.Y.0
    two="$(printf '%s' "$clean" | sed -nE 's/^(.+)[-_. ]v?([0-9]+)[._-]([0-9]+)$/\1 \2.\3.0/p')"
    if [ -n "$two" ]; then
      parsed="$two"
      ylw "  ! $base.zip — версия из двух частей, читаю как ${two#* } (§43: всегда X.Y.Z)"
    fi
  fi
  # вариантный постфикс (finpilot_v6_20_1_intl): срезаем ТОЛЬКО для реп из VARIANT_REPOS,
  # чтобы случайно не откусить кусок имени у чужой репы
  if [ -z "$parsed" ]; then
    vclean="$(printf '%s' "$clean" | sed -E 's/[-_](intl|international|ru|en)$//')"
    if [ "$vclean" != "$clean" ]; then
      vparsed="$(printf '%s' "$vclean" | sed -nE 's/^(.+)[-_. ]v?([0-9]+)[._-]([0-9]+)[._-]([0-9]+)$/\1 \2.\3.\4/p')"
      vname="$(printf '%s' "${vparsed%% *}" | sed -E 's/[-_. ]+$//')"
      for vr in $VARIANT_REPOS; do
        if [ -n "$vparsed" ] && [ "$vname" = "$vr" ]; then
          parsed="$vparsed"
          VARIANTS="$VARIANTS
  $base.zip → $vr v${vparsed#* }"
          break
        fi
      done
    fi
  fi
  if [ -z "$parsed" ]; then
    if printf '%s' "$base" | LC_ALL=C grep -qE '[0-9]+[._-][0-9]+'; then
      ylw "  ? $base.zip — похоже на версию, но не читается. Канон: <repo>-vX.Y.Z.zip"
    else
      UNKNOWN="$UNKNOWN
  $base.zip"
    fi
    continue
  fi
  name="${parsed%% *}"; ver="${parsed#* }"
  name="$(printf '%s' "$name" | sed -E 's/[-_. ]+$//')"
  # Переименование по карте применяется ТОЛЬКО если в архиве нет .repo-id.
  # .repo-id — заявление владельца о принадлежности архива, и оно старше карты.
  # Без этого приоритета архив finpilot-vX.Y.Z.zip с .repo-id=finpilot уезжал бы
  # в personal-finance-dss по исторической записи карты, а потом отбраковывался
  # проверкой ниже как «.repo-id ≠ целевая репа». Ровно этот тупик и случился 08.08.
  _has_rid=0
  unzip -Z1 "$z" 2>/dev/null | LC_ALL=C grep -qE '^([^/]+/)?\.repo-id$' && _has_rid=1
  if [ "$_has_rid" -eq 0 ]; then
    for _m in $REPO_MAP; do
      case "$_m" in
        "$name="*) _t="${_m#*=}"
          [ "$_t" != "$name" ] && MAPPED="$MAPPED
  $base.zip → репозиторий $_t (архив назван $name)"
          name="$_t";;
      esac
    done
  fi

  # ПРЕДПОЛЁТНАЯ ПРОВЕРКА целостности. Делается ДО создания репы: иначе битый архив
  # успевал породить на GitHub пустую репу-сироту, которую потом удалять руками.
  #
  # 🔴 РАНЬШЕ ЗДЕСЬ СТОЯЛ `unzip -t`, и комментарий утверждал «дёшево, без распаковки».
  # Утверждение было неверным: `-t` проверяет CRC КАЖДОГО файла, то есть распаковывает
  # весь архив в память. Замер 23.08.2026: 3.8 с на архив в 268 МБ, **47 секунд молча**
  # на 47 архивах — владелец видел «скрипт стоит на Шаге 1» и дважды прерывал прогон.
  #
  # `zipinfo -1` читает только центральную директорию — она дописывается ПОСЛЕДНЕЙ,
  # поэтому её наличие и есть признак дописанного архива (`PIT-130`). Это то, что
  # проверка и должна была делать: отличить оборванный файл от целого, а не
  # пересчитать CRC.
  if ! zipinfo -1 "$z" >/dev/null 2>&1; then
    sleep 3
    if ! zipinfo -1 "$z" >/dev/null 2>&1; then
      red "  ✗ $base.zip — битый архив (нет оглавления), пропускаю"; continue
    fi
    ylw "  ~ $base.zip — дочитался со второй попытки (файл ещё писался)"
  fi
  # LC_ALL=C: имена внутри архивов бывают не в UTF-8 (кириллица в CP1251, macOS-NFD).
  # BSD-шные cut/grep под UTF-8 локалью на таких байтах падают с Illegal byte sequence.
  _ent="$(unzip -Z1 "$z" 2>/dev/null | LC_ALL=C grep -v '/$' | LC_ALL=C grep -vE '(^|/)__MACOSX/|(^|/)\.DS_Store$|(^|/)\._')"
  _nf="$(printf '%s\n' "$_ent" | LC_ALL=C grep -c .)"
  if [ "$_nf" -lt "$MIN_FILES" ]; then
    red "  ✗ $base.zip — файлов $_nf (< $MIN_FILES), не похоже на репу — пропускаю"; continue
  fi
  if ! printf '%s\n' "$_ent" | LC_ALL=C grep -qE '(^|/)README\.md$'; then
    red "  ✗ $base.zip — корень не опознан (нет README.md) — пропускаю"; continue
  fi
  _roots0="$(printf '%s\n' "$_ent" | LC_ALL=C cut -d/ -f1 | LC_ALL=C sort -u | LC_ALL=C grep -c .)"
  # .repo-id читаем ПРЯМО ИЗ ZIP, до создания репы: иначе при несовпадении
  # успевала завестись пустая репа-сирота (кейс C12).
  # СТРОГО корневой: в dota-dossier вложена base-repo со своим .repo-id, и первый
  # найденный файл принадлежал вложенной репе. Та же ловушка, что была с VERSION.
  if [ "$_roots0" = "1" ]; then
    _ridpath="$(printf '%s\n' "$_ent" | LC_ALL=C grep -xE '[^/]+/\.repo-id')"
  else
    _ridpath="$(printf '%s\n' "$_ent" | LC_ALL=C grep -x '\.repo-id')"
  fi
  _ridpath="$(printf '%s\n' "$_ridpath" | head -1)"
  if [ -n "$_ridpath" ]; then
    _ridval="$(unzip -p "$z" "$_ridpath" 2>/dev/null | head -1 | tr -d ' \t\r\n')"
    _ridrepo="${_ridval#*/}"
    # Сравниваем с ЦЕЛЕВОЙ репой (после REPO_MAP): у finpilot имя архива и репа
    # намеренно разные, и это не ошибка.
    if [ -n "$_ridrepo" ] && [ "$_ridrepo" != "$name" ]; then
      red "  ✗ $base.zip — .repo-id внутри указывает на «${_ridrepo}», целевая репа «${name}» — пропускаю"
      loud "$base.zip: .repo-id=$_ridrepo ≠ $name. Архив уехал бы не в ту репу."
      continue
    fi
  fi
  # VERSION берём СТРОГО корневой. Глоб '*/VERSION' ловил ещё и вложенные репы
  # (base-repo внутри dota-dossier) и склеивал их содержимое: "1.13.0"+"2.13.0".
  _roots="$(printf '%s\n' "$_ent" | LC_ALL=C cut -d/ -f1 | LC_ALL=C sort -u | LC_ALL=C grep -c .)"
  if [ "$_roots" = "1" ]; then
    _wrap="$(printf '%s\n' "$_ent" | LC_ALL=C cut -d/ -f1 | LC_ALL=C sort -u)"
    _vf="$(unzip -p "$z" "$_wrap/VERSION" 2>/dev/null | head -c 32 | tr -d ' \n\r')"
  else
    _vf="$(unzip -p "$z" 'VERSION' 2>/dev/null | head -c 32 | tr -d ' \n\r')"
  fi
  if [ -n "$_vf" ] && [ "$_vf" != "$ver" ]; then
    red "  ✗ $base.zip — VERSION в дереве = $_vf, а архив v$ver — пропускаю"; continue
  fi
  # §НЕЙМИНГ: канон — точки. Подчёркивания принимаем (легаси), но говорим об этом вслух.
  [ "$clean" = "$name-v$ver" ] || NONCANON="$NONCANON
  $base.zip → канон: $name-v$ver.zip"
  skip=0
  for s in ${SKIP:-}; do [ "$name" = "$s" ] && skip=1; done
  [ "$skip" = "1" ] && continue
  if [ -n "${ONLY:-}" ]; then
    keep=0; for o in $ONLY; do [ "$name" = "$o" ] && keep=1; done
    [ "$keep" = "1" ] || continue
  else
    for m in ${MIRRORS:-}; do
      [ "$name" = "$m" ] && { MIRROR_SKIPPED="$MIRROR_SKIPPED $m"; skip=1; }
    done
    [ "$skip" = "1" ] && continue
  fi
  printf '%s\t%s\t%s\n' "$name" "$ver" "$z" >> "$INDEX"
done
# 🔴 Найдено владельцем 27.08.2026: строка сканирования выше идёт через `\r`
# (обновляется на месте, курсор остаётся в середине строки после последнего
# архива) — без явного перевода строки здесь первая репа из следующей сводки
# («repo — версий: N → X») печаталась ВПРИТЫК к хвосту этой строки на одной
# визуальной строке, а не с новой, как остальные репы списка. Косметический
# дефект, не логический — но ломает читаемость первой строки сводки.
[ "${_ntotal:-0}" -gt 0 ] && printf '\n' >&2
[ -n "$MIRROR_SKIPPED" ] && ylw "  ⊘ публичные зеркала пропущены:$MIRROR_SKIPPED (назови через ONLY, если надо)"
[ "$N_SERVICE" -gt 0 ] && plain "  пропущено служебных архивов: $N_SERVICE (загрузки из чата, не наши артефакты)"
if [ -n "$DUPES" ]; then
  echo ""; ylw "  рабочие копии и дубликаты — НЕ публикую (переименуй, если это поставка):"
  printf '%s\n' "$DUPES" | sed '/^$/d'
fi
if [ -n "$VARIANTS" ]; then
  echo ""; cyn "  вариантные имена (постфикс отброшен, версия взята как есть):"
  printf '%s\n' "$VARIANTS" | sed '/^$/d'
fi
if [ -n "$MAPPED" ]; then
  echo ""; cyn "  переименование по REPO_MAP (архив едет в другую репу):"
  printf '%s\n' "$MAPPED" | sed '/^$/d'
fi
if [ -n "$UNKNOWN" ]; then
  echo ""; plain "  не версионные архивы — не трогаю (для полноты картины):"
  printf '%s\n' "$UNKNOWN" | sed '/^$/d' | while IFS= read -r _u; do plain "$_u"; done
fi

if [ ! -s "$INDEX" ]; then
  # Ремонтные режимы работают по тому, что уже на GitHub, и архив им не нужен —
  # ровно наоборот, их запускают когда архив уже удалён как опубликованный.
  # Ранний выход здесь глушил ASSETS_ONLY/REPAIR/CHLOG_FILL молча и с кодом 0:
  # владелец видел «публиковать нечего» и считал, что починка отработала.
  _repair_mode=0
  for _m in "$REPAIR" "$ASSETS_ONLY" "$CHLOG_FILL" "$AUDIT" "$ALL_REPOS"; do
    [ "$_m" = "1" ] && _repair_mode=1
  done
  if [ "$_repair_mode" = "1" ]; then
    if [ -n "${ONLY:-}" ]; then
      cyn "  архивов нет — ремонтный режим работает по списку ONLY: $ONLY"
    else
      ALL_REPOS=1
      cyn "  архивов нет — ремонтный режим берёт репы из repos-map"
    fi
  else
    # Пустая папка — НЕ ошибка. После автоудаления или обычной уборки это ровно тот
    # результат, к которому шли: всё опубликовано, локальных архивов не осталось.
    # Раньше здесь печаталась «ОШИБКА» и возвращался ненулевой код на успешном исходе.
    echo ""
    grn "Публиковать нечего — версионных архивов в папке нет."
    if [ "$N_SERVICE" -gt 0 ] || [ -n "$DUPES" ] || [ -n "$UNKNOWN" ]; then
      plain "В папке остались только файлы, которые скрипт не публикует по определению:"
      [ "$N_SERVICE" -gt 0 ] && plain "  · служебные загрузки из чата: $N_SERVICE"
      [ -n "$DUPES" ]  && plain "  · рабочие копии и дубликаты"
      [ -n "$UNKNOWN" ] && plain "  · архивы без версии в имени"
    fi
    # Архивов нет, но распакованные зеркала могли остаться — убираем и их.
    if [ "$DELETE_AFTER" = "1" ] && [ "$HAVE_GH" -eq 1 ]; then
      echo ""; bld "── Убираю распакованные копии того, что полностью на GitHub"
      MIR_DEL=0; cleanup_mirrors
      [ "$MIR_DEL" -gt 0 ] && grn "  удалено: $MIR_DEL" || plain "  удалять нечего"
    fi
    echo ""
    ylw "Если ждал другого — проверь папку и имена: канон <repo>-vX.Y.Z.zip"
    ylw "Папка сейчас: $DIR"
    exit 0
  fi
fi

REPOLIST="$(mktemp)"
cut -f1 "$INDEX" | sort -u > "$REPOLIST"
# ONLY в ремонтном режиме задаёт список напрямую: репы может не быть в индексе,
# потому что её архив уже опубликован и удалён.
if [ ! -s "$REPOLIST" ] && [ -n "${ONLY:-}" ]; then
  for _o in $ONLY; do printf '%s\n' "$_o"; done | sort -u > "$REPOLIST"
fi

# ALL_REPOS=1: ревизия ВСЕХ реп системы, а не только тех, где нашлись архивы.
# Список берём из repos-map.md (единственный реестр), фолбэк — gh repo list.
if [ "$ALL_REPOS" = "1" ]; then
  AUDIT=1
  MAPSRC=""
  for cand in "${BASE_REPO:-}" "$DIR/base-repo" "./base-repo" "$HOME/base-repo"; do
    [ -n "$cand" ] && [ -f "$cand/repos-map.md" ] && { MAPSRC="$cand/repos-map.md"; break; }
  done
  if [ -z "$MAPSRC" ] && [ "$HAVE_GH" -eq 1 ]; then
    _tmpmap="$(mktemp -d)/repos-map.md"
    git clone -q --depth 1 "$REMOTE_BASE/base-repo.git" "$(dirname "$_tmpmap")/br" 2>/dev/null \
      && [ -f "$(dirname "$_tmpmap")/br/repos-map.md" ] && MAPSRC="$(dirname "$_tmpmap")/br/repos-map.md"
  fi
  if [ -n "$MAPSRC" ]; then
    # имена реп в карте — заголовки вида «## `repo-name`»
    # Между решёткой и именем бывает что угодно (у авто-регистрации там 🆕),
    # поэтому берём первое имя в бэктиках из любой строки-заголовка.
    LC_ALL=C sed -nE 's/^#+[^`]*`([a-z0-9][a-z0-9._-]*)`.*/\1/p' "$MAPSRC" 2>/dev/null \
      | sort -u >> "$REPOLIST"
    cyn "  ALL_REPOS=1: список реп взят из repos-map.md"
  elif [ "$HAVE_GH" -eq 1 ]; then
    gh repo list "$OWNER" --limit 200 --json name --jq '.[].name' 2>/dev/null | sort -u >> "$REPOLIST"
    ylw "  ALL_REPOS=1: карта не найдена, список взят из gh repo list"
  fi
  # Тот же фильтр, что и для архивов: список из repos-map не должен быть лазейкой,
  # через которую массовый режим доберётся до публичного зеркала.
  if [ -z "${ONLY:-}" ]; then
    for m in ${MIRRORS:-}; do
      if grep -qx "$m" "$REPOLIST" 2>/dev/null; then
        grep -vx "$m" "$REPOLIST" > "$REPOLIST.tmp" && mv "$REPOLIST.tmp" "$REPOLIST"
        MIRROR_SKIPPED="$MIRROR_SKIPPED $m"
      fi
    done
  fi
  sort -u "$REPOLIST" -o "$REPOLIST"
fi
while IFS= read -r r; do
  [ -n "$r" ] || continue
  n="$(awk -F'\t' -v r="$r" '$1==r' "$INDEX" | wc -l | tr -d ' ')"
  vers="$(awk -F'\t' -v r="$r" '$1==r{print $2}' "$INDEX" | sort -t. -k1,1n -k2,2n -k3,3n | tr '\n' ' ')"
  grn "  $r — версий: $n → $vers"
done < "$REPOLIST"
[ -n "${SKIP:-}" ] && ylw "  пропускаются по SKIP: $SKIP"
if [ -n "$NONCANON" ]; then
  echo ""; ylw "  имена не по стандарту (обработаю, но переименуй у себя — канон это ТОЧКИ):"
  printf '%s\n' "$NONCANON" | sed '/^$/d'
fi
[ "$REPAIR" = "1" ] && cyn "  режим REPAIR: только приведение существующих релизов к стандарту"

if [ "$DRY" = "1" ]; then
  ylw ""; ylw "DRY=1 — это только план, ничего не изменено. Убери DRY, чтобы выполнить."
  rm -f "$INDEX" "$REPOLIST" "$PARSER"; exit 0
fi

# --- РЕЖИМ VERIFY: можно ли удалять локальные архивы -----------------------------
# Архив считается безопасным к удалению, только если на GitHub есть ВСЁ:
# тег, релиз и канонический ассет <repo>-vX.Y.Z.zip. Иначе — держать.
if [ "$VERIFY" = "1" ]; then
  echo ""; bld "── Проверка: что можно удалить локально"
  [ "$HAVE_GH" -eq 1 ] || die "нужен gh, иначе проверить нечем"
  SAFE=""; KEEP=""
  while IFS="$(printf '\t')" read -r r v z; do
    [ -n "$r" ] || continue
    _miss="$(missing_parts "$r" "$v")"
    if [ -z "$_miss" ]; then
      grn "  ✓ $(basename "$z") — на GitHub есть всё, можно удалять"
      SAFE="$SAFE
  $z"
    else
      red "  ✗ $(basename "$z") — не хватает:$_miss — ДЕРЖАТЬ"
      KEEP="$KEEP
  $(basename "$z") —$_miss"
    fi
  done < "$INDEX"
  echo ""
  if [ -n "$KEEP" ]; then
    bld "НЕ УДАЛЯТЬ:"; printf '%s\n' "$KEEP" | sed '/^$/d'
    echo ""
  fi
  if [ -n "$SAFE" ]; then
    # Пути пишем БЕЗ отступа: иначе xargs получит имя с ведущими пробелами
    # и удаление сломается (или удалит не то).
    printf '%s\n' "$SAFE" | sed '/^$/d; s/^[[:space:]]*//' > "$HOME/Downloads/safe_to_delete.txt"
    grn "Список безопасных к удалению: ~/Downloads/safe_to_delete.txt"
    cyn "Удалить одной командой:"
    # Ни xargs -d (нет в BSD), ни tr '\\0' (BSD хочет \\000) не переносимы.
    # while-read работает везде и корректно обрабатывает пробелы в путях.
    echo "  while IFS= read -r f; do rm -- \"\$f\"; done < ~/Downloads/safe_to_delete.txt"
    echo ""
    cyn "Либо один раз включи автоудаление, и список больше не понадобится:"
    echo "  DELETE_AFTER=1 zsh $0"
  fi
  ylw ""
  ylw "Помни: после удаления единственная копия — GitHub (приватные репы)."
  ylw "Прежде чем сносить всё, подумай про офлайн-бэкап хотя бы флагмана."
  rm -f "$INDEX" "$REPOLIST" "$PARSER"; exit 0
fi

mkdir -p "$WORK" || die "mkdir $WORK"
NEW_REPOS=""

# --- ШАГ 2. Обработка каждой репы ------------------------------------------------
while IFS= read -r REPO; do
  [ -n "$REPO" ] || continue
  echo ""; bld "══ Репозиторий: $REPO"
  URL="$REMOTE_BASE/$REPO.git"

  # Репу считаем отсутствующей ТОЛЬКО при внятном ответе сервера. Раньше любой
  # сбой связи выглядел как «репы нет», и скрипт лез создавать существующую
  # (случай с family: GraphQL «Name already exists»).
  REPO_STATE=0
  if [ "$HAVE_GH" -eq 1 ]; then
    _rv="$(gh_try repo view "$OWNER/$REPO" --json name 2>&1)" || {
      # По умолчанию «репы нет». Сбоем связи считаем только явные признаки —
      # иначе любой обычный «не найдено» выглядит как отказ сети (эту ошибку
      # уже допускали с релизами, повторять нельзя).
      REPO_STATE=1
      case "$_rv" in
        *timeout*|*"connection reset"*|*"TLS handshake"*|*"i/o timeout"*|\
        *"502"*|*"503"*|*"504"*|*"rate limit"*) REPO_STATE=2 ;;
      esac
    }
  fi
  if [ "$REPO_STATE" -eq 2 ]; then
    red "→ $REPO: GitHub не отвечает — пропускаю репу (перезапусти позже)"
    note "$REPO|—|репа|✗ сеть"; continue
  fi
  # --- метаданные из .repo-meta (лежит в корне архива, едет вместе с деревом) ---
  # Без этого описание = имя репы. Отсюда родился finpilot-mirror с описанием
  # "finpilot-mirror". Берём из САМОГО СВЕЖЕГО архива репы: $ZIP здесь ещё не задан,
  # он появляется ниже, внутри цикла по версиям.
  DESC="$REPO"; TOPICS=""
  _metazip="$(awk -F'\t' -v r="$REPO" '$1==r{v=$2; z=$3} END{if(z!="")print z}' "$INDEX")"
  _metapath=""
  if [ -n "${_metazip:-}" ] && [ -f "$_metazip" ]; then
    _metapath="$(unzip -Z1 "$_metazip" 2>/dev/null | LC_ALL=C grep -E '(^|/)\.repo-meta$' | head -1)"
  fi
  if [ -n "${_metapath:-}" ]; then
    _meta="$(unzip -p "$_metazip" "$_metapath" 2>/dev/null)"
    _d="$(printf '%s\n' "$_meta" | LC_ALL=C grep -m1 '^description=' | cut -d= -f2-)"
    TOPICS="$(printf '%s\n' "$_meta" | LC_ALL=C grep -m1 '^topics=' | cut -d= -f2-)"
    [ -n "${_d:-}" ] && DESC="$_d"
  fi

  # Ремонтный режим чинит то, что УЖЕ есть, и создавать ничего не имеет права.
  # 09.08.2026 ALL_REPOS взял список из repos-map, где оставалась строка про
  # удалённую finpilot-mirror, — и деплойер молча создал её заново.
  _repairing=0
  for _m in "$REPAIR" "$ASSETS_ONLY" "$CHLOG_FILL" "$AUDIT" "$ALL_REPOS"; do
    [ "$_m" = "1" ] && _repairing=1
  done
  if [ "$REPO_STATE" -eq 1 ] && [ "$_repairing" = "1" ]; then
    red "→ $REPO: репы на GitHub нет — ремонтный режим НЕ создаёт репозитории"
    ylw "   если она удалена намеренно — вычисти строку из repos-map.md"
    note "$REPO|—|репа|✗ нет на GitHub, пропущена (ремонт)"
    continue
  fi

  if [ "$HAVE_GH" -eq 1 ] && [ "$REPO_STATE" -eq 1 ]; then
    VIS="--private"; [ "$PRIVATE" = "0" ] && VIS="--public"
    ylw "→ репозитория нет, создаю ($VIS)"
    gh repo create "$OWNER/$REPO" $VIS --description "$DESC" >/dev/null \
      || { red "не удалось создать $OWNER/$REPO — пропускаю репу"; note "$REPO|—|репа|✗ не создана"; continue; }
    grn "✓ репозиторий создан"; NEW_REPOS="$NEW_REPOS $REPO"
    note "$REPO|—|репа|СОЗДАНА (новая)"
  fi

  # Описание и топики обновляются на КАЖДОМ прогоне, не только при создании:
  # иначе существующие репы навсегда остаются с описанием от старого скрипта.
  if [ "$HAVE_GH" -eq 1 ] && [ -n "${_metapath:-}" ]; then
    gh repo edit "$OWNER/$REPO" --description "$DESC" >/dev/null 2>&1 \
      && grn "  ✓ описание обновлено"
    if [ -n "$TOPICS" ]; then
      TOPIC_ARGS=""; _rest="$TOPICS"
      while [ -n "$_rest" ]; do
        t="${_rest%%,*}"
        if [ "$t" = "$_rest" ]; then _rest=""; else _rest="${_rest#*,}"; fi
        t="$(printf '%s' "$t" | tr -d ' ')"
        [ -n "$t" ] && TOPIC_ARGS="$TOPIC_ARGS --add-topic $t"
      done
      [ -n "$TOPIC_ARGS" ] && gh repo edit "$OWNER/$REPO" $TOPIC_ARGS >/dev/null 2>&1 \
        && grn "  ✓ топики: $TOPICS"
    fi
  fi

  # 🔴 Найдено владельцем 27.08.2026: рабочая папка иногда исчезает ПОСРЕДИ клона
  # без Ctrl+C (среда нестабильна — VPN/диск/файловая система), и без этой проверки
  # скрипт бился в retry() 5 раз на КАЖДОЙ следующей репе с одинаковой бессмысленной
  # ошибкой «Unable to read current working directory» — 5 попыток × N реп впустую,
  # пока не понятно, что чинить нечего, среда сама сломана. Проверяем один раз здесь.
  [ -d "$WORK" ] || die "рабочая папка $WORK исчезла посреди прогона (не по Ctrl+C) —
     среда нестабильна: VPN, диск или файловая система. Перезапусти скрипт заново,
     это не сетевая ошибка отдельной репы — retry() её не почини́т."
  CLONE="$WORK/$REPO"
  ylw "→ клонирую"
  # Прогресс печатается всегда: у крупных реп (portrait-of-taste, dota-dossier)
  # клон идёт минутами, и без вывода невозможно отличить работу от зависшей сети.
  # git отдаёт прогресс в stderr и только когда видит терминал — отсюда --progress.
  # Пишем в файл и одновременно показываем последнюю строку, чтобы не терять текст
  # ошибки: он нужен ниже, если клон упадёт.
  _clone_log="$WORK/clone_$REPO.log"
  : > "$_clone_log"
  git -c "http.lowSpeedLimit=$CLONE_LOW_SPEED_LIMIT" -c "http.lowSpeedTime=$CLONE_LOW_SPEED_TIME" \
    clone --progress "$URL" "$CLONE" 2>"$_clone_log" &
  _git_pid=$!
  ACTIVE_CHILD_PID="$_git_pid"  # см. cleanup_work — гонка Ctrl+C/rm-rf, найдена 27.08.2026
  while kill -0 "$_git_pid" 2>/dev/null; do
    # 🔴 Найдено владельцем 27.08.2026: если `$_clone_log` пропал (папка `$WORK`
    # исчезла посреди клона — тот же класс проблемы среды, что и WORK-guard выше),
    # `< "$_clone_log"` на отсутствующий файл кричит "no such file or directory"
    # ПРЯМО В ТЕРМИНАЛ — проверено эмпирически: `2>/dev/null` эту ошибку НЕ гасит
    # ни в bash, ни в zsh, потому что это ошибка ОТКРЫТИЯ редиректа самим шеллом,
    # а не ошибка команды, чей stderr редиректится. Раньше цикл слепо читал файл
    # каждую секунду и печатал одну и ту же ошибку десятками раз подряд, пока жив
    # PID клона. Проверяем существование перед чтением — тихо пропускаем итерацию,
    # а не спамим нечитаемым мусором.
    if [ -f "$_clone_log" ]; then
      _last="$(tr '\r' '\n' < "$_clone_log" 2>/dev/null | LC_ALL=C grep -E '[0-9]+%' | tail -1)"
      [ -n "${_last:-}" ] && printf '\r    %-70s' "$(printf '%s' "$_last" | cut -c1-70)"
    fi
    sleep 1
  done
  _clone_rc=0; wait "$_git_pid" || _clone_rc=$?
  ACTIVE_CHILD_PID=""
  printf '\r%-76s\r' " "
  _clone_err="$(tr '\r' '\n' < "$_clone_log" 2>/dev/null | tail -20)"
  if [ "$_clone_rc" -eq 0 ]; then
    _sz="$(du -sh "$CLONE" 2>/dev/null | cut -f1)"
    grn "  ✓ склонировано${_sz:+ ($_sz)}"
  else
    REPO_EXISTS=0
    [ "$REPO_STATE" -eq 0 ] && REPO_EXISTS=1
    if [ "$REPO_EXISTS" = "1" ]; then
      # 🔴 Найдено владельцем 27.08.2026: если $WORK пропала ПОСРЕДИ этого самого
      # клона (символ — «Unable to read current working directory» в _clone_err),
      # retry() ниже раньше слепо бил 5 попыток в ту же несуществующую папку —
      # гарантированно одинаковый провал, ~2 минуты чистого ожидания впустую на
      # одной репе. Останавливаемся сразу, а не жжём ретраи там, где чинить нечего.
      if ! [ -d "$WORK" ]; then
        die "рабочая папка $WORK исчезла посреди клона $REPO —
     среда нестабильна (VPN/диск/файловая система), retry() это не почини́т.
     Перезапусти скрипт заново."
      fi
      ylw "  репа существует — похоже на сетевой сбой, повторяю"
      printf '%s\n' "$_clone_err" | tail -3 | sed 's/^/      /'
      retry "git clone" git -c "http.lowSpeedLimit=$CLONE_LOW_SPEED_LIMIT" \
        -c "http.lowSpeedTime=$CLONE_LOW_SPEED_TIME" clone "$URL" "$CLONE" 2>/dev/null \
        || { red "  клон не удался — пропускаю репу"; note "$REPO|—|клон|✗ сеть"; continue; }
    else
      ylw "  репы нет / пустая — инициализирую локально"
      mkdir -p "$CLONE" && cd "$CLONE" || { red "mkdir клона"; continue; }
      git init -q -b "$BRANCH"; git remote add origin "$URL"
    fi
  fi
  cd "$CLONE" || continue
  git checkout -B "$BRANCH" >/dev/null 2>&1 || true
  git config user.name  >/dev/null 2>&1 || git config user.name  "$OWNER"
  git config user.email >/dev/null 2>&1 || git config user.email "$OWNER@users.noreply.github.com"

  TAGS="$(git tag -l 2>/dev/null | tr '\n' ' ')"

  # АУДИТ ДЕРЕВА (fail loud). Класс ошибки, который скрипт чинить НЕ будет: тег стоит,
  # но дерево под ним от другой версии (наследие старых скриптов / PIT-014). Переписать
  # это = переписать историю опубликованного тега — решение только человека.
  for _t in $TAGS; do
    _tv="${_t#v}"
    case "$_tv" in ''|*[!0-9.]*) continue;; esac
    _tf="$(git show "$_t:VERSION" 2>/dev/null | tr -d ' \n')"
    [ -n "$_tf" ] || continue
    if [ "$_tf" != "$_tv" ]; then
      loud "$REPO: тег $_t указывает на дерево с VERSION=$_tf — история тега битая, авто-чинить не буду"
      note "$REPO|$_t|дерево|✗ тег≠дерево (нужно решение)"
    fi
  done
  HIGHEST="$(git tag -l 'v*' 2>/dev/null | sed 's/^v//' | sort -t. -k1,1n -k2,2n -k3,3n | tail -1)"
  [ -n "$HIGHEST" ] && ylw "  старший тег: v$HIGHEST"
  NOTES_DIR="$WORK/notes_$REPO"; mkdir -p "$NOTES_DIR"
  PUBLISHED=""

  # --- 2Z. РЕЖИМ CHLOG_FILL: дописать секции журнала по данным git ---------------
  # Нужен, когда тег и коммит уже на GitHub, а релиза нет из-за отсутствия секции,
  # и локального архива тоже нет. Единственный источник о версии — сам репозиторий.
  if [ "$CHLOG_FILL" = "1" ]; then
    _fill="$(python3 "$CHFILL" "$CLONE" "$REPO" 2>"$WORK/fill_err.txt")"
    if [ -n "$_fill" ]; then
      grn "  ✓ журнал приведён к стандарту: $(printf '%s' "$_fill" | tr '\n' ' ')"
      LC_ALL=C grep -q '^норм:' "$WORK/fill_err.txt" 2>/dev/null && \
        cyn "    разряд дописан в заголовки: $(sed -n 's/^норм://p' "$WORK/fill_err.txt")"
      ( cd "$CLONE" \
        && git add CHANGELOG.md \
        && git commit -q -m "$REPO — CHANGELOG приведён к стандарту по данным git" \
        && git push -q origin "$BRANCH" ) \
        && grn "  ✓ CHANGELOG запушен" \
        || { red "  ✗ CHANGELOG не запушен"; note "$REPO|—|changelog|✗ push"; }
    else
      ylw "  секции CHANGELOG на месте — дописывать нечего"
    fi
    # дальше сразу приводим релизы к стандарту: ради этого режим и запускался
    REPAIR=1
  fi

  # --- 2A. РЕЖИМ REPAIR / ASSETS_ONLY: чиним существующее, новое не публикуем ----
  if [ "$REPAIR" = "1" ] || [ "$ASSETS_ONLY" = "1" ]; then
    # Порядок починки — от СВЕЖИХ к старым, и с `LAST` берём только начало
    # списка. Раньше шли в порядке `git tag -l`, то есть лексикографически:
    # при обрыве на середине чинилось непонятно что.
    _rtags="$(printf '%s\n' $TAGS | grep '^v[0-9]' \
              | sed 's/^v//' | sort -t. -k1,1nr -k2,2nr -k3,3nr | sed 's/^/v/')"
    if [ -n "$LAST" ]; then
      _total="$(printf '%s\n' $_rtags | grep -c . || true)"
      _rtags="$(printf '%s\n' $_rtags | head -n "$LAST")"
      cyn "  LAST=$LAST: чиню последние $LAST из $_total тегов"
    fi
    for TAG in $_rtags; do
      V="${TAG#v}"
      case "$V" in ''|*[!0-9.]*) continue;; esac
      Z="$(awk -F'\t' -v r="$REPO" -v v="$V" '$1==r && $2==v{print $3; exit}' "$INDEX")"
      # PIT-016: код возврата build_notes не проверялся, и провал сборки описания
      # уезжал в заголовок релиза целиком, вместе с цветовыми кодами.
      TITLE="$(build_notes "$CLONE" "$V" "$REPO" "$NOTES_DIR/v$V.md")" || TITLE=""
      TITLE="$(safe_title "$TITLE" "$REPO" "$V")"
      ylw "  → $TAG: $TITLE"
      # $CLONE обязателен шестым аргументом: без него ensure_release не соберёт
      # канонический zip из тега (git archive), и версии, чей архив уже удалён,
      # получат релиз без ассета. Ровно так вышло с portrait-of-taste 3.4.3–3.4.5.
      ensure_release "$REPO" "$V" "$NOTES_DIR/v$V.md" "$TITLE" "$Z" "$CLONE"
    done
    continue
  fi

  # --- 2B. Публикация версий по возрастанию -------------------------------------
  VERLIST="$WORK/vers_$REPO.txt"
  awk -F'\t' -v r="$REPO" '$1==r{print $2}' "$INDEX" | sort -t. -k1,1n -k2,2n -k3,3n > "$VERLIST"
  while IFS= read -r VER; do
    [ -n "$VER" ] || continue
    ZIP="$(awk -F'\t' -v r="$REPO" -v v="$VER" '$1==r && $2==v{print $3; exit}' "$INDEX")"
    case " $TAGS " in *" v$VER "*) ylw "→ v$VER: тег есть, пропускаю"; continue;; esac
    if [ -n "$HIGHEST" ] && [ "$BACKFILL" != "1" ]; then
      NEWEST="$(printf '%s\n%s\n' "$HIGHEST" "$VER" | sort -t. -k1,1n -k2,2n -k3,3n | tail -1)"
      if [ "$NEWEST" != "$VER" ]; then
        ylw "→ v$VER: ниже v$HIGHEST — пропускаю (BACKFILL=1 чтобы залить)"; continue
      fi
    fi

    echo ""; ylw "→ v$VER  ($(basename "$ZIP"))"

    # ─── ПРЕДОХРАНИТЕЛЬ ДОСТАВКИ (v4.25.0, `74-planner-bridge.md` §4б) ───────────
    # 🔴 Публикация СНОСИТ рабочее дерево клона и кладёт содержимое архива.
    # Архив собран из ЛОКАЛЬНОГО дерева, а файл доставки `INBOX-FROM-*` лежит
    # только на GitHub — мост кладёт его туда напрямую. Значит порядок
    # «доставка → деплой → вахта» стирал задачу БЕЗ ЕДИНОГО СИГНАЛА:
    # в репе просто нет файла, и вахта не отличает «не доставляли»
    # от «доставили и стёрли».
    #
    # Это не грязь в выводе, а молча пропущенный шаг — тот же класс, что PIT-014.
    #
    # Отказ ставится ДО распаковки: не начатая публикация чинится повторным
    # запуском, а начатая и оборванная оставляет дерево в промежуточном виде.
    # 🔴 ПУСТАЯ РЕПА — НЕ ДОСТАВКА. Отказ найден владельцем 04.09.2026 на живом
    # прогоне: `audiobook-forge` только что создана, дерева нет, и GitHub на
    # `contents` отвечает 404 с телом `{"message":"This repository is empty."}`.
    # Прежняя строка глотала код возврата (`|| true`) и подставляла это тело
    # в `_inbox` как «имя доставки» — публикация ПЕРВОЙ версии новой репы
    # становилась невозможной навсегда.
    #
    # Два предохранителя вместо одного:
    #   · код возврата `gh api` проверяется ОТДЕЛЬНО, а не сливается в строку;
    #   · фильтр отвечает только на МАССИВ (`if type=="array"`), иначе пусто —
    #     объект-ошибка не может притвориться списком файлов.
    # Плюс третий, на выходе: имя обязано выглядеть именем (`^INBOX-FROM-`).
    #
    # Тесты этого не поймали, потому что стаб `gh` не знал команды `api`
    # и отвечал на неё успехом с пустым выводом — «нет такого случая»
    # неотличимо от «случай проверен» (`69` §4м). Стаб научен отвечать.
    if [ "$HAVE_GH" -eq 1 ]; then
      _inbox=""
      if _raw="$(gh api "repos/$OWNER/$REPO/contents" --jq \
            'if type=="array" then (.[] | select(.name | startswith("INBOX-FROM-")) | .name) else empty end' \
            2>/dev/null)"; then
        _inbox="$(printf '%s\n' "$_raw" | grep '^INBOX-FROM-' || true)"
      fi
      if [ -n "$_inbox" ]; then
        # 🔴 Смотрим В АРХИВ, а не в дерево: дерева ещё нет — распаковка ниже.
        # Проверять надо ровно то, что ляжет в репу, а ляжет содержимое архива.
        # Первая редакция ссылалась на `$SRC_TREE`, которой в этой точке
        # не существует, — поймано `bash -n` не было (переменная синтаксически
        # верна), поймано `grep`ом по имени. Проверка правки ЗАПУСКОМ,
        # а не перечитыванием (`/auto` §2г п.3).
        _names="$(unzip -Z1 "$ZIP" 2>/dev/null || true)"
        _missing=""
        for _f in $_inbox; do
          printf '%s\n' "$_names" | grep -qE "(^|/)$_f\$" || _missing="$_missing $_f"
        done
        if [ -n "$_missing" ]; then
          red "  🔴 ОТКАЗ: на GitHub есть доставка, которой нет локально:$_missing"
          red "     Публикация снесла бы её молча — задача исчезла бы без следа."
          red "     Разобрать доставку ДО публикации (74-planner-bridge.md §4б),"
          red "     затем повторить прогон."
          note "$REPO|v$VER|доставка|✗ INBOX только на GitHub:$_missing"
          continue
        fi
      fi
    fi
    # ─────────────────────────────────────────────────────────────────────────────

    SRCDIR="$WORK/unpack_${REPO}_$VER"; rm -rf "$SRCDIR"; mkdir -p "$SRCDIR"
    unzip -oq "$ZIP" -d "$SRCDIR" </dev/null || { red "  unzip не удался — пропускаю"; note "$REPO|v$VER|распаковка|✗ битый архив"; continue; }

    # PIT-015 (главная причина «архив не пушится»): macOS кладёт рядом с обёрткой
    # __MACOSX/ и .DS_Store. Тогда в корне НЕ один объект, разворот обёртки не срабатывает,
    # и в репу уезжает дерево, вложенное в папку-обёртку. Поэтому мусор сносим СНАЧАЛА.
    find "$SRCDIR" -name '__MACOSX' -type d -exec rm -rf {} + 2>/dev/null || true
    find "$SRCDIR" -name '.DS_Store' -delete 2>/dev/null || true
    find "$SRCDIR" -name '._*' -delete 2>/dev/null || true

    SRC="$SRCDIR"                                            # PIT-007: разворот обёртки
    _depth=0
    while [ ! -f "$SRC/README.md" ] && [ "$_depth" -lt 3 ]; do
      n_all=$(ls -A "$SRC" | wc -l | tr -d ' ')
      n_dir=$(find "$SRC" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
      [ "$n_all" = "1" ] && [ "$n_dir" = "1" ] || break
      SRC="$SRC/$(ls -A "$SRC")"; _depth=$((_depth+1))
    done
    [ "$_depth" -gt 0 ] && plain "  обёртка развёрнута (уровней: $_depth)"

    # маркеры корня — ДО любого деструктива
    if [ ! -f "$SRC/README.md" ]; then
      red "  корень не опознан (нет README.md) — пропускаю"; note "$REPO|v$VER|проверка|✗ нет README"; continue
    fi
    # .repo-id — принадлежность архива. Если файл есть и указывает на ДРУГУЮ репу,
    # это стоп: значит архив уехал бы не туда (переименовали, ошиблись в REPO_MAP).
    # Файла нет — пока только напоминание: старые репы его ещё не завели.
    _aid="$(find_repo_id "$SRC" || true)"
    if [ -n "$_aid" ]; then
      if [ "$_aid" != "$REPO" ]; then
        red "  ✗ .repo-id внутри архива указывает на «${_aid}», а публикуем в «${REPO}» — СТОП"
        loud "$REPO v$VER: .repo-id=$_aid ≠ целевая репа. Архив уехал бы не туда."
        note "$REPO|v$VER|проверка|✗ .repo-id не совпал"; continue
      fi
    else
      ylw "    нет .repo-id — принадлежность архива не подтверждена (см. §48)"
      note "$REPO|v$VER|проверка|~ нет .repo-id"
    fi
    if false; then :
    fi
    SRC_N=$(find "$SRC" -type f | wc -l | tr -d ' ')
    if [ "$SRC_N" -lt "$MIN_FILES" ]; then
      red "  файлов $SRC_N (< $MIN_FILES) — не похоже на репу, пропускаю"; note "$REPO|v$VER|проверка|✗ мало файлов"; continue
    fi
    if [ -f "$SRC/VERSION" ]; then
      VF="$(tr -d ' \n' < "$SRC/VERSION")"
      if [ "$VF" != "$VER" ]; then
        red "  VERSION в дереве = $VF, а архив v$VER — пропускаю"; note "$REPO|v$VER|проверка|✗ VERSION≠имени"; continue
      fi
    fi

    # PIT-018: точка входа в вахту — WATCHLOG §0. Она протухала четыре раза подряд:
    # версия в шапке поднималась, тело §0 описывало состояние трёх версий назад,
    # и следующая вахта начинала работу по неверной картине. Ручная дисциплина здесь
    # не работает по той же причине, что и с картой, — поэтому проверка, а не напоминание.
    if [ -f "$SRC/WATCHLOG.md" ]; then
      # 🔴 29.08.2026: корневой WATCHLOG.md может быть УКАЗАТЕЛЕМ на настоящий
      # журнал в docs/ — у `personal-finance-dss` своя продуктовая конвенция
      # (вся документация в `docs/`), а файл в корне стоит ради guard'а
      # доставки (`74-planner-bridge.md` §4а). Указатель состояния не хранит
      # (`revision_check.py` это теперь проверяет), поэтому строку «Версия»
      # надо искать в том файле, на который он показывает.
      # Признак указателя тот же, что в гейте и `bump_repo.py`: файл короткий
      # И несёт ссылку на одноимённый файл в подкаталоге.
      WLF="$SRC/WATCHLOG.md"
      if [ "$(wc -l < "$WLF")" -le 40 ]; then
        PTR="$(sed -n 's|.*(\([^)]*WATCHLOG\.md\)).*|\1|p' "$WLF" | head -1)"
        if [ -n "$PTR" ] && [ -f "$SRC/$PTR" ]; then
          WLF="$SRC/$PTR"
        fi
      fi
      WLV="$(sed -n 's/.*\*\*Версия:\*\*[[:space:]]*\([0-9][0-9.]*\).*/\1/p' "$WLF" | head -1)"
      if [ -z "$WLV" ]; then
        loud "$REPO v$VER: в WATCHLOG.md нет строки «**Версия:** X.Y.Z» — §0 не читается машиной"
        note "$REPO|v$VER|watchlog|⚠ §0 без версии"
      elif [ "$WLV" != "$VER" ]; then
        loud "$REPO v$VER: WATCHLOG §0 стоит на $WLV — точка входа в вахту отстала. Обнови §0 и перезапусти"
        note "$REPO|v$VER|watchlog|✗ §0=$WLV ≠ $VER"
        red "  WATCHLOG §0 = $WLV, публикуется $VER — пропускаю"
        continue
      else
        grn "  ✓ WATCHLOG §0 на версии $VER"
      fi
    fi

    TITLE="$(build_notes "$SRC" "$VER" "$REPO" "$NOTES_DIR/v$VER.md")" || TITLE=""
    TITLE="$(safe_title "$TITLE" "$REPO" "$VER")"
    cyn "  заголовок релиза: $TITLE"

    find . -mindepth 1 -maxdepth 1 -not -name '.git' -exec rm -rf {} +   # PIT-004
    cp -a "$SRC/." .
    find . -name '.DS_Store' -delete 2>/dev/null || true
    find . -name '__MACOSX' -type d -exec rm -rf {} + 2>/dev/null || true

    # PIT-014: cp -a сохраняет mtime архива. У архивов одной серии mtime совпадает,
    # а VERSION ещё и одного размера — git по паре size+mtime решает «файл не менялся»
    # и НЕ хэширует содержимое. Итог: дерево новое, индекс пуст, тег висит на старом
    # дереве. Поэтому индекс пересобираем принудительно, а не доверяем stat-кэшу.
    git rm -r --cached -q . >/dev/null 2>&1 || true
    git add -A -f                                                        # PIT-006
    if git diff --cached --quiet && [ -n "$(git tag -l)" ]; then
      ylw "  дерево не изменилось — ставлю только тег"
    else
      # Сообщение коммита по §42: «<repo> vX.Y.Z — <тезис>». «tree sync» ничего
      # не говорит о содержании версии — в истории git такой коммит бесполезен.
      CMSG="$(build_notes "$SRC" "$VER" "$REPO" "$NOTES_DIR/v$VER.md" 2>/dev/null)" || CMSG=""
      [ -n "$CMSG" ] || CMSG="$REPO v$VER"
      git commit -q -m "$CMSG" || { red "  commit не удался"; continue; }
      TREE_N=$(find . -path ./.git -prune -o -type f -print | wc -l | tr -d ' ')
      GIT_N=$(git ls-tree -r --name-only HEAD | wc -l | tr -d ' ')
      if [ "$GIT_N" != "$TREE_N" ]; then
        red "  в коммите $GIT_N файлов, в дереве $TREE_N (PIT-006/007) — стоп по этой репе"
        note "$REPO|v$VER|коммит|✗ расхождение файлов"; break
      fi
      grn "  ✓ коммит: $GIT_N файлов"
    fi
    git tag -a "v$VER" -m "$TITLE" || { red "  tag не удался"; continue; }
    PUBLISHED="$PUBLISHED $VER"
    note "$REPO|v$VER|дерево|закоммичено+тег"
    rm -rf "$SRCDIR"
  done < "$VERLIST"

  # --- 2C. Push. Даже если релизы упадут — дерево и теги уже на месте ------------
  if [ -n "$PUBLISHED" ]; then
    # 🔴 Проверка размеров ДО push. Дешевле узнать о лимите здесь, чем после
    # заливки 549 МБ и отказа `pre-receive` (22.08.2026, edu-base).
    _big="$(find . -type f -size +100M -not -path './.git/*' 2>/dev/null | head -5)"
    if [ -n "$_big" ]; then
      red "  ✗ файлы тяжелее 100 МБ — GitHub отклонит push (GH001):"
      printf '%s\n' "$_big" | sed 's|^\./|      |'
      red "  Свернуть в служебки: python3 base-repo/07-media-to-text-lab/tools/heavy_media_to_note.py --repo $REPO --apply"
      note "$REPO|$VER|push|ОТКАЗ: файлы >100МБ"
      continue
    fi
    echo ""; ylw "→ пушу ветку и теги"
    pushb(){ git -c "http.lowSpeedLimit=$CLONE_LOW_SPEED_LIMIT" \
      -c "http.lowSpeedTime=$CLONE_LOW_SPEED_TIME" push -u origin "$BRANCH"; }
    pusht(){ git -c "http.lowSpeedLimit=$CLONE_LOW_SPEED_LIMIT" \
      -c "http.lowSpeedTime=$CLONE_LOW_SPEED_TIME" push origin --tags; }
    if retry "git push branch" pushb && retry "git push tags" pusht; then
      grn "✓ запушено"
    else
      red "✗ push не удался (проверь токен/сеть) — репа пропущена, локальная работа в $WORK"
      note "$REPO|—|push|✗ не удался"; continue
    fi
  else
    ylw "→ новых версий нет"
  fi

  # --- 2D. Релизы: и на новые версии, и починка старых (главный прежний баг) -----
  if [ "$HAVE_GH" -eq 1 ]; then
    echo ""; ylw "→ релизы"
    # РЕЖИМЫ. По умолчанию трогаем только опубликованные в этом прогоне версии —
    # быстро. Полная ревизия всех релизов репы — по AUDIT=1 (долго, но
    # приводит к стандарту всю историю).
    if [ "$AUDIT" = "1" ] || [ "$REPAIR" = "1" ] || [ "$FORCE" = "1" ]; then
      ALLTAGS="$(git tag -l 'v*' | sed 's/^v//' | sort -t. -k1,1n -k2,2n -k3,3n | tr '\n' ' ')"
    else
      ALLTAGS="$PUBLISHED"
    fi
    NOREL=""; ASSET_OK=""
    for V in $ALLTAGS; do
      Z="$(awk -F'\t' -v r="$REPO" -v v="$V" '$1==r && $2==v{print $3; exit}' "$INDEX")"
      release_state "$REPO" "$V"; _st=$?
      if [ "$_st" -eq 2 ]; then
        red "    ✗ v$V: не смог узнать состояние релиза — пропускаю"
        [ -n "$RELEASE_STATE_ERR" ] && plain "        ответ gh: $RELEASE_STATE_ERR"
        cyn "        починка: REPAIR=1 zsh ~/Downloads/deploy.sh"
        note "$REPO|v$V|релиз|✗ $RELEASE_STATE_ERR"
        continue
      fi
      if [ "$_st" -eq 1 ]; then
        # TITLE считаем ЗАНОВО для каждой версии. Раньше он переиспользовался
        # с прошлой итерации, если notes-файл уже был создан на этапе публикации,
        # и младшая версия получала заголовок старшей.
        TITLE="$(build_notes "$CLONE" "$V" "$REPO" "$NOTES_DIR/v$V.md")" || { NOREL="$NOREL v$V"; continue; }
        [ -s "$NOTES_DIR/v$V.md" ] || { NOREL="$NOREL v$V"; continue; }
        [ -n "$TITLE" ] || TITLE="$REPO v$V"
        ensure_release "$REPO" "$V" "$NOTES_DIR/v$V.md" "$TITLE" "$Z" "$CLONE"
      else
        # Существующий релиз проверяется ВСЕГДА: сверка с CHANGELOG, заголовок, ассет.
        # Ничего не ломаем — правится только то, что расходится со стандартом.
        if T2="$(build_notes "$CLONE" "$V" "$REPO" "$NOTES_DIR/v$V.md" 2>/dev/null)"; then
          ensure_release "$REPO" "$V" "$NOTES_DIR/v$V.md" "$T2" "$Z" "$CLONE"
        else
          # секции нет — описание не трогаем, но ассет доложить обязаны
          ensure_release "$REPO" "$V" "$NOTES_DIR/v$V.md" "" "$Z" "$CLONE"
        fi
      fi
    done
    [ -n "$NOREL" ] && ylw "  без релиза (нет секции в CHANGELOG):$NOREL"
  fi
  grn "ГОТОВО: $REPO —$([ -n "$PUBLISHED" ] && echo "$PUBLISHED" || echo ' актуальна')"
done < "$REPOLIST"

# --- ШАГ 3.0. СВЕРКА КАРТЫ: идёт ВСЕГДА, а не только при создании новой репы -----
# За месяц карта отстала на восемь реп, потому что сверка была привязана к событию
# "создали репу в этом прогоне". Репу можно завести и руками через gh, и тогда
# она в карту не попадёт никогда. Правило (протокол 07): репа без строки в карте
# считается незаведённой. Проверяем по факту — списком с GitHub.
if [ "$HAVE_GH" -eq 1 ] && [ "$DRY" != "1" ]; then
  # 🔴 Каждый шаг сверки отчитывается ЗА СЕБЯ (`PIT-137`). Прежде здесь стоял общий
  # `2>/dev/null || :`, и любой отказ — не склонировалось, файла нет, python упал —
  # выглядел одинаково: «сверку карты выполнить не удалось (python3/парсинг)».
  # Сообщение называло виновником python, который при живом файле отрабатывает.
  _mapfile="$WORK/_mapcheck.md"
  _mapstage="клон base-repo"
  if git clone -q --depth 1 "$REMOTE_BASE/base-repo.git" "$WORK/_mapchk" 2>/dev/null \
     && [ -f "$WORK/_mapchk/repos-map.md" ]; then
    _mapstage="копирование repos-map.md"
    cp "$WORK/_mapchk/repos-map.md" "$_mapfile"
    _mapstage="разбор карты"
    gh repo list "$OWNER" --limit 300 --json name,isArchived \
       --jq '.[] | select(.isArchived==false) | .name' > "$WORK/_ghrepos.txt" 2>/dev/null || : > "$WORK/_ghrepos.txt"

    # PIT-017: прежняя сверка искала `имя` где угодно в файле и потому проходила
    # на любом упоминании — ссылка в оглавлении, строчка в чужом абзаце. Витринные
    # зеркала vk-graph / health-report-generator / bron-kerbosch были «в карте»
    # ровно так: упомянуты, своей секции нет. Считается только оформленная секция
    # `## \`имя\`` — то есть зона ответственности и границы с соседями.
    python3 - "$_mapfile" "$WORK/_ghrepos.txt" > "$WORK/_mapverdict.txt" 2>/dev/null <<'PYMAP' || :
import re, sys
mp, gl = sys.argv[1], sys.argv[2]
text = open(mp, encoding="utf-8", errors="replace").read()
# Заголовок записи выглядит как «## 🧩 `base-repo`  ·  🌐 публичная»: между решёткой
# и именем стоит эмодзи, после имени — пометки. Выражение обязано это допускать,
# иначе проверка объявит LOOSE все 54 записи разом и станет бесполезной.
entries = set(re.findall(r"(?m)^#{2,3}\s+.*?`([A-Za-z0-9._-]+)`", text))
mentions = set(re.findall(r"`([A-Za-z0-9._-]+)`", text))
live = [l.strip() for l in open(gl, encoding="utf-8") if l.strip()]
declared = re.search(r"(\d+)\s*заведено", text)
missing  = [r for r in live if r not in mentions]
loose    = [r for r in live if r in mentions and r not in entries]
stale    = [r for r in sorted(entries) if r not in live]
if missing: print("MISSING " + " ".join(sorted(missing)))
if loose:   print("LOOSE "   + " ".join(sorted(loose)))
if stale:   print("STALE "   + " ".join(stale))
if declared and int(declared.group(1)) != len(entries):
    print(f"COUNT в шапке карты {declared.group(1)}, оформленных секций {len(entries)}")
if not (missing or loose or stale):
    print(f"OK секций {len(entries)}, реп на GitHub {len(live)}")
PYMAP

    _verdict="$(cat "$WORK/_mapverdict.txt" 2>/dev/null || true)"
    _mapclean=1
    while IFS= read -r _line; do
      case "$_line" in
        MISSING*) loud "repos-map: нет в карте вовсе —${_line#MISSING}. Шаг 3 добавит строку-заглушку автоматически — от тебя нужно только дописать содержательное описание зоны ответственности (протокол 07)"; _mapclean=0 ;;
        LOOSE*)   loud "repos-map: упомянуты, но своей секции нет —${_line#LOOSE}. Упоминание не заменяет описания зоны и границ (протокол 20)"; _mapclean=0 ;;
        STALE*)   loud "repos-map: секция есть, репы на GitHub нет —${_line#STALE}. Вычисти строку либо верни репу"; _mapclean=0 ;;
        COUNT*)   loud "repos-map: ${_line#COUNT }"; _mapclean=0 ;;
        OK*)      grn "✓ repos-map сверена со списком GitHub — ${_line#OK }" ;;
      esac
    done <<EOF
$_verdict
EOF
    [ -n "$_verdict" ] || ylw "  сверку карты выполнить не удалось на шаге: $_mapstage — проверь вручную"
  fi
fi

# --- ШАГ 3. repos-map: регистрируем новые репы ------------------------------------
if [ -n "$NEW_REPOS" ]; then
  echo ""; bld "── Шаг 3. Новые репы → repos-map"
  MAP=""
  # ВАЖНО: только ПОСТОЯННЫЕ клоны. $WORK/base-repo сюда не годится — он удаляется
  # в конце прогона, и правка карты исчезнет вместе с ним (баг, пойманный на боевом тесте).
  for cand in "${BASE_REPO:-}" "$DIR/base-repo" "./base-repo" "$HOME/base-repo" \
              "$HOME/repos/base-repo" "$HOME/Documents/base-repo" "$HOME/Documents/GitHub/base-repo"; do
    [ -n "$cand" ] && [ -f "$cand/repos-map.md" ] && { MAP="$(cd "$cand" && pwd)"; break; }
  done
  case "$MAP" in "$WORK"*) MAP="";; esac
  TODAY="$(date +%Y-%m-%d)"
  MAP_REGISTERED=""   # что реально попало в карту этим прогоном (v4.17.1)

  # Локального клона нет — берём base-repo с GitHub сами. Пользователь не должен
  # ничего задавать руками: одна команда должна делать всё до конца.
  MAP_AUTO=0
  if [ -z "$MAP" ] && [ "$DRY" != "1" ]; then
    MAPCLONE="$WORK/_map/base-repo"
    mkdir -p "$WORK/_map"
    # одна попытка, без retry: если base-repo нет или сети нет — не висим, а идём в фолбэк
    if git clone -q --depth 1 "$REMOTE_BASE/base-repo.git" "$MAPCLONE" 2>/dev/null \
       && [ -f "$MAPCLONE/repos-map.md" ]; then
      MAP="$MAPCLONE"; MAP_AUTO=1
      plain "  base-repo склонирована с GitHub для обновления карты"
    fi
  fi
  if [ -n "$MAP" ]; then
    for R in $NEW_REPOS; do
      if grep -q "^## .*\`$R\`" "$MAP/repos-map.md" 2>/dev/null; then
        ylw "  $R — уже в карте"; continue
      fi
      python3 - "$MAP/repos-map.md" "$R" "$TODAY" <<'PYEOF'
import sys, re
from pathlib import Path
path, repo, today = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
text = path.read_text(encoding="utf-8")
entry = (f"\n## 🆕 `{repo}`\n**⚠️ НЕ ОПИСАНА.** Репа заведена автоматически деплойером {today}. "
         f"Опиши зону ответственности и убери этот маркер.\n")
marker = "\n---\n\n# 📐 Стандарт репозитория"
text = text.replace(marker, entry + marker, 1) if marker in text else text + entry
text = re.sub(r"(\*\*Актуальность:\*\*\s*)\d{4}-\d{2}-\d{2}", r"\g<1>" + today, text)
path.write_text(text, encoding="utf-8")
print(f"  + {repo} добавлена в repos-map.md")
PYEOF
      CL="$MAP/repos-map-CHANGELOG.md"
      [ -f "$CL" ] && printf '\n## %s — авто\n- `%s` — репа создана деплойером, добавлена в карту как **не описанная**.\n' \
        "$TODAY" "$R" >> "$CL"
      note "$R|—|repos-map|добавлена (требует описания)"
      MAP_REGISTERED="$MAP_REGISTERED $R"
    done
    # Вердикт сверки собран ДО этого шага — снимаем то, что здесь и починили.
    map_resolve "$MAP_REGISTERED"
    if [ "$MAP_AUTO" = "1" ]; then
      # Сначала СОСТОЯНИЕ дерева, потом действие. Раньше проверялся код возврата
      # цепочки add && commit && push: когда все новые репы уже были в карте,
      # commit падал с "nothing to commit", цепочка рвалась, и скрипт печатал
      # "push не прошёл" — то есть объявлял успех провалом и мусорил копией
      # в ~/Downloads. Успех и отсутствие работы это разные вещи, и путать их нельзя.
      if [ -z "$(cd "$MAP" && git status --porcelain 2>/dev/null)" ]; then
        grn "✓ repos-map уже актуальна — правок не требуется"
      elif ! ( cd "$MAP" && git add -A && \
               git commit -q -m "repos-map: авторегистрация новых реп ($TODAY)" ); then
        cp "$MAP/repos-map.md" "$HOME/Downloads/repos-map-updated.md" 2>/dev/null
        red "  ✗ карта правлена, но коммит не удался — копия: ~/Downloads/repos-map-updated.md"
        note "repos-map|—|карта|✗ коммит"
      elif ( cd "$MAP" && git push -q origin HEAD 2>/dev/null ); then
        grn "✓ repos-map обновлена и запушена в base-repo — опиши новые репы позже"
      else
        cp "$MAP/repos-map.md" "$HOME/Downloads/repos-map-updated.md" 2>/dev/null
        ylw "  карта закоммичена, но push не прошёл — копия: ~/Downloads/repos-map-updated.md"
        note "repos-map|—|карта|✗ push"
      fi
    else
      grn "✓ repos-map обновлена: $MAP/repos-map.md — опиши новые репы и закоммить"
    fi
  else
    ADD="$HOME/Downloads/repos-map-additions.md"
    ylw "  base-repo недоступна (нет сети или репы) — карту обновлю текстом."
    ylw "  Чтобы ничего не потерялось, кладу его в: $ADD"
    for R in $NEW_REPOS; do
      printf '\n## 🆕 `%s`\n**⚠️ НЕ ОПИСАНА.** Заведена автоматически деплойером %s. Опиши зону и убери маркер.\n' \
        "$R" "$TODAY" | tee -a "$ADD"
      note "$R|—|repos-map|⚠ вставить вручную из repos-map-additions.md"
    done
    loud "repos-map не обновлена автоматически — перенеси блоки из $ADD"
  fi
fi

# --- ШАГ 4. Сводка ---------------------------------------------------------------
echo ""; bld "── Итог прогона"
if [ -n "$SUMMARY" ]; then
  printf '%s\n' "$SUMMARY" | awk -F'|' 'NF==4{printf "  %-24s %-10s %-14s %s\n",$1,$2,$3,$4}'
else
  grn "  изменений не потребовалось — всё уже по стандарту"
fi
if [ -n "$LOUD" ]; then
  echo ""; printf '%s%s── ТРЕБУЕТ ТВОЕГО РЕШЕНИЯ (скрипт намеренно НЕ трогал)%s\n' "$C_BLD" "$C_MAG" "$C_OFF"
  printf '%s\n' "$LOUD" | sed '/^$/d'
  echo ""; ylw "  Это не сбой прогона: остальное опубликовано. Разбери эти пункты руками."
fi
# --- ШАГ 3.5. Автоудаление опубликованных архивов --------------------------------
# Отдельным проходом по ВСЕМ архивам папки, а не только по опубликованным в этом
# прогоне: архив мог уехать на GitHub раньше, и его всё равно надо убрать с диска.
if [ "$DELETE_AFTER" = "1" ] && [ "$HAVE_GH" -eq 1 ]; then
  echo ""; bld "── Убираю локальные копии того, что полностью на GitHub"
  _del=0; _kept=""
  while IFS="$(printf '\t')" read -r r v z; do
    [ -n "$r" ] && [ -f "$z" ] || continue
    _m="$(missing_parts "$r" "$v")"
    if [ -z "$_m" ]; then
      rm -f "$z" && { grn "  − $(basename "$z")"; note "$r|v$v|архив|удалён локально"; _del=$((_del+1)); }
    else
      _kept="$_kept
  $(basename "$z") — не хватает:$_m"
    fi
  done < "$INDEX"
  MIR_DEL=0; cleanup_mirrors; _del=$((_del + MIR_DEL))
  [ "$_del" -gt 0 ] && grn "  удалено: $_del" || plain "  удалять нечего"
  if [ -n "$_kept" ]; then
    echo ""; ylw "  оставлены (на GitHub не всё):"
    printf '%s\n' "$_kept" | sed '/^$/d'
    # Диагноз без команды починки — половина работы. По умолчанию релизы делаются
    # только для версий ЭТОГО прогона; тег, уехавший без релиза, сам не починится
    # никогда, и повторный запуск честно скажет «новых версий нет». Пока команда
    # не названа здесь, владелец видит проблему и не видит выхода.
    case "$_kept" in
      *релиз*)
        echo ""
        cyn "  Тег есть, релиза нет — обычным прогоном это не чинится:"
        cyn "  по умолчанию релизы делаются только для версий текущего прогона."
        bld "      REPAIR=1 zsh ~/Downloads/deploy.sh"
        cyn "  (пройдёт по ВСЕМ тегам репы и до-создаст недостающие релизы с ассетами)"
        ;;
    esac
  fi
fi

# 🔴 Лог кладётся В РАБОЧУЮ ПАПКУ, а не жёстко в `~/Downloads` (v4.24.0).
# Прежде он всегда уезжал в `Downloads`, даже когда прогон шёл с другой
# папкой: `zsh deploy.sh ~/Desktop/archives` писал лог не туда, где работал.
# Лог относится к прогону — значит лежит там же, где его артефакты.
printf '%s\n' "$SUMMARY" > "$DIR/deploy_last_run.log"
# Владельцу не нужно помнить про режим — говорим сами, каждый раз.
echo ""
if [ "$DELETE_AFTER" != "1" ]; then
cyn "Архивы не удалялись (KEEP_ARCHIVES=1). Посмотреть, что уже можно убрать —"
cyn "  VERIFY=1 zsh $0"
fi
echo ""; cyn "лог: $DIR/deploy_last_run.log"

rm -f "$INDEX" "$REPOLIST" "$PARSER"
grn "✓ все репозитории обработаны"
