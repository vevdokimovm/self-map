# reports/research — исследования по внешним источникам

> **Навигатор заведён 04.09.2026 01:45.** До него часть исследований лежала
> недостижимой — найдено `refcount.py --orphans`. Работа сделана и оплачена
> токенами, а следующая вахта не узнала бы о ней (`PIT-176`).

| Документ | О чём |
|---|---|
| [`agent-skill-plugin-sources-2026-08-28.md`](agent-skill-plugin-sources-2026-08-28.md) | откуда берутся агенты, скиллы, плагины Claude Code — первоисточники |
| [`claude-official-practice-vs-internal-2026-08-28.md`](claude-official-practice-vs-internal-2026-08-28.md) | официальная практика Anthropic против нашей внутренней |
| [`paradigms-and-contracts-2026-08-29.md`](paradigms-and-contracts-2026-08-29.md) | 🔴 ООП, ФП, контракты, кибернетика — **источник первой волны** `08-systems-theory-lab/OOP_MECHANISMS.md` |
| [`system-building-and-analysis-2026-08-29.md`](system-building-and-analysis-2026-08-29.md) | системные дисциплины: SE, resilience, SRE, эволюция ПО |
| [`systems-and-integration-2026-08-29.md`](systems-and-integration-2026-08-29.md) | интеграция систем |
| [`functional-music-and-focus-tools-2026-09-02.md`](functional-music-and-focus-tools-2026-09-02.md) | доказана ли «музыка для концентрации» (Endel, Brain.fm), ежедневные заметки, помодоро |
| [`git-in-working-copies-mechanics-2026-09-09.md`](git-in-working-copies-mechanics-2026-09-09.md) | 🔴 **механика локального `.git` в рабочих копиях**: почему git докачивает содержимое, когда файлы уже на диске. Контролируемым экспериментом найдена настоящая причина — `core.autocrlf`, а не выбор между `reset` и `read-tree` (`PIT-210`). Плюс: размер `.git` по трём осям, запрет ленивой докачки, `fsmonitor`, грабли macOS (NFD/NFC, +x через zip) |
| [`five-open-issues-local-git-2026-09-09.md`](five-open-issues-local-git-2026-09-09.md) | 🔴 **разбор пяти нерешённых мест схемы с локальным git** — что из них настоящая проблема. Две оказались несуществующими (Time Machine не работает вовсе, NFD-путей ноль), одна лечится `flock`, ленивую докачку запрещать вредно. 🔴 **И найдена шестая, которой в списке не было** — `extensions.partialClone` не стоял ни в одной репе, git считал их повреждёнными |
| [`git-maintenance-macos-partial-clone-2026-09-09.md`](git-maintenance-macos-partial-clone-2026-09-09.md) | 🔴 **включать ли `git maintenance` — вывод: НЕТ.** Скорость не страдает вовсе (0.02 с при 0 и при 7800 loose-объектах), порог авто-`gc` наступит через **~14 лет**, и `git commit` вызовет его сам, оффлайн. 🔴 Найдено: `maintenance.auto=false` **остаётся в конфиге навсегда** после `unregister` — репа больше никогда не делает авто-gc |

## Чем это отличается от соседей

| Каталог | Отвечает на |
|---|---|
| **`research/`** | как устроено **вне нас**: индустрия, наука, рынок |
| `investigations/` | что случилось **у нас** и почему |
| `experiments/` | что показал **наш замер** |
| `incidents/` | что **сломалось** и как чинили |

🔴 **Исследование устаревает по дате, а не по содержанию.** Дата в имени
обязательна: без неё непонятно, описывает документ нынешнее состояние рынка
или прошлогоднее.
