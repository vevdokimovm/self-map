#!/usr/bin/env python3
"""close_batch.py — закрыть батч одной командой.

ЗАКАЗ ВЛАДЕЛЬЦА 28.08.2026: *«автоматизировать все процессы, что захардкожены
и часто приходится делать вручную, но почему-то до сих пор не автоматизированы»*.

ПОВОД — ЗАМЕР, А НЕ ОЩУЩЕНИЕ. Ритуал закрытия батча (`06-autonomous-mode-kit/
STANDARD.md` §2) — **семь шагов**, и за одну сессию 28.08.2026 он выполнялся
**больше двадцати раз** руками. Из семи автоматизированы были четыре
(`bump_repo.py`), остальные три вызывались отдельными командами, и порядок
приходилось помнить. Забытый шаг не виден сразу: версия поднята, а архива нет —
батч выглядит закрытым, но не пережил бы обрыв.

ЧТО ДЕЛАЕТ — весь ритуал, в правильном порядке, с остановкой на первом отказе:

    1. revision_check.py     — гейт обязан дать CLEAN (иначе стоп)
    2. bump_repo.py          — VERSION + CHANGELOG + WATCHLOG §0 +
                               «Текущая точка» + README-статус
    3. pack_release.py       — архив в ~/Downloads (старые НЕ удаляются)
    4. auto_log.py           — подтверждение строки в журнале прогона
                               (саму строку пишет шаг 2 — см. ниже)
    5. sync_base_local.py    — раздача канона (ТОЛЬКО для base-repo)

🔴 ЖУРНАЛ ПРОГОНА ПИШЕТ ШАГ 2, А НЕ ШАГ 4 — с 03.09.2026 (`ROADMAP` §P0-1,
`ADR-007`). Признак жизни для watchdog излучает `bump_repo.py`: он и есть
тот, кто закрывает батч, а ритуал — лишь один из его вызывающих. Пока строку
писал ритуал, любой обход ритуала гасил watchdog молча (`PIT-174`).

Шаг 4 сохранён и вызывает журнал по-прежнему — он стал **подтверждением**:
повторная запись отсекается самим `auto_log.py` по дословному совпадению
заметки, и шаг печатает «уже записано». Смысл шага изменился, порядок и
нумерация — нет: перенумерованный ритуал переписал бы таблицу состояний,
скиллу и три докстроки ради косметики.

🔴 КОНТРАКТ РИТУАЛА — кандидат №10 очереди внедрения, заведён 29.08.2026.
Предусловия проверялись и раньше, но нигде не были НАЗВАНЫ; постусловия
не проверялись вовсе. Разница существенна: непроверенное постусловие
превращает «ритуал отработал» в «ритуал не упал», а это разные утверждения.

ПРЕДУСЛОВИЯ (проверяются до первой записи, отказ останавливает всё):
  · аргумент — ИМЯ репы, не путь, и такая репа существует;
  · у репы есть `VERSION` — она версионируемая;
  · задан `--title`, кроме режима осмотра `--state`;
  · гейт ревизии зелёный (или явный `--skip-gate` с разобранным падением);
  · мета-гейт подтверждает, что сами проверки живы.

ПОСТУСЛОВИЯ (проверяются ПОСЛЕ, и это новое):
  · `VERSION` выросла ровно на одну ступень выбранного разряда;
  · в `CHANGELOG.md` появилась секция ровно этой версии;
  · архив собран и записан строкой в `reports/releases/LEDGER.tsv`;
  · в `runs/auto.log` появилась строка с этой версией.

ИНВАРИАНТ (верен до и после, нарушение = батч оборвался посередине):
  · `VERSION` == последний тег в `LEDGER.tsv` == версия в последней строке
    `auto.log` для этой репы. Три числа сходятся — батч закрыт; расходятся —
    видно, на каком шаге оборвалось (`STANDARD.md`, таблица состояний).

ЧЕГО НЕ ДЕЛАЕТ И ПОЧЕМУ:
  · **не пишет за вахту тело CHANGELOG** — это содержание работы, не ритуал;
    текст передаётся аргументом или файлом, иначе батч закрывается пустым
    описанием, и через месяц непонятно, что в нём было;
  · **не решает, какой это подъём** (major/minor/patch) — суждение;
  · **не гасит и не ставит сторожа** — им управляет авто-режим, у которого
    свои основания (`/auto` §0).

🔴 ГЕЙТ ПЕРВЫМ, НЕ ПОСЛЕДНИМ. Если проверка падает — версия не поднимается
вовсе. Обратный порядок (сначала поднять, потом проверить) оставляет репу
в состоянии «версия новая, содержание сломано», которое чинится сложнее,
чем не начатый батч.

ЗАПУСК
    close_batch.py <репа> --patch --title "…" --body-stdin < body.md
    close_batch.py <репа> --minor --title "…" --body-file body.md
    close_batch.py <репа> --patch --title "…" --dry-run
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Корень определяется общим модулем: скрипт может быть запущен и из базы,
# и из копии кита в репе-наследнике (`_base/scripts/`). См. `_roots.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402
BASE_REPO, REPOS, FROM_KIT = resolve_roots(__file__)


def run(cmd: list[str], stdin_text: str | None = None) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, input=stdin_text)
    return p.returncode, (p.stdout + p.stderr)


def step(n: int, total: int, title: str) -> None:
    print(f"\n[{n}/{total}] {title}")


def batch_state(repo: Path) -> tuple[str, str, str]:
    """Три числа, по которым видно, закрыт ли батч: VERSION · LEDGER · журнал.

    🔴 Заведено 29.08.2026 после двух обрывов за день. Батч закрыт, когда
    три источника сходятся; расходятся — видно, на каком шаге оборвалось
    (`06-autonomous-mode-kit/STANDARD.md`, таблица состояний).

    ЧЕГО НЕ ЛОВИТ: батч, где все три числа записаны, но содержание не сделано.
    Совпадение чисел доказывает, что ритуал прошёл, а не что работа выполнена.
    """
    version = (repo / "VERSION").read_text(encoding="utf-8").strip() \
        if (repo / "VERSION").is_file() else "—"

    ledger = repo / "reports" / "releases" / "LEDGER.tsv"
    last_archive = "—"
    if ledger.is_file():
        rows = [r for r in ledger.read_text(encoding="utf-8").splitlines()
                if r.strip() and not r.startswith("#")]
        if rows:
            parts = rows[-1].split("\t")
            if len(parts) > 1:
                last_archive = parts[1]

    log = BASE_REPO / "06-autonomous-mode-kit" / "runs" / "auto.log"
    last_log = "—"
    if log.is_file():
        for line in reversed(log.read_text(encoding="utf-8").splitlines()):
            parts = line.split("\t")
            if len(parts) >= 4 and parts[1] == repo.name and parts[2] == "batch":
                import re as _re
                m = _re.search(r"v?(\d+\.\d+\.\d+)", parts[3])
                if m:
                    last_log = m.group(1)
                break
    return version, last_archive, last_log


def canon_spread(repo: Path) -> tuple[bool, str]:
    """Роздан ли канон наследникам. Только для базы; (ок, пояснение).

    🔴 ЗАВЕДЕНО 03.09.2026 ЖИВЫМ ОБРЫВОМ. Ритуал базы — ШЕСТЬ шагов, а состояние
    знало о трёх (VERSION · архив · журнал). Раздача оборвалась на таймауте,
    четыре последние по алфавиту репы остались без канона, — и `--state`
    ответил «батч закрыт **полностью**».

    Утверждение было ложным, и ложным в сторону успокоения: вахта, спросившая
    состояние, узнала бы о недоделке только от `system_status.py`, если бы его
    позвали. Это тот же класс, что весь день: «шаг не упал» и «результат шага
    на месте» — разные утверждения, а шаг, который вообще не проверяется, —
    третье, худшее.

    ЦЕНА ИЗМЕРЕНА: 3.2 с на 63 репы (`--check` не пишет ничего). Дёшево
    настолько, что вопрос «а не дорого ли спрашивать» не стоит.

    🔴 ОТКАЗ НЕ ГЛУШИТСЯ (`71` §7ж): недоступный `gh` роняет раздачу
    с ненулевым кодом, и это сообщается как «проверить не удалось»,
    а НЕ как «всё хорошо».
    """
    try:
        res = subprocess.run(
            ["python3", str(BASE_REPO / "scripts/sync_base_local.py"), "--all", "--check"],
            capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"раздача не отвечает: {exc}"
    if res.returncode != 0:
        tail = (res.stdout or res.stderr or "").strip().splitlines()
        return False, (f"🔴 проверить НЕ УДАЛОСЬ (код {res.returncode}): "
                       f"{tail[-1][:70] if tail else 'без вывода'}")
    lag = [x.split()[0] for x in res.stdout.splitlines()
           if "ОТСТАЛА" in x or "РАЗОШЛАСЬ" in x]
    if lag:
        show = ", ".join(lag[:4]) + (f" и ещё {len(lag) - 4}" if len(lag) > 4 else "")
        return False, f"канон НЕ роздан: {len(lag)} реп ({show})"
    return True, "канон роздан всем наследникам"


def print_state(repo: Path) -> None:
    v, a, l = batch_state(repo)
    # 🔴 У базы шагов шесть, и шестой — единственный, пишущий ЗА ПРЕДЕЛЫ репы.
    # Раньше он не входил в состояние вовсе, см. `canon_spread`.
    spread_ok, spread_why = (True, "") if repo != BASE_REPO else canon_spread(repo)
    if v == a == l and spread_ok:
        print(f"  состояние: батч закрыт полностью (v{v})")
        return
    if v == a == l and not spread_ok:
        print(f"  🔴 версия закрыта (v{v}), но раздача НЕ завершена: {spread_why}")
        print("     → доделать: python3 scripts/sync_base_local.py --all")
        print("     🔴 Версию заново НЕ поднимать — раздача идёт последней "
              "именно затем, чтобы её обрыв не стоил батча (STANDARD.md).")
        return
    # 🔴 Журнал прогона заведён позже части реп: у закрытых до него записи нет
    # и быть не может. «Версия = архив, журнала нет» — это НЕ незакрытый батч,
    # а репа, не трогавшаяся с тех пор. Требовать от неё записи задним числом
    # значило бы выдумать факт.
    if v == a and l == "—":
        print(f"  состояние: батч закрыт (v{v}); записи в журнале нет — "
              f"репа закрыта до заведения журнала прогона")
        return
    if not spread_ok:
        print(f"     плюс раздача: {spread_why}")
    print(f"  🔴 РАСХОЖДЕНИЕ — батч закрыт не до конца:")
    print(f"       VERSION      : {v}")
    print(f"       архив LEDGER : {a}")
    print(f"       журнал прогона: {l}")
    if v != a:
        print(f"     → архива нет: python3 scripts/pack_release.py {repo}")
    if v != l:
        print(f"     → записи нет: 06-autonomous-mode-kit/bin/auto_log.py "
              f"--repo {repo.name} --type batch --note \"v{v}: …\"")
    print("     🔴 Версию заново НЕ поднимать — будет дыра в нумерации "
          "(STANDARD.md, таблица состояний).")


def verify_postconditions(repo: Path, new_version: str) -> list[str]:
    """Постусловия ритуала — проверяются ПОСЛЕ работы, а не вместо неё.

    🔴 Зачем это отдельно от шагов. Каждый шаг сообщает, что он отработал.
    Но «шаг не упал» и «результат шага на месте» — разные утверждения:
    `pack_release.py` может вернуть ноль и не дописать строку в реестр,
    и до сегодня это заметил бы только следующий батч, а то и никто.

    Проверяется РЕЗУЛЬТАТ на диске, а не коды возврата, которые уже
    проверены выше.
    """
    problems = []
    if (repo / "VERSION").read_text(encoding="utf-8").strip() != new_version:
        problems.append(f"VERSION не равна {new_version}")

    changelog = repo / "CHANGELOG.md"
    if changelog.is_file() and f"[{new_version}]" not in \
            changelog.read_text(encoding="utf-8", errors="replace"):
        problems.append(f"в CHANGELOG нет секции [{new_version}]")

    ledger = repo / "reports" / "releases" / "LEDGER.tsv"
    if ledger.is_file():
        # Строка из одних пробелов проходила фильтр и роняла разбор
        # IndexError'ом — причём ПОСЛЕ подъёма версии и сборки архива:
        # батч сделан, а вахта видит traceback вместо вердикта.
        # Соседний `batch_state()` делал это правильно (ревью 29.08.2026).
        rows = [l for l in ledger.read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.startswith("#")]
        last = rows[-1].split("\t") if rows else []
        if len(last) < 2 or last[1] != new_version:
            problems.append(f"в LEDGER.tsv последняя запись не {new_version}")
    else:
        problems.append("реестра выпусков нет вовсе")

    log = BASE_REPO / "06-autonomous-mode-kit" / "runs" / "auto.log"
    if log.is_file():
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-5:]
        if not any(new_version in l and repo.name in l for l in tail):
            problems.append(f"в auto.log нет строки про {new_version}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    # 🔴 НЕ `required=True`. Режим `--state` только ЧИТАЕТ состояние и ничего
    # не пишет — заголовок ему не нужен по смыслу. Требование обязательного
    # `--title` делало диагностику невозможной без выдумывания фиктивного
    # заголовка, то есть инструмент осмотра требовал материала для записи.
    # Поймано 29.08.2026 при попытке узнать состояние после обрыва по лимиту.
    ap.add_argument("--title", help="тезис батча одной строкой "
                                    "(обязателен для закрытия, не для --state)")
    ap.add_argument("--body-stdin", action="store_true")
    ap.add_argument("--body-file")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--major", action="store_true")
    g.add_argument("--minor", action="store_true")
    g.add_argument("--patch", action="store_true")
    ap.add_argument("--state", action="store_true",
                    help="показать состояние батча (VERSION · архив · журнал) и выйти")
    ap.add_argument("--dry-run", action="store_true",
                    help="показать план, ничего не выполняя")
    ap.add_argument("--skip-gate", action="store_true",
                    help="🔴 только когда падение гейта уже разобрано и признано "
                         "предсуществующим — иначе батч закроется поверх дефекта")
    a = ap.parse_args()

    # 🔴 Имя репы, а НЕ путь. Аргумент всегда доклеивается к ~/repos/, поэтому
    # привычное `.` из каталога репы разворачивается в сам `~/repos` — каталог
    # без VERSION. Заведено 29.08.2026: вызов `close_batch.py .` ответил
    # «это не версионируемая репа», и сообщение было верным по факту и ложным
    # по смыслу — проверялся не тот каталог, который имел в виду вызывающий
    # (`71-fail-loud-and-sourcing.md` §7ж: отказ обязан называть, ЧТО проверено).
    if a.repo in {".", ".."} or "/" in a.repo:
        print(f"🔴 ожидается ИМЯ репы, а не путь: получено «{a.repo}»")
        print(f"   аргумент доклеивается к {REPOS} — путь здесь не работает.")
        guess = Path(a.repo).resolve().name
        if (REPOS / guess / "VERSION").is_file():
            print(f"   вероятно, имелось в виду: {guess}")
        return 1

    repo = REPOS / a.repo
    if not (repo / "VERSION").is_file():
        print(f"🔴 нет файла VERSION по пути {repo / 'VERSION'}")
        if not repo.is_dir():
            print(f"   каталога {repo} не существует вовсе — проверь имя репы.")
            near = sorted(d.name for d in REPOS.iterdir()
                          if d.is_dir() and a.repo.lower() in d.name.lower())
            if near:
                print(f"   похожие имена: {', '.join(near[:5])}")
        else:
            print("   каталог есть, но версии в нём нет — это не версионируемая репа.")
        return 1

    if not a.state and not a.title:
        print("🔴 для закрытия батча нужен --title (тезис одной строкой)")
        return 1

    # 🔴 РАЗРЯД ПОДЪЁМА ОБЯЗАТЕЛЕН. Раньше группа была необъявлена
    # обязательной, и забытый флаг молча поднимал patch — то есть ритуал
    # принимал за вахту решение, которое докстрока прямо называет суждением
    # («не решает, какой это подъём»). Откатить нельзя: версию заново
    # не поднимают. Найдено ревью 29.08.2026.
    if not a.state and not (a.major or a.minor or a.patch):
        print("🔴 нужен разряд подъёма: --major | --minor | --patch")
        print("   Это суждение вахты, ритуал его за неё не принимает.")
        return 1

    body = ""
    if a.body_stdin:
        body = sys.stdin.read()
    elif a.body_file:
        body = Path(a.body_file).read_text(encoding="utf-8")

    bump_flag = "--major" if a.major else "--minor" if a.minor else "--patch"
    # У базы шагов шесть: добавляется раздача канона наследникам.
    total = 6 if (REPOS / a.repo) == BASE_REPO else 5

    if a.state:
        print_state(repo)
        return 0

    if a.dry_run:
        print(f"ПЛАН для {a.repo} ({bump_flag}):")
        print("  1. revision_check.py --root … → обязан CLEAN")
        print("  2. gate_monitor.py → живы ли сами проверки (не блокирует)")
        print(f"  3. bump_repo.py {bump_flag} --title {a.title!r}")
        print("  4. pack_release.py → архив в ~/Downloads")
        print("  5. auto_log.py --type batch")
        if repo == BASE_REPO:
            print("  6. sync_base_local.py --all → раздача канона "
                  "по 54 наследникам")
            print("     🔴 единственный шаг, который пишет ЗА ПРЕДЕЛЫ "
                  "этой репы")
        return 0

    # --- 1. гейт -------------------------------------------------------------
    step(1, total, "гейт ревизии")
    if a.skip_gate:
        print("  ⚠ пропущен по --skip-gate (падение признано предсуществующим)")
    else:
        rc, out = run(["python3", str(BASE_REPO / "scripts/revision_check.py"),
                       "--root", str(repo)])
        last = [l for l in out.strip().split("\n") if l.strip()][-1:]
        print("  " + (last[0] if last else "нет вывода"))
        # 🔴 29.08.2026: проверяем КОД ВОЗВРАТА, а не слово в выводе.
        # Раньше искали «CLEAN» в тексте — и это сломалось в тот же день,
        # когда вердикт переформулировали («ни одна из проверок не сработала»,
        # см. `UNCOVERED` в гейте: пустой положительный вердикт вреден).
        # Код возврата — контракт, текст — оформление. Опираться надо
        # на контракт: он не меняется от того, что кто-то переписал строку.
        if rc != 0:
            print("\n🔴 ОСТАНОВЛЕНО: гейт не CLEAN — версия НЕ поднята.")
            print("   Починить и повторить, либо --skip-gate, если падение")
            print("   предсуществующее и это разобрано.")
            return 1

    # --- 1а. мета-гейт: живы ли сами проверки --------------------------------
    # 🔴 Добавлено 29.08.2026. Зелёный гейт означает «ни одна проверка не
    # сработала» — и это ровно то, что видно, когда проверки МЁРТВЫ. Различить
    # «чисто» и «не проверялось» изнутри самого гейта нельзя; для этого нужен
    # второй, внешний по отношению к нему инструмент (69 §4г: гейт был красным
    # 41 день, 65 релизов, и никто не смотрел).
    step(2, total, "мета-гейт: живы ли проверки")
    rc, out = run(["python3", str(BASE_REPO / "scripts/gate_monitor.py"),
                   "--root", str(repo)])
    tail = [l for l in out.strip().split("\n") if l.startswith(("ИТОГ", "🔴", "[FAIL]"))]
    print("  " + (tail[-1] if tail else "нет вывода"))
    if "[FAIL]" in out:
        # НЕ останавливаем батч: мёртвая проверка — дефект инфраструктуры,
        # а не содержания, и чинить её посреди чужого батча значит смешивать
        # два предмета. Но и молчать нельзя — иначе повторится тот же 41 день.
        print("  ⚠ найдены мёртвые проверки — разобрать отдельным батчем базы")
        for line in out.split("\n"):
            if line.strip().startswith("·"):
                print("    " + line.strip())

    # --- 3. версия и живые документы -----------------------------------------
    step(3, total, "версия · CHANGELOG · WATCHLOG · README")
    rc, out = run(["python3", str(BASE_REPO / "scripts/bump_repo.py"), a.repo,
                   bump_flag, "--title", a.title, "--body-stdin"], stdin_text=body)
    print("\n".join("  " + l for l in out.strip().split("\n")[:8]))
    if rc != 0:
        print("\n🔴 ОСТАНОВЛЕНО на подъёме версии.")
        return 1

    new_version = (repo / "VERSION").read_text(encoding="utf-8").strip()

    # --- 3. архив ------------------------------------------------------------
    step(4, total, "архив релиза")
    rc, out = run(["python3", str(BASE_REPO / "scripts/pack_release.py"), str(repo)])
    print("\n".join("  " + l for l in out.strip().split("\n")[-3:]))
    if rc != 0:
        print("\n🔴 архив не собран — батч НЕ закрыт (версия уже поднята,")
        print("   собрать вручную: pack_release.py " + str(repo))
        return 1

    # --- 4. журнал прогона ---------------------------------------------------
    # 🔴 Подтверждение, а не запись: строку уже оставил `bump_repo.py`.
    # Шаг оставлен исполняемым, а не выброшен, ровно затем, чтобы отказ
    # журнала на шаге 2 был виден здесь — вместо него напечатается
    # «записано», и это будет означать, что признака жизни не было.
    step(5, total, "журнал авто-режима (подтверждение)")
    rc, out = run(["python3", str(BASE_REPO / "06-autonomous-mode-kit/bin/auto_log.py"),
                   "--repo", a.repo, "--type", "batch",
                   "--note", f"v{new_version}: {a.title}"])
    print("  " + out.strip().split("\n")[-1])

    # 🔴 ШЕСТОЙ ШАГ, И ТОЛЬКО ДЛЯ БАЗЫ: раздать новый канон наследникам.
    #
    # Заведено 29.08.2026 находкой уровневого смотрителя (`system_status.py`):
    # он показал «54 репы отстали от канона» ЧЕРЕЗ ЧАС после того, как канон
    # был роздан вручную. Причина не в раздаче — она исправна: просто база
    # с тех пор закрыла три батча, и каждый сделал все 54 репы отставшими
    # заново. Раздача руками не может за этим успевать по построению.
    #
    # Стоимость измерена, а не предположена: `timing.py` — **32 секунды**
    # на все репы. Это дешевле, чем постоянное расхождение канона и копий.
    #
    # Раздача идёт ПОСЛЕ архива: если она упадёт, батч уже сохранён, и потеря
    # ограничена расхождением копий, которое чинится следующим прогоном.
    # Сравнение по ПУТИ, а не по имени: корень уже вычислен
    # `_roots.resolve_roots`, заведённым ровно чтобы не гадать по имени.
    if repo == BASE_REPO:
        step(6, total, "раздача канона наследникам")
        rc, out = run(["python3", str(BASE_REPO / "scripts/sync_base_local.py"),
                       "--all"])
        moved = [l for l in out.splitlines() if "→" in l]
        if rc == 0:
            print(f"  обновлено реп: {len(moved)}")
        else:
            # Не фатально: канон в базе уже верен, разошлись только копии.
            print(f"  ⚠️  раздача не прошла (код {rc}) — копии отстали, "
                  f"почини: python3 scripts/sync_base_local.py --all")

    # 🔴 ПОСТУСЛОВИЯ. «Ритуал не упал» и «результат на месте» — разные
    # утверждения, и до 29.08.2026 проверялось только первое.
    broken = verify_postconditions(repo, new_version)
    if broken:
        print(f"\n🔴 ПОСТУСЛОВИЯ НАРУШЕНЫ ({len(broken)}) — батч закрыт НЕ полностью:")
        for line in broken:
            print(f"    · {line}")
        print("   Разбор: 06-autonomous-mode-kit/STANDARD.md, таблица состояний.")
        print_state(repo)
        return 1

    print_state(repo)
    print(f"\n✅ батч закрыт: {a.repo} v{new_version}")
    print("   Сторож авто-режима переставляется отдельно — им управляет /auto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
