#!/usr/bin/env bash
# =============================================================================
# fix_release_notes.sh — привести УЖЕ ВЫПУЩЕННЫЕ GitHub Release к канону:
#     title = "vX.Y.Z" (только версия)
#     notes = секция CHANGELOG.md ВМЕСТЕ со строкой '## [X.Y.Z] — дата — название'
#
# Зачем: релизы, выпущенные publish.sh до версии с исправленным парсером, могли
# получить описание-фолбэк («Release X.Y.Z») или потерять строку заголовка секции.
# Скрипт правит их задним числом, ничего не пересобирая и не трогая теги/ассеты.
#
# ЗАПУСК (внутри клона репы, macOS/zsh):
#   zsh ./fix_release_notes.sh 1.1.0 1.2.0        # конкретные версии
#   zsh ./fix_release_notes.sh --all              # все теги vX.Y.Z, что есть в CHANGELOG
#
# Идемпотентно: повторный запуск просто перезапишет тем же содержимым.
# =============================================================================

set -u

CHANGELOG_FILE="${CHANGELOG_FILE:-CHANGELOG.md}"
PY="$(command -v python3 || command -v python)"

red(){ printf '\033[31m%s\033[0m\n' "$*"; }
grn(){ printf '\033[32m%s\033[0m\n' "$*"; }
ylw(){ printf '\033[33m%s\033[0m\n' "$*"; }
die(){ red "ОШИБКА: $*"; exit 1; }

command -v gh >/dev/null 2>&1 || die "gh не найден — поставь GitHub CLI или правь релизы вручную"
git rev-parse --git-dir >/dev/null 2>&1 || die "запускать внутри клона репы"
[ -f "$CHANGELOG_FILE" ] || die "нет $CHANGELOG_FILE в текущей папке"
[ -n "$PY" ] || die "python3 не найден"

# --- список версий -----------------------------------------------------------
VERSIONS="${*:-}"
if [ -z "$VERSIONS" ] || [ "${1:-}" = "--all" ]; then
  VERSIONS="$(git tag --list 'v[0-9]*' | sed 's/^v//' | sort -t. -k1,1n -k2,2n -k3,3n | tr '\n' ' ')"
  ylw "→ режим --all: версии из тегов: $VERSIONS"
fi
[ -n "$VERSIONS" ] || die "нечего править: не переданы версии и нет тегов vX.Y.Z"

extract_notes() {  # $1 = версия, печатает секцию в stdout
  "$PY" - "$CHANGELOG_FILE" "$1" <<'PYEOF'
import sys, re, io
path, version = sys.argv[1], sys.argv[2]
try:
    text = io.open(path, encoding="utf-8").read()
except FileNotFoundError:
    sys.exit(1)
lines = text.splitlines()
pat = re.compile(r'^\s{0,3}##\s+\[?' + re.escape(version) + r'\]?')
start = None
for i, ln in enumerate(lines):
    if pat.match(ln):
        start = i
        break
if start is None:
    sys.exit(1)
end = len(lines)
for j in range(start + 1, len(lines)):          # +1: строка заголовка сама матчится '## '
    if re.match(r'^\s{0,3}##\s+', lines[j]):
        end = j
        break
body = "\n".join(lines[start:end]).strip()      # заголовок ВКЛЮЧЁН в описание
if not body:
    sys.exit(1)
print(body)
PYEOF
}

FIXED=0; SKIPPED=0
for V in $VERSIONS; do
  TAG="v$V"
  if ! gh release view "$TAG" >/dev/null 2>&1; then
    ylw "  $TAG — релиза нет, пропускаю"; SKIPPED=$((SKIPPED+1)); continue
  fi
  NOTES="$(mktemp -t fixnotes.XXXXXX)"
  if ! extract_notes "$V" > "$NOTES"; then
    ylw "  $TAG — секции [$V] нет в $CHANGELOG_FILE, пропускаю"
    rm -f "$NOTES"; SKIPPED=$((SKIPPED+1)); continue
  fi
  if gh release edit "$TAG" --title "$TAG" --notes-file "$NOTES" >/dev/null 2>&1; then
    grn "  ✓ $TAG — title и описание обновлены ($(wc -c < "$NOTES" | tr -d ' ') байт)"
    FIXED=$((FIXED+1))
  else
    red "  ✗ $TAG — gh release edit не удался (проверь права токена)"
  fi
  rm -f "$NOTES"
done

echo ""
grn "ГОТОВО: исправлено $FIXED, пропущено $SKIPPED"
gh release list --limit 5 2>/dev/null || true
