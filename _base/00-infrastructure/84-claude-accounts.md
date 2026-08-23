# 84. Аккаунты Claude: идентификаторы, границы, что даёт Team

> **Решение владельца 21.08.2026: файл живёт здесь, в базе.** Обоснование его же —
> **база приватная и раздаётся только приватным репам**. Первая редакция лежала
> в `mission-control` из опасения «раздастся в 57 реп»; владелец это опасение снял.
>
> 🔴 **Опасение было проверяемым, и предохранитель существует — не список, а факт.**
> `mission-control/scripts/sync-base.sh` перед раздачей спрашивает GitHub:
> ```bash
> [ "$(gh repo view "$O/$n" --json isPrivate --jq '.isPrivate')" = "false" ] && continue
> ```
> Публичная репа базу **не получает**, как бы ни выглядел список исключений.
> Это исполнение PIT-097 («список — намерение, свойство объекта — факт»).
>
> **Замер 21.08.2026:** `_base/` нет **ни в одной** из восьми публичных реп —
> `finpilot`, `vk-graph`, `bron-kerbosch`, `health-report-generator`,
> `algorithms-site`, `game-analytics-engine`, `claude-usage`, `salvation`.
> Предохранитель работает, а не только описан.
>
> **Org ID — не секрет:** сам по себе доступа не даёт, в отличие от токена
> (`00-CLAUDE-STOP.md` §2 не нарушается).

---

## Идентификаторы

| Вахта | Org ID | Продление подписки |
|---|---|---|
| **V** | `7cc76e8d-50ee-4d9e-a37d-e66972d7a846` | 14.09, 20:10 |
| **S** | `a583ff32-acec-4f10-90cd-d506845d9e6a` | 18.09, 09:00 |
| **J** | `bc43a107-d24a-4365-9b9e-ec7f590f6932` | — |
| **M** | `eb2988ac-e9ba-4fb0-9b05-29ea9cd46abb` | — |

**Даты продления — внешние сроки.** Пропущенное продление обрывает вахту посреди
работы. По J и M дат нет — дополнить. Дублировать в календарь: файл не напомнит.

---

## Что достаётся с машины автоматически

Снято 21.08.2026 командой `claude auth status` и из `~/.claude.json` → `oauthAccount`.
**Только по залогиненному аккаунту** — остальные три так не проверяются.

| Поле | Значение (вахта V) | Откуда |
|---|---|---|
| `orgId` | `7cc76e8d-50ee-4d9e-a37d-e66972d7a846` | `claude auth status` |
| `email` | `vevdokimovm@gmail.com` | `claude auth status` |
| `authMethod` | `claude.ai` | `claude auth status` |
| `subscriptionType` | `pro` | `claude auth status` |
| `organizationType` | `claude_pro` | `.claude.json` |
| `organizationRole` | **`admin`** | `.claude.json` |
| `organizationRateLimitTier` | `default_claude_ai` | `.claude.json` |
| `accountCreatedAt` | `2026-01-23T17:35:45Z` | `.claude.json` |
| `subscriptionCreatedAt` | `2026-03-10T18:59:06Z` | `.claude.json` |
| `billingType` | `stripe_subscription` | `.claude.json` |
| `hasExtraUsageEnabled` | `false` | `.claude.json` |

Проверить сейчас:

```bash
claude auth status
python3 -c "import json,os;print(json.dumps(json.load(open(os.path.expanduser('~/.claude.json')))['oauthAccount'],ensure_ascii=False,indent=1))"
```

### 🔴 Даты продления среди этих полей НЕТ

`subscriptionCreatedAt` — дата **создания** подписки, и она её не заменяет:
подписка создана **10.03 в 18:59**, а в таблице выше стоит **14.09 в 20:10** —
не сходится ни числом, ни временем. Значит дата взята из письма Stripe или из
`claude.ai/settings/billing`, и **выводить продление из даты создания нельзя**.
Единственный источник — биллинг, CLI его не знает.

### Что подтвердилось само

- **Org ID вахты V сверен машинно** — совпал с записанным. Раньше это было
  переписанное вручную число, теперь проверенное.
- **`hasExtraUsageEnabled: false`** согласуется с `overageStatus: rejected`
  из логов лимитов: при упоре работа **встаёт**, а не идёт платно.
  Два независимых источника сошлись.

---

## 🔴 Объединить четыре аккаунта на Pro НЕЛЬЗЯ — и вот граница

Ресёрч 21.08.2026 по документации Anthropic. Вопрос владельца: *«для чего он вообще
тогда? как-то можно объединить в общую систему?»*

### Что говорит документация дословно

> **The Admin API is unavailable for individual accounts.**
> To collaborate with teammates and add members, set up your organization in
> **Console → Settings → Organization**.

`organizationType` = `claude_pro` — это **личная** организация Pro-подписки.
`organizationRole: admin` в ней означает «админ самого себя» и **Admin API не открывает**.

### Что закрыто вместе с Admin API

| API | Что даёт | Доступно на Pro |
|---|---|---|
| **Admin API** | участники организации, роли, приглашения, рабочие пространства | ❌ |
| **Claude Code Analytics** | **сессии, токены, стоимость, принятия/отказы инструментов — по каждому участнику** | ❌ |
| **Usage & Cost** | расход и деньги по всей организации | ❌ |
| **Rate Limits API** | сконфигурированные лимиты организации | ❌ |
| **Compliance API** | аудит и лента активности | ❌ |

### Чем org ID полезен НА PRO — честно, три вещи

1. **Опознание вахты.** `claude auth status` отдаёт `orgId` — по нему видно,
   какой аккаунт ведёт сессию, без вопросов человеку. Единственное применение,
   которое работает сегодня.
2. **Сверка записи с фактом.** Записанный ID можно подтвердить командой, а не памятью.
3. **Ключ на будущее.** Если появится Team — эти ID и станут точками, по которым
   организации сводятся.

**Всё остальное — нет.** Ни общего контекста, ни передачи сессии, ни чужих лимитов:
`claude agents --json` показывает сессии **только текущего пользователя ОС**
(`base-repo/00-infrastructure/50` §4).

---

## Что откроет Team — если решишь переходить

Это **единственный** способ получить то, что владелец описывал как «объединить
в общую систему». Не «может быть», а прямо документированный путь:
Console → Settings → Organization.

**Claude Code Analytics API** после перехода даёт **по каждому участнику за день**:

- `num_sessions` — число сессий
- `lines_of_code.added / removed`
- `commits_by_claude_code`, `pull_requests_by_claude_code`
- принятия и отказы по каждому инструменту (`edit`, `multi_edit`, `write`, `notebook_edit`)
- **разбивку по моделям:** `tokens.input / output / cache_read / cache_creation`
  и `estimated_cost.amount` **в центах**
- `terminal_type` — где именно работали (`iTerm.app`, `vscode`, `tmux`)

Данные с задержкой до часа, хранятся без срока, **API бесплатен** для всех,
у кого есть доступ к Admin API.

### Почему это стоит рассмотреть отдельно от цены

Половина того, что делает `claude-usage` (`base-repo`, свой инструмент), на Team
приходит готовым и **по всем четырём вахтам сразу**, а не по одной машине.
Своё останется ценным там, где официального нет: **рост контекста по ходам,
цена хода по бакетам, TTL записи в кэш, машинное время сброса лимита**.

**Чего Team не отменяет:** передачу живой сессии между аккаунтами.
Сессия принадлежит аккаунту CLI (`base-repo/06-autonomous-mode-kit/SWITCHES.md` §4),
и это ограничение продукта, а не плана.

**Решение не принято.** Записано, чтобы вопрос «а можно ли объединить» больше
не переоткрывался: **на Pro — нет, на Team — да, вот ровно что откроется.**

---

## Связки

`50-parallel-accounts-and-admin-orchestration.md` §2а (граница Admin API, правило) ·
`06-autonomous-mode-kit/SWITCHES.md` §4 (сессия принадлежит аккаунту CLI) ·
`reports/experiments/token-consumption/` (свои замеры расхода) ·
`59-public-mirror-filter.md` (что не уезжает в публичное) ·
`mission-control/scripts/sync-base.sh` (предохранитель раздачи по `isPrivate`).
