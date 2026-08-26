# Как убрать Claude из соавторов git-коммитов и очистить историю (актуально на 2026)

## TL;DR
- **На будущее:** добавьте в `~/.claude/settings.json` блок `"attribution": { "commit": "", "pr": "", "sessionUrl": false }` — это официальный, актуальный способ (ключ `attribution` появился в v2.0.62 и заменил устаревший `includeCoAuthoredBy`). Пустые строки полностью убирают трейлер `Co-Authored-By: Claude <noreply@anthropic.com>`, строку `🤖 Generated with Claude Code` и ссылку на сессию.
- **Из истории:** перепишите все коммиты одной командой `git filter-repo --message-callback` (удаляет и `Co-Authored-By`, и `Generated with Claude Code`), затем force-push веток и тегов. Это ломает хеши коммитов, теги и релизы — их нужно перепроверить.
- **Из списка контрибьюторов на GitHub:** список кешируется отдельно от git-истории и обновляется в фоне (обычно до 24–48 часов, иногда 1–2 дня, а на «тихих» репозиториях может залипнуть на недели). Самый надёжный форсаж — трюк с переименованием ветки через API или обращение в GitHub Support.

## Key Findings

### 1. Что именно добавляет Claude Code
По умолчанию Claude Code при создании коммита дописывает в конец сообщения два элемента:
- строку `🤖 Generated with [Claude Code](https://claude.com/claude-code)`;
- трейлер `Co-Authored-By: Claude <noreply@anthropic.com>` (в трейлере указывается имя активной модели, например `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`).

Кроме того:
- при создании PR через `gh pr create` в тело PR добавляется футер `🤖 Generated with Claude Code`;
- в веб- и Remote Control-сессиях (не в локальном CLI) с версии v2.1.179 добавляется трейлер `Claude-Session: <url>` со ссылкой на сессию claude.ai (issue #69614: «As of v2.1.179, commits that Claude creates in a web session include a Claude-Session: <url> git trailer»).

**Как это выглядит на GitHub.** GitHub распознаёт трейлер `Co-authored-by:` как стандартную git-конвенцию и показывает соавтора в UI коммита, а также включает его в список контрибьюторов репозитория и в статистику. То есть «Claude» появляется и на карточке коммита, и на вкладке Insights → Contributors. При этом почта `noreply@anthropic.com` не принадлежит официальному аккаунту Anthropic, и GitHub привязывает такие коммиты к постороннему пользователю, зарегистрировавшему этот email: в issue #1653 (anthropics/claude-code) зафиксировано, что «commits are being attributed to GitHub user "Panchajanya1999" who appears to have registered the noreply@anthropic.com email». По другому адресу, который Claude Code использовал в части версий (`claude-code@anthropic.com`), коммиты привязывались к пользователю @Karim13014, ранее не контрибьютившему в репозиторий.

### 2. Как отключить на будущее
**Актуальный способ (рекомендуется).** Ключ `attribution` (в `settings.json`), введён в Claude Code v2.0.62, официально задокументирован на code.claude.com/docs/en/settings. Он имеет приоритет над устаревшим `includeCoAuthoredBy` — в официальной схеме прямо сказано: «The attribution setting takes precedence over the deprecated includeCoAuthoredBy setting».

Точный рабочий фрагмент для `~/.claude/settings.json`:
```json
{
  "attribution": {
    "commit": "",
    "pr": "",
    "sessionUrl": false
  }
}
```
- `commit: ""` — убирает трейлер и строку Generated в коммитах;
- `pr: ""` — убирает футер в описаниях PR;
- `sessionUrl: false` — убирает трейлер `Claude-Session:` (ключ добавлен в v2.1.183; актуально только для web/Remote Control сессий, для локального CLI это no-op — в docs-выписке прямо помечено «Has no effect in local CLI sessions»).

**Устаревший способ.** Раньше использовали `{"includeCoAuthoredBy": false}`. Он ещё работает, но помечен как deprecated (ClaudeLog: «The attribution setting (v2.0.62)... replaces and deprecates the previous includeCoAuthoredBy setting»). Известны баги, когда `includeCoAuthoredBy: false` игнорировался и атрибуция всё равно добавлялась (issues #7543, #7666, #4224). Поэтому на 2026 год предпочтителен `attribution`.

**Приоритет и области видимости (scopes).** Официальная документация задаёт порядок приоритета (от высшего к низшему): Managed → аргументы командной строки → Local (`.claude/settings.local.json`) → Project (`.claude/settings.json`) → User (`~/.claude/settings.json`). То есть:
- `~/.claude/settings.json` (User) — применяется ко всем вашим проектам, но перебивается проектными и локальными;
- `.claude/settings.json` (Project) — коммитится в репозиторий, общий для команды;
- `.claude/settings.local.json` (Local) — личный, не коммитится (Claude Code сам добавляет его в git excludes), перебивает Project и User.

Для одного разработчика на одной машине, который хочет глобально убрать атрибуцию во всех репозиториях, правильное место — **User scope** (`~/.claude/settings.json`).

**Дополнительный «пояс и подтяжки».** Базовая инструкция о co-author частично зашита в системный промпт Claude Code (issue #53259: «Claude Code's system prompt contains a hardcoded instruction to append Co-Authored-By... This instruction cannot be reliably overridden by any user-facing mechanism» — то есть CLAUDE.md и settings.json в отдельных случаях перебивались системным промптом). Поэтому некоторые дополнительно добавляют в `~/.claude/CLAUDE.md` явное правило вроде «Never add Co-Authored-By or any AI-attribution trailer to commit messages». Это работает как второй слой, но `attribution` — основной и, в большинстве версий, достаточный механизм. Настройки читаются при старте сессии; после правки запустите `/status` (или перезапустите сессию), чтобы убедиться, что файл подхватился.

**Изменения вступают в силу**: Claude Code следит за файлами настроек и подхватывает большинство ключей без перезапуска.

### 3. Как убрать существующие следы из истории
**Вариант A — весь репозиторий сразу (рекомендуется): `git filter-repo`.**
Установка на macOS: `brew install git-filter-repo` (или `pip install git-filter-repo`).

Команда, удаляющая обе строки атрибуции во всех коммитах, ветках и тегах:
```bash
git filter-repo --message-callback '
import re
message = re.sub(b"(?m)^.*Co-Authored-By:.*Claude.*\n?", b"", message)
message = re.sub(b"(?m)^.*Generated with \[?Claude Code.*\n?", b"", message)
message = re.sub(b"(?m)^Claude-Session:.*\n?", b"", message)
return message
'
```
`git filter-repo` автоматически обновляет теги на новые хеши и в целях безопасности удаляет remote `origin`. После проверки `git log` нужно вернуть remote и сделать force-push:
```bash
git remote add origin https://github.com/vevdokimovm/<repo>.git
git push origin --force --all
git push origin --force --tags
```

**Вариант B — несколько коммитов: `git rebase -i` / `--amend`.**
Для точечной правки:
```bash
git rebase -i <BAD_COMMIT_SHA>^
# заменить pick на reword у нужных коммитов, удалить строки Co-Authored-By/Generated
git push --force-with-lease origin <branch>
```
Минус: rebase работает по одной ветке и не трогает теги и другие ветки.

**Вариант C — устаревший `git filter-branch`.**
```bash
git filter-branch --msg-filter 'sed "/^Co-Authored-By:/d"' -- --all
```
Git сам предупреждает, что `filter-branch` устарел, медленный и склонен портить историю; официально рекомендуется `git filter-repo`. Упоминается для полноты.

**Важные предупреждения при перезаписи истории:**
- перезапись меняет все хеши коммитов → обязателен force-push;
- **теги** переезжают на новые хеши (filter-repo это делает), но их нужно принудительно запушить (`--force --tags`);
- **релизы GitHub** привязаны к тегам/коммитам: после перезаписи релиз может указывать на несуществующий коммит, а ассеты (загруженные бинарники) не пересобираются автоматически — их надо проверить и при необходимости пересоздать релиз;
- открытые PR: filter-repo/BFG меняют SHA, что ломает открытые PR — GitHub рекомендует слить или закрыть их до перезаписи;
- форки и уже сделанные клоны сохраняют старые коммиты; на публичных зеркалах (finpilot) старые коммиты с трейлером останутся, пока их отдельно не перезаписать.

### 4. Удаляется ли Claude из списка контрибьюторов и когда
Список контрибьюторов на GitHub — это **отдельно кешируемый индекс, а не живое чтение git-истории**. После корректной перезаписи и force-push «Claude» исчезнет, но с задержкой: GitHub Discussion #166884 указывает «usually up to 24–48 hours to update after force-pushing... it often refreshes within 1–2 days»; а на «тихих» репозиториях (Discussion #198886) «it can lag for weeks». Ручной кнопки «обновить» нет.

Способы ускорить пересчёт:
- **пустой/обычный коммит в дефолтную ветку** — часто триггерит пересчёт в течение нескольких часов;
- **трюк с переименованием ветки через API** — по Discussion #191565 это единственный надёжно сработавший приём: «The fix is a branch rename, which forces GitHub to recalculate the contributor index: `gh api repos/OWNER/REPO/branches/main/rename --method POST -f new_name='main-temp'`... Make the repo private first, do both renames, make it public again. Force-pushing and deleting/recreating the branch do not work». То есть: сделать репозиторий приватным, переименовать `main` → `main-temp`, затем `main-temp` → `main`, вернуть публичность (для приватного репо шаг с публичностью не нужен). Тот же трюк работает и через веб-UI (переименовать и вернуть обратно). На org-owned репозиториях у части пользователей срабатывал не rename, а кратковременный перенос владения и возврат;
- **обращение в GitHub Support** — самый цитируемый как «most reliable»: «you need to contact GitHub Support and ask them to refresh/recompute the contributor graph». Канал — форма support.github.com/contact (не community-форум). Оговорка: один пользователь получил автоответ, что виджеты авторских контрибуций нельзя обновить вручную, — то есть Support не всегда гарантирует результат.

**Важный нюанс:** объединённые PR создают ref'ы `refs/pull/*/head`, которые контролирует GitHub и которые нельзя перезаписать force-push'ем. По Discussion #191565: «every merged PR created a refs/pull/*/head ref that GitHub controls and you cannot overwrite. If those PRs had Co-Authored-By lines, GitHub's indexer can still count them no matter how clean your current history is». То есть при наличии смерженных PR с трейлером Claude может остаться в индексе даже при полностью чистой основной истории.

### 5. Риски и подводные камни
- **Публичные зеркала (finpilot).** Если репозиторий публичный или имеет публичные зеркала/форки, старые коммиты с трейлером остаются доступны по SHA и в кешах, пока их не перезаписать в каждом зеркале отдельно. Для приватных репозиториев риск меньше, но кеш всё равно есть.
- **GitHub держит «висячие» коммиты.** После force-push старый коммит может ещё какое-то время доставаться по прямому SHA (detached), пока GitHub не проведёт сборку мусора.
- **Индекс поиска GitHub лагает.** Даже после amend старый коммит может ещё показываться в поиске.
- **Теги/релизы/CI.** Перезапись ломает семантические релизы и пайплайны, парсящие трейлеры; проверьте CODEOWNERS/DCO-хуки.
- **Одна машина — плюс.** Так как работа с одного компьютера и репозитории приватные, риск конфликтов с чужими клонами минимален — это самый безопасный сценарий для force-push.

### 6. Другие места, где остаются следы
- **Автор коммита (не соавтор).** По умолчанию Claude Code ставит автором коммита *вас* (ваши `user.name`/`user.email` из git config), а себя добавляет только как co-author. То есть отдельного «автора Claude» обычно нет — проверьте `git log --format=full`, но менять авторство обычно не требуется.
- **PR-описания через `gh`.** Футер `🤖 Generated with Claude Code` в теле PR — снимается ключом `attribution.pr`.
- **Трейлер сессии.** `Claude-Session:` в web/Remote Control — снимается `attribution.sessionUrl: false`; в старых версиях он игнорировал `attribution.commit` (issues #41873, #77830).
- **Комментарии от cloud-routines.** Отдельный баг: комментарии, оставляемые cloud-routine, содержат «Generated by Claude Code» и не управляются `attribution` (issue #62791) — к обычному локальному CLI не относится.
- **Ветки.** Имена веток Claude Code сам по себе не брендирует.

## Recommendations
1. **Сначала закройте будущее (5 минут).** Создайте/отредактируйте `~/.claude/settings.json`, добавьте блок `attribution` с пустыми `commit`/`pr` и `sessionUrl: false`. Запустите `/status` в сессии и сделайте тестовый коммит: `git log -1` не должен содержать ни `Co-Authored-By`, ни `Generated with Claude Code`.
2. **Для небольшого числа коммитов** (последние 1–5) используйте `git rebase -i` + `--force-with-lease` — это быстрее и безопаснее полной перезаписи.
3. **Для массовой очистки** используйте `git filter-repo` на свежем клоне. Перед этим: слейте/закройте открытые PR, зафиксируйте список тегов и релизов. После — force-push веток и тегов, затем проверьте каждый GitHub Release (не указывает ли он на пропавший коммит) и при необходимости пересоздайте.
4. **Ускорьте пересчёт контрибьюторов:** сделайте пустой коммит в `main` и запушьте; если через 24–48 ч Claude всё ещё в списке — примените трюк с переименованием ветки (`gh api .../branches/main/rename` туда-обратно) или напишите в GitHub Support через support.github.com/contact.
5. **Проверьте публичные зеркала finpilot:** если они публичные, повторите очистку истории и там, иначе трейлеры останутся видны.

**Пороги, меняющие план:** если репозиторием пользуется кто-то ещё или есть активные форки — не делайте force-push без согласования (все должны заново склонировать). Если Claude остаётся в контрибьюторах >72 ч после чистого пуша — это почти наверняка кеш или `refs/pull/*/head` от смерженных PR, и решается только переименованием ветки или обращением в Support.

## Caveats
- Многие точные рецепты (трюк с переименованием ветки, влияние `refs/pull/*/head`, сроки обновления кеша) взяты из community-обсуждений GitHub (Discussions #191565, #166884, #198886), а не из официальной инженерной документации — они многократно подтверждаются пользователями, но GitHub официально не документирует влияние на индекс контрибьюторов. Официально подтверждено лишь то, что список кешируется и обновляется в фоне.
- Поведение Claude Code быстро меняется между версиями; проверяйте актуальную страницу code.claude.com/docs/en/settings и `CHANGELOG.md`. В части версий системный промпт мог перебивать пользовательские настройки (issue #53259) — после обновления Claude Code сделайте контрольный тестовый коммит.
- Точный regex в `--message-callback` может потребовать подгонки под ваш формат сообщений; всегда работайте на свежем клоне и проверяйте `git log` до force-push.