# Официальная практика Anthropic против внутренней: что сошлось, что разошлось

> Внешнее исследование 28.08.2026. Повод: довести внутреннюю лабораторию по эффективной
> работе с Claude/Claude Code до максимума с опорой на **опубликованные источники**,
> а не только на собственные замеры.
>
> **Сознательно не пересказывает** то, что уже измерено внутри
> (`reports/experiments/token-consumption/hypothesis.md`, 54 раздела) и что уже сведено
> из документации (`00-infrastructure/49-token-economy-and-prompting.md`). Здесь только
> **дельта**: подтверждения, расхождения и то, чего в базе не было.
>
> Родня: `49-token-economy-and-prompting.md` · `69-agents-hooks-and-gates.md` ·
> `51-autonomous-agent-loop.md` · `27-claude-memory-and-instructions.md` ·
> `64-claude-code-sandbox.md` · `reports/research/agent-skill-plugin-sources-2026-08-28.md`
> (тот же день, **другой предмет** — где брать чужих агентов и скиллы, не пересекается).

---

## 0. Прямой ответ

**Внутренняя практика совпала с официальной рекомендацией почти везде, где её проверяли —
и разошлась ровно в трёх местах, каждое из которых стоит денег.**

1. **Параллельный веер форк-агентов оплачивается полностью каждым форком.** Официально:
   запись в кэш становится читаемой только после того, как первый ответ **начал стримиться**,
   поэтому N одновременных запросов с общим префиксом пишут N отдельных записей и не читают
   ни одной чужой. Это даёт вторую, более сильную гипотезу к измеренной 28.08 аномалии
   «субагенты 97.6 % в дорогом 5-минутном режиме против 0 % у родителя».
2. **Появилась официальная ручка ровно под эту аномалию** — `experimental.cacheTtl`
   (`5m`/`1h`) во frontmatter субагента, версия **2.1.248 от 27.08.2026**, то есть за день
   до замера. Лаборатория измерила проблему, у которой уже сутки как есть штатное решение.
3. **Утверждение базы «переменной `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` в официальной
   документации нет» опровергнуто** — она найдена в доках. Требует одной перепроверки
   (см. §4), но статус «неверна» уже вероятнее статуса «верна».

Плюс отдельно: **самый сильный принцип системы — «запрет живёт в хуке, не в тексте» —
подтверждён Anthropic четырьмя независимыми дословными формулировками** и оказался
не догадкой этой системы, а официальной архитектурной позицией.

---

## Как это делалось

**Классификация запроса: breadth-first** — тема распалась на три независимых под-вопроса,
не на три ракурса одного. **Субагентов: 3**, запущены параллельно одним сообщением:

| Субагент | Угол | Границы |
|---|---|---|
| 1 | блог `anthropic.com/engineering` + `code.claude.com/docs` (best practices, context engineering) | не трогает cookbook и changelog |
| 2 | `anthropics/claude-cookbooks` + официальные доки по prompt caching и длинному контексту | не трогает блог и changelog |
| 3 | `code.claude.com/docs` по механизмам CLI + сырой `CHANGELOG.md` с датами версий | не трогает блог и API-механику кэша |

Суммарно **55 вызовов инструментов** субагентами (14 + 15 + 26); раздел между `WebSearch`
и `WebFetch` внутри субагентов не фиксировался и здесь не выдумывается. Лидер собственных
веб-запросов **не делал ни одного** — только чтение своей базы (`Grep`/`Glob`/`Read`)
перед делегированием и синтез после. Синтез написан лидером, субагентам не поручался.

**Честная граница метода:** у субагентов из внешних источников были только `WebSearch` и
`WebFetch`. Ничего, что требует авторизации (Console, Analytics API, приватные каналы),
проверено быть не могло; на выводы это не повлияло — вся тема оказалась покрыта публичными
источниками.

---

## 1. Что подтвердилось — внутренняя практика оказалась официальной

### 1.1 «Запрет живёт в хуке, знание — в скилле» (`69` §1) — подтверждено четырежды

> «Claude treats them as context, **not enforced configuration**. To block an action
> regardless of what Claude decides, use a PreToolUse hook instead.»
> (https://code.claude.com/docs/en/memory)

> «Unlike CLAUDE.md instructions which are advisory, **hooks are deterministic and
> guarantee the action happens**.» — и подзаголовок раздела: «Use hooks for actions that
> must happen every time with zero exceptions.»
> (https://code.claude.com/docs/en/best-practices)

Там же официальный алгоритм перевода правила в хук и антипаттерн «over-specified
CLAUDE.md» с предписанием: «If Claude already does something correctly without the
instruction, **delete it or convert it to a hook**». Формулировка базы, добытая своей
болью, дословно совпала с позицией вендора.

**Оговорка, которой в базе не было:** у Stop-хука есть потолок детерминизма — «Claude Code
overrides the hook and **ends the turn after 8 consecutive blocks**». У PreToolUse-deny
такого потолка нет. Гейт, рассчитанный на «блокировать, пока не починят», после восьмой
блокировки перестаёт блокировать (https://code.claude.com/docs/en/best-practices).

### 1.2 Таймаут хука и fail-open (`69` §2, пункт 3) — подтверждено точно

Внутренняя запись: «у хука есть таймаут (порядка 10 минут), полная суита в него не влезает,
и хук **молча пропускает всё** — fail-open, гейт не работает, а выглядит работающим».

Официально: дефолт **600 с** для `command`/`http`/`mcp_tool` (это ровно 10 минут), 30 с для
`prompt`-хуков, 60 с для `agent`-хуков, пониженные бюджеты у `UserPromptSubmit` (30 с),
`MessageDisplay` (10 с), `SessionEnd` (1.5 с на все хуки). По таймауту хук отменяется, вывод
отбрасывается, решение не выносится, и **на `PreToolUse` это не блокирует вызов** — команда
идёт обычным потоком разрешений (https://code.claude.com/docs/en/hooks).

Внутренний вывод был получен наблюдением и оказался верен вплоть до величины таймаута.

### 1.3 `exit 2` блокирует, `exit 1` — нет (`69` §2, пункт 1) — подтверждено

«Exit Code 2 — Blocking error», и он блокирует **даже вопреки** JSON с
`permissionDecision: "allow"`. Прочие ненулевые коды — неблокирующая ошибка, действие
продолжается. Версионная деталь, которой в базе нет: **до v2.1.214 (18.07.2026)** `exit 2`
с невалидным JSON считался неблокирующей ошибкой — то есть хуки, написанные раньше и
проверенные один раз, могли вести себя иначе, чем сегодня.

### 1.4 «Одна работа на агента, tools урезаны до минимума» (`69` §3) — подтверждено, мотивировка шире

> «Design focused subagents: each subagent should excel at one specific task» ·
> «Limit tool access: grant only necessary permissions **for security and focus**»
> (https://code.claude.com/docs/en/sub-agents)

Официальный пример в best-practices — ровно урезанный набор `tools: Read, Grep, Glob, Bash`.

**Поправка к формулировке базы:** в `69` §3 мотивировка одна — «физически не может ничего
испортить». Официальная — двойная: узкий набор инструментов улучшает **качество** работы,
а не только безопасность. Перекликается с прямой цитатой из context-engineering: «If a human
engineer can't definitively say which tool should be used in a given situation, an AI agent
can't be expected to do better».

### 1.5 Постановка задачи субагенту (`69` §3а) — подтверждено пунктом в пункт

> «Each subagent needs **an objective, an output format, guidance on the tools and sources
> to use, and clear task boundaries**.» Без этого — «agents duplicate work, leave gaps, or
> fail to find necessary information».
> (https://www.anthropic.com/engineering/multi-agent-research-system, 13.06.2025)

Это дословно чеклист, по которому в этой системе пишутся задания форкам.

### 1.6 «Разрешение не найти» у ревьюера (`69` §3, `70`) — подтверждено прямым предупреждением

> «A reviewer prompted to find gaps **will usually report some, even when the work is
> sound**, because that is what it was asked to do. Chasing every finding leads to
> over-engineering… Tell the reviewer to flag only gaps that affect correctness or the
> stated requirements.» (https://code.claude.com/docs/en/best-practices)

Внутреннее правило «если ничего правдоподобного не нашлось — скажи одной строкой, не
выдумывай слабые гипотезы ради объёма» — тот же механизм, найденный самостоятельно.

### 1.7 Субагент как изоляция контекста (`49` §3, `69` §1) — подтверждено с числом

> «Since context is your fundamental constraint, **subagents are one of the most powerful
> tools available**.» Субагент возвращает «only a condensed, distilled summary of its work
> (**often 1,000–2,000 tokens**)».
> (best-practices · https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents, 29.09.2025)

Внутренний замер «записей `isSidechain` в логе родителя ноль» и официальная механика
описывают одно и то же явление с двух сторон.

### 1.8 Массовая правка в отдельном дереве (`69` §4б) — есть штатный механизм

Официальный `/batch` порождает **5–30 субагентов, каждый в своём worktree с PR**
(best-practices). Внутреннее правило «worktree → прогон → diff → ревью → мерж → push
руками» совпадает по замыслу; штатный инструмент под него в базе не назван.

### 1.9 Множители кэша (`49` §1) — совпали точно

Cache write TTL 5 мин — **1.25×**, TTL 1 час — **2×**, cache read — **0.1×**
(https://platform.claude.com/docs/en/build-with-claude/prompt-caching). Внутренняя таблица
верна без правок. Минимум кэшируемого префикса «512–4096 в зависимости от модели» и тихий
отказ без ошибки — тоже подтверждены дословно: «will be processed without caching, and
**no error is returned**».

### 1.10 Пределы параллелизма — внутренние замеры уложились в официальные потолки

Измеренный максимум **7 одновременных субагентов** и вложенность **depth=2** (hypothesis.md,
28.08.2026) лежат внутри официальных лимитов: `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` по
умолчанию **20** (введён в 2.1.217, 21.07.2026, именно чтобы одно сообщение не порождало
неограниченный веер), глубина вложенности по умолчанию **3**
(`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`). Замеры не упирались в потолок — теперь известно,
где он.

---

## 2. Что разошлось — и это главная часть отчёта

### 2.1 🔴 Параллельный веер форков ломает кэш по построению, а не из-за пауз

**Внутреннее объяснение (hypothesis.md, 28.08.2026, статус PLAUSIBLE):** субагенты сидят
в дорогом 5-минутном TTL-режиме (97.6 % записей против 0 % у родителя), потому что
«запускались короткими изолированными задачами с паузами между волнами».

**Официальная механика даёт вторую гипотезу, более сильную:**

> «A cache entry becomes readable **only after the first response begins streaming**.
> N parallel requests with identical prefixes **all pay full price** — none can read what
> the others are still writing.» И далее: «N parallel workers each assembling a slightly
> different prompt over the same context write N separate cache entries and read none of
> each other's.»
> (`shared/prompt-caching.md` из официального бандл-скилла `claude-api`, поставка 2.1.247)

Плюс два усилителя того же эффекта, оба измеримы на внутренних данных:
- **Кэш scoped по модели.** Субагенты сессии шли на `opus-5` (47 ходов) и `haiku-4.5` (6),
  родитель — 100 % `sonnet-5`. Кэш родителя такими форками не переиспользуется **в принципе**,
  escape hatch отсутствует.
- **Форк обязан копировать префикс родителя дословно** (`system`, `tools`, `model`), иначе
  промахивается мимо родительского кэша целиком.

> **Следствие для лаборатории: волна из 7 форков 27.08 в 14:34:13 стоимостью ≈1 584 714
> усл. ед. за пять минут, вероятно, объясняется не паузами, а самим фактом одновременности.**

**Официальная рекомендация, которую можно проверить OFAT прямо здесь:** запустить **один**
запрос, дождаться первого стримленного токена и только потом пустить остальные N−1 — тогда
они читают то, что записал первый. Предсказание: `cache_creation` волны падает кратно,
`cache_read` растёт. Это готовый предрегистрируемый эксперимент в стиле `28` §3 — сильнее
существующей формулировки backlog, потому что различает две гипотезы, а не подтверждает одну.

### 2.2 🟢 Ручка под измеренную аномалию появилась за день до замера

`experimental.cacheTtl` со значениями `5m` / `1h` во frontmatter субагента — добавлено
в **2.1.248 (27.08.2026)** (https://code.claude.com/docs/en/sub-agents, CHANGELOG).

Внутренний замер 28.08 зафиксировал: родитель — TTL 1 ч / 5 м = 22 093 212 / **0**,
субагенты — 48 222 / **1 991 027**. Теперь TTL субагента задаётся явно, а не наблюдается
как данность. Это переводит пункт из «PLAUSIBLE, нужен контролируемый замер» в «есть рычаг,
замер становится двусторонним: можно не только наблюдать режим, но и назначить его».

### 2.3 🔴 `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` в документации есть

`49` §2а утверждает: «Переменной `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`, которую цитируют
сторонние статьи, **в официальной документации нет**». Субагент 3 нашёл её среди официальных
переменных управления компакцией (процент 1–100 от auto-compact-окна),
https://code.claude.com/docs/en/model-config.

Статус: **вероятно опровергнуто, требует одной прямой перепроверки** — переменная пришла
в общем перечне, без отдельной дословной цитаты со страницы. Два сценария, оба возможны:
переменную добавили в доки после 21.08, либо первая проверка её просто не нашла. Разница
важна: в первом случае запись базы была верна на свою дату и нуждается в датированной
поправке, во втором — была ошибкой сверки.

### 2.4 🔴 Внутреннее число «Sonnet 5 компактится на 934 095» получило срок годности

`49` §2а: по документации ~967K, замерено **934 095**. Субагент 3: окно автокомпакции
Sonnet 5 изменено в **2.1.247 (26.08.2026)** и теперь ~**967K**, было ~934K.

То есть внутренний замер не ошибочен — он **датирован** и описывает поведение до 26.08.2026.
Это буквальная иллюстрация собственного правила базы «фиксировать не только модель, но и
версию CLI и дату» (`49` §2а): правило сработало, число пережило смену продуктового слоя
и теперь читается корректно только вместе с датой.

### 2.5 🟡 «ultrathink» и `budget_tokens` — устаревшие цитаты

Статья `anthropic.com/engineering/claude-code-best-practices` больше не существует: **308
Permanent Redirect** на https://code.claude.com/docs/en/best-practices. Слов
«think / think hard / think harder / ultrathink» в актуальной документации Claude Code нет
(проверены best-practices и common-workflows целиком). API-доки: «On Claude 4.7 and later
models, setting `budget_tokens` **returns a 400 error**. Prefer lowering the effort setting»
(https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices).

`49` §1 упоминает «в Claude Code ещё `ultracode`-режим оркестрации поверх» — это уже
опровергнуто внутренне (`51` §5а: в CLI 2.1.238 такого ключа нет), но упоминание в `49`
осталось. Внешний источник закрывает вопрос со второй стороны: словесный бюджет размышления
как официальный интерфейс исчез, остался `effort`.

### 2.6 🟡 «Критерий проверки в промпт» — верно, но на Opus 5 с исключением

`49` §4, правило 11 подтверждено целым разделом «Give Claude a way to verify its work»:
«Claude stops when the work looks done. Without a check it can run, "looks done" is the only
signal available, **and you become the verification loop**».

**Но** в API-доках: «**Claude Opus 5 is the exception**: it verifies its own work well
without explicit instruction, and verification instructions carried over from prompts tuned
for earlier models can cause **over-verification, adding tokens and latency**. When migrating
to Claude Opus 5, **remove these instructions rather than rewriting them**.»

Разграничение, которого в базе нет: **критерий успеха** (тест-кейсы, команда проверки, что
считается «сделано») кладётся в промпт всегда; **заклинание «перепроверь себя перед ответом»**
на Opus 5 официально рекомендовано снимать. Прямо касается системы: рабочая модель — Opus 5.

### 2.7 🟡 Внутреннее «agent teams ≈ 7× расход» внешнего подтверждения не имеет

`49` §3 и правило 7 называют «ориентировочно в ~7 раз больше». Официальные числа другие и
про другое: агенты ≈ **4×** относительно чата, мульти-агентные системы ≈ **15×**
(https://www.anthropic.com/engineering/multi-agent-research-system, 13.06.2025). Числа 7×
не нашёл ни один из трёх субагентов ни за, ни против.

Честный статус: **число внутреннее, источник неизвестен, официального аналога нет.** Либо
пометить его происхождение, либо заменить на официальную пару 4× / 15×, но не выдавать
за подтверждённое.

### 2.8 🟡 `{"decision":"block","reason":...}` — уже не общий механизм

`69` §2 подаёт эту форму как способ вернуть осмысленное решение из любого хука. В актуальной
справке решающие поля — `hookSpecificOutput` с `permissionDecision`/`permissionDecisionReason`
(для `PreToolUse`/`PermissionRequest`/`PermissionDenied`), `continue`/`stopReason` (для
`Stop`), `additionalContext`, `updatedInput`, `retry`. Верхнеуровневого `decision` в перечне
нет. При этом changelog 2.1.105 (13.04.2026) дословно допускает `{"decision":"block"}` для
`PreCompact`. Вывод: форма жива минимум для одного события, **универсальной считать нельзя**.

### 2.9 🟡 Импорты `@path` контекст не экономят

> «Splitting into @path imports helps organization but **doesn't reduce context, since
> imported files load at launch**.» (https://code.claude.com/docs/en/memory)

Прямо касается конфигурации этой машины: глобальный `~/.claude/CLAUDE.md` состоит из двух
`@`-импортов. Организационно это правильно, но как приём экономии контекста — не работает,
и рассчитывать на него нельзя. Официальный целевой размер CLAUDE.md — **менее 200 строк**;
жёсткий предел — **4 MiB**, файл больше **пропускается целиком**. Глубина импортов — максимум
**4 хопа**.

---

## 3. Новое: чего в базе не было вовсе

### 3.1 Длинный документ — в начало, вопрос — в конец (до +30 % качества)

> «Put longform data at the top… **Queries at the end can improve response quality by up to
> 30 percent in tests**, especially with complex, multidocument inputs.»

Плюс два спутника: заворачивать документы в `<document>` / `<document_content>` / `<source>`
и просить процитировать релевантные куски **до** ответа («ground responses in quotes»). Порог
применимости — **20k+ токенов**
(https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices).

В системе, где в контекст регулярно уезжают длинные `.md`, это самый дешёвый неиспользуемый
рычаг: меняется порядок сборки промпта, не объём.

### 3.2 Пять официальных антипаттернов, из которых два — прямые правила

Раздел «Avoid common failure patterns» (best-practices): kitchen sink session · correcting
over and over · over-specified CLAUDE.md · trust-then-verify gap · infinite exploration.
Два несут проверяемое действие, которого в базе нет:

- «**After two failed corrections, `/clear` and write a better initial prompt incorporating
  what you learned**» — счётчик, а не ощущение. Правило «два провала подряд — сброс, а не
  третья попытка» ложится ровно на дисциплину батчей.
- «**If you can't verify it, don't ship it**» — та же формулировка, что внутреннее
  «доказательство сделанного», но с явной остановкой.

### 3.3 Context rot: у внимания есть бюджет, и он квадратичный

> «as the number of tokens in the context window increases, the model's ability to accurately
> recall information from that context **decreases**» — механизм: «**n² pairwise
> relationships** for n tokens», у модели есть «attention budget».
> (https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents, 29.09.2025)

Внутренняя лаборатория меряет **цену** длинного контекста в токенах. Официальный источник
добавляет вторую ось — **деградацию качества** с длиной, независимо от цены. Это меняет
трактовку плато множителя ×4.0: длинная сессия дороже не только в деньгах.

Там же — ядро подхода: «find the **smallest possible set of high-signal tokens** that maximize
the likelihood of some desired outcome».

### 3.4 Числа под делегирование

Из multi-agent-статьи (13.06.2025): «three factors explained **95 %** of the performance
variance», причём «**token usage by itself explains 80 %**». Масштабирование усилия:
«Simple fact-finding requires just **1 agent with 3–10 tool calls**, direct comparisons might
need **2–4 subagents with 10–15 calls** each, complex research might use **more than 10
subagents**». Связка Opus 4 lead + Sonnet 4 subagents обошла одиночного Opus 4 на **90.2 %**
на внутреннем ресёрч-эвале; сокращение времени — «up to 90 %».

### 3.5 Третий механизм памяти: `.claude/rules/*.md` с `paths:`

Между «грузится всегда» (CLAUDE.md) и «грузится по вызову» (скилл) есть промежуточный слой:
правила с glob-скоупом во frontmatter, которые подгружаются **только когда Claude трогает
подходящие файлы** (бюджет 1000 развёрнутых паттернов / 4 MiB). В `27` и `69` этого слоя нет.

### 3.6 Хуков не шесть, а 31

`69` §2 работает с шестью событиями. Официальный список — **31**, из них блокирующих 14.
Не названы в базе, в частности: `Setup`, `UserPromptExpansion`, `PermissionRequest`,
`PermissionDenied`, `PostToolUseFailure`, `PostToolBatch`, `MessageDisplay`, `SubagentStart`,
`TaskCreated`, `TaskCompleted`, `StopFailure`, `TeammateIdle`, `InstructionsLoaded`,
`ConfigChange`, `CwdChanged`, `DirectoryAdded`, `FileChanged`, `WorktreeCreate`,
`WorktreeRemove`, `PostCompact`, `Elicitation`, `ElicitationResult`. И важное уточнение:
**`PostToolUse` блокировать не умеет** («Can block: No»), а `Stop` и `SubagentStop` — умеют.
Типы хуков тоже шире команды: `command`, `http`, `mcp_tool`, `prompt`, `agent`.

### 3.7 `--restricted` — новейший режим ограничения прав

`--restricted` / `CLAUDE_CODE_RESTRICTED=1`, **2.1.248 (27.08.2026)**: убирает встроенные
инструменты, исполняющие код, и `WebFetch`; держит файловые инструменты внутри рабочей
директории; **отказывает в `bypassPermissions`**; игнорирует user/project/local settings.
Прямая родня `64-claude-code-sandbox.md`, который его не знает.

Там же официальная формулировка про bypass, которой стоит заменить любую смягчённую:
«`bypassPermissions` **offers no protection against prompt injection or unintended actions**»
(https://code.claude.com/docs/en/permission-modes).

### 3.8 Прогрев кэша: официальный приём под сторожевой будильник

Приём «пинг раз в 60 с, чтобы не вывалиться из TTL» официально **не описан** — ни термина
keep-alive, ни фиксированного интервала; все найденные реализации сторонние. Но описана
его механика и рекомендация того же смысла: чтение обновляет TTL **бесплатно** («The cache
is refreshed for no additional cost each time the cached content is used»), а для трафика
с разрывами — «**re-warm just under the TTL** or switch to `ttl: "1h"` and re-warm less
often». Прогрев делается запросом с `max_tokens: 0` (output не биллится, платится обычная
цена записи).

**Уточнение, меняющее расчёт интервала:** TTL отсчитывается **от начала запроса, а не от
конца ответа**, и время генерации съедает окно — «if a response takes 4 minutes to stream,
a follow-up request must start within about 1 minute of that response completing».
Для длинных ходов агента реальный запас меньше номинального, и 60 с внутри пятиминутного
окна — оправданный, а не избыточный запас.

### 3.9 Ловушка «дешёвой модели субагенту»

Минимум кэшируемого префикса **не монотонен по поколениям**: 512 токенов у Opus 5 / Fable 5 /
Mythos 5, 1024 у Sonnet 5 / Opus 4.8, 2048 у Opus 4.7 / Haiku 3.5, но **4096 у Haiku 4.5 и
Opus 4.6/4.5**. Правило `49` §4.6 «ставь субагентам дешёвую модель» на Haiku 4.5 означает,
что префикс короче 4096 токенов **молча не кэшируется вовсе** — без ошибки, с нулями в обоих
счётчиках. Дешёвая модель на коротких задачах может выйти дороже ожидаемого.

### 3.10 Официальное предупреждение прямо про эту систему

> «Claude Opus 4.6 has a strong predilection for subagents and may spawn them in situations
> where a simpler, direct approach would suffice… **Claude Opus 5 also delegates to subagents
> more readily than prior models.**»

Официально рекомендован **гасящий** промпт, а не поощряющий. Внутреннее правило «агент —
только там, где нужно суждение» (hypothesis.md, вахта IX) оказывается не экономией ради
экономии, а компенсацией известного смещения модели. Это усиливает правило, а не отменяет.

---

## 4. Противоречия и неопределённости — не сглажены

| Предмет | Источник A | Источник B | Что взято |
|---|---|---|---|
| `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` | `49` §2а: «в официальной документации нет» (21.08.2026) | субагент 3: есть в перечне переменных model-config | помечено как **вероятно опровергнуто, нужна прямая перепроверка** |
| Порог MCP tool search | страница `/mcp`: `auto:N`, N = **число инструментов**, дефолт `auto:100` | changelog 2.1.9: `auto:N`, N = **процент контекстного окна**; страница context-window: порог **10 %** | **не разрешено**, три официальные формулировки не сводятся |
| Имя инструмента поиска тулов | `ToolSearch` (страница `/mcp`) | `MCPSearch` (changelog 2.1.7) | оба приведены, выбор не сделан |
| Название паттерна | cookbook README: **Orchestrator-Subagents** | ноутбук `orchestrator_workers.ipynb`, блог: **orchestrator-workers** | дрейф наименования внутри самих официальных материалов |
| Таблица инвалидации кэша | страница prompt-caching, нотация галочек считана неоднозначно (самоотчёт субагента 2) | смысловая формулировка «изменение инвалидирует свой уровень и все нижележащие» — достоверна | взят смысл; **построчную разметку `thinking`/`effort` перед использованием в коде перечитать** |
| Окно автокомпакции Sonnet 5 | внутренний замер: 934 095 | доки после 2.1.247 (26.08.2026): ~967K | оба верны, **на разные даты** |

**Отдельно про возраст фактов.** Ни на одной странице `code.claude.com/docs` и
`platform.claude.com/docs` **нет даты публикации или обновления**. Датированы только три
блог-поста (19.12.2024, 13.06.2025, 29.09.2025) и changelog по версиям. Значит любое число
из доков — без возраста, и версионировать его можно только внешне: датой снятия и версией
CLI. Ровно то, что предписывает `49` §1б («метка "публично не существует" — четвёртая
степень уверенности» и «срок годности такой таблицы низкий»).

---

## 5. Что осталось неизвестным

1. **Внутреннее правило «вопрос-карта против вопроса-точки» (`69` §3а) — внешнего
   подтверждения нет ни за, ни против.** Субагент 1 проверял целенаправленно и не нашёл
   ничего эквивалентного; ближайшее по смыслу («develop several competing hypotheses»,
   «hypothesis tree») — про исследовательский процесс, а не про форму задания. Это
   **собственное наблюдение системы**, и выдавать его за цитируемую практику Anthropic
   нельзя.
2. **Число «agent teams ≈ 7×»** — происхождение не установлено, официального аналога нет
   (см. §2.7).
3. **Шорткат `#` для быстрой записи в память** — на странице memory отсутствует, вытеснен
   механизмом auto memory; страница `interactive-mode`, где он мог сохраниться, не проверена.
4. **Не прочитаны четыре официальных ноутбука**, тематически ближайших к лаборатории:
   `misc/prompt_caching.ipynb`, `cost_optimization/cost_optimization.ipynb`,
   `patterns/agents/async_multi_agent_orchestration.ipynb`,
   `multimodal/using_sub_agents.ipynb`. Первые два могут содержать измеренные примеры
   экономии, прямо сопоставимые с `measurements.csv`.
5. **Не прочитана страница `prompting-claude-opus-5`** — на неё ссылаются два самых
   релевантных сюжета (over-verification и гасящий промпт против избыточного спавна
   субагентов). Самый ценный незакрытый адрес для следующей вахты.
6. **Не проверены `code.claude.com/docs/en/context-window` и `/how-claude-code-works`
   целиком** — там разбивка стартового контекста по байтам и раздел «What survives
   compaction», прямой материал под `61-token-analytics.md`.
7. **Числа 4× / 15× / 95 % / 80 %** сняты субагентом 1 через саммари страницы, а не
   построчной вычиткой. Домен официальный и дата есть, но если число пойдёт в базу как
   опорное — перечитать абзац дословно; список самих «трёх факторов» остался неполным.
8. **Ничего, что требует авторизации**, не проверялось (Console, Analytics API) — у метода
   были только публичные `WebSearch`/`WebFetch`.

---

## 6. Куда это ложится в системе (адреса, не правки)

Правки живых документов здесь **не сделаны намеренно** — маршрут называется, решение за
владельцем.

| Находка | Адрес |
|---|---|
| §2.1 параллельные форки и кэш, §2.2 `experimental.cacheTtl`, §2.4 срок годности 934K | `reports/experiments/token-consumption/hypothesis.md` — новым датированным разделом в конец, к записи от 28.08.2026 |
| §2.1 — предрегистрируемый OFAT (один запрос → первый токен → остальные N−1) | `hypothesis.md` §5, backlog экспериментов |
| §2.3 `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`, §2.5 ultrathink/`budget_tokens`, §2.7 число 7×, §3.9 минимум префикса у Haiku 4.5 | `00-infrastructure/49-token-economy-and-prompting.md` §1, §2а, §3, §4 |
| §1.1 потолок 8 блокировок, §2.8 форма `decision`, §3.6 31 событие хуков, §1.4 мотивировка урезания tools | `00-infrastructure/69-agents-hooks-and-gates.md` §1–§3 |
| §2.9 импорты не экономят контекст, 200 строк, `.claude/rules/*.md` (§3.5) | `00-infrastructure/27-claude-memory-and-instructions.md` |
| §3.7 `--restricted`, формулировка про `bypassPermissions` | `00-infrastructure/64-claude-code-sandbox.md`, `51-autonomous-agent-loop.md` §2 |
| §3.1 порядок сборки длинного промпта, §3.2 антипаттерны, §2.6 исключение Opus 5 | `00-infrastructure/49` §4 (playbook) и `07-writing-methodology.md` |
| §3.3 context rot | `00-infrastructure/61-token-analytics.md` — вторая ось: качество, не только цена |
| §3.10 смещение Opus 5 к делегированию | `00-infrastructure/66-model-and-effort-selection.md` |

---

## Источники

Официальные, блог (единственные датированные):
- https://www.anthropic.com/engineering/building-effective-agents — 19.12.2024
- https://www.anthropic.com/engineering/multi-agent-research-system — 13.06.2025
- https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents — 29.09.2025

Официальные, документация (**дат на страницах нет**, снято 28.08.2026):
- https://code.claude.com/docs/en/best-practices (сюда 308-редирект со старой статьи
  `anthropic.com/engineering/claude-code-best-practices`)
- https://code.claude.com/docs/en/memory · https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/sub-agents · https://code.claude.com/docs/en/agent-teams
- https://code.claude.com/docs/en/sandboxing · https://code.claude.com/docs/en/permission-modes
- https://code.claude.com/docs/en/context-window · https://code.claude.com/docs/en/model-config
- https://code.claude.com/docs/en/mcp
- https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices

Официальные, код и журнал версий:
- https://github.com/anthropics/claude-cookbooks/tree/main/patterns/agents (паттерны
  Prompt Chaining · Routing · Multi-LLM Parallelization · Orchestrator-Subagents ·
  Evaluator-Optimizer; каталог `prompts/` с `research_lead_agent.md`,
  `research_subagent.md`, `citations_agent.md`)
- https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md (даты версий —
  через GitHub Releases API `published_at`; сам CHANGELOG дат не содержит)
- `shared/prompt-caching.md` из бандл-скилла `claude-api` поставки 2.1.247 — официальная
  поставка Anthropic, **не публичная веб-страница**; помечено отдельно

Внутренние, с которыми сверялось:
- `reports/experiments/token-consumption/hypothesis.md` (записи от 27–28.08.2026)
- `00-infrastructure/49-token-economy-and-prompting.md` · `69-agents-hooks-and-gates.md`
- `00-infrastructure/51-autonomous-agent-loop.md` · `02-claude-workflow.md`
- `reports/research/agent-skill-plugin-sources-2026-08-28.md`
