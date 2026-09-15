#!/usr/bin/env python3
"""system_status.py — «система в порядке?» одним ответом, по СОСТОЯНИЮ.

🔴 ВОПРОС ВЛАДЕЛЬЦА 28.08.2026 дословно: «что ещё не хватает нашему
планировщику, чтобы полностью обслуживать систему? Кажется, что он довольно
слабый. Как уменьшить мой контроль и автоматизировать процесс?»

ОТВЕТ, НАЙДЕННЫЙ ИССЛЕДОВАНИЕМ 29.08.2026: планировщик слаб не составом
файлов, а **природой**. Он целиком **событийный** (edge-triggered): пункт
появляется в нём, только если кто-то заметил и записал. Потерялось
наблюдение — потерялось действие, и никто об этом не узнает.

Устойчивые системы устроены наоборот. Контроллеры Kubernetes работают
**уровнево** (level-triggered): событие — лишь повод посмотреть ещё раз,
а решение принимается по ТЕКУЩЕМУ состоянию. Ключевое следствие: если
событие потеряно — сеть моргнула, сессия оборвалась, вахта забыла, —
уровневая система всё равно сойдётся к цели на следующем проходе,
а событийная теряет действие навсегда.

Этот скрипт и есть уровневый проход. Он ничего не помнит и ни на что не
подписан: каждый запуск заново спрашивает диск, «соответствует ли текущее
состояние целевому».

🔴 ВТОРАЯ ПОЛОВИНА ОТВЕТА — ПОЧЕМУ ОТВЕТ ОДИН, А НЕ СПИСОК ИЗ СОРОКА СТРОК.
Уведомление, которое всё равно надо прочитать и осмыслить, **контроль не
снижает** — оно меняет активное решение на пассивный надзор, а пассивный
надзор человек выполняет ХУЖЕ: Mackworth (1948) замерил падение точности
обнаружения на 10–15 % за первые полчаса наблюдения. И дальше вступает
усталость от тревог: в медицине **72–99 % клинических тревог ложные**
(обзоры PMC), а вероятность отреагировать на напоминание падает на 30 %
с каждым повтором.

Поэтому здесь порог, а не поток: **зелёное молчит**. Сообщается только то,
что перешло границу, — как error budget в SRE, где вмешательство вызывает
не любое отклонение, а исчерпание бюджета.

🔴 ЧЕГО ЭТОТ ИНСТРУМЕНТ НЕ ДЕЛАЕТ И НЕ БУДЕТ (`71` §7г-бис):

  · **не чинит найденное.** Уровневый контроллер обычно и приводит систему
    к цели, но здесь половина расхождений требует необратимых действий
    (раздача по 60 репам, правка чужих реп), а необратимое вовне — стоп-класс
    авто-режима. Смотритель докладывает, чинит человек или отдельный скрипт;
  · **не проверяет содержание** — только то, что выразимо состоянием диска.
    «Задача сформулирована плохо» ему недоступно;
  · **не заменяет гейт.** Гейт судит ОДНУ репу по правилам; смотритель судит
    СИСТЕМУ по целевому состоянию. Пересечение есть, назначение разное;
  · **🔴 не знает о том, чего нет в файлах.** Дыра, про которую никто не
    написал, невидима и для него. Уровневость снимает потерю СОБЫТИЯ,
    но не отсутствие ЗНАНИЯ.

ЗАПУСК
    system_status.py             вердикт; молчит о зелёном
    system_status.py --all       показать и зелёное тоже
    system_status.py --selftest  канарейка
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
import time
from pathlib import Path

# Корень определяется общим модулем: скрипт может быть запущен и из базы,
# и из копии кита в репе-наследнике (`_base/scripts/`). См. `_roots.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402
BASE_REPO, REPOS, FROM_KIT = resolve_roots(__file__)

# 🔴 ПОРОГИ — не «сколько плохо», а «когда звать человека». Число выбрано так,
# чтобы срабатывание означало действие, а не наблюдение. Слишком низкий порог
# даёт поток ложных тревог и обучает не читать вывод (см. докстроку).
THRESHOLDS = {
    "отставших от канона": 1,     # раздача не запускалась — расхождение видно сразу
    "не проходят гейт": 1,        # красная репа
    "просроченных задач": 5,      # единичная просрочка — жизнь, пять — затор
    "дней без архива": 2,         # архив собирается каждым батчем
    # 🔴 Порога у хуков сначала НЕ БЫЛО, и три находки показались молча:
    # значение выводилось, сравнивать было не с чем. Проверка без порога —
    # не проверка, а строка. Поймано первым же живым прогоном 29.08.2026.
    "хуков без +x": 1,
    # Битый архив = потерянная версия: у базы нет git, zip —
    # единственный экземпляр. Порог 1, потому что второго шанса нет.
    "повреждённых архивов": 1,
    # Медиана промежутка между батчами — 13 мин, девятая доля — 82 (timing.py,
    # 208 замеров). 120 взято заметно выше, чтобы длинный честный батч
    # не поднимал ложную тревогу: ложная тревога дороже позднего замечания.
    # Порог 1: одна репа за потолком — уже повод. `01-repo-standard` §4
    # называет 500 МБ жёстким, потому что выше Claude не берёт архив целиком,
    # то есть репа перестаёт быть читаемой машиной как единое целое.
    "реп за жёстким потолком": 1,
    # Порог 1: две копии одной репы — уже расхождение, вопрос только когда
    # оно проявится. Результат сверки начинает зависеть от того, в какой
    # каталог зашли (`SYN-017`).
    "реп с копиями": 1,
    "минут тишины": 120,
    # Крупный транскрипт стирается сам через 30 дней, и продлить срок нельзя —
    # места на диске нет (99-claude-code-sessions.md §4). Порог 1: одна долгая
    # вахта на грани — уже повод вынуть из неё ценное в репу, пока она есть.
    "сессий на грани удаления": 1,
    # 🔴 Порог 7, а не 1: неделя без разбора — обычная жизнь (батчи бывают
    # механические, и это законно). Восемь дней подряд — уже затор, и именно
    # столько очередь простояла незамеченной (`PIT-195`). Порог 1 давал бы
    # красное каждый день, когда работали над гейтами, — то есть всегда,
    # а всегда красное перестают читать (`69` §4з).
    "дней без разбора переписи": 7,
    # 🔴 Порог 1 и без вариантов: одна публичная репа вне `MIRRORS` — это
    # один массовый прогон до служебного канона в витрине (`PIT-196`).
    # Здесь «редко и не страшно» не работает: цена одного случая — утечка
    # содержимого наружу, и она необратима.
    "публичных реп вне защиты": 1,
    # Порог 1: скилл, которого нет в карте, вахта не вспомнит — а карта
    # заведена ровно для того, чтобы вспоминала. Один пропущенный делает
    # её ложно полной, и это хуже её отсутствия.
    "скиллов вне карты": 1,
}

# 🔴 ОБРАТНЫЕ ПОРОГИ: тревога при значении НИЖЕ порога, а не выше.
# «Дней до упора в порог размера» — чем меньше, тем хуже; обычное правило
# `значение >= предела` здесь дало бы тревогу при восьми годах запаса
# и молчание за день до упора, то есть ровно наоборот. Поймано на первом же
# прогоне способности Anticipate 29.08.2026.
LOWER_IS_WORSE = {"дней до порога размера": 90}


def canon_lag() -> tuple[int, list[str]]:
    """Сколько реп отстало от канона базы. Спрашивается у самой раздачи."""
    # 🔴 КОД ВОЗВРАТА ПРОВЕРЯЕТСЯ. Найдено ревью 29.08.2026: раньше судили
    # только по тексту stdout, и при недоступном `gh` раздача возвращала 2,
    # печатала «не удалось получить список приватных реп», строк ОТСТАЛА
    # не было — и смотритель молчал ЗЕЛЁНЫМ. Громкий отказ раздачи стирался
    # вызывающим кодом ровно там, где был нужен (`71` §7ж).
    try:
        res = subprocess.run(
            ["python3", str(BASE_REPO / "scripts" / "sync_base_local.py"),
             "--all", "--check"],
            capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return -1, ["раздача не отвечает"]
    if res.returncode != 0:
        first = (res.stdout or res.stderr or "").strip().splitlines()
        return -1, [f"раздача отказала (код {res.returncode}): "
                    f"{first[-1][:80] if first else 'без вывода'}"]
    out = res.stdout
    # Ловятся оба класса: отставание (версия старее) и расхождение (версия
    # та же, содержимое другое). Второй до 29.08.2026 был невидим вовсе.
    lagging = [l.split()[0] for l in out.splitlines()
               if "ОТСТАЛА" in l or "РАЗОШЛАСЬ" in l]
    return len(lagging), lagging[:8]


def overdue_tasks() -> tuple[int, list[str]]:
    """Задачи с прошедшим сроком, у которых не выбран исход."""
    sys.path.insert(0, str(BASE_REPO / "scripts"))
    try:
        import revision_check
    except ImportError:
        return -1, ["гейт не импортируется"]
    found = []
    for repo in sorted(REPOS.iterdir()):
        if repo.is_dir() and (repo / "TASKS.md").is_file():
            found += revision_check.check_task_expiry(repo)
    return len(found), found[:5]


def archive_age() -> tuple[int, list[str]]:
    """Сколько дней прошло с последней записи в реестре выпусков."""
    ledger = BASE_REPO / "reports" / "releases" / "LEDGER.tsv"
    if not ledger.is_file():
        return -1, ["реестра выпусков нет"]
    dates = [l.split("\t")[0] for l in ledger.read_text(encoding="utf-8").splitlines()
             if l and not l.startswith("#")]
    if not dates:
        return -1, ["реестр пуст"]
    # Битая строка реестра роняла ВЕСЬ смотритель traceback'ом, а не одну
    # проверку (ревью 29.08.2026). Идём с конца до первой разбираемой даты.
    for raw in reversed(dates):
        try:
            last = dt.date.fromisoformat(raw.strip())
        except ValueError:
            continue
        return (dt.date.today() - last).days, [f"последний выпуск {last}"]
    return -1, ["в реестре нет разбираемых дат"]


def hooks_executable() -> tuple[int, list[str]]:
    """Хуки без бита +x — молча не исполняются, и об этом никто не сообщает.

    🔴 Файлы с `_` в начале имени ПРОПУСКАЮТСЯ: по соглашению это внутренние
    модули, которые импортируются, а не запускаются, и бит им не нужен.
    Проверено на живом материале: `_parse.py`, `_affected_tests.py`,
    `_run_test_slice.py` в `personal-finance-dss` не объявлены в `settings.json`
    и импортируются соседним файлом. Требовать от них `+x` — ложная тревога,
    а ложная тревога в смотрителе дороже пропуска: она обучает не читать вывод.
    """
    import os
    lost = []
    for repo in sorted(REPOS.iterdir()):
        for rel in (".claude/hooks", ".githooks", "tests/bin"):
            folder = repo / rel
            if not folder.is_dir():
                continue
            for path in folder.iterdir():
                if path.is_file() and not os.access(path, os.X_OK) \
                        and not path.name.startswith((".", "_")):
                    lost.append(str(path.relative_to(REPOS)))
    return len(lost), lost[:8]


def batch_silence() -> tuple[int, list[str]]:
    """Минут с последнего закрытого батча — признак, что работа встала.

    🔴 Закрывает дыру, которую сторож авто-режима не видит по построению.
    Сторож возобновляет **ход**, если ход кончился. Он не знает, идёт ли
    внутри хода работа: залипший ход для него неотличим от работающего.

    Это ровно различие watchdog и ретрая. Ретрай повторяет операцию, считая
    среду исправной; watchdog **не доверяет системе целиком** и действует,
    если признак жизни не поступил вовремя. Признак жизни здесь —
    запись о закрытом батче.

    🔴 ПОРОГ ИЗМЕРЕН, А НЕ ПРИДУМАН. `timing.py` по 208 промежуткам:
    медиана 13 минут, девять из десяти укладываются в 82. Порог 120 минут —
    заметно выше девятой доли, чтобы длинный честный батч не поднимал тревогу.
    """
    log = BASE_REPO / "06-autonomous-mode-kit" / "runs" / "auto.log"
    if not log.is_file():
        return -1, ["журнала прогона нет"]
    moments = []
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2] == "batch":
            try:
                moments.append(dt.datetime.fromisoformat(parts[0]))
            except ValueError:
                continue
    if not moments:
        return -1, ["батчей в журнале нет"]
    minutes = int((dt.datetime.now() - max(moments)).total_seconds() / 60)
    return minutes, [f"последний батч {max(moments):%d.%m %H:%M}"]


def repo_copies() -> tuple[int, list[str]]:
    """Реп, существующих более чем в одном экземпляре на диске.

    🔴 ПОВОД — `ROADMAP`: 21.08.2026 контрольная сверка нашла, что **ни одна
    из пяти закрытых реп не имеет единственной копии**; у `mission-control`
    их было пять, версии от 0.25.0 до 1.12.0. Вывод был: «`SYN-017` оказался
    не особенностью одной репы, а свойством системы».

    Замер 04.09.2026 показал **ноль**: миграция в `~/repos` проблему решила.
    Порог заведён не как чистка, а как сторож — чтобы возврат был замечен
    сразу, а не через месяц расхождений.

    🔴 КОПИЯ ОПОЗНАЁТСЯ ПО ПРИЗНАКУ РЕПЫ, А НЕ ПО ИМЕНИ. Первый прогон
    считал тёзок и дал **13 ложных**: `~/repos/business` против
    `personal-finance-dss/knowledge/business` — подкаталог, а не копия.
    Признак: каталог содержит `.repo-id` или `VERSION` (`PIT-183`).

    🔴 ЧЕГО НЕ ЛОВИТ: копию вне домашнего каталога, копию глубже четырёх
    уровней и копию под другим именем — переименованный экземпляр
    не опознаётся ничем, кроме содержимого.
    """
    SKIP = {".Trash", "node_modules", ".venv", "Library", ".git", "_base",
            "__pycache__", ".cache"}
    try:
        names = {p.name for p in REPOS.iterdir() if p.is_dir()}
    except OSError:
        return -1, ["корень реп недоступен"]

    found: dict[str, list[Path]] = {}

    def walk(d: Path, depth: int = 0) -> None:
        if depth > 4:
            return
        try:
            entries = list(d.iterdir())
        except (OSError, PermissionError):
            return
        for e in entries:
            if not e.is_dir() or e.is_symlink() or e.name in SKIP:
                continue
            if e.name in names and ((e / ".repo-id").is_file()
                                    or (e / "VERSION").is_file()):
                found.setdefault(e.name, []).append(e)
            walk(e, depth + 1)

    walk(Path.home())
    multi = {k: v for k, v in found.items() if len(v) > 1}
    detail = []
    for k, v in sorted(multi.items()):
        where = ", ".join(str(p).replace(str(Path.home()), "~") for p in v[:3])
        detail.append(f"{k}: {len(v)} экз. — {where}")
    return len(multi), detail


def heavy_repos() -> tuple[int, list[str]]:
    """Сколько реп перевалило НАШ жёсткий потолок 500 МБ.

    🔴 ЗАЧЕМ ОТДЕЛЬНО ОТ `growth_forecast`. Тот считает **прогноз для базы**
    по ряду размеров её архивов — то есть отвечает «когда упрёмся».
    Здесь вопрос другой: **кто уже упёрся**, по всем 66 репам. Прогноз
    и факт — разные утверждения, и прогноз о базе ничего не говорит
    о `self-map`.

    🔴 ПОВОД — ЗАМЕР 04.09.2026, а не предположение. Аудитор приёмки показал,
    что `self-map/reports` вырос на 5303 файла; `git_limits_check` подтвердил
    **1018 МБ при потолке 500**. Порог существовал (`01-repo-standard` §4),
    инструмент существовал — но в ЕЖЕДНЕВНУЮ проверку не входил, и репа
    висела за потолком, пока её не нашли случайно.

    Первый прогон нашёл не одну репу, а **семь**: self-map 1110, edu-base 767,
    academic-portfolio 738, it-base 720, personal-finance-dss 617,
    health-vault 596, portrait-of-taste 503.

    ЦЕНА ИЗМЕРЕНА: обход 66 реп — **15.4 с**. Дорого для проверки, которую
    зовут между батчами, поэтому результат кэшируется на сутки: размер репы
    за час не меняется настолько, чтобы это стоило пятнадцати секунд каждый раз.

    🔴 СЧИТАЕТСЯ ВЕС АРХИВА, А НЕ ВЕС НА ДИСКЕ. Первая редакция мерила диск —
    и объявила тяжёлыми **семь** реп. Проверка показала, что это ложная
    тревога на всех семи:

        self-map:             диск 1110 МБ · в архив пойдёт 245 МБ
        personal-finance-dss: диск  617 МБ · в архив пойдёт 104 МБ

    Причина: порог 500 МБ существует ради одного — **Claude не берёт архив
    целиком**. А `pack_release.py` в архив не кладёт `node_modules`, `.venv`,
    `dist`, `__pycache__` и импортированные изображения. Вес на диске
    к этому порогу отношения не имеет.

    🔴 Это ровно тот класс, что нашёлся часом раньше в `acceptance_audit.py`:
    **инструмент проверки принёс свой счёт вместо счёта проверяемого — и стал
    измерять себя.** Дважды за один батч, разными путями: там сравнивались
    определения «файла в репе», здесь — определения «веса репы».

    Набор исключений берётся у `pack_release`, а не копируется: копия
    разошлась бы на первой же правке упаковщика (`PIT-178`).

    🔴 ЧЕГО НЕ ЛОВИТ: почему репа тяжёлая. Разбирает `git_limits_check.py`.
    И не ловит вес НА ДИСКЕ — он тоже важен (место кончается), но это другой
    вопрос и другой порог, которого пока нет.
    """
    import json
    import time

    HARD = 500 * 2**20
    cache = BASE_REPO / "reports" / ".repo-sizes-cache.json"
    now = time.time()
    if cache.is_file():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if now - data.get("снято", 0) < 86400:
                big = data["тяжёлые"]
                return len(big), [f"{m:.0f} МБ — {n}" for n, m in big]
        except (OSError, ValueError, KeyError):
            pass                    # кэш битый — считаем заново, это не отказ

    # Исключения СПРАШИВАЮТСЯ у упаковщика — он и решает, что поедет в архив.
    sys.path.insert(0, str(BASE_REPO / "scripts"))
    try:
        from pack_release import JUNK_DIRS, JUNK_NAMES
    except Exception:                                 # noqa: BLE001
        return -1, ["упаковщик не отвечает — вес архива не посчитать"]

    big = []
    for repo in sorted(REPOS.iterdir()):
        if not repo.is_dir():
            continue
        total = 0
        for f in repo.rglob("*"):
            if f.is_symlink() or not f.is_file():
                continue
            if set(f.parts) & JUNK_DIRS or f.name in JUNK_NAMES:
                continue
            try:
                total += f.stat().st_size
            except OSError:
                continue
        if total > HARD:
            big.append((repo.name, total / 2**20))
    big.sort(key=lambda x: -x[1])
    try:
        cache.write_text(json.dumps({"снято": now, "тяжёлые": big},
                                    ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass                        # без кэша инструмент работает, просто дольше
    return len(big), [f"{m:.0f} МБ — {n}" for n, m in big]


def growth_forecast() -> tuple[int, list[str]]:
    """Через сколько дней репа упрётся в жёсткий порог размера.

    🔴 Способность **Anticipate** из Resilience Assessment Grid (Hollnagel):
    устойчивая система знает не только своё состояние (Monitor), но и то,
    **чего ждать**. До 29.08.2026 это была единственная из четырёх
    способностей без механизма — Respond закрыт стоп-условиями и таблицей
    состояний, Learn — реестром на 152 карточки и 20 разборами.

    Считается по ряду размеров архивов в `LEDGER.tsv` — 272 замера с датами.
    Наклон берётся по первому и последнему замеру за последние 30 дней:
    сложнее не значит точнее, а простое правило видно насквозь.

    🔴 ЧЕГО НЕ УМЕЕТ (`71` §7г-бис):
      · **линейная экстраполяция на нелинейном процессе.** Рост базы идёт
        рывками: один батч добавляет 6 КБ, разбор инцидента — 40. Прогноз
        говорит «при нынешнем темпе», а темп меняется;
      · **не предсказывает событий** — только продолжение тренда. Настоящий
        Anticipate обязан спрашивать «что может случиться, чего ещё не было»,
        и на это механизма нет ни у кого;
      · молчит, если замеров меньше двух или рост нулевой.
    """
    ledger = BASE_REPO / "reports" / "releases" / "LEDGER.tsv"
    if not ledger.is_file():
        return -1, ["реестра выпусков нет"]
    rows = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line:
            continue
        parts = line.split("\t")
        if len(parts) >= 4 and parts[3].isdigit():
            try:
                rows.append((dt.date.fromisoformat(parts[0]), int(parts[3])))
            except ValueError:
                continue
    # 🔴 SENTINEL, А НЕ НОЛЬ. Метка живёт в LOWER_IS_WORSE с порогом 90,
    # где тревога при значении НИЖЕ порога. Возврат 0 означал «0 дней
    # до упора» — то есть громкую тревогу вместо обещанного молчания.
    # Найдено ревью 29.08.2026; докстрока обещала обратное.
    SILENT = 10 ** 6          # заведомо выше любого порога
    if len(rows) < 2:
        return SILENT, ["замеров мало — прогноз не строится"]

    horizon = dt.date.today() - dt.timedelta(days=30)
    window = [r for r in rows if r[0] >= horizon] or rows[-2:]
    days = (window[-1][0] - window[0][0]).days or 1
    grew = window[-1][1] - window[0][1]
    if grew <= 0:
        return SILENT, ["рост не обнаружен — прогноз не строится"]

    per_day = grew / days
    hard_limit = 500 * 1024 * 1024        # тот же порог, что у гейта
    left = (hard_limit - window[-1][1]) / per_day
    if left < 0:
        return 0, ["🔴 жёсткий порог уже превышен"]
    return int(left), [f"растёт на {per_day / 1024:.0f} КБ/день, "
                       f"сейчас {window[-1][1] / 1024 / 1024:.1f} МБ"]


def broken_archives() -> tuple[int, list[str]]:
    """Повреждённые архивы выпусков — потерянные версии, а не неудобство.

    Проверяются только те, что есть на диске: отсутствующие потеряны
    безвозвратно и порогом не лечатся (`archive_check.py`).
    """
    # 🔴 Та же поправка, что у `canon_lag`: код возврата важнее текста.
    # Проверка с порогом «1, потому что второго шанса нет» молча зеленела,
    # когда замер вообще не состоялся.
    try:
        res = subprocess.run(
            ["python3", str(BASE_REPO / "scripts" / "archive_check.py")],
            capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return -1, ["проверка архивов не отвечает"]
    m = re.search(r"повреждённых: (\d+)", res.stdout)
    if m:
        return int(m.group(1)), ["см. archive_check.py"]
    # Код 1 у archive_check означает найденные повреждения; строки нет —
    # значит замер не состоялся, и это НЕ «ноль повреждённых».
    if res.returncode not in (0, 1):
        return -1, [f"замер архивов отказал (код {res.returncode})"]
    return 0, []


def sessions_expiring() -> tuple[int, list[str]]:
    """Крупные транскрипты, которым осталось меньше недели до автоудаления.

    Claude Code сам стирает сессии старше `cleanupPeriodDays` (дефолт 30).
    Продлить срок нельзя — при темпе 70 МБ в день и 7.4 ГБ свободного диска
    даже 180 дней не умещаются (`00-infrastructure/99-claude-code-sessions.md` §4).
    Значит остаётся одно: предупредить, пока ценное ещё можно вынуть в репу.

    🔴 Считаются только КРУПНЫЕ сессии (≥10 МБ). Мелкие истекают постоянно,
    это норма, и тревога на них была бы шумом, который научит её не читать.
    Крупная сессия — долгая вахта: разборы, отменённые решения, обоснования.
    В `WATCHLOG` попадает решение, в транскрипт — путь к нему.
    """
    import json as _json
    projects = Path.home() / ".claude" / "projects"
    if not projects.is_dir():
        return 0, []
    period = 30
    for cfg in (Path.home() / ".claude" / "settings.json",
                BASE_REPO / ".claude" / "settings.json"):
        try:
            v = _json.loads(cfg.read_text()).get("cleanupPeriodDays")
        except (OSError, ValueError):
            continue
        if isinstance(v, int) and v > 0:
            period = v
    now = time.time()
    doomed = []
    for f in projects.glob("*/*.jsonl"):
        try:
            st = f.stat()
        except OSError:
            continue
        mb = st.st_size / 1024 / 1024
        if mb < 10:
            continue
        left = period - (now - st.st_mtime) / 86400
        if left <= 7:
            doomed.append((left, mb, f))
    doomed.sort()
    lines = [f"{mb:.0f} МБ, осталось {left:.0f} дн: {f.parent.name[:44]}"
             for left, mb, f in doomed[:5]]
    return len(doomed), lines


# 🔴 ГДЕ МАССОВОСТЬ НОРМАЛЬНА, А ГДЕ ОНА ПРИЗНАК ДЕФЕКТА ПРОВЕРКИ.
#
# Заведено 04.09.2026 после того, как ОДИН класс ошибки сработал трижды
# за сутки (`PIT-183`): `acceptance_audit` объявил выросшими все 19 реп,
# `heavy_repos` — 7 за потолком, замер копий — 13 с копиями. Все три раза
# расхождения не было: инструмент приносил своё определение вместо свойства
# проверяемого и в итоге мерил себя.
#
# Различающий признак был выведен и записан — и не сработал бы сам, потому
# что правило, которое надо помнить, не работает (`PIT-163`). Здесь оно
# становится исполнителем: проверка, нашедшая расхождение почти у всех,
# печатает подсказку прямо в момент находки.
#
# 🔴 НО МАССОВОСТЬ БЫВАЕТ ЗАКОННОЙ, и это не исключение, а частый случай:
# любая правка базы делает отставшими ВСЕ 57 реп разом — так устроена
# раздача. Подсказка на такой проверке была бы шумом, а шум учит не читать
# вывод. Поэтому каждая проверка объявляет это сама.
MASS_IS_NORMAL = {
    "отставших от канона",      # правка базы делает отставшими всех сразу
    "просроченных задач",       # накапливаются, к населению не привязаны
    "минут тишины",             # не доля от населения вовсе
    "дней до порога размера",   # прогноз, не счёт
    "дней без архива",          # то же
    "сессий на грани удаления", # своё население, не репы
}

# Население, с которым сравнивается значение. None — сравнивать не с чем.
def _population(label: str) -> int | None:
    if label in ("реп за жёстким потолком", "реп с копиями"):
        try:
            return len([d for d in REPOS.iterdir() if d.is_dir()])
        except OSError:
            return None
    return None


def census_stalled() -> tuple[int, list[str]]:
    """Сколько дней очередь переписи метода стоит без движения.

    🔴 ПОВОД — `PIT-195`. Перепись `scan_lessons.py` отвечает «что читать»
    и отвечала верно **восемь дней**, пока очередь стояла: 27.08 разобран
    первый кандидат, дальше ноль до 04.09. Простой был невидим — ни одна
    проверка не считала, сколько разобрано за период.

    Корень назван там же: механика отчитывается числами («821 дубль снят»),
    подъём урока — одним абзацем в чужом документе. При выборе, чем закрыть
    батч, механика выигрывает не по важности, а по видимости результата.
    Здесь простой становится числом — то есть уравнивается в видимости.

    🔴 ГРАНИЦА: считается движение счётчика `разобрано`, а не польза от него.
    Разбор, признанный «покрыто, поднимать нечего», двигает счётчик так же,
    как поднятый раздел, — и это верно: «уже покрыто» такой же результат
    прохода (`ROADMAP` §P2). Отписку гейт не отличит, как и `check_campaign_log`.
    """
    journal = BASE_REPO / "05-infra-synthesis-lab/tools/census-progress.tsv"
    if not journal.is_file():
        return 0, []
    rows = [l.split("\t") for l in
            journal.read_text(encoding="utf-8").splitlines()[1:] if l.strip()]
    if not rows:
        return 0, []
    import datetime
    last_moved, last_seen = None, None
    prev = None
    for r in rows:
        if len(r) < 3:
            continue
        last_seen = r[0]
        if prev is None or int(r[1]) > prev:
            last_moved = r[0]
        prev = int(r[1])
    queue = int(rows[-1][2])
    if queue == 0 or last_moved is None:
        return 0, []
    days = (datetime.date.today() - datetime.date.fromisoformat(last_moved)).days
    if days == 0:
        return 0, []
    return days, [f"очередь ≥400: {queue} · последний разбор {last_moved}"
                  f" · последний замер {last_seen}"]


def public_unprotected() -> tuple[int, list[str]]:
    """Публичные репы, которых нет в `MIRRORS` деплойера.

    🔴 ПОВОД — `PIT-196`. Две публичные репы (`vevdokimovm` и его сайт)
    отсутствовали в списке защищённых, и массовый режим залил бы в них
    `_base/` — служебный канон в витрину. Ровно это случилось 08.08.2026
    с публичной `finpilot`.

    Команда сверки **уже стояла** в комментарии над списком и не
    запускалась. Правило `PIT-196` требует, чтобы команда стала вызовом,
    и вот он.

    🔴 `gh` недоступен — возвращается НОЛЬ и пустой список, то есть порог
    молчит. Это сознательный выбор: тревожить владельца отсутствием сети
    нечем, а объявить «всё хорошо» при недоступном источнике инструмент
    не может — он и не объявляет, просто молчит. Развёрнутый ответ
    с явным «проверка НЕ ВЫПОЛНЕНА» даёт `visibility_check.py`.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import visibility_check as vc
    except ImportError:
        return 0, []
    gh = vc.public_on_github()
    if gh is None:
        return 0, []
    try:
        mr = vc.mirrors_in_deploy(
            (BASE_REPO / "templates/deploy.sh").read_text(
                encoding="utf-8", errors="replace"))
    except OSError:
        return 0, []
    bad = sorted(gh - mr)
    return len(bad), [f"{n} — публична, но не в MIRRORS: массовый режим "
                      f"зальёт в неё _base/" for n in bad]


def skills_uncharted() -> tuple[int, list[str]]:
    """Скиллы на диске, которых нет в карте `/auto` §2д.

    🔴 ПОВОД, 04.09.2026. Карта заведена 29.08 со словами «скиллов стало
    девять за один день, и без списка вахта их не вспомнит». Через неделю
    выяснилось, что **`/machine` в ней не было вовсе** — скилл существовал
    с 02.09, а карта про него не знала.

    Список, который ведут руками, стареет — даже список, заведённый против
    забывания (`PIT-097`: список — намерение, свойство объекта — факт).
    Здесь свойство объекта — **каталог в `.claude/skills/`**.
    """
    import re
    skills_dir = BASE_REPO / ".claude/skills"
    card = skills_dir / "auto/SKILL.md"
    if not skills_dir.is_dir() or not card.is_file():
        return 0, []
    on_disk = {d.name for d in skills_dir.iterdir() if (d / "SKILL.md").is_file()}
    charted = set(re.findall(r"^\|\s*\*\*`/([a-z-]+)`\*\*",
                             card.read_text(encoding="utf-8", errors="replace"), re.M))
    missing = sorted(on_disk - charted)
    return len(missing), [f"{n} — есть на диске, нет в карте `/auto` §2д"
                          for n in missing]


CHECKS = (
    ("скиллов вне карты", skills_uncharted),
    ("публичных реп вне защиты", public_unprotected),
    ("дней без разбора переписи", census_stalled),
    ("отставших от канона", canon_lag),
    ("повреждённых архивов", broken_archives),
    ("дней до порога размера", growth_forecast),
    ("реп за жёстким потолком", heavy_repos),
    ("реп с копиями", repo_copies),
    ("минут тишины", batch_silence),
    ("просроченных задач", overdue_tasks),
    ("дней без архива", archive_age),
    ("хуков без +x", hooks_executable),
    ("сессий на грани удаления", sessions_expiring),
)


def over_threshold(value: int, limit: int, inverted: bool) -> bool:
    """Перейдён ли порог. Вынесено из `main()`, чтобы канарейка проверяла
    ТУ САМУЮ логику, а не свою копию.

    🔴 Прежняя канарейка сравнивала литералы и была тождеством, истинным
    при любом пороге, а настоящее сравнение с ветвлением по `inverted`
    жило в `main()` и не покрывалось вовсе. Именно инверсию докстрока
    называет уже пойманным дефектом — и её повторное появление канарейка
    не заметила бы (ревью 29.08.2026).
    """
    return value <= limit if inverted else value >= limit


def selftest() -> bool:
    """Проверяется РАЗЛИЧЕНИЕ обоих направлений порога, на границе.

    Обычный порог: тревога при значении НА пороге и выше, молчание ниже.
    Обратный: наоборот. Канарейка, не покрывающая оба направления,
    пропустила бы ровно тот дефект, ради которого заведён `LOWER_IS_WORSE`.
    """
    checks = (
        # (значение, порог, обратный, ожидаем тревогу)
        (4, 5, False, False),      # ниже обычного — молчит
        (5, 5, False, True),       # на обычном — тревога
        (6, 5, False, True),       # выше обычного — тревога
        (91, 90, True, False),     # выше обратного — молчит
        (90, 90, True, True),      # на обратном — тревога
        (0, 90, True, True),       # сильно ниже обратного — тревога
    )
    if not all(over_threshold(v, l, inv) is expected
               for v, l, inv, expected in checks):
        return False
    # И сами разряды не должны пересекаться: метка не может быть в обоих.
    if set(THRESHOLDS) & set(LOWER_IS_WORSE):
        return False

    # 🔴 У КАЖДОЙ ПРОВЕРКИ ОБЯЗАН БЫТЬ ПОРОГ. Без этой строки новая проверка,
    # добавленная в CHECKS без записи в THRESHOLDS, печатала бы значение
    # и молчала бы навсегда — «проверка без порога не проверка, а строка»
    # (поймано на хуках 29.08.2026, и повторилось бы на счётчике переписи).
    labels = {lab for lab, _ in CHECKS}
    if labels - set(THRESHOLDS) - set(LOWER_IS_WORSE):
        return False

    # 🔴 Счётчик переписи проверяется НА СВОИХ ДАННЫХ, а не на литералах
    # (`PIT-195`): движение счётчика `разобрано` должно гасить тревогу,
    # а стоящая непустая очередь — поднимать.
    import tempfile, datetime, io, contextlib
    global BASE_REPO
    real = BASE_REPO
    y = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    cases = (
        # (строки журнала, ожидаем тревогу)
        ((f"{y}\t5\t9\t100", f"{datetime.date.today()}\t7\t9\t100"), False),
        ((f"{y}\t5\t9\t100", f"{datetime.date.today()}\t5\t9\t100"), True),
        ((f"{y}\t5\t0\t100", f"{datetime.date.today()}\t5\t0\t100"), False),
    )
    ok = True
    try:
        for lines, expect in cases:
            with tempfile.TemporaryDirectory() as d:
                j = Path(d) / "05-infra-synthesis-lab/tools"
                j.mkdir(parents=True)
                (j / "census-progress.tsv").write_text(
                    "дата\tразобрано\tочередь_400\tвсего\n" + "\n".join(lines) + "\n",
                    encoding="utf-8")
                BASE_REPO = Path(d)
                days, _ = census_stalled()
                ok &= bool(days) is expect
    finally:
        BASE_REPO = real
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--all", action="store_true",
                    help="показать и зелёное — обычно оно молчит намеренно")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        ok = selftest()
        print("🟢 канарейка: порог пропускает ниже себя и ловит на себе"
              if ok else "🔴 канарейка: ПОРОГ НЕ РАЗЛИЧАЕТ")
        return 0 if ok else 1

    if not selftest():
        print("🔴 канарейка не прошла — вердикту ниже верить нельзя")
        return 1

    print(f"═══ Состояние системы · {dt.date.today()} ═══\n")
    crossed = []
    for label, probe in CHECKS:
        value, detail = probe()
        limit = THRESHOLDS.get(label, LOWER_IS_WORSE.get(label))
        inverted = label in LOWER_IS_WORSE
        if value < 0:
            print(f"  ⚠️  {label}: замер не удался — {detail[0]}")
            crossed.append(label)
            continue
        over = limit is not None and over_threshold(value, limit, inverted)
        if over:
            crossed.append(label)
            sign = "≤" if inverted else "≥"
            print(f"  🔴 {label}: {value}  (порог {sign} {limit})")
            for line in detail:
                print(f"        · {line}")
            # 🔴 Подсказка в момент находки, а не правило в документе.
            pop = _population(label)
            if (label not in MASS_IS_NORMAL and pop and value >= pop * 0.9):
                print(f"        🔴 {value} из {pop} — расхождение почти у ВСЕХ.")
                print("           Это чаще расхождение ОПРЕДЕЛЕНИЙ, чем состояния:")
                print("           мир не меняется одновременно и одинаково "
                      "(`PIT-183`).")
                print("           Проверить, тем ли считается, ДО разбора находок.")
        elif a.all:
            print(f"  🟢 {label}: {value}" + (f"  (порог {limit})" if limit else ""))

    if not crossed:
        print("  🟢 ни один порог не перейдён.\n")
        print("🔴 Зелёное молчит НАМЕРЕННО: уведомление, которое всё равно надо")
        print("   читать, контроль не снижает (Mackworth 1948 — минус 10–15 %")
        print("   точности за полчаса наблюдения; 72–99 % клинических тревог ложны).")
    else:
        print(f"\n  перешли порог: {len(crossed)} из {len(CHECKS)}")

    print("\n🔴 Проход УРОВНЕВЫЙ: состояние спрошено заново, ничего не помнится")
    print("   с прошлого раза. Потерянное событие потери действия не вызывает.")
    print("🔴 Но дыра, про которую никто не написал, невидима и здесь:")
    print("   уровневость снимает потерю события, а не отсутствие знания.")
    return 1 if crossed else 0


if __name__ == "__main__":
    sys.exit(main())
