# investigations/ — полные разборы расследований

Здесь лежат **полные investigation report'ы** — разборы подозрительных ситуаций, где реального
дефекта НЕ оказалось (внешнее / артефакт метода / недопонимание). Формат —
`../investigation_report_guide.md`. Сводки-строки — в реестре `../investigations_summary.md`.

Имя файла: `<тема>_investigation.md` (английский snake_case).

Автогенерация: разобрались, но реального дефекта нет → разбор сюда + строка в реестр, без просьбы
(`../../00-infrastructure/20-knowledge-capture-protocol.md`).

> **Что здесь лежит в самой base-repo:** расследования про **систему** — среду исполнения,
> инструменты, протоколы. Разборы про содержание конкретной репы остаются в ней.
> Граница и порядок повышения — `../README.md`.

## Три разбора с длинными именами-транслитом

Заведены до правила `<тема>_investigation.md`, имена — транслит первой строки
заголовка, обрезанный по длине. **Лежали недостижимыми** — найдено
`refcount.py --orphans` 04.09.2026.

| Файл | Вопрос |
|---|---|
| [`claude-code-dlya-sistemy-iz-41-repozitoriya-bazy-znaniy-anal.md`](claude-code-dlya-sistemy-iz-41-repozitoriya-bazy-znaniy-anal.md) | как Claude Code работает с системой из 41 репы-базы знаний |
| [`diagnoz-problemy-claude-ai-pro-you-re-out-of-usage-credits-p.md`](diagnoz-problemy-claude-ai-pro-you-re-out-of-usage-credits-p.md) | Claude.ai Pro: «You're out of usage credits» — что это на деле |
| [`kak-ubrat-claude-iz-soavtorov-git-kommitov-i-ochistit-istori.md`](kak-ubrat-claude-iz-soavtorov-git-kommitov-i-ochistit-istori.md) | как убрать Claude из соавторов коммитов и почистить историю |

🔴 **Имена обрезаны на полуслове** (`...-anal`, `...-p`, `...-istori`) — так
работал генератор, дававший имя из заголовка. Это ровно то, против чего
заведён стандарт `43`: **имя файла — адрес, а не пересказ содержания.**

**Не переименованы:** переименование обрывает ссылки, которые могли остаться
в чужих репах и в истории; находятся они теперь через этот навигатор.
Правило действует для новых разборов.
