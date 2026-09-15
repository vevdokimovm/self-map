#!/usr/bin/env bash
# Генератор knowledge-кита: пересобирает _knowledge-kit/ из канонических файлов репы.
# Кит — это ТОНКИЙ СРЕЗ «мозга» проекта (правила + реестр + состояние + протокол
# текущего источника) для загрузки в Project knowledge, БЕЗ сырья (06-diaries, 08-feedback,
# дословных заметок закрытых источников, deliverables). Полное «тело» проекта живёт в гите.
#
# Файлы в ките — КОПИИ, не оригиналы. Единственный источник правды — канонические пути.
# Кит НИКОГДА не редактируется руками: правишь оригинал → прогоняешь этот скрипт.
# Запуск из корня репы:  bash _knowledge-kit/build-kit.sh
set -euo pipefail
cd "$(dirname "$0")/.."
K="_knowledge-kit"

cp 10-life-history/00-protocol/01-rules.md                        "$K/protocol/"
cp 10-life-history/00-protocol/02-process.md                      "$K/protocol/"
cp 10-life-history/00-protocol/03-channels.md                     "$K/protocol/"
cp 10-life-history/00-protocol/04-visual-and-reports-standard.md  "$K/protocol/"
cp 10-life-history/00-protocol/05-context-mechanics.md            "$K/protocol/"
cp 10-life-history/00-protocol/07-handoff-prompt-base.md          "$K/protocol/"

cp 10-life-history/01-registry/facts-and-hypotheses.md           "$K/registry/"
cp 10-life-history/01-registry/file-checklist.md                 "$K/registry/"
cp 10-life-history/01-registry/roadmap.md                        "$K/registry/"
cp 10-life-history/01-registry/corpus-inventory.md               "$K/registry/"
cp 10-life-history/01-registry/source-map.md                     "$K/registry/"

cp 10-life-history/02-notes/handwritten-diary.md                 "$K/notes/"
cp 10-life-history/02-notes/quality-passports.md                 "$K/notes/"

cp 00-infrastructure/34-pdf-reading-channels.md                  "$K/infra/"
cp 00-infrastructure/35-pdf-channels-experiment.md              "$K/infra/"
cp 00-infrastructure/reports/investigations/vision-channel_investigation.md "$K/infra/"

echo "kit rebuilt: $(find "$K" -name '*.md' | wc -l) файлов, $(du -sh "$K" | cut -f1)"
