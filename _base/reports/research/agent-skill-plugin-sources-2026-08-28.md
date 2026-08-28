# Откуда брать готовых агентов, скиллы и плагины — карта источников

> Исследование 28.08.2026. Повод: «очень слабое место по агентам/скиллам/плагинам,
> только 3 скилла по сути сделали».
> Родня: `36-plugins-and-marketplaces.md` (про Cowork-плагины, **другой слой**),
> `37-skills-system.md`, `69-agents-hooks-and-gates.md`.

---

## 0. Прямой ответ

**Официальный реестр плагинов Claude Code существует, называется `claude-plugins-official`
и добавляется автоматически** при первом интерактивном запуске Claude Code — его не надо
искать. Рядом лежит `claude-plugins-community` с автоматическим security-скринингом
Anthropic. Плюс два открытых слоя: репозиторий `anthropics/skills` под Apache 2.0
(скиллы, которые можно форкать и переписывать) и community-маркетплейсы (`wshobson/agents`,
`VoltAgent/…`), которые ставятся той же командой `/plugin marketplace add owner/repo`,
но **никем не проверены**.

**Ключевой вывод (интерпретация, не факт из источника):** узкое место системы не в
«где взять скиллы», а в **канале раскатки**. Механизм есть (`extraKnownMarketplaces`
в `.claude/settings.json`), он даже был настроен и лежит в бэкапе конфига — но своего
маркетплейса у системы нет, поэтому каждый скилл живёт в одной репе.

**Как это делалось.** Реальных субагентов запущено **0** — в тулсете исполнителя не было
инструмента спавна субагентов. Углы разбиты до первого поиска, прогнано **10 `WebSearch` +
14 `WebFetch`** батчами по 4–5 независимых вызовов. Перед вебом проверена собственная база
(`Grep`/`Glob`).

---

## 1. Что уже было в базе (не переоткрывалось)

| Находка | Где лежит |
|---|---|
| `find-skills` — скилл-навигатор по экосистеме `npx skills` / skills.sh | `01-claude-context/imported-from-disk/.agents/skills/find-skills/SKILL.md` |
| Тот же `find-skills` **выключен**: `"skillOverrides": {"find-skills": "off"}` | `.../config-backups/settings.json.backup` |
| Рабочий `extraKnownMarketplaces` (3 маркетплейса) и 16 записей `enabledPlugins@claude-plugins-official` | там же |
| Три research-промпта Anthropic (lead / subagent / citations) | `.claude/agents/prompts/` |

Маркетплейсы в системе уже использовались — в конфиге FINPILOT-эпохи стояли
`security-guidance`, `hookify`, `semgrep`, `chrome-devtools-mcp`. Знание не доехало
до `00-infrastructure/` — `36` описывает **Cowork-плагины** (`SearchPlugins`/`ListPlugins`),
а не CLI-маркетплейсы (`/plugin marketplace add`). Это два разных механизма под одним словом.

---

## 2. Официальные источники Anthropic

| Источник | Что это | Как подключить | Сигнал |
|---|---|---|---|
| **`claude-plugins-official`** | Курируемый Anthropic каталог. LSP-плагины (11 языков), внешние интеграции (github, gitlab, linear, notion, figma, sentry, slack, supabase, vercel…), `security-guidance`, dev-workflow (`commit-commands`, `pr-review-toolkit`, `agent-sdk-dev`, `plugin-dev`), output-styles | Добавляется сам при первом интерактивном старте. Вручную: `/plugin marketplace add anthropics/claude-plugins-official` | 34.6k★, 3.9k форков |
| **`claude-plugins-community`** | Read-only зеркало. Каждый плагин прошёл автоматический security-скан и ручное одобрение; пиннится к commit SHA | `/plugin marketplace add anthropics/claude-plugins-community`, ставить как `<name>@claude-community` | 2.4k★ |
| **`anthropics/skills`** | 19 скиллов: `skill-creator`, `doc-coauthoring`, `internal-comms`, `brand-guidelines`, `frontend-design`, `mcp-builder`, `webapp-testing`, `canvas-design`, `theme-factory`, `algorithmic-art`, `slack-gif-creator`, `web-artifacts-builder`, `claude-api`, `academy-guide`, `discernment-nudge`, `docx`/`pdf`/`pptx`/`xlsx` | `/plugin marketplace add anthropics/skills` | 172k★ (проверено одним источником, отношусь скептически). Apache 2.0, кроме document-skills |
| **`anthropics/claude-code`** (`claude-code-plugins`) | Демо-маркетплейс с примерами | `/plugin marketplace add anthropics/claude-code` | Учебный, не продакшен |
| **`anthropics/claude-cookbooks`** `patterns/agents/` | Референс-реализации: `basic_workflows.ipynb`, `evaluator_optimizer.ipynb`, `orchestrator_workers.ipynb`, `async_multi_agent_orchestration.ipynb`, `util.py`, `prompts/` | Читать/копировать код | 52.2k★, 6.2k форков |

Четыре ноутбука с рабочими реализациями паттернов (`orchestrator_workers`,
`async_multi_agent_orchestration` и др.) не были замечены раньше — прямая родня
`51-autonomous-agent-loop.md`.

### Что документация говорит про переиспользование чужого

- Уровни скиллов: `enterprise` → `personal` (`~/.claude/skills/`) → `project`
  (`.claude/skills/`). Приоритет: enterprise > personal > project.
- `CLAUDE_CODE_SYNC_SKILLS` тянет скиллы с claude.ai в `~/.claude/skills/synced/`.
- Скилл-директория может быть симлинком.
- Карточка плагина перед установкой показывает Context cost (токены за ход),
  Last updated, полный список «Will install».
- Неиспользуемые ≥2 недели за ≥10 сессий плагины попадают в «Not used recently».

---

## 3. Community-источники: реальный сигнал

| Репозиторий | ★ (со страницы репо) | Что внутри | Лицензия | Ставится как |
|---|---|---|---|---|
| `wshobson/agents` | 39.2k, 4.2k форков | 93 плагина, 202 агента, 181 скилл, 105 команд | MIT | `/plugin marketplace add wshobson/agents` |
| `VoltAgent/awesome-claude-code-subagents` | 24.7k, 2.9k форков | 158+ субагентов, 10 категорий | MIT | копировать в `.claude/agents/` |
| `rohitg00/awesome-claude-code-toolkit` | 2.6k, 910 форков | 135 агентов, 35 скиллов, 42 команды, 176+ плагинов, 20 хуков | Apache 2.0 | смешанный |
| `vercel-labs/skills` + skills.sh | — | Кросс-платформенная экосистема: `npx skills find/add/check/update` | — | `npx skills add owner/repo@skill` |
| `claudemarketplaces.com` | — | Каталог-агрегатор: 23 600+ скиллов, 12 800+ MCP | — | **не официальный** («not affiliated with Anthropic») |

Экосистема skills.sh запущена Vercel 20.01.2026; чек-лист качества из `find-skills`:
1K+ инсталлов — норма, <100 — осторожно, репо с <100★ — скепсис.

---

## 4. Конкретные кандидаты на заимствование

| # | Что | Откуда | Что даст этой системе |
|---|---|---|---|
| 1 | **`skill-creator`** | `/plugin install skill-creator@claude-plugins-official` | Цикл интервью → SKILL.md → кейсы в `evals/evals.json` → прогон with-skill vs baseline → грейд → оптимизация `description`. Прямой ответ на измеренные 55% активации (`37` §4а) |
| 2 | **`plugin-dev`** | официальный маркетплейс | Свой приватный маркетплейс — `auto`/`handoff`/`tokens`/`research` одним бандлом на все репы |
| 3 | **`doc-coauthoring`** (Apache 2.0 — форк) | `anthropics/skills` | Трёхфазный gather → refine → reader test — фазы «reader test» в `07-writing-methodology.md` пока нет |
| 4 | **`context: fork` + `agent:`** | доки Claude Code | Скилл выполняется как субагент в изолированном контексте — обновляет `69` §1 |
| 5 | **`commit-commands`, `pr-review-toolkit`, `security-guidance`, `hookify`, `semgrep`** | официальный маркетплейс | Первые два на `58-git-practice.md`; остальные три уже были включены раньше, но не задокументированы |
| 6 | **4 ноутбука cookbooks** | `claude-cookbooks/patterns/agents/` | Рабочий код orchestrator-workers/async-оркестрации под `51-autonomous-agent-loop.md` |

---

## 5. Риски: что проверять до установки

Дословно из доков Anthropic:
> «Plugins and marketplaces are highly trusted components that can execute arbitrary code
> on your machine with your user privileges.»
> «Anthropic doesn't control what MCP servers, files, or other software are included
> in plugins and can't verify that they work as intended.»
> «A skill can grant itself broad tool access, so review the `allowed-tools` of skills
> checked into a repository before you run Claude Code there.»

### Чек-лист аудита (сведён из Red Hat Developer + Repello AI)

**Репозиторный уровень:**
1. `main` защищён ревью, прямые пуши запрещены.
2. Ставить с тега версии, не с дефолтной ветки.
3. Есть `SECURITY.md` с контактом.
4. Задокументировано, что плагин читает и куда отправляет.
5. Публикация через OIDC, не долгоживущие секреты.

**Уровень компонентов:**
6. `SessionStart`-хуки не читают креды.
7. Красные флаги в `SKILL.md`: доступ к `~/.aws`/`~/.ssh`/`.env`, сборка URL наружу,
   слова «always»/«silently»/«regardless».
8. Инвентаризация файлов не по назначению (форматтер коммитов не должен нести `.py`/`.sh`/бинарь).
9. Обфускация: base64, скрытый unicode, неанглийский текст внутри английского скилла.
10. Любой домен/IP вне заявленного эндпоинта.

Ограничение, названное самой статьёй Red Hat честно: «This is signal-reading, not
verification.» Даже прошедший все проверки репозиторий может быть скомпрометирован
через мейнтейнера.

### Встроенные механизмы защиты Claude Code

| Механизм | Что делает |
|---|---|
| `"disableSkillShellExecution": true` | `!`-команды в скиллах не выполняются |
| deny-правило `Skill` в `/permissions` | Полное отключение вызова скиллов моделью |
| `Skill(name)` / `Skill(name *)` | Точечный allow/deny |
| `disable-model-invocation: true` | Скилл убирается из контекста модели целиком |
| `skillOverrides` в `settings.local.json` | Управление видимостью чужого скилла без правки его файла |
| Context cost в карточке плагина | Видно цену в токенах до установки |

Правило «запрет живёт в хуке» (`69` §1) применимо и к чужим скиллам — но здесь заслон
уже встроен настройками, свой хук писать не нужно.

---

## 6. Противоречия между источниками (не сглажены)

| Предмет | Источник A | Источник B | Что взято |
|---|---|---|---|
| `wshobson/agents` — звёзды | сниппет: 37.5k, «194 агента, 158 скиллов» | страница репо: 39.2k, «93 плагина, 202 агента, 181 скилл» | страница репо |
| `VoltAgent/…` | сниппет: 22.9k★ | страница репо: 24.7k★ | страница репо |
| Размер официального маркетплейса | блоги называют от 36 до «200+» плагинов | официальные доки чисел не называют вовсе | числа не приводить — доки прямо говорят смотреть `/plugin` вживую |
| Community-маркетплейс | статья: «70+ плагинов, прошедших автоскрининг» | страница репо счётчика не показывает | помечено как непроверенное |
| `anthropics/skills` — 172k★ | страница репо (два фетча) | второго независимого источника нет | указано с оговоркой |

---

## 7. Что осталось неизвестным

1. Даты последних коммитов community-репозиториев не проверены — главный сигнал
   «живой/мёртвый» не получен.
2. Точное число плагинов в официальных маркетплейсах — доки намеренно не называют.
3. Совместимость `npx skills` с плагинной системой Claude Code — не проверена.
4. Кампания «ClawHavoc» (335 вредоносных скиллов) — единственный источник, независимого
   подтверждения нет, годится как иллюстрация класса атаки, не как факт.
5. Стоят ли `security-guidance`/`hookify`/`semgrep` в текущей живой конфигурации сейчас,
   не только в бэкапе — не проверено, проверяется локально `/plugin list`.
6. Числа `anthropics/skills` (172k★) не триангулированы.

---

## 8. Где это логичное место в системе (решение вахты)

- `36-plugins-and-marketplaces.md` описывает Cowork-слой, не CLI-маркетплейсы —
  нужен либо новый раздел, либо отдельный документ про `/plugin marketplace add`.
- `37-skills-system.md` §4б описывает формат `evals.json`, но не инструмент прогона —
  `skill-creator` закрывает пробел.
- `69-agents-hooks-and-gates.md` §1 утверждает, что субагенту нужна скилла-обёртка —
  `context: fork` это меняет, раздел требует ревизии.
- `.claude/skills/README.md` в base-repo отсутствует — при 4 скиллах/4 агентах навигатор
  выглядит уместным, особенно если появится свой маркетплейс.

---

## Источники

- https://code.claude.com/docs/en/discover-plugins
- https://code.claude.com/docs/en/skills
- https://github.com/anthropics/claude-plugins-official
- https://github.com/anthropics/claude-plugins-community
- https://github.com/anthropics/skills
- https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md
- https://github.com/anthropics/claude-cookbooks/tree/main/patterns/agents
- https://github.com/wshobson/agents
- https://github.com/VoltAgent/awesome-claude-code-subagents
- https://github.com/rohitg00/awesome-claude-code-toolkit
- https://github.com/vercel-labs/skills · https://www.skills.sh/docs
- https://claudemarketplaces.com/
- https://developers.redhat.com/articles/2026/08/18/securing-claude-code-plug-ins-best-practices-repository-security
- https://repello.ai/blog/claude-code-skill-security
- https://pluto.security/blog/claude-extension-ecosystem-security-practitioner-guide/
- Внутренние: `01-claude-context/imported-from-disk/.agents/skills/find-skills/SKILL.md`,
  `01-claude-context/imported-from-disk/config-backups/settings.json.backup`,
  `00-infrastructure/36-plugins-and-marketplaces.md`, `37-skills-system.md`,
  `69-agents-hooks-and-gates.md`
