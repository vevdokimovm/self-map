# Прогон — 27.08.2026 — `docs_to_md.py`, второй проход по всей системе

## Повод

`ROADMAP.md` п.2 (ревизия базы и каждой репы), приоритет владельца: дожать содержательную
часть — «документы → текст» — а не мехпроверки. Первый проход (`2026-08-23`) закрыл 543
файла из тогдашних 5236 медиа-файлов (0.4% → ~10%, включая изображения, которые
`docs_to_md.py` не трогает вовсе).

## Блокер до прогона

`docs_to_md.py --all` падал: `REPOS = Path.home() / "Documents" / "система_репозиториев"` —
путь не существует, все репы уже переехали в `~/repos/` (`88-local-repo-location-standard.md`,
26.08.2026). Тот же дефект нашёлся ещё в 18 python-скриптах `scripts/` и
`07-media-to-text-lab/tools/`/`05-infra-synthesis-lab/tools/`, плюс в `night.sh`,
`templates/deploy.sh`, `.claude/skills/auto/SKILL.md`, `LAUNCH_BRIEF.md`, `RUNS.md`,
`.claude/agents/repo-inventory.md`, `86-entity-classes.md`. Починено — везде путь
теперь выводится от `Path(__file__).resolve()` (тот же приём, что уже стоял в
`sync_base_local.py`/`distribute_claude_kit.py`/`drift_versions.py`), а не от константы.
Исторические записи (`CHANGELOG.md`, `WATCHLOG.md`, `reports/pitfalls.md`, ADR, инциденты,
`migrate_to_repos.py`) не трогались — это снимки состояния на момент написания, не инструкции.

## Что сделано

`docs_to_md.py --all --apply` (только pdf/docx/pptx/xlsx — тип, который умеет тул):

| Репа | выжимок | без текста (нужен OCR) |
|---|---|---|
| academic-portfolio | 77 | 1 |
| it-base | 40 | 5 |
| legal-knowledge-base | 322 | 23 |
| personal-finance-dss | 11 | 3 |
| research-craft | 16 | 1 |
| finpilot | 4 | 1 |
| **итого** | **472** | **34** |

Остальные репы (career, christ-walk, dota-dossier, edu-base, exam-kit, family,
health-vault, master-admission, mathematics, misc-vault, mission-control, ml-base,
portrait-of-taste, science, self-map, truth-seeking, character-a-analysis) дали
0 новых выжимок — не потому что пропущены, а потому что их pdf/docx/pptx/xlsx **уже**
несли `.md` из прогона `2026-08-23`. Проверено вручную на `health-vault`: строка
`measurements.csv` от 22.08 («не начат») была устаревшей записью, не фактом — все 269 PDF
там уже с выжимками.

**Замер по системе целиком** (pdf/docx/pptx/xlsx, все 61 репы): **1511 из 1513** файлов
несут `.md`-выжимку — **99.9%**. Это не 0.4%, с которых начинался `PIT-138` (та цифра
считала ВСЕ медиа, включая изображения — их этот инструмент не трогает).

## Что осталось непрочитанным — 2 файла, оба объяснены

- `legal-knowledge-base/04-reference/raznoe-import/Шаблон доверенности.docx` — 0 байт
  **на самом GitHub** (не заглушка синка), рядом лежит содержательный дубль
  `Шаблон доверенности__from-юриспруденция.docx` (24 КБ) и оригинал
  `Шаблон доверенности.pdf` (118 КБ, без своей выжимки — тоже стоит сделать).
- `master-admission/achievements/rezultaty-bochvara/01.04.04 Прикладная математика ИТКН.pdf`
  — тоже 0 байт на GitHub, рядом полноценный дубль с суффиксом `__from-магистратура ` (144 КБ),
  **уже несущий выжимку**, и ещё одна интактная копия того же файла в
  `achievements/bochvar/` (тоже с выжимкой).

Оба — husk-дубли, оставшиеся от кампании переноса; контент цел под другим именем.
Не удалялись в этом прогоне — решение об удалении дублей не входит в мандат содержательной
ревизии, оставлено `TASKS.md` владельцу.

## Что сделано сверх конвертации

Пять затронутых реп с ненулевым `.repo-class`≠MISSING получили патч-версию через
`bump_repo.py` (CHANGELOG + VERSION + WATCHLOG §0) и архив в `~/Downloads` через
`pack_release.py` — деплой на GitHub НЕ выполнялся (стоп-класс §5, ждёт владельца):
`academic-portfolio` 0.2.2→0.2.3, `it-base` 1.4.1→1.4.2,
`legal-knowledge-base` 2.24.1→2.24.2, `personal-finance-dss` 8.28.0→8.28.1,
`research-craft` 0.2.0→0.2.1.

**Допущение:** `finpilot` пропущен намеренно — нет `VERSION`/`.repo-id`/`.repo-class`
локально, известный незаконченный случай (`ROADMAP.md` п.2: `finpilot` и
`personal-finance-dss` — по всей видимости один и тот же GitHub-контент в двух копиях,
решение оставлено владельцу). 4 новых выжимки в его дереве остались локально без версии/архива.

**Находка по ходу:** `personal-finance-dss` не имел `.repo-class` вовсе (пакует не давал
собрать архив — `43-archive-naming-and-packaging.md` §3а требует пять служебок в корне).
Проставлено `product` — репа несёт SemVer/CHANGELOG/релизы, это ровно определение класса
`product` из `76-repo-classes.md`, по аналогии с `algorithms-site`/`control-panel`/`vk-graph`
и т.п. `finpilot` тем же дефектом не лечился — решение по нему за владельцем целиком.

## Что дальше по содержательной ревизии

Документы (pdf/docx/pptx/xlsx) закрыты на 99.9% — следующий содержательный разрыв: **изображения**
(`METHOD_IMAGES.md`, очередь 173 серии/1495 кадров) и **OCR** для 34+40=74 сканов без
текстового слоя.
