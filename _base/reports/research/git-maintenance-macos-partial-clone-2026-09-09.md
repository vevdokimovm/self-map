# `git maintenance` для partial+shallow knowledge-репозиториев на macOS

> Дата: 09.09.2026 · git 2.50.1 (Apple Git-155) · macOS 15.7.7 (24G720)
> Профиль: 4 (в перспективе 67) репозитория, `--filter=blob:none --depth 1`,
> живут локально годами, редкие правки, канал — рвущийся мобильный хотспот.
> Смежный документ: `reports/research/git-in-working-copies-mechanics-2026-09-09.md`
> (§«Разрастание и обслуживание») — там та же тема снята только по документации,
> здесь она **проверена экспериментом** и в двух местах поправлена.

---

## Прямой ответ

**Фоновое обслуживание включать не нужно, и в этом профиле оно почти целиком
бесполезно.** Причины по убыванию весомости:

1. **Скорость не страдает.** Между 0, 800 и 7800 loose-объектами разница
   `git status`, `git add .`, `git log --oneline -50` — **в пределах шума
   таймера** (0.020–0.030 с, разрешение `/usr/bin/time -p` = 10 мс). Ни одно
   измерение не подтверждает «git тормозит без gc» на этом профиле.
2. **Порог `gc.auto`=6700 наступит через 7–46 лет** (4.00 loose-объекта на
   коммит → 1675 коммитов до порога).
3. **Когда он наступит — `git commit` вызовет `gc` сам и оффлайн.** Проверено:
   демон для этого не нужен.
4. **Половина задач инкрементального расписания в shallow-клоне даёт
   тождественный ноль** (`commit-graph` при `--depth 1` не создаёт файла вообще),
   а одна — сетевая (`prefetch`), то есть ровно то, чего на рвущемся хотспоте
   быть не должно.

**Что делать вместо:** ничего не регистрировать; раз в несколько месяцев, когда
удобно, руками `git gc` (или `git maintenance run --task=gc`) — 0.5 с, минус 86 %
от размера `.git`. Всё. Подробный рецепт — §6.

**Единственный аргумент за обслуживание — диск, и он слабый:** 12-кратное
раздутие `.git` (3.4 МБ против 0.5 МБ на 200 коммитов), ~1.8 МБ лишних в год при
10 коммитах/мес. На фоне порогов 50/100/500 МБ — незначимо.

---

## Как это исследовалось (процесс)

**Классификация запроса: breadth-first** — пять почти независимых под-вопросов
(состав задач · пути включения · механика launchd · нужность для partial+shallow ·
ручной режим), каждый отвечается своим набором экспериментов, а не разными
ракурсами на один вопрос.

Рассмотрено три способа ответить: **(а)** свести документацию `git-maintenance(1)`
и `git-config(1)`; **(б)** только эксперимент в песочнице; **(в)** гибрид —
эксперимент как источник фактов, документация как источник дефолтов и
формулировок. Выбран **(в)**: путь (а) уже пройден в смежном документе и,
как выяснилось, дал **две ошибки** (см. §7), а путь (б) не даёт дефолтов, потому
что они в конфиг не записываются вообще (§1.3).

**Четыре субагента, запущены параллельно одним сообщением:**

| # | Угол | Инструмент |
|---|---|---|
| 1 | состав задач, дефолты `enabled`, включение без `prefetch` | эксперимент, 14 вызовов |
| 2 | механика launchd: plist, `register`/`start`/`stop`/`unregister`, 67 реп | эксперимент, 19 вызовов |
| 3 | `gc` в partial+shallow, `gc.auto`, риск удаления/докачки, ручной режим | эксперимент, 24 вызова |
| 4 | первоисточники: man 2.50.1, kernel.org, RelNotes, lore.kernel.org | 18 вызовов |

Второго круга не было: ответ на исходный вопрос собран после первого,
противоречий между субагентами по существу не нашлось.

⚠️ **Побочный эффект параллельности, честно:** субагенты 1 и 2 реально
регистрировали песочные репозитории, поэтому на несколько минут в
`~/.gitconfig` владельца появлялись четыре записи `maintenance.repo`
(`/private/tmp/gitmaint-*`) и три `org.git-scm.git.*.plist` в
`~/Library/LaunchAgents/`. Оба откатились; я независимо проверил после
завершения — `~/.gitconfig` вернулся байт в байт, git-плистов не осталось.
Из-за наложения по времени субагент 1 в своём отчёте написал, что
«`git maintenance start` на этой машине никогда не запускался» — это верно про
исходное состояние машины и неверно про момент его проверки: plist'ы в ту
секунду стояли, поставленные субагентом 2. Артефакт метода, не расхождение
о предмете.

---

## 1. Состав задач, дефолты, цена

### 1.1 Полный список — девять задач

Ровно девять в 2.50: `commit-graph`, `prefetch`, `gc`, `loose-objects`,
`incremental-repack`, `pack-refs`, `reflog-expire`, `rerere-gc`,
`worktree-prune`. Последние три — **новые в 2.50**: RelNotes прямо говорят
*«Make repository clean-up tasks that "gc" can do available to "git maintenance"
front-end»* и *«"git maintenance" learns a new task to expire reflog entries»*.
<https://raw.githubusercontent.com/git/git/master/Documentation/RelNotes/2.50.0.adoc>

| задача | что делает | подпроцессы (снято `GIT_TRACE=1`) | сеть |
|---|---|---|---|
| `commit-graph` | инкрементально пишет и верифицирует commit-graph | `git commit-graph write --split --reachable --no-progress` | нет |
| `prefetch` | `git fetch` по каждому remote, refspec переписан в `refs/prefetch/`, теги не обновляются | `git fetch origin --prefetch --prune --no-tags --no-write-fetch-head --recurse-submodules=no --quiet` | **ДА, единственная** |
| `gc` | *«repacks all Git objects into a single pack-file… deletes stale data»* | `git gc --quiet --no-detach` → `pack-refs`, `reflog expire`, `repack -d -l -q --cruft --cruft-expiration=2.weeks.ago`, 2× `pack-objects` | нет |
| `loose-objects` | удаляет loose, уже лежащие в паке; **затем** пакует пачку в пак `loose-…`. Batch 50 000 | `git prune-packed --quiet`, `git pack-objects … pack/loose` | нет |
| `incremental-repack` | multi-pack-index write/expire/repack | `multi-pack-index write`, `… expire`, `… repack --batch-size=1` | нет |
| `pack-refs` | сводит loose-рефы в один файл | `git pack-refs --all --prune` | нет |
| `reflog-expire` · `rerere-gc` · `worktree-prune` | обёртки над одноимёнными командами | внутренние, без `run_command` | нет |

<https://git-scm.com/docs/git-maintenance> · `man git-maintenance` (Apple Git-155)

**Сетевая ровно одна — проверено.** При заведомо битом remote
(`https://127.0.0.1:1/nonexistent.git`) восемь задач из девяти дают rc=0,
а `prefetch` — rc=1 и `fatal: unable to access … Failed to connect to 127.0.0.1
port 1` / `error: task 'prefetch' failed`.

### 1.2 Расписание `incremental` — и расхождение внутри самой документации

Итог (проверено `GIT_TRACE=1 git maintenance run --schedule=X`):
**hourly** — `prefetch`, `commit-graph`; **daily** — `+ loose-objects`,
`incremental-repack`; **weekly** — `+ pack-refs`. Расписания **вложенные**:
weekly-прогон выполняет и hourly-, и daily-задачи. `gc`, `reflog-expire`,
`rerere-gc`, `worktree-prune` при `incremental` не запускаются никогда.

🔴 Секция `register` в `man git-maintenance` 2.50.1 перечисляет
*«gc: disabled. commit-graph: hourly. prefetch: hourly. loose-objects: daily.
incremental-repack: daily»* — **и не упоминает `pack-refs`**, тогда как секция
`maintenance.strategy` на той же странице говорит *«…and the pack-refs task
weekly»*. Прав второй — эксперимент показал `git pack-refs --all --prune`
в weekly-прогоне. Это расхождение внутри одной man-страницы, найдено
независимо двумя субагентами.

Дефолт стратегии — `none`: *«This default setting implies no tasks are run at
any schedule»*. И приоритет: *«if a `maintenance.<task>.schedule` config value is
set, then that value is used **instead** of the one provided by
`maintenance.strategy`»*.

### 1.3 🔴 Дефолты `maintenance.<task>.enabled` в конфиг НЕ попадают

Документировано: *«By default, only `maintenance.gc.enabled` is true»*.

Проверено экспериментом — до и после `git maintenance register` все девять
`git config --get maintenance.<task>.enabled` возвращают пусто, rc=1.
`register` пишет ровно **три** ключа:

```
~/.gitconfig     maintenance.repo=<абсолютный путь>
.git/config      maintenance.auto=false
.git/config      maintenance.strategy=incremental
```

**Практический вывод: по конфигу невозможно узнать, что реально будет
запускаться.** Ни `git config --list`, ни `--show-origin` не покажут ни одного
`enabled`/`schedule` — всё расписание выводится в коде из строки
`maintenance.strategy=incremental`. Единственный способ увидеть план —
`GIT_TRACE=1 git maintenance run --schedule=…`. Опции `--dry-run` в 2.50 нет:
`error: unknown option 'dry-run'`.

### 1.4 Ловушка: голый `git maintenance run` запускает именно `gc`

Проверено: в репозитории со `strategy=incremental` команда `git maintenance run`
**без** `--schedule` запускает `git gc --quiet --no-detach` — ровно ту задачу,
которую `incremental` намеренно отключает. `maintenance.strategy` влияет
**только** на прогоны с `--schedule`; голый `run` смотрит исключительно на
`maintenance.<task>.enabled`, где по умолчанию true один `gc`.

### 1.5 Цена задач

Стенд: 30 коммитов + 200 файлов, `.git` = 1296 КБ, 292 loose-объекта.

```
prefetch            0.08 s   +4 КБ        commit-graph        0.05 s   +8 КБ
loose-objects       0.14 s  +32 КБ        incremental-repack  0.05 s  +12 КБ
pack-refs           0.03 s   −8 КБ        reflog-expire/rerere-gc/worktree-prune  ~0.03 s, 0
gc                  0.18 s  −1180 КБ  (1344 → 164 КБ, в 8 раз)
```

Инкрементальные задачи на этом масштабе — десятки миллисекунд, и они
**увеличивают** `.git`: создают новые паки, старое удаляется только следующим
`expire`. Единственная, кто ужимает, — `gc`, и она же самая дорогая.
Это и есть тот trade-off, ради которого `incremental` её выключает.

---

## 2. Как включить без сетевого `prefetch`

### 2.1 `maintenance.prefetch.enabled false` — работает

Проверено при битом remote: после `git config maintenance.prefetch.enabled false`
прогон `--schedule=hourly` выполняет только `commit-graph write`, fetch не
вызывается вообще (битый URL не сработал — значит в сеть не ходили).
**`enabled=false` перебивает расписание, унаследованное от стратегии.**

### 2.2 `maintenance.prefetch.schedule none` — тоже работает, но опасно

Работает и с валидным `none`, и — молча — с любой чушью: `schedule=bogus` даёт
rc=0 и просто не совпадает ни с одним расписанием, **без предупреждения**, хотя
man утверждает *«The value must be one of "hourly", "daily", or "weekly"»*.
Опечатка тихо убивает задачу. Пользоваться `enabled=false` — явнее.

### 2.3 🔴 `--task=` игнорирует `enabled` — и это документировано

```
git config maintenance.prefetch.enabled false
git maintenance run --task=prefetch
→ fatal: unable to access … / error: task 'prefetch' failed    rc=1
```

*«These config values are ignored if a `--task` option exists.»*
То есть `enabled=false` защищает **только** от автоматических и расписанных
прогонов; любой скрипт (и ты сам) может дёрнуть `--task=prefetch` и уйти в сеть.
<https://git-scm.com/docs/git-maintenance>

### 2.4 Путь «register + своё расписание»

`register` **не создаёт никакого планировщика** — проверено: crontab пуст,
plist'ов нет. После чистого `register` не запускается вообще ничего, пока не
поднимешь расписание руками. Опции `--schedule=` у `register`/`start` не
существует — она принадлежит только `run`; частота задаётся частотой вызова.
Готовые строки для cron документированы в man дословно:

```
0 1-23 * * * "/<path>/git" --exec-path="/<path>" for-each-repo --config=maintenance.repo maintenance run --schedule=hourly
0 0 * * 1-6 …--schedule=daily
0 0 * * 0   …--schedule=weekly
```

### 2.5 `--auto`

`--auto` и `--schedule` взаимоисключающи (`fatal: use at most one of --auto and
--schedule=<frequency>`). `--auto` = пересечение двух условий: задача включена
через `enabled` **и** перейдён её собственный порог. Дефолты порогов:
`maintenance.commit-graph.auto`=100, `loose-objects.auto`=100,
`incremental-repack.auto`=10, `reflog-expire.auto`=100, `rerere-gc.auto`=1,
`worktree-prune.auto`=1. На штатных настройках `--auto` практически всегда
означает «может быть gc, если накопилось». Проверено: `--auto` при 303 loose
не сделал ничего, а `git -c gc.auto=10 maintenance run --auto` запустил gc.

---

## 3. Механика на macOS

### 3.1 Что создаёт `git maintenance start`

Ровно **три** файла: `~/Library/LaunchAgents/org.git-scm.git.{hourly,daily,weekly}.plist`
(2.9 КБ / 1.6 КБ / 924 Б). `launchctl list | grep -i git`:

```
-	0	org.git-scm.git.daily
-	0	org.git-scm.git.weekly
-	0	org.git-scm.git.hourly
```

Команда во всех трёх одна с точностью до `--schedule`:

```
/Library/Developer/CommandLineTools/usr/libexec/git-core/git \
  --exec-path=/Library/Developer/CommandLineTools/usr/libexec/git-core \
  -c credential.interactive=false -c core.askPass=true \
  for-each-repo --keep-going --config=maintenance.repo \
  maintenance run --schedule=<hourly|daily|weekly>
```

`credential.interactive=false` + `core.askPass=true` — чтобы фоновый прогон
никогда не всплыл с запросом пароля (это про `prefetch`). `--keep-going` —
одна упавшая репа не рвёт обход остальных.

| plist | StartCalendarInterval |
|---|---|
| hourly | Hour **1–23**, Minute 21 — 23 записи, **часа 0 нет** |
| daily | Weekday **1–6**, Hour 0, Minute 33 — 6 записей, воскресенья нет |
| weekly | Weekday 0, Hour 0, Minute 47 — одна запись |

Часы не пересекаются by design: *«Each run executes the "hourly" tasks. At
midnight, that process also executes the "daily" tasks. At midnight on the first
day of the week, that process also executes the "weekly" tasks»*; минуты
21/33/47 случайны — *«scheduled to a random minute of the hour per client to
spread out the load»*.

🔴 **Логов нет вообще.** Ключей `StandardOutPath`/`StandardErrorPath` в
plist'ах нет ни в одном — значит оба потока идут в `/dev/null` по дефолту
launchd. Если `prefetch` каждый час бьётся об оборванный хотспот, ты об этом
не узнаешь никак. Свои ключи добавить можно, но `git maintenance start` их
перезатрёт: *«git maintenance start will overwrite these files… so any
customizations should be done by creating your own .plist files with distinct
names»*.

Из `launchctl print gui/501/org.git-scm.git.hourly`: `SSH_AUTH_SOCK`
наследуется (значит `prefetch` по SSH в принципе может работать), а `PATH`
урезан до `/usr/bin:/bin:/usr/sbin:/sbin` — отсюда полный путь и `--exec-path`
в аргументах.

### 3.2 `register` без `start` — plist'ов не создаёт

Проверено: `diff` каталога LaunchAgents до и после — без изменений,
`launchctl list | grep -i git` пуст. `register` — чисто конфигурационная
операция. *«start — This performs the same config updates as the register
subcommand, then updates the background scheduler…»*

### 3.3 Снятие: `stop`, `unregister` и то, что остаётся навсегда

- **`stop`** снимает все три plist'а и выгружает сервисы, **конфиг не трогает
  ни глобальный, ни локальный**. Операция общесистемная: вызванный в одной репе,
  гасит расписание для всех. *«The current repository is not removed from the
  list of maintained repositories.»*
- **`unregister`** убирает только свою строку из `maintenance.repo`.
  Plist'ы не трогает. *«It does not stop the background maintenance processes
  from running.»* Повторный вызов → `fatal: repository '...' is not registered`,
  **rc=128**; с `--force` → rc=0. Для цикла по 67 репам под `set -e` — **всегда
  `--force`**.

🔴 **Главная грабля.** `maintenance.auto=false` и `maintenance.strategy=incremental`
остаются в локальном `.git/config` **навсегда** — переживают и `stop`, и
`unregister`, и `unregister --force`. Проверено на трёх репозиториях.
Про первый ключ man Apple Git-155 честно предупреждает: *«will also disable
foreground maintenance by setting `maintenance.auto = false` in the current
repository. **This config setting will remain after a `git maintenance
unregister` command.**»* Про то, что `maintenance.strategy` тоже остаётся,
документация **молчит** — это ненаблюдаемое в доках поведение.

**Последствие:** репозиторий, который однажды зарегистрировали и потом
отменили, **больше никогда не делает авто-`gc`** после `commit`/`fetch`/`merge`
(`maintenance.auto` по умолчанию true, и `register` глушит его локально).
Фонового расписания уже нет, foreground выключен — репа остаётся без
обслуживания вообще, и loose-объекты копятся бесконечно. Лечится только руками:
`git config --unset maintenance.auto && git config --unset maintenance.strategy`.

### 3.4 Много репозиториев: 67 реп = те же 3 plist'а

Проверено на трёх песочных репах: plist'ов по-прежнему три, и они **побитово
не изменились** (md5 `hourly.plist` до и после регистрации r2/r3 совпадает,
mtime тот же). Масштабирование идёт через многозначный ключ:

```
[maintenance]
	repo = /path/r1
	repo = /path/r2
	repo = /path/r3
```

`git for-each-repo --config=maintenance.repo` читает его в момент запуска и
обходит **последовательно, в один поток**. Документированное следствие:
*«Depending on the number of registered repositories and their sizes, this
process may take longer than an hour. In this case, multiple git maintenance run
commands may run on the same repository at the same time, colliding on the
object database lock. This results in one of the two tasks not running.»*
Для 67 небольших текстовых реп это секунды — риск не про твой случай.
А вот `prefetch` — это **67 сетевых `git fetch` подряд каждый час**.
Точечно исключить remote: `remote.<name>.skipFetchAll` — *«ignored by the
prefetch task of git maintenance»*.

Ещё: путь в `maintenance.repo` абсолютный и фиксированный. Переименуешь или
перенесёшь репу — запись протухнет, `unregister` из несуществующего пути уже не
сработает, чистить придётся `git config --global --unset-all maintenance.repo <regex>`.

### 3.5 Отличия от других планировщиков

| ОС | Механизм | Где живёт | Как посмотреть |
|---|---|---|---|
| macOS | launchctl | `~/Library/LaunchAgents/org.git-scm.git.{hourly,daily,weekly}.plist` | `launchctl list \| grep -i git` |
| POSIX | cron | блок между `# BEGIN GIT MAINTENANCE SCHEDULE` и `# END …` | `crontab -l` |
| Linux | systemd user timers | `~/.config/systemd/user/git-maintenance@.{timer,service}` | `systemctl --user list-timers` |
| Windows | schtasks | задачи `Git Maintenance (<frequency>)` | Task Scheduler |

Содержательная разница: на cron — три строки и **минута всегда 0** (не
рандомизируется), на launchd — 23+6+1 = 30 явных временных точек и случайная
минута. Почему на macOS не cron — документировано: *«git maintenance start
interacts with the launchctl tool, which is the recommended way to schedule
timed jobs in macOS… requires some launchctl features available only in
macOS 10.11 or later»*.

Проверено: `--scheduler=crontab` и `--scheduler=schtasks` на этой машине
**недоступны** (`fatal: crontab scheduler is not available`, rc=128), причём
команда отваливается атомарно — ни crontab, ни plist'ов, ни записи в конфиг.
На macOS 15.7.7 реальный выбор один — `launchctl`, и `auto` берёт именно его.

⚠️ **Неизвестно:** снимает ли `start` с новым `--scheduler` расписание с
предыдущего. В man 2.50.1 этого нет; фраза *«when git maintenance start
--scheduler=XXX is run, it removes git maintenance run tasks from all other
schedulers»* найдена только в описании патч-серии
(<https://patchwork.kernel.org/project/git/patch/20210823204011.87023-3-lenaic@lhuard.fr/>) —
это не документация. Проверить экспериментом на этой машине нельзя: второй
планировщик недоступен.

---

## 4. Нужно ли обслуживание partial+shallow клону

### 4.1 Стенд

`srv`: 300 коммитов, 40 файлов по ~4 КБ. `git clone --filter=blob:none --depth 1
file:///…` — **фильтр через `file://` работает** при `uploadpack.allowFilter=true`.
Клон: `in-pack: 43, packs: 2, .git = 216 КБ`, `.git/shallow` — одна строка.

🔴 **Важный факт, которого не было видно на этапе плана:** при
`--filter=blob:none --depth 1` после чекаута в клоне **физически нет ни одного
отсутствующего объекта** — всё достижимое от HEAD уже скачано, promisor-паки
помечены «на всякий случай». Поэтому опасные операции прогонялись ещё и на
втором стенде — `--filter=blob:none` без `--depth`, где реально отсутствуют
**260 исторических блобов**.

### 4.2 Сколько мусора набегает

200 локальных коммитов:

| метрика | значение |
|---|---|
| loose-объектов на коммит | **4.00** (коммит + корневое дерево + подкаталог + блоб) |
| диск на loose-объект | 4 КБ (блок APFS; полезных данных ~0.7 КБ) |
| прирост `.git` на коммит | ~17.6 КБ |
| то же после `gc` | 1.44 КБ |
| **цена «не делать gc»** | **~16 КБ на коммит, 12× раздутие** |

### 4.3 Когда сработает `gc.auto`=6700

6700 / 4.00 = **1675 коммитов**.

| темп | до порога |
|---|---|
| 3 коммита/мес | ~46 лет |
| 10/мес | **~14 лет** |
| 20/мес | ~7 лет |
| 50/мес | ~2.8 года |

Оговорка из документации: *«When there are **approximately** more than this many
loose objects… The default value is 6700»* — git не считает объекты точно,
а оценивает по одному подкаталогу `objects/17/` × 256, так что точка
срабатывания гуляет. <https://git-scm.com/docs/git-config>

### 4.4 Скорость: честные числа

`/usr/bin/time -p`, 5 прогонов, avg/min:

| команда | 0 loose | 800 loose | **7800 loose** | после `gc` |
|---|---|---|---|---|
| `git status --porcelain` | 0.022/0.020 | 0.022/0.020 | 0.024/0.020 | 0.020/0.020 |
| `git log --oneline -50` | 0.020/0.020 | 0.030/0.030 | 0.030/0.030 | 0.020/0.020 |
| `git add .` | 0.022/0.020 | 0.022/0.020 | 0.020/0.020 | 0.020/0.020 |

**Разница в пределах шума.** Разрешение таймера 10 мс, все значения — 2–4 тика.
Даже 7800 loose-объектов (30 МБ) не замедлили `status`/`add` вообще.
Единственное измеримое — `log --oneline -50`: +10 мс, ровно один тик.
Заявлять ускорение от `gc` на этом профиле нельзя.

Что `gc` реально меняет — диск: 7800 loose = `.git` 31 МБ → после
`gc --prune=now` **504 КБ**, в 60 раз. Время самого `gc`: 0.47 с на 800
объектах, 1.47 с на 7800.

### 4.5 `gc.auto` срабатывает сам, оффлайн

При `gc.auto=10`, `gc.autoDetach=false`, **недоступном** remote:

```
ДО:              count: 800  in-pack: 43   packs: 2
git commit …
ПОСЛЕ commit:    count: 0    in-pack: 847  packs: 3
```

| команда | дёрнула auto-gc |
|---|---|
| `git commit` | **да** (800 → 0 loose) |
| `git rebase` | **да** (800 → 3) |
| `status` · `log` · `branch` · `checkout` · `add` | нет |
| `git merge` | **не подтверждено** — прогон оказался неинформативным |

`gc.autoPackLimit`: при 8 паках и лимите 3 команда напечатала `Auto packing the
repository for optimum performance.` и свела 8 паков → 2 (promisor остался
отдельным). При дефолте 50 в этом профиле не сработает никогда — паки не
плодятся без `fetch`.

**Вывод: демон не нужен, чтобы репозиторий не зарос. `git commit` вызовет `gc`
сам при достижении порога, и сделает это без сети.**

### 4.6 🔴 Риск в partial clone: не подтвердился

Все прогоны — при **переименованном каталоге сервера** (fetch падает).

Стенд partial+shallow, 800 loose:

| операция | rc | время | `.git` | promisor | `.git/shallow` | `fsck` |
|---|---|---|---|---|---|---|
| `git gc` | 0 | 0.51 с | 3512 → **504 КБ** | 2 → 1, сохранён | цел | чисто |
| `git repack -adf` | 0 | 0.36 с | 3512 → 520 КБ | 2 → 1, сохранён | цел | чисто |
| `--task=incremental-repack` | 0 | 0.05 с | +4 КБ | не тронуты | цел | чисто |
| `--task=loose-objects` | 0 | 0.25 с | 3512 → **4192 КБ** | не тронуты | цел | чисто |

Стенд partial с **260 реально отсутствующими блобами**, remote OFF: после
`gc`, `repack -adf`, `incremental-repack`, `loose-objects` — во всех четырёх
случаях missing 260 → **260**, promisor-пак сохранён, `fsck` чист.

- **(а) Удалит ли нужное — нет.** `fsck` чист после каждой операции,
  `rev-list --count HEAD` не изменился, `checkout` на старую ветку и
  `cat-file` по блобу из HEAD работают оффлайн. `gc --prune=now` удаляет
  **недостижимые** loose-объекты — это штатно и содержимого promisor-паков
  не касается.
- **(б) Докачки не происходит.** Ни одна операция не попыталась связаться с
  недоступным remote.
- **`.promisor` сохраняется.** После `gc`/`repack -adf` остаётся один
  promisor-пак, и он **не слит** с обычным. Документировано дословно:
  *«Promisor packfiles are repacked separately: if there are packfiles that have
  an associated ".promisor" file, these packfiles will be repacked into another
  separate pack, and an empty ".promisor" file corresponding to the new separate
  pack will be written.»* <https://git-scm.com/docs/git-repack> И в дизайн-нотах:
  *«Repack essentially treats promisor and non-promisor packfiles as 2 distinct
  partitions and does not mix them.»*
  <https://www.kernel.org/pub/software/scm/git/docs/technical/partial-clone.html>
- **`.git/shallow` не трогается** ни одной операцией — файл побайтово идентичен
  до и после во всех прогонах. Единственное документированное касание shallow в
  цепочке gc — в `git-prune(1)`: *«It also removes entries from `.git/shallow`
  that are not reachable by any ref»*.

⚠️ Одна замеченная неприятность: `git repack -adf` пересчитывает дельты и
**ухудшил** упаковку — `size-pack` 281 → **397 КБ** (+41 %). Флаг `-f` на этом
профиле бесполезен и вреден.

📌 Отдельно стоит знать: в `man git-gc` 2.50.1 слова `shallow`, `promisor`,
`partial` **не встречаются вообще** (проверено грепом всей страницы).
Предупреждений о том, что gc/prune в partial clone может потребовать докачки,
в документации нет — ни в `git-gc(1)`, ни в `git-prune(1)`. Эксперимент это
молчание подтверждает: докачки не происходит.

---

## 5. Ручной `git maintenance run --task=<t>`

Каждая задача — на свежей копии клона (800 loose, `.git` = 3512 КБ, 2 пака),
remote недоступен.

| задача | rc | real | `.git` КБ | что появилось | полезна? |
|---|---|---|---|---|---|
| `gc` | 0 | **0.47 с** | 3512 → **504** (−86 %) | — | **ДА, единственная с эффектом** |
| `commit-graph` | 0 | 0.04 с | 3512 → 3512 (**0**) | **ничего** | **НЕТ** |
| `loose-objects` | 0 | 0.25 с | 3512 → **4192** (**+680**) | пак `loose-…`, `prune-packable: 800` | вредна в одиночном запуске |
| `incremental-repack` | 0 | 0.05 с | +4 | `multi-pack-index`, 2.4 КБ | НЕТ |
| `pack-refs` | 0 | 0.04 с | −20 | `packed-refs` уже был | НЕТ (шум) |
| `prefetch` | **1** | 0.04 с | — | — | сетевая, падает |
| `run` без опций | 0 | 0.57 с | 3512 → 504 | ничего сверх gc | = `gc` |

Разбор трёх неочевидных:

- 🔴 **`commit-graph` при `--depth 1` — тождественный ноль.** Задача выходит с
  rc=0 и **не создаёт ни файла**: `.git/objects/info/` пуст. Явный
  `git commit-graph write --reachable` тоже молча ничего не пишет, потому что
  `git rev-parse --is-shallow-repository` = `true`. Контроль на обычном клоне
  того же сервера: файл создаётся, 19 КБ — но и там ускорять нечего:
  `git log --oneline` по 300 коммитам даёт **0.023 с с graph и 0.023 с без**.
  При `--depth 1` истории ровно один коммит.
- 🔴 **`loose-objects` в одиночном запуске делает хуже.** Она не удаляет
  loose-объекты в первом проходе: создаёт пак `loose-…` с их копиями и
  оставляет оригиналы (`prune-packable: 800`), `.git` вырос на 680 КБ.
  Документировано: *«First, it deletes any loose objects that already exist in a
  pack-file… Second, it creates a new pack-file (starting with "loose-")
  containing a batch of loose objects»* — удаление произойдёт только на
  **следующем** запуске. Для режима «раз в несколько месяцев» это значит: либо
  два прогона подряд, либо просто `gc`, который делает то же за один проход.
- **`prefetch`** — rc=1, `error: failed to prefetch remotes`, репозиторий цел.
  На рвущемся хотспоте это ровно та задача, которую нельзя ставить в демон.

📌 И документированное предостережение, важное, если всё-таки решишь совмещать
режимы: *«the `git gc` command should not be combined with `git maintenance run`
commands. `git gc` modifies the object database but does not take the lock in
the same way as `git maintenance run`. If possible, use `git maintenance run
--task=gc` instead of `git gc`.»* Плюс отдельный конфликт задач:
*«it is not advisable to enable both the loose-objects and gc tasks at the same
time»*. <https://git-scm.com/docs/git-maintenance>

---

## 6. Рецепты

### 6.1 Рекомендуемый: ничего не включать

Раз в несколько месяцев, по настроению:

```bash
for r in ~/repos/*/; do
  [ -d "$r/.git" ] && git -C "$r" maintenance run --task=gc
done
```

0.5 с на репу, `.git` минус ~86 %, сети не касается, promisor и shallow целы.
Всё остальное — `commit-graph`, `incremental-repack`, `pack-refs`,
`loose-objects` — на этом профиле либо ноль, либо вред. `repack -f` не
использовать.

### 6.2 Если всё-таки нужен демон — без сети

```bash
git -C <первая-репа> maintenance start          # один раз: конфиг + 3 plist
for r in <остальные>; do
  git -C "$r" maintenance register              # только конфиг, plist не трогается
  git -C "$r" config maintenance.prefetch.enabled false   # 🔴 обязательно, до первого запуска
done
```

Останутся `commit-graph` (hourly), `loose-objects` + `incremental-repack`
(daily), `pack-refs` (weekly) — все локальные. Для shallow-клонов, напомню,
`commit-graph` не делает ничего.

### 6.3 Полное снятие — с двумя строками, которых git не делает сам

```bash
git maintenance stop                            # один раз: снимает 3 plist глобально
for r in <все репы>; do
  git -C "$r" maintenance unregister --force    # --force обязателен, иначе rc=128
  git -C "$r" config --unset maintenance.auto     # 🔴 иначе авто-gc навсегда выключен
  git -C "$r" config --unset maintenance.strategy
done
```

Без последних двух строк репозитории тихо останутся **без всякого**
обслуживания: фон снят, foreground заглушён конфигом (§3.3).

---

## 7. Что здесь исправляет прежнюю запись базы

`reports/research/git-in-working-copies-mechanics-2026-09-09.md`, §«Разрастание
и обслуживание» — две правки:

1. Там сказано «Инкрементальное расписание по умолчанию: `gc` — выключен,
   `commit-graph` и `prefetch` — ежечасно, `loose-objects` и
   `incremental-repack` — ежедневно». **Пропущен `pack-refs` — weekly**
   (подтверждено экспериментом; в самой man-странице список в секции `register`
   неполон, полный — в описании `maintenance.strategy`).
2. Там сказано, что `start` «выключает `maintenance.auto`» — верно, но не
   сказано главного: **этот ключ переживает `unregister` и остаётся навсегда**,
   вместе с `maintenance.strategy`. Это и есть настоящий риск массовой
   регистрации 67 реп, больший, чем ежечасный `prefetch`.

Не подтвердилось предположение оттуда же, что `gc` в partial clone рискован:
экспериментально — не рискован (§4.6). Формулировка «`git repack` специально
обновлён, чтобы не трогать promisor-паки» подтверждена и man-страницей, и
дизайн-нотами, и опытом.

---

## 8. Что осталось неизвестным

- **Дёргает ли `git merge` авто-gc.** Прогон оказался неинформативным (объекты
  уже были упакованы предыдущим коммитом). Документация говорит расплывчато —
  «some Porcelain commands».
- **Снимает ли `git maintenance start --scheduler=X` расписание с других
  планировщиков.** В man 2.50.1 этого нет; фраза есть только в описании
  патч-серии. Проверить на macOS нельзя — cron и schtasks тут недоступны.
- **Дословное подтверждение, что multi-pack-index не отслеживает
  promisor-паки.** Формулировка всплывала в поисковой выдаче по
  `technical/multi-pack-index`, но из первоисточника не снята.
- **Официальный список отличий Apple Git-155 от upstream 2.50.1.** Apple такого
  не публикует. По man-страницам расхождений нет: присутствуют все три новые
  задачи 2.50 и `maintenance.loose-objects.batchSize`.
- **Конкретный коммит за строкой RelNotes 2.50 «Fix for scheduled maintenance
  tasks on platforms using launchctl»** — не локализован.
- **Поведение при `gc.autoDetach=true`** (дефолт): в экспериментах detach
  гасили, чтобы видеть вывод. На 0.5 с работы это неважно, но фоновый gc
  в принципе может конкурировать за лок.

### Ограничение метода

`WebFetch` на `git-scm.com` в среде субагента-документалиста **блокировался
политикой домена**, поэтому документация снималась с локальных man-страниц
Apple Git-155 (они соответствуют upstream 2.50.1, футер
`Git 2.50.1.428.g0e8243, 2025-07-22`) и с зеркал kernel.org/MIT/raw.github.
На содержание это не повлияло — man и git-scm.com для 2.50.1 совпадают, — но
ссылки на git-scm.com в тексте выше указывают на страницу, а сверка велась по
man той же версии.
