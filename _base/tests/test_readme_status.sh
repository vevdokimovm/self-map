#!/usr/bin/env bash
# =============================================================================
# test_readme_status.sh — регрессионный набор для scripts/readme_status_gate.py.
#
# Гоняет гейт на одноразовых репах-песочницах: настоящий git, настоящие коммиты,
# никакой сети и никаких реальных реп. Проверяется не «скрипт запустился»,
# а что он ЛОВИТ каждый способ оставить README несвежим.
#
# ЗАПУСК:  bash tests/test_readme_status.sh      (из корня base-repo)
# Код возврата 0 — всё зелено; 1 — есть падения.
# =============================================================================
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
GATE="${GATE:-$HERE/../scripts/readme_status_gate.py}"
[ -f "$GATE" ] || { echo "не найден гейт: $GATE"; exit 1; }

PASS=0; FAIL=0; CURRENT=""
ok(){   printf '  \033[32m✓\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
bad(){  printf '  \033[31m✗ %s\033[0m\n' "$1"; [ -n "${2:-}" ] && printf '      %s\n' "$2"; FAIL=$((FAIL+1)); }
case_(){ CURRENT="$2"; printf '\n\033[1m[%s] %s\033[0m\n' "$1" "$2"; }
assert_rc(){ [ "$2" = "$3" ] && ok "$1" || bad "$1" "ждал код $3, получил $2"; }
assert_contains(){ printf '%s' "$2" | grep -qF -- "$3" && ok "$1" || bad "$1" "нет подстроки: $3"; }

SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT

# --- фабрика песочницы --------------------------------------------------------
# Заводит репу с VERSION и README, блок статуса — из переданной строки.
make_repo(){
  local name="$1" version="$2" status_line="$3"
  local repo="$SANDBOX/$name"
  mkdir -p "$repo"
  printf '%s\n' "$version" > "$repo/VERSION"
  {
    printf '# %s\n\n' "$name"
    printf '<!-- STATUS -->\n'
    printf '%s\n' "$status_line"
    printf '<!-- /STATUS -->\n\n'
    printf 'Тело README.\n'
  } > "$repo/README.md"
  printf '%s' "$repo"
}

git_init(){
  local repo="$1"
  git -C "$repo" init -q 2>/dev/null
  git -C "$repo" config user.email "t@t.t"
  git -C "$repo" config user.name "t"
  git -C "$repo" add -A && git -C "$repo" commit -qm init
}

run_gate(){ python3 "$GATE" --root "$1" 2>&1; }
TODAY="$(date +%F)"

# =============================================================================
case_ A1 "блок статуса на месте и совпадает с VERSION → проходит"
REPO="$(make_repo a1 1.4.0 "> **Сейчас:** \`v1.4.0\` · $TODAY · Живое описание текущего состояния.")"
OUT="$(run_gate "$REPO")"; assert_rc "код возврата 0" "$?" "0"

case_ A2 "блока статуса нет вовсе → ловится и показывает шаблон"
REPO="$SANDBOX/a2"; mkdir -p "$REPO"
printf '1.4.0\n' > "$REPO/VERSION"
printf '# a2\n\nREADME без блока статуса.\n' > "$REPO/README.md"
OUT="$(run_gate "$REPO")"; assert_rc "код возврата 1" "$?" "1"
assert_contains "объясняет, чего нет" "$OUT" "нет разбираемого блока статуса"
assert_contains "выдаёт готовый шаблон" "$OUT" "**Сейчас:**"

case_ A3 "блок есть, но строка внутри чужого формата → не считается разобранной"
REPO="$(make_repo a3 1.4.0 "> Версия 1.4.0, вроде всё нормально")"
OUT="$(run_gate "$REPO")"; assert_rc "код возврата 1" "$?" "1"
assert_contains "не принимает вольный формат" "$OUT" "нет разбираемого блока статуса"

case_ B1 "версия в README отстала от VERSION → ловится"
REPO="$(make_repo b1 1.9.0 "> **Сейчас:** \`v1.4.0\` · $TODAY · Обычная рабочая правка репы.")"
OUT="$(run_gate "$REPO")"; assert_rc "код возврата 1" "$?" "1"
assert_contains "называет обе версии" "$OUT" "1.4.0"
assert_contains "и версию из VERSION" "$OUT" "1.9.0"

case_ B2 "нет файла VERSION → гейт говорит, с чем не с чем сверять"
REPO="$SANDBOX/b2"; mkdir -p "$REPO"
printf '# b2\n' > "$REPO/README.md"
OUT="$(run_gate "$REPO")"; assert_rc "код возврата 1" "$?" "1"
assert_contains "называет причину" "$OUT" "нет VERSION"

case_ C1 "дата не ISO → ловится"
REPO="$(make_repo c1 1.4.0 "> **Сейчас:** \`v1.4.0\` · 2026-13-45 · Обычная рабочая правка репы.")"
OUT="$(run_gate "$REPO")"; assert_rc "код возврата 1" "$?" "1"

case_ C2 "дата из будущего → ловится"
FUTURE="$(python3 -c 'import datetime;print(datetime.date.today()+datetime.timedelta(days=30))')"
REPO="$(make_repo c2 1.4.0 "> **Сейчас:** \`v1.4.0\` · $FUTURE · Обычная рабочая правка репы.")"
OUT="$(run_gate "$REPO")"; assert_rc "код возврата 1" "$?" "1"
assert_contains "говорит про будущее" "$OUT" "из будущего"

case_ D1 "описание — плейсхолдер из шаблона → ловится"
REPO="$(make_repo d1 1.4.0 "> **Сейчас:** \`v1.4.0\` · $TODAY · <одна строка: что происходит прямо сейчас>")"
OUT="$(run_gate "$REPO")"; assert_rc "код возврата 1" "$?" "1"
assert_contains "называет плейсхолдер" "$OUT" "плейсхолдер"

case_ D2 "описание из одной точки → ловится (гейт нельзя пройти случайно)"
REPO="$(make_repo d2 1.4.0 "> **Сейчас:** \`v1.4.0\` · $TODAY · .")"
OUT="$(run_gate "$REPO")"; assert_rc "код возврата 1" "$?" "1"
assert_contains "объясняет, чего не хватает" "$OUT" "слишком короткое"

case_ D3 "описание «ок» → ловится"
REPO="$(make_repo d3 1.4.0 "> **Сейчас:** \`v1.4.0\` · $TODAY · ок")"
OUT="$(run_gate "$REPO")"; assert_rc "код возврата 1" "$?" "1"

case_ D4 "описание в четыре слова и 20+ символов → проходит"
REPO="$(make_repo d4 1.4.0 "> **Сейчас:** \`v1.4.0\` · $TODAY · Мост запущен, доска разрезана.")"
(run_gate "$REPO" >/dev/null 2>&1); assert_rc "код возврата 0" "$?" "0"

case_ E1 "VERSION в коммите, README — нет → ловится в режиме --staged"
REPO="$(make_repo e1 1.4.0 "> **Сейчас:** \`v1.4.0\` · $TODAY · Первое описание состояния.")"
git_init "$REPO"
printf '1.5.0\n' > "$REPO/VERSION"
git -C "$REPO" add VERSION
OUT="$(cd "$REPO" && python3 "$GATE" --staged 2>&1)"; RC=$?
assert_rc "код возврата 1" "$RC" "1"
assert_contains "требует README в том же коммите" "$OUT" "не в коммите"

case_ E2 "версию подняли, описание оставили прежним → ловится"
REPO="$(make_repo e2 1.4.0 "> **Сейчас:** \`v1.4.0\` · $TODAY · Неизменный текст описания.")"
git_init "$REPO"
printf '1.5.0\n' > "$REPO/VERSION"
python3 - "$REPO" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1]) / "README.md"
p.write_text(p.read_text().replace("v1.4.0", "v1.5.0"))
PY
git -C "$REPO" add VERSION README.md
OUT="$(cd "$REPO" && python3 "$GATE" --staged 2>&1)"; RC=$?
assert_rc "код возврата 1" "$RC" "1"
assert_contains "называет неизменное описание" "$OUT" "описание в блоке статуса не изменилось"

case_ E3 "версию подняли и описание переписали → проходит"
REPO="$(make_repo e3 1.4.0 "> **Сейчас:** \`v1.4.0\` · $TODAY · Старое описание состояния.")"
git_init "$REPO"
printf '1.5.0\n' > "$REPO/VERSION"
python3 - "$REPO" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1]) / "README.md"
p.write_text(p.read_text()
             .replace("v1.4.0", "v1.5.0")
             .replace("Старое описание состояния.", "Новое описание после разбора."))
PY
git -C "$REPO" add VERSION README.md
(cd "$REPO" && python3 "$GATE" --staged >/dev/null 2>&1); assert_rc "код возврата 0" "$?" "0"

case_ E4 "VERSION не трогали → гейт не мешает обычному коммиту"
REPO="$(make_repo e4 1.4.0 "> **Сейчас:** \`v1.4.0\` · $TODAY · Обычная рабочая правка репы.")"
git_init "$REPO"
printf 'заметка\n' > "$REPO/note.md"
git -C "$REPO" add note.md
(cd "$REPO" && python3 "$GATE" --staged >/dev/null 2>&1); assert_rc "код возврата 0" "$?" "0"

case_ F1 "--fix проставляет версию и дату"
REPO="$(make_repo f1 2.0.0 "> **Сейчас:** \`v1.4.0\` · 2020-01-01 · Ценное описание состояния репы.")"
OUT="$(python3 "$GATE" --root "$REPO" --fix 2>&1)"; assert_rc "код возврата 0" "$?" "0"
assert_contains "новая версия в файле" "$(cat "$REPO/README.md")" "v2.0.0"
assert_contains "сегодняшняя дата в файле" "$(cat "$REPO/README.md")" "$TODAY"

case_ F2 "--fix НЕ трогает описание — ради него гейт и написан"
assert_contains "описание на месте" "$(cat "$REPO/README.md")" "Ценное описание состояния репы."
assert_contains "предупреждает, что описание на человеке" "$OUT" "описание НЕ тронуто"

case_ F3 "после --fix гейт проходит"
(python3 "$GATE" --root "$REPO" >/dev/null 2>&1); assert_rc "код возврата 0" "$?" "0"

# --- зона G: хук целиком, настоящим git ---------------------------------------
# Гейт можно проверить в одиночку, но владельца защищает не гейт, а ХУК. Здесь
# проверяется вся цепочка: core.hooksPath → pre-commit → check_readme_status → гейт.
#
# NB: код возврата берётся у `git commit` напрямую. В конвейере `git commit | tail`
# статус принадлежит tail и всегда 0 — первая редакция этой проверки так и соврала,
# отрапортовав «пропустил» там, где хук на самом деле останавливал коммит.
HOOK="$HERE/../.githooks/pre-commit"
PROBE="$SANDBOX/hook-probe"
mkdir -p "$PROBE/.githooks" "$PROBE/scripts"
cp "$HOOK" "$PROBE/.githooks/pre-commit"; chmod +x "$PROBE/.githooks/pre-commit"
cp "$GATE" "$PROBE/scripts/readme_status_gate.py"
printf '1.0.0\n' > "$PROBE/VERSION"
{
  printf '# probe\n\n<!-- STATUS -->\n'
  printf '> **Сейчас:** `v1.0.0` · %s · Первое живое описание.\n' "$TODAY"
  printf '<!-- /STATUS -->\n'
} > "$PROBE/README.md"
git -C "$PROBE" init -q
git -C "$PROBE" config user.email t@t.t
git -C "$PROBE" config user.name t
git -C "$PROBE" config core.hooksPath .githooks
git -C "$PROBE" add -A && git -C "$PROBE" commit -qm init --no-verify

try_commit(){ # try_commit <имя> <block|pass>
  # Код возврата снимается СРАЗУ. И `local got=...`, и конвейер `| tail` затирают $?
  # своим успехом — на обоих эта проверка уже соврала «пропустил» там, где хук
  # останавливал коммит. Замер обязан стоять вплотную к измеряемой команде.
  git -C "$PROBE" commit -m probe >/dev/null 2>&1
  local rc=$?
  local got="pass"; [ "$rc" -ne 0 ] && got="block"
  [ "$got" = "$2" ] && ok "$1" || bad "$1" "ждал $2, получил $got"
}
bump_readme(){ python3 - "$PROBE" "$1" "$2" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1]) / "README.md"
p.write_text(p.read_text().replace(sys.argv[2], sys.argv[3]))
PY
}

case_ G1 "хук останавливает коммит: VERSION поднят, README не тронут"
printf '1.1.0\n' > "$PROBE/VERSION"; git -C "$PROBE" add VERSION
try_commit "коммит остановлен" block

case_ G2 "хук останавливает коммит: в README поменяли только цифру"
bump_readme "v1.0.0" "v1.1.0"; git -C "$PROBE" add README.md
try_commit "коммит остановлен" block

case_ G3 "хук пропускает: версия поднята и описание переписано"
bump_readme "Первое живое описание." "Новое состояние после разбора."
git -C "$PROBE" add README.md
try_commit "коммит прошёл" pass

case_ G4 "хук молчит на обычном коммите без VERSION"
printf 'note\n' > "$PROBE/note.md"; git -C "$PROBE" add note.md
try_commit "коммит прошёл" pass

# =============================================================================
printf '\n\033[1m── итог ──\033[0m\n'
printf '  пройдено: %s\n  падений:  %s\n\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
