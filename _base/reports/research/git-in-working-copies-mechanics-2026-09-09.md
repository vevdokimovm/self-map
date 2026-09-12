# Механика `.git` в рабочих копиях: размер, докачка блобов, нагрузка, macOS

**Дата:** 09.09.2026 · **Метод:** lead agent + 5 параллельных субагентов (круг 1)
+ 1 субагент на разрешение противоречия (круг 2, с реальным экспериментом)
**Повод:** ADR-008 — заведение локального `.git` в 67 рабочих копиях
**Связки:** `reports/adr/adr_008_release_from_working_copy.md` ·
`scripts/git_adopt.py` · `00-infrastructure/80-mass-repo-automation.md`

---

## 🔴 Главный результат: `read-tree` не решает проблему, а откладывает её

`scripts/git_adopt.py` заменил `reset --mixed` на `read-tree` + `update-ref`
и зафиксировал в докстринге: *«Замер той же операции: 0 с, ноль байт из сети»*.
Замер верен. **Вывод из него — нет.**

Контролируемый эксперимент (git 2.50.1 Apple Git-155, macOS 15.7.7, репозиторий
`psf/requests`, ~170 файлов, история ~13 МБ) воспроизвёл обе стороны:

| вариант | условия | прирост `.git` | время | сетевых докачек |
|---|---|---|---|---|
| A | пустое дерево + `reset --mixed` | +24 КБ | 0.04 с | **0** |
| B | пустое дерево + `read-tree`+`update-ref` | +28 КБ | ~0 с | **0** |
| **C** | **дерево с файлами** + `reset --mixed` | **+760 КБ** | **85–120 с** | **122** |
| C2 | то же + `core.autocrlf=false` | +48 КБ | быстро | 2 (симлинки) |
| C3 | то же + `diff.renames=false` | +760 КБ | 118 с | 122 (без изменений) |
| **D** | **`read-tree` + затем просто `git status`** | **+768 КБ** | **122 с** | **122** |
| E | `reset --mixed --no-refresh` | +24 КБ | 0.03 с | 0 |

**Строка D — главная.** `read-tree` действительно бесплатен, но первый же
`git status` (или `diff`, или `add`) в этой репе делает ровно ту же докачку:
122 запроса, 122 секунды, те же объекты. Экономия не достигнута — она
перенесена на момент, когда владелец в следующий раз посмотрит статус.

### Настоящая причина — `core.autocrlf=input` в личном `~/.gitconfig`

Докачку запускает не `reset` и не `status` как таковые, а конвертация CRLF.
Путь кода (`git/git` master):

1. `refresh_index()` → `ie_modified()` (`read-cache.c:444`) → `ce_compare_data()`
   (`read-cache.c:231`) → `index_fd(..., OBJ_BLOB, ce->name, 0)`.
2. `index_fd()` (`object-file.c:942`): если `would_convert_to_git(istate, path)` —
   идёт в `index_mem()` → `convert_to_git()` → `crlf_to_git()` (`convert.c:502`).
3. 🔴 `crlf_to_git()` при `crlf_action ∈ {CRLF_AUTO, CRLF_AUTO_INPUT,
   CRLF_AUTO_CRLF}` (`convert.c:527`) **безусловно** — не только когда в файле
   есть CR — зовёт `has_crlf_in_index()` (`convert.c:224`).
4. `has_crlf_in_index()` вызывает `read_blob_data_from_index()` (`convert.c:231`) —
   это чтение **оригинального блоба из object database**, а не файла с диска.
5. При `blob:none` блоба нет → prosmisor-докачка, **по одному HTTP-запросу на файл**.

`convert_attrs()` (`convert.c:1362`): без записи в `.gitattributes` и при
`core.autocrlf=input` получается `CRLF_AUTO_INPUT`. При `core.autocrlf=false`
получается `CRLF_BINARY`, и первая строка `crlf_to_git()` возвращает 0 **до**
чтения блоба. Это и показал контроль C2.

На машине владельца: `git config --show-origin core.autocrlf` →
`file:/Users/vasyaevdokimov/.gitconfig  input`. Настройка глобальная, действует
на все 67 реп.

> **Хеширование локального файла — это не `sha1(file)`, а
> `sha1(convert_to_git(file))`, и конвертация подглядывает в старый блоб.**
> Отсюда вся ошибка рассуждения «файлы уже на диске, содержимое не нужно».

**Что из этого следует практически** (находка, не применённое решение):
`core.autocrlf=false` — локально в этих репах или на время операций — убирает
докачку целиком. `--no-refresh` (вариант E) её не убирает, а откладывает:
индекс остаётся без валидного stat-кеша, и следующая команда делает refresh.

---

## Как это исследовалось (прозрачность метода)

**Классификация:** breadth-first — пять почти независимых под-вопросов.
**Субагентов круга 1: пять**, по одному на вопрос: (1) анатомия `.git` и размер,
(2) модель идентификации и потребность в блобах по операциям, (3) partial clone
и ленивая докачка, (4) производительность и обслуживание, (5) macOS-грабли.
**Круг 2: один** — на разрешение противоречия между чтением исходников и
замером владельца, с правом запускать git в песочнице. Всего 6 субагентов,
~100 обращений к инструментам.

Проверка по своей базе сделана до веба: `adr_008_release_from_working_copy.md`
и `scripts/git_adopt.py` дали исходный замер, который потом оказался
интерпретирован неверно.

---

## 1. Из чего состоит `.git` и чем определяется размер

### Объекты

Четыре типа: `blob` (содержимое файла), `tree` (список записей каталога —
режим, имя, OID), `commit`, `tag` (аннотированный).
<https://git-scm.com/book/en/v2/Git-Internals-Git-Objects>

**Loose objects** — по файлу на объект в `objects/xx/yyyy…`, целиком zlib.
**Packfile** — `PACK` + версия + число объектов, далее записи с 3-битным типом и
variable-length размером, zlib-поток либо дельта; трейлер — контрольная сумма.
Типы `OBJ_OFS_DELTA` (смещение, эффективнее) и `OBJ_REF_DELTA` (по имени,
допускает thin pack). <https://git-scm.com/docs/gitformat-pack>

Дельта-сжатие управляется `pack.window` (сколько кандидатов на базу
рассматривается) и `pack.depth` (максимальная длина цепочки дельт: длиннее —
компактнее, но дороже чтение).
<https://git-scm.com/book/en/v2/Git-Internals-Packfiles>

`.idx` v2 (magic `0xff744f63`): fan-out 256×4 байта, таблица OID, таблица CRC32,
таблица 31-битных смещений с отдельной таблицей «больших» смещений для паков
>4 ГиБ. `.rev` (`RIDX`) — обратный индекс offset→OID. `.midx` (`MIDX`) — единый
индекс поверх нескольких паков, чанки `PNAM`/`OIDF`/`OIDL`/`OOFF`/`LOFF`.
<https://git-scm.com/docs/gitformat-pack>

### Индекс — единственное, что строго линейно по числу файлов

`.git/index`: заголовок `DIRC` 12 байт, далее по записи на **отслеживаемый файл**,
далее расширения (`TREE` — cache tree, `UNTR` — untracked cache, `FSMN` —
fsmonitor, `REUC`, sparse-directory), в конце контрольная сумма 20/32 байта.

Фиксированная часть записи v2/v3: `ctime`(8) + `mtime`(8) + `dev`(4) + `ino`(4) +
`mode`(4) + `uid`(4) + `gid`(4) + `size`(4) + OID(20 для SHA-1) + flags(2)
[+ extended flags(2) в v3] ≈ **62 байта**, плюс путь с NUL и паддингом до
кратности 8. В **v4** путь хранится с префиксным сжатием относительно
предыдущей записи и без паддинга — документация заявляет снижение размера
индекса на **30–50 %** на крупных репозиториях.
<https://git-scm.com/docs/gitformat-index>

Прикидка для базы: 100 000 отслеживаемых файлов со средней длиной пути 60 байт
≈ 100 000 × ~130 байт ≈ **13 МБ индекса** в v2 и порядка 7–9 МБ в v4.
Это читается и переписывается целиком при каждой операции над индексом.

### Остальное

`refs/` — по файлу на ссылку (текстовый OID); `packed-refs` — те же ссылки одним
плоским файлом. `logs/` (reflog) — история движений каждой ссылки, растёт с
числом операций. `objects/info/alternates`. `FETCH_HEAD` — результат последнего
`fetch`. `shallow` — граница истории при `--depth`.
<https://git-scm.com/docs/gitrepository-layout>

### Три оси размера

| ось | что растёт |
|---|---|
| **число файлов** | `.git/index` (линейно, ~62 байта + путь на файл); tree-объекты (по одному на каталог) |
| **число коммитов** | commit-объекты (малые, фиксированные); **новые tree-объекты на каждый изменённый каталог и все родительские вплоть до корня** — рост ≈ число коммитов × глубина изменённых путей; reflog |
| **вес и сжимаемость содержимого** | blob-объекты |

🔴 Для базы владельца решает третья ось. PDF, PNG, ZIP уже сжаты: zlib даёт
почти ноль, а дельта между версиями почти бесполезна — правка одного байта
внутри контейнера меняет весь поток после него. *Механизм дельт документирован
(<https://git-scm.com/docs/gitformat-pack>), сам вывод про эти форматы —*
***широко наблюдаемая практика***, *отдельной строки в документации нет.*
Следствие: каждая правка PDF/PNG кладёт в историю практически полную копию.

`core.bigFileThreshold` (по умолчанию **512 МиБ**) — выше порога git не пытается
дельтить и не грузит файл целиком в память, обрабатывает потоково.
<https://git-scm.com/docs/git-config> *(страница на git-scm.com отдаётся
усечённой; значение и семантика — из документации, дословная цитата не снята.)*

### Что реально лежит на диске при `--filter=blob:none`

Сервер отдаёт **все достижимые commit- и tree-объекты**, но не блобы.
Документация прямо допускает, что «отфильтрованные packfile могут содержать
объекты, ссылающиеся на объекты, отсутствующие в этом packfile».
<https://www.kernel.org/pub/software/scm/git/docs/technical/partial-clone.html>

Такой пак помечается файлом `<name>.promisor` рядом с `.pack`/`.idx`.
В `.git/config` появляются `extensions.partialClone=<remote>`,
`remote.<name>.promisor=true`, `remote.<name>.partialCloneFilter=blob:none`.
Partial clone задуман **независимо** от `--depth`/single-branch — механизмы
комбинируются. (Там же.)

Замер владельца (`it-base`, история 118 МБ): полный клон ~118 МБ; `blob:none
--depth 1` **с** checkout — 116 МБ, 54 с; **без** checkout — 448 КБ, 2 с.
Разница в 260 раз — потому что checkout выкладывает рабочее дерево и ради этого
тянет содержимое каждого файла. `adr_008_release_from_working_copy.md`

---

## 2. Почему git докачивает, если байты уже на диске

### Идентификация

`oid = SHA-1("blob " + <размер десятичным> + "\0" + <содержимое>)`.
<https://git-scm.com/book/en/v2/Git-Internals-Git-Objects> ·
<https://git-scm.com/docs/git-hash-object>

SHA-256 (`--object-format=sha256`) поддерживается git с 2.29 (2020), блокер —
экосистема: **GitHub репозитории с SHA-256 не поддерживает**.
<https://git-scm.com/docs/hash-function-transition> ·
<https://github.com/orgs/community/discussions/12490> *(второе — практика.)*

### Ответ на вопрос «почему нельзя признать локальный файл равным»

**Формально — можно, и git так и делает.** Он считает хеш локального файла и
сравнивает с OID из дерева, не открывая старый блоб. Более того, в штатном
режиме он даже не хеширует: запись индекса хранит `ctime`, `mtime`, `dev`,
`ino`, `mode`, `uid`, `gid`, `size` **и** OID; `refresh_index()` сначала делает
только `lstat()` и сравнивает stat-поля. Совпало — блоб не открывается вообще.
<https://git-scm.com/docs/gitformat-index>

`git update-index --refresh` документирован дословно: *«does not calculate a new
sha1 file… it does "re-match" the stat information»*.
<https://git-scm.com/docs/git-update-index>

🔴 **Но `read-tree` без `-u` заполняет индекс из дерева без реальных stat-данных
с диска** (<https://git-scm.com/docs/git-read-tree>), поэтому первый же
`refresh_index()` видит расхождение по всем записям и идёт хешировать каждый
файл. А хеширование — это `convert_to_git()`, и вот там при `core.autocrlf`
всплывает `has_crlf_in_index()` и лезет за старым блобом (см. раздел 0).

Смежный механизм — **racy git**: если mtime файла совпадает по секунде с
моментом записи индекса, чистому stat-совпадению доверять нельзя; git
перечитывает и хеширует содержимое, а при следующей записи индекса **обнуляет
закешированный `st_size`** для таких записей, чтобы форсировать перепроверку.
<https://raw.githubusercontent.com/git/git/master/Documentation/technical/racy-git.adoc>

Ручные оверрайды: `CE_VALID` / `--assume-unchanged` («не проверяй даже stat»),
`--skip-worktree` (файла может не быть на диске).

### По операциям

| операция | нужен ли blob из object store |
|---|---|
| `git status` | **Нет** при совпавшем stat. При расхождении — хеширует файл **с диска**; старый блоб не читается… **кроме** пути `convert_to_git` при `core.autocrlf` (раздел 0) |
| `git diff` против HEAD, текстовый | **Да** — нужен старый блоб целиком |
| `git diff --name-only` / `--name-status` | Нет — достаточно сравнения OID |
| `git diff --stat` | **Да** — считает добавленные/удалённые строки, нужен сам дифф |
| `git commit` | Нет — новые блобы пишутся из рабочего дерева, дерево строится по OID из индекса |
| `git push` | Локальные блобы неизменённых файлов не нужны: что есть у remote, определяется через have/want. **Но** документация помечает push **в** promisor-remote как ограниченный: *«It is not possible to push only specific objects to a promisor remote»* — в списке future work |
| `git log --stat`, `log -p`, `blame`, `checkout`, `merge` | **Да**, все |
| `git grep` по рабочему дереву | Нет (читает файлы). `--cached` / по ref — да |

<https://raw.githubusercontent.com/git/git/master/Documentation/technical/partial-clone.adoc>

---

## 3. Partial clone: что провоцирует докачку и как её запретить

**Fault-in:** если обычный lookup объекта не нашёл, git зовёт
`promisor_remote_get_direct()` и повторяет lookup — внутренний эквивалент
`git fetch --filter=blob:none <promisor> <oid>`.

🔴 Документация прямо признаёт слабое место: *«Dynamic object fetching tends to
be slow as objects are fetched one at a time»* и *«invokes fetch-pack once for
each item… This may incur significant overhead»*. Это ровно то, что владелец
наблюдал как «2.9 МБ за 10 минут» и что эксперимент воспроизвёл как
122 отдельных запроса за 122 секунды на 170 файлах.

**Батчинг есть, но не везде:** `checkout` и всё на `unpack-trees` обучены
предзагружать недостающие блобы одной пачкой; `git rev-list --missing=print`
существует, чтобы другие команды могли предзагрузить заранее. Путь
`refresh_index` → `convert_to_git` в этот батчинг **не попадает** — отсюда
запрос на файл. <https://raw.githubusercontent.com/git/git/master/Documentation/technical/partial-clone.adoc>

**Что докачку не вызывает:** `git repack` специально обновлён, чтобы не трогать
promisor-паки; `git fsck` знает про promisor-объекты и не считает их отсутствие
ошибкой. (Там же.)

### Как запретить

- **`GIT_NO_LAZY_FETCH=1`** (переменная окружения) — документирована в `git(1)`:
  запрещает ленивую докачку. Появилась как серверная защита в фиксе
  **CVE-2024-32004** (`upload-pack` теперь сам выставляет её по умолчанию).
  <https://git-scm.com/docs/git> ·
  <https://github.com/git/git/commit/7b70e9efb18c2cc3f219af399bd384c5801ba1d7>
- **`git --no-lazy-fetch <cmd>`** — глобальный флаг, git **2.45.0**:
  *«allows to run "cmd" while disabling lazy fetching of objects from the
  promisor remote, which may be handy for debugging»*. Команда, которой объект
  реально нужен, упадёт с ошибкой вместо похода в сеть.
  <https://github.com/git/git/blob/master/Documentation/RelNotes/2.45.0.adoc>
- `remote.<name>.partialclonefilter`: очистка влияет **только на будущие**
  фетчи; чтобы добрать объекты для уже имеющихся коммитов — `git fetch --refetch`.
  <https://raw.githubusercontent.com/git/git/master/Documentation/config/remote.adoc>
- ❌ **`fetch.negotiationAlgorithm` к ленивой докачке отношения не имеет** —
  это про переговоры при обычном fetch. Исходная гипотеза не подтвердилась.
- ⚠️ `remote.origin.promisor=false` — документированного эффекта «выключить
  докачку» нет; по архитектуре команды просто упадут на отсутствующем объекте.
  *Вывод по архитектуре, не цитата.*
- ⚠️ Порча `remote.origin.url` — грязный хак, ломает все сетевые операции.
  *Практика, не документация.*

Смежное: **`git backfill`** — команда батчевой докачки исторических блобов
заранее, вместо череды мелких lazy-fetch. <https://git-scm.com/docs/git-backfill>

### Диагностика

```bash
git rev-list --objects --all --missing=print | grep -c '^?'
git config --get-regexp 'remote\..*\.(promisor|partialclonefilter)'
git count-objects -v
GIT_TRACE_PACKET=1 git status 2>trace.log   # считать "want" в трейсе
```

---

## 4. Нагрузка в повседневной работе

### `git status`

Складывается из: чтение и парсинг индекса (O(число файлов)), `lstat()` на каждый
отслеживаемый файл, **обход рабочего дерева ради untracked-файлов — обычно
самая дорогая часть**, проверка `.gitignore` на каждом уровне.

**Измерения вендора (GitHub, синтетический репозиторий 2 млн файлов /
111 тыс. каталогов):** без FSMonitor команды занимали **17–85 с**, с ним —
**меньше 1 с**. Отдельный прогон: `status` **970 мс → 204 мс → 40 мс** по мере
включения FSMonitor и untracked cache; другой пример — **1.2 с → 0.08 с**.
<https://github.blog/engineering/infrastructure/improve-git-monorepo-performance-with-a-file-system-monitor/>

⚠️ Промежуточных опубликованных точек на 10 тыс. и 100 тыс. файлов **не нашлось**.
Линейность lstat-фазы документирована, но конкретных чисел для этих объёмов
нет — экстраполировать пришлось бы самому, и я этого не делаю.

### Настройки

| настройка | что делает |
|---|---|
| `core.fsmonitor=true` | встроенный `fsmonitor--daemon`, на macOS через нативный **FSEvents** (`compat/fsmonitor/fsm-listen-darwin.c`), IPC через Unix domain socket. **Не работает на сетевых ФС, NTFS, FAT32.** Версия появления: источники расходятся — 2.36 против 2.37.0 |
| `core.untrackedCache` | кэширует mtime каталогов, пропускает readdir/stat для неизменившихся. Критично зависит от того, обновляет ли ФС `st_mtime` каталога — проверять `git update-index --test-untracked-cache` |
| `feature.manyFiles` | включает `index.version=4`, `core.untrackedCache=true`, `index.skipHash=true` |
| `index.version` 2/3/4 | v4 — префиксное сжатие путей, −30–50 % размера индекса; v3 — extended flags |
| `index.skipHash` | пропускает SHA-1 трейлер индекса при записи. 🔴 Индекс не читается git < 2.13.0, а git < 2.40.0 репортует его как corrupted при `fsck` |
| `core.preloadIndex` | параллельное сравнение индекса с ФС; включён по умолчанию с v2.1. Число потоков в найденных источниках не задокументировано |
| `core.splitIndex` | **не проверен** — см. «неизвестно» |

<https://git-scm.com/docs/git-fsmonitor--daemon> ·
<https://git-scm.com/docs/git-update-index> ·
<https://github.com/git/git/commit/c6cc4c5afd2efd5f8081a3839b48d003de4e094f>

### RAM

`pack.deltaCacheSize` — по умолчанию **256 МиБ**. `pack.windowMemory` — 0
(без ограничения) на поток. `core.packedGitLimit` — **8 ГиБ** на 64 бита
(256 МиБ на 32). `core.packedGitWindowSize` — **1 ГиБ** на 64 бита (32 МиБ на 32,
1 МиБ при сборке с `NO_MMAP`). `pack.threads` — числовой дефолт не подтверждён.
<https://github.com/git/git/blob/master/Documentation/config/pack.txt>

OOM при repack больших бинарных репозиториев — **широко наблюдаемая практика**;
тюнинг сводится к снижению `pack.windowMemory`/`pack.deltaCacheSize` и
ограничению `pack.threads`. Точных порогов в МБ/файлах не нашлось.
<https://www.strichnet.com/tuning-git-for-large-binary-repositories/>

### Разрастание и обслуживание

Дефолты: `gc.auto` = **6700** loose-объектов, `gc.autoPackLimit` = **50** паков,
`gc.reflogExpire` = **90 дней**, `gc.reflogExpireUnreachable` = **30 дней**.
<https://www.kernel.org/pub/software/scm/git/docs/git-gc.html>

`git maintenance` — задачи `commit-graph`, `prefetch`, `gc`, `loose-objects`,
`incremental-repack`, `pack-refs`, `reflog-expire`, `rerere-gc`, `worktree-prune`.
`start` = `register` (пишет `maintenance.repo`, ставит `maintenance.strategy=
incremental`, **выключает** `maintenance.auto`) + регистрация в планировщике.
Инкрементальное расписание по умолчанию: `gc` — **выключен**, `commit-graph` и
`prefetch` — ежечасно, `loose-objects` и `incremental-repack` — ежедневно.
**На macOS это `launchctl` и `.plist` в `~/Library/LaunchAgents/`**
(`org.git-scm.git.hourly.plist`, `.daily`, `.weekly`).
<https://git-scm.com/docs/git-maintenance>

🔴 Для 67 реп `git maintenance start` в каждой означает 67 записей в
`maintenance.repo` и ежечасные задачи, включая `prefetch` — **сетевой** по
природе. Для partial clone это отдельный риск: `prefetch` ходит в сеть каждый час.

### macOS-инфраструктура

- **Spotlight.** `.metadata_never_index` на современных версиях macOS **больше
  не работает**; действующие способы — Privacy-список в System Settings →
  Spotlight, либо `mdutil -i off <том>` (том целиком, не каталог — точечного
  исключения каталога `mdutil` не даёт). *Широко наблюдаемая практика*,
  официальной документации Apple по исключению каталога не найдено.
  <https://eclecticlight.co/2024/11/29/using-and-troubleshooting-spotlight-in-sequoia-summary/>
- **Time Machine.** `tmutil addexclusion <path>` без `-p` ставит xattr
  `com.apple.metadata:com_apple_backup_excludeItem` — исключение «липкое»,
  следует за файлом при переносе, root не нужен. Рекурсивно:
  `find ~/repos -name '.git' | xargs tmutil addexclusion`.
  <https://alexwlchan.net/notes/2024/exclude-files-from-time-machine-with-tmutil/>
  🔴 **Обе стороны:** исключать разумно, пока история продублирована на GitHub;
  если `.git` — единственный носитель какой-то ветки или незапушенных коммитов,
  исключение означает, что Time Machine сохранит только текущие файлы, а
  историю — нет. С учётом ADR-008 (архивы больше не единственный носитель версий)
  это не косметический выбор.
- Антивирус/индексаторы против `.git/index` — **неизвестно**, замеров не нашлось.

---

## 5. Грабли macOS

### Case-insensitivity

`core.ignoreCase` — дословно из man: *«Internal variable which enables various
workarounds to enable Git to work better on filesystems that are not case
sensitive, like APFS, HFS+, FAT, NTFS… The default is false, except git-clone(1)
or git-init(1) will probe and set core.ignoreCase true if appropriate when the
repository is created»*. Ручное изменение — *«may result in unexpected
behavior»*. APFS по умолчанию case-insensitive и case-preserving; case-sensitive
вариант существует, но форматируется явно.
<https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/APFS_Guide/FAQ/FAQ.html>

Следствия: `README.md` и `Readme.md` как два пути в дереве на APFS
одновременно не материализуются. Переименование только регистра требует
`git mv --force` (или через промежуточное имя) — обычный `mv` git не увидит,
потому что при `core.ignoreCase=true` индекс и рабочее дерево «совпадают».
*Механизм документирован, конкретное поведение при коллизии — трактовка.*

### NFD/NFC — самое опасное для базы с кириллицей

`core.precomposeUnicode`, дословно: *«This option is only used by Mac OS
implementation of Git. When core.precomposeUnicode=true, Git reverts the unicode
decomposition of filenames done by Mac OS… When false, file names are handled
fully transparent by Git»*.
<https://github.com/git/git/commit/76759c7dff53e8c84e975b88cb8245587c14c7ba>

🔴 **Чего он НЕ делает:** он влияет только на чтение путей из ФС в момент
операции. Пути, **уже закоммиченные в NFD**, остаются в дереве в NFD навсегда.
Одно и то же на вид имя может существовать как два разных пути. Сигнатура
проблемы: `git status` показывает файл одновременно в двух написаниях
(deleted + untracked). Автоматической миграции нет — только `git rm` старого
пути и `git add` нормализованного.
<https://www.git-tower.com/help/guides/faq-and-tips/faq/unicode-filenames/mac>

APFS, в отличие от HFS+, **не нормализует** имена на диске (сохраняет байты как
даны), но с High Sierra является normalization-insensitive при сравнении.
Для case-sensitive варианта формулировки Apple и вторичных источников
расходятся — **частично неопределённо**; практический риск (ENOENT при открытии
файла в «другой» нормализации) в отдельных конфигурациях отмечен, но не
подтверждён technote Apple.

🟢 Это напрямую бьёт по известной записи в памяти владельца — «NFD/NFC
false-positive DIFF в скрипте verify». Причина та же, и она не в скрипте.

### CRLF/LF

`core.autocrlf=true` = `text=auto` на всё + `core.eol=crlf`, предназначено для
Windows. `input` — конвертация CRLF→LF при коммите, без обратной при checkout.
На macOS рекомендуется `input` или `false`; `true` вреден — порождает CRLF в
рабочем дереве Unix-инструментов.

`core.safecrlf` — проверка обратимости конверсии, дословно предупреждает:
*«for binary files that are accidentally classified as text the conversion can
corrupt data»*. 🔴 Для базы с PDF/PNG/ZIP это прямое предупреждение.

`.gitattributes` надёжнее глобального конфига: настройка per-path едет вместе с
репозиторием, `core.autocrlf` — локальная в каждом клоне. Канонический пример
из man gitattributes и протокол смены на существующем репо:

```
* text=auto
*.sh text eol=lf
*.jpg -text
```
```bash
git add --renormalize .
git status        # что будет нормализовано
git commit -m "Introduce end-of-line normalization"
```

`binary` — встроенный макрос, эквивалентен `-diff -merge -text`.
<https://git-scm.com/docs/gitattributes>

🔴 **Связка с разделом 0:** запись `*.md -text` / `* -text` в `.gitattributes`
даёт `CRLF_BINARY` и обрывает путь `crlf_to_git()` до чтения блоба — то есть
это второй, более декларативный способ убить докачку, чем `core.autocrlf=false`.
*Логический вывод из подтверждённого механизма; отдельно в эксперименте
не проверялся — проверять на C2-манер.*

### `.DS_Store`, +x, длинные пути

- **`.DS_Store`** создаётся Finder в каждом просмотренном каталоге. Глобальный
  игнор — `core.excludesFile`, по умолчанию `$XDG_CONFIG_HOME/git/ignore` или
  `~/.config/git/ignore`. `defaults write com.apple.desktopservices
  DSDontWriteNetworkStores` — **только для сетевых томов**, для локального APFS
  не помогает вообще. Для уже закоммиченного — `git rm --cached`, для истории —
  `git filter-repo --path .DS_Store --invert-paths`.
- **+x.** Git хранит только 100644 / 100755 — один бит, не полный набор прав.
  `core.fileMode` автопробуется при `init`/`clone`. Потеря +x при zip→unzip —
  специфика формата ZIP (unix-права лежат в необязательном поле external file
  attributes, многие кроссплатформенные архиваторы его не пишут/не
  восстанавливают, файл извлекается с 644). Это **широко наблюдаемая практика**,
  но она точно объясняет известный владельцу паттерн «`.claude/hooks/*.sh` и
  `tests/bin/*` периодически теряют +x во всех репах разом»: источник — не git,
  а конвейер синхронизации через архив. Починка — `git update-index --chmod=+x`.
  `umask` на то, что хранит git, не влияет; влияет на права инода при checkout.
- **Длинные пути.** `NAME_MAX` формально 255, но по обсуждениям Apple фактическое
  ограничение APFS ближе к 255 UTF-16 code units — **несостыковка не разрешена**,
  точный ответ даёт только `pathconf(path, _PC_NAME_MAX)` на конкретном томе.
  Кириллица: 2 байта в UTF-8, но 1 code unit в UTF-16 — практический лимит
  зависит от того, чем именно ограничивает ФС.
  <https://developer.apple.com/forums/thread/726970>
- `core.protectHFS`, дословно: *«If set to true, do not allow checkout of paths
  that would be considered equivalent to `.git` on an HFS+ filesystem. Defaults
  to true on Mac OS, and false elsewhere»*.
- `core.longpaths` — настройка Git for Windows, **в core git на macOS её нет**.
- **xattr и resource forks git не хранит** — Finder-теги, `com.apple.quarantine`
  и прочее теряются при коммите безвозвратно. При копировании на
  не-HFS-совместимый том macOS порождает AppleDouble-спутники `._<имя>` —
  их стоит игнорировать паттерном `._*` по той же логике, что `.DS_Store`.

---

## 6. Противоречия между субагентами (названы, не сглажены)

1. 🔴 **`reset --mixed` и блобы.** Субагент по partial clone, читая
   `builtin/reset.c`, заключил: докачки быть не должно, `refresh_index()` —
   только stat и хеш локального файла. Замер владельца говорил обратное.
   **Разрешено экспериментом:** правы оба, но при разных условиях. Ошибка
   рассуждения по исходникам — в допущении, что «хеш локального файла» это
   `sha1(file)`; на деле `sha1(convert_to_git(file))`, и конвертация читает
   старый блоб. Условия докачки: непустое рабочее дерево **и** включённый
   `core.autocrlf`.
2. **Версия появления `fsmonitor--daemon`:** git-scm говорит 2.36, GitHub-блог —
   2.37.0. Разночтение не разрешено, релизы соседние.
3. **`fetch.negotiationAlgorithm`** — гипотеза из постановки задачи не
   подтвердилась: механизм не тот.
4. **Расхождение внутри самой базы:** `scripts/git_adopt.py` в коде зовёт
   `read-tree` + `update-ref`, а докстринг в двух местах всё ещё описывает
   старый путь — строка 24 («`reset --mixed` ставит HEAD и индекс») и строка 69
   («план: init + config + fetch 448 КБ + reset»). Плюс сам вывод докстринга
   «read-tree = 0 байт из сети» верен буквально и неверен по смыслу
   (см. раздел 0, строка D).

---

## 7. Что осталось неизвестным

- Опубликованных замеров `git status` на **10 тыс. и 100 тыс.** файлов не
  нашлось — есть только точка 2 млн от GitHub. Не экстраполирую.
- Цифр вида «репозиторий X: full N МБ / blob:none M МБ / treeless K МБ» в
  первоисточниках нет. Статья GitHub Blog прямо отсылает к отдельному посту с
  данными, который в бюджет не влез.
- Точный дефолт `pack.threads`; число потоков `core.preloadIndex`.
- `core.splitIndex` — детали и известные проблемы не проверены.
- Точный текст RelNotes 2.37.0 по `--no-refresh` (404 на raw-URL); надёжный
  путь — `git show v2.37.0:Documentation/RelNotes/2.37.0.txt` в клоне git/git.
- Формат `commit-graph` и `reftable` — не смотрел.
- Поведение `--no-lazy-fetch` под контролируемым тестом (какая именно операция
  падает и с каким сообщением) — не доведено до конца.
- Абсолютные числа эксперимента сняты на `psf/requests` (~170 файлов, 13 МБ),
  не на `it-base` (118 МБ). Механизм воспроизведён точно (1 запрос на файл),
  масштаб — по линейности, а не по прямому замеру.
- Влияние антивирусов/индексаторов на `.git/index` — источников не нашлось.
- Официальной документации Apple по исключению **каталога** (не тома) из
  Spotlight не найдено.

### Честно о разнице с оригинальной архитектурой

У субагентов только веб + Bash; внутренних источников вроде переписки
git mailing list через нормальный поиск нет. Это повлияло на пункт 3 списка
выше: часть дефолтов пришлось брать из вторичных агрегаций, а `git-scm.com/docs/
git-config` отдаётся усечённым при статическом фетче (страница подгружает
секцию VARIABLES скриптом). **Надёжнее всего дефолты снимаются локально:
`git help --config` и `man git-config` на самой машине** — так, кстати, и был
получен ряд дословных цитат в разделе 5.
