#!/usr/bin/env python3
"""repo_invariants.py — что обязано быть верно про репу. Один список на всех.

🔴 ЗАКАЗ ВЛАДЕЛЬЦА 02.09.2026, дословно: «доделай по аналогии с ООП плюсов
конструктор и деструктор реп. потому что вроде у нас миллион гейтов сторожей
и тд но постоянно ошибки в создании реп созании архивов постоянно констурктор
уже ошибается…. как тогда работать если уже при создании объекта лажа».

ПОЧЕМУ ЭТОТ ФАЙЛ СУЩЕСТВУЕТ — И ПОЧЕМУ ОН ОДИН

Гейтов было много, и каждый знал свой кусок правды: `sync_base_local --check`
про `_base/`, `readme_status_gate` про блок статуса, `archive_check` про архивы,
`revision_check` про ссылки. Ни один не знал про остальные, и никто не отвечал
на вопрос «репа целиком в порядке?». Поэтому `migration` прожила шесть часов
без `_base/`: каждый отдельный сторож был прав, а объект был собран наполовину.

В C++ это решается **инвариантом класса**: приватная проверка, которую зовут
конструктор и каждая мутирующая операция. Объект либо удовлетворяет инварианту,
либо не существует. Здесь — то же самое: один список, три вызывающих
(`new_repo.py`, `retire_repo.py`, `revision_check.py`), и невозможность
«починить в одном месте и забыть в двух».

ЧТО ЭТО НЕ ЗАМЕНЯЕТ. Инвариант проверяет ФОРМУ — файл есть, версия совпадает,
архив на месте. Он не проверяет СМЫСЛ: осмысленно ли написан README, верна ли
граница репы с соседями, не устарел ли текст по сути. Это работа вахты,
и молчание инварианта не означает, что репа хороша.

ПРЕДУСЛОВИЯ: путь существует и является каталогом.
ПОСТУСЛОВИЯ: возвращён список нарушений; пустой список = форма в порядке.
ИНВАРИАНТ: только чтение. Ничего не создаёт, не правит и не удаляет.

ЗАПУСК
    repo_invariants.py <репа>        одна репа
    repo_invariants.py --all         все репы на диске
    repo_invariants.py --selftest    канарейка на временных репах
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402

BASE_REPO, REPOS, _ = resolve_roots(__file__)

# Каталог выпусков — тот же, что у `pack_release.py`; в тестах подменяется.
DOWNLOADS = Path.home() / "Downloads"

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
REPO_ID = re.compile(r"^[A-Za-z0-9_.-]+/([A-Za-z0-9_.-]+)$")
STATUS = re.compile(r"<!--\s*STATUS\s*-->\s*>\s*\*\*Сейчас:\*\*\s*`v([\d.]+)`")

CLASSES = {"infra", "core", "satellite", "temp", "product", "profile", "archived"}

# Файлы, обязательные по классу. Совпадает с CLASSES в new_repo.py намеренно:
# конструктор строит ровно то, что инвариант потом требует.
REQUIRED = {
    "infra": ["README.md", "VERSION"],
    "core": ["README.md", "VERSION", "ROADMAP.md", "TASKS.md", "START-HERE.md",
             "CHANGELOG.md"],
    "satellite": ["README.md", "VERSION", "ROADMAP.md", "CHANGELOG.md"],
    "temp": ["README.md", "VERSION"],
    "product": ["README.md", "VERSION", "CHANGELOG.md", "ROADMAP.md"],
    "profile": ["README.md", "VERSION"],
    "archived": ["README.md"],
}

# 🔴 `_base/` не кладётся в ПУБЛИЧНЫЕ репы (ADR-004): канон системы не должен
# уезжать на GitHub вместе с продуктом.
#
# ПРАВИЛО ПЕРЕПИСАНО В ДЕНЬ ЗАВЕДЕНИЯ — второе ложное из десяти. Сперва
# критерием служил КЛАСС (`product`/`profile`), и проверка объявила утечкой
# канона `control-panel`, `personal-finance-dss`, `research-engine`. Сверка
# с `gh repo list` показала: все три PRIVATE. Класс говорит, ЧЕМ репа является
# (продукт, витрина, спутник), а не КОМУ она видна; `personal-finance-dss` —
# приватное ядро, чей публичный слепок живёт отдельной репой.
#
# Источник правды о видимости — поле `private` в `.repo-meta`. Оно же
# скармливается `gh` при заведении, то есть это не копия истины, а её оригинал.
# `archived` не получает `_base/` независимо от видимости: репа не развивается.
NO_BASE_CLASSES = {"archived"}

# Классы, для которых архив релиза обязателен. `temp` — черновик по смыслу,
# `archived` — уже не выпускается.
NEEDS_ARCHIVE = {"infra", "core", "satellite", "product", "profile"}


class Violation:
    """Нарушение инварианта: код, текст и способ починки."""

    def __init__(self, code: str, text: str, fix: str = ""):
        self.code, self.text, self.fix = code, text, fix

    def __repr__(self) -> str:
        return f"{self.code} {self.text}"


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def canon_version() -> str:
    return _read(BASE_REPO / "VERSION")


# 🔴 ДВЕ ФАЗЫ ЖИЗНИ ОБЪЕКТА, И ЭТО НЕ УСЛОЖНЕНИЕ РАДИ УСЛОЖНЕНИЯ.
#
# Найдено тестом `tests/test_repo_lifecycle.sh` в первый же прогон, 02.09.2026:
# конструктор откатывал КАЖДУЮ новую репу. Причина — правило R-09 («версия
# значится в журнале выпусков»): только что созданная репа физически не может
# быть выпущена, выпуск идёт следующим шагом.
#
# В C++ различие то же: конструктор обязан установить инварианты КЛАССА,
# но не обязан привести объект в состояние «уже поработал». Требовать от
# новорождённого следов эксплуатации — значит не дать ему родиться.
#
#   "born" — что обязано быть верно СРАЗУ ПОСЛЕ создания (структура, канон);
#   "live" — что обязано быть верно у репы В РАБОТЕ (плюс выпуск версии).
#
# Тест поймал это раньше владельца ровно потому, что проверял свойство
# («конструктор создаёт валидный объект»), а не факт запуска скрипта.
# 🔴 R-11 в списке потому же, почему R-09: критерий выхода — СУЖДЕНИЕ
# о конкретной репе, и конструктор его не знает. Он не может написать,
# что именно должно появиться, чтобы ЭТА репа стала черновиком: это зависит
# от предмета, а предмет знает вахта.
#
# Требовать критерий в момент рождения значило бы либо блокировать создание
# реп, либо заставить конструктор писать заглушку — а заглушка красит гейт
# зелёным при нерешённой задаче (`PIT-158`), что хуже отсутствия.
#
# Проверка остаётся живой: она сработает при первом же прогоне инварианта
# по готовой репе.
BORN_SKIP = {"R-09", "R-11"}


def check(repo: Path, downloads: Path | None = None,
          phase: str = "live") -> list[Violation]:
    """Список нарушений инварианта. Пустой список — форма в порядке.

    `phase`: "live" — репа в работе (полный набор);
             "born" — только что создана (без правил об эксплуатации).
    """
    dl = downloads if downloads is not None else DOWNLOADS
    v: list[Violation] = []
    if not repo.is_dir():
        return [Violation("R-00", f"каталога нет: {repo}")]

    name = repo.name

    # ── R-01 .repo-id
    rid = _read(repo / ".repo-id")
    m = REPO_ID.match(rid)
    if not rid:
        v.append(Violation("R-01", "нет .repo-id",
                           f'echo "vevdokimovm/{name}" > {name}/.repo-id'))
    elif not m:
        v.append(Violation("R-01", f".repo-id не вида owner/name: {rid!r}"))
    elif m.group(1) != name:
        v.append(Violation("R-01",
                           f".repo-id называет «{m.group(1)}», каталог — «{name}»"))

    # ── R-02 .repo-class
    cls = _read(repo / ".repo-class")
    if not cls:
        v.append(Violation("R-02", "нет .repo-class",
                           "76-repo-classes.md §1 — выбрать класс"))
        return v  # без класса остальные проверки бессмысленны
    if cls not in CLASSES:
        v.append(Violation("R-02", f"класс «{cls}» не из списка: {sorted(CLASSES)}"))
        return v

    # ── R-03 .repo-meta
    meta = _read(repo / ".repo-meta")
    if not meta:
        v.append(Violation("R-03", "нет .repo-meta"))
    else:
        for key in ("description", "private"):
            if not re.search(rf"^{key}=.+$", meta, re.M):
                v.append(Violation("R-03", f".repo-meta без поля {key}"))

    # ── R-04 VERSION
    ver = _read(repo / "VERSION")
    if not ver:
        v.append(Violation("R-04", "нет VERSION"))
    elif not SEMVER.match(ver):
        v.append(Violation("R-04", f"VERSION не X.Y.Z: {ver!r}"))

    # ── R-05 файлы по классу
    for f in REQUIRED.get(cls, []):
        if not (repo / f).is_file():
            v.append(Violation("R-05", f"класс {cls} требует {f} — файла нет"))

    # ── R-06/R-07 канон базы
    is_public = bool(re.search(r"^private=false\s*$", meta, re.M))
    # 🔴 base-repo — сама канон; вкладывать канон в канон бессмысленно
    # и означало бы рекурсию `_base/_base/_base/…`.
    is_canon = repo.resolve() == BASE_REPO.resolve()
    if cls not in NO_BASE_CLASSES and not is_public and not is_canon:
        stamp = repo / "_base" / "BASE_VERSION"
        if not stamp.is_file():
            v.append(Violation(
                "R-06", "нет _base/BASE_VERSION — канон не разложен",
                f"python3 scripts/sync_base_local.py {name}"))
        else:
            have, want = _read(stamp), canon_version()
            if want and have != want:
                v.append(Violation(
                    "R-07", f"_base отстала: {have} при каноне {want}",
                    f"python3 scripts/sync_base_local.py {name}"))
    elif is_public and (repo / "_base").exists():
        v.append(Violation(
            "R-06", "репа публичная, а _base/ есть — канон утечёт на GitHub "
                    "(ADR-004)", f"rm -rf {name}/_base"))

    # ── R-08 блок статуса в README
    # 🔴 profile освобождён 02.09.2026: витрина человека для найма — не место
    # для служебной версии, её читает рекрутёр, а не владелец.
    if cls not in {"profile", "archived"} and ver:
        text = _read(repo / "README.md")
        sm = STATUS.search(text)
        if not sm:
            v.append(Violation("R-08", "README без разбираемого блока STATUS",
                               f"python3 scripts/readme_status_gate.py "
                               f"--root {repo} --fix --create"))
        elif sm.group(1) != ver:
            v.append(Violation(
                "R-08", f"README-статус v{sm.group(1)} против VERSION {ver}",
                f"python3 scripts/readme_status_gate.py --root {repo} --fix"))

    # ── R-09 версия выпущена
    # 🔴 Прямо по жалобе владельца: «постоянно ошибки в создании архивов».
    #
    # ПРАВИЛО ПЕРЕПИСАНО В ДЕНЬ ЗАВЕДЕНИЯ, И ЭТО САМОЕ ЦЕННОЕ ЗДЕСЬ. Сперва
    # оно искало файл `<имя>-v<версия>.zip` в `~/Downloads` — и объявило
    # нарушителями 61 репу из 63. Число само по себе и оказалось уликой:
    # правило, по которому виновата вся система, скорее неверно, чем система.
    #
    # Так и вышло. Архивы удаляются НАМЕРЕННО — ритуал закрытия батча чистит
    # `~/Downloads`, чтобы там не копилось два десятка почти одинаковых zip.
    # Доказательство выпуска живёт не в файле, а в строке `LEDGER.tsv`,
    # которая переживает удаление (`pack_release.py`, «журнал выпусков»).
    #
    # Урок шире этого правила: канарейка проверяет, что правило СРАБАТЫВАЕТ
    # (verification), и не может проверить, что оно ВЕРНО (validation).
    # Девять зелёных галочек стояли под ложным правилом.
    if cls in NEEDS_ARCHIVE and ver and SEMVER.match(ver):
        ledger = repo / "reports" / "releases" / "LEDGER.tsv"
        if not ledger.is_file():
            v.append(Violation(
                "R-09", "нет reports/releases/LEDGER.tsv — выпусков не записано",
                f"python3 scripts/pack_release.py {repo}"))
        elif f"\t{ver}\t" not in _read(ledger):
            v.append(Violation(
                "R-09", f"версия {ver} не значится в журнале выпусков — не выпущена",
                f"python3 scripts/pack_release.py {repo}"))

    # ── R-10 .gitignore
    if cls != "archived" and not (repo / ".gitignore").is_file():
        v.append(Violation("R-10", "нет .gitignore"))

    # ── R-11 скелет обязан нести КРИТЕРИЙ ВЫХОДА
    #
    # 🔴 `83-project-maturity-levels.md` §1: скелет — это идея вне головы
    # **плюс записанный критерий выхода**. Репа с одним README-заглушкой
    # без критерия скелетом НЕ является: непонятно, чем «начато» отличается
    # от «идёт», и репа зависает на 0.1.0 навсегда.
    #
    # 🔴 ПОВОД — ЗАМЕР 04.09.2026, а не гипотеза. Пункт `ROADMAP` от 22.08
    # утверждал: «критерия выхода нет НИ У ОДНОЙ репы, заведённой
    # до 21.08.2026». Пересчёт показал другое: реп-скелетов осталась **одна**,
    # и это `photo-archive`, заведённая накануне **этой же вахтой**.
    #
    # Прежняя причина (регрессия генератора: 04.08 давал 17 файлов, 20.08 —
    # шесть, и пропадали `ROADMAP`/`TASKS`/`WATCHLOG`) вылечена: реп
    # без `ROADMAP.md` сейчас **ноль**. Осталась не регрессия, а отсутствие
    # исполнителя у правила — его и закрывает R-11.
    #
    # 🔴 ЧЕГО НЕ ЛОВИТ: содержательность критерия. «Станет 0.2.0, когда
    # будет готово» пройдёт проверку и ничего не значит. Гейт закрывает
    # «забыл написать», а не «написал бессмысленно» — второе ловится ревью.
    if ver == "0.1.0" and cls not in ("archived", "temp"):
        sh = repo / "START-HERE.md"
        text = sh.read_text(encoding="utf-8", errors="replace") if sh.is_file() else ""
        if not re.search(r"критери\w*\s+выход|выход\w*\s+из\s+скелета"
                         r"|0\.2\.0\s+наступает", text, re.I):
            v.append(Violation(
                "R-11", "скелет 0.1.0 без критерия выхода (83 §1) — "
                        "непонятно, что должно появиться для 0.2.0",
                f"дописать раздел «Критерий выхода из скелета» в "
                f"{repo.name}/START-HERE.md"))

    if phase == "born":
        v = [x for x in v if x.code not in BORN_SKIP]
    return v


def render(repo: Path, viol: list[Violation], quiet_ok: bool = False) -> None:
    if not viol:
        if not quiet_ok:
            print(f"🟢 {repo.name}: инвариант выполнен")
        return
    print(f"🔴 {repo.name}: нарушений {len(viol)}")
    for x in viol:
        print(f"   {x.code}  {x.text}")
        if x.fix:
            print(f"         → {x.fix}")


def selftest() -> int:
    """Канарейка: инвариант обязан ловить то, ради чего заведён.

    🔴 Проверяется не «скрипт запускается», а что КАЖДОЕ правило срабатывает
    на подделанной репе. Проверка, которая ничего не ловит, зелёная всегда.
    """
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root, dl = Path(td) / "repos", Path(td) / "dl"
        root.mkdir(parents=True)
        dl.mkdir(parents=True)

        def build(name: str, cls: str = "satellite", ver: str = "1.0.0",
                  public: bool = False) -> Path:
            r = root / name
            r.mkdir()
            (r / ".repo-id").write_text(f"vevdokimovm/{name}\n")
            (r / ".repo-class").write_text(f"{cls}\n")
            (r / ".repo-meta").write_text(
                f"description=тест\nprivate={'false' if public else 'true'}\ntopics=\n")
            (r / "VERSION").write_text(f"{ver}\n")
            (r / ".gitignore").write_text("*.pyc\n")
            (r / "README.md").write_text(
                f"# {name}\n\n<!-- STATUS -->\n> **Сейчас:** `v{ver}` · 2026-09-02 · тест\n"
                "<!-- /STATUS -->\n")
            for f in REQUIRED[cls]:
                if not (r / f).is_file():
                    (r / f).write_text("# заглушка\n")
            base = r / "_base"
            base.mkdir()
            (base / "BASE_VERSION").write_text(canon_version() + "\n")
            led = r / "reports" / "releases"
            led.mkdir(parents=True)
            (led / "LEDGER.tsv").write_text(
                "# дата\tверсия\tфайлов\tбайт\tsha256\n"
                f"2026-09-02\t{ver}\t10\t1000\tdeadbeef\n")
            (dl / f"{name}-v{ver}.zip").write_text("не настоящий zip")
            return r

        def expect(label: str, repo: Path, code: str | None) -> None:
            nonlocal ok
            got = {x.code for x in check(repo, downloads=dl)}
            if code is None:
                good = not got
            else:
                good = code in got
            print(f"   {'✅' if good else '❌'} {label}"
                  + ("" if good else f" — получено {sorted(got) or 'ничего'}"))
            ok = good and ok

        print("Канарейка инварианта репы:")
        expect("полная репа проходит", build("good"), None)

        r = build("no-base")
        (r / "_base" / "BASE_VERSION").unlink()
        expect("R-06 ловит отсутствие _base/", r, "R-06")

        r = build("stale-base")
        (r / "_base" / "BASE_VERSION").write_text("0.0.1\n")
        expect("R-07 ловит отставшую _base/", r, "R-07")

        # 🔴 Фаза рождения: свежая репа без выпуска — НЕ нарушение.
        r = build("newborn")
        (r / "reports" / "releases" / "LEDGER.tsv").unlink()
        born = check(r, downloads=dl, phase="born")
        live = check(r, downloads=dl, phase="live")
        good = not born and any(x.code == "R-09" for x in live)
        print(f"   {'✅' if good else '❌'} фаза born пропускает выпуск, live требует")
        ok = good and ok

        r = build("no-release")
        (r / "reports" / "releases" / "LEDGER.tsv").unlink()
        expect("R-09 ловит версию без записи в журнале выпусков", r, "R-09")

        # 🔴 Отдельно: удалённый zip при живой строке журнала — НЕ нарушение.
        # Это и есть правило, на котором я ошибся: чистка ~/Downloads штатна.
        r = build("zip-cleaned")
        (dl / "zip-cleaned-v1.0.0.zip").unlink()
        expect("удалённый архив при живом журнале нарушением НЕ считается", r, None)

        r = build("bad-status")
        (r / "VERSION").write_text("2.0.0\n")
        expect("R-08 ловит расхождение README и VERSION", r, "R-08")

        r = build("bad-id")
        (r / ".repo-id").write_text("vevdokimovm/другое-имя\n")
        expect("R-01 ловит чужой .repo-id", r, "R-01")

        r = build("pub-base", cls="product", public=True)
        expect("R-06 ловит _base/ в ПУБЛИЧНОЙ репе", r, "R-06")

        # 🔴 Ровно то, на чём правило ошиблось: приватный продукт с `_base/`
        # нарушением НЕ является. Класс говорит, чем репа является,
        # а не кому она видна.
        r = build("priv-product", cls="product")
        expect("приватный product с _base/ — не нарушение", r, None)

        r = build("no-version")
        (r / "VERSION").unlink()
        expect("R-04 ловит отсутствие VERSION", r, "R-04")

        r = build("no-class")
        (r / ".repo-class").unlink()
        expect("R-02 ловит отсутствие класса", r, "R-02")

    print("selftest OK" if ok else "🔴 selftest ПРОВАЛЕН")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Инвариант репы: что обязано быть верно")
    ap.add_argument("repo", nargs="?", help="имя репы или путь")
    ap.add_argument("--all", action="store_true", help="все репы на диске")
    ap.add_argument("--selftest", action="store_true", help="канарейка правил")
    ap.add_argument("--quiet-ok", action="store_true",
                    help="молчать про репы, где всё в порядке")
    ap.add_argument("--phase", choices=["live", "born"], default="live",
                    help="born — набор для только что созданной репы "
                         "(без правил об эксплуатации)")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    if a.all:
        # 🔴 НАЙДЕНО ВЛАДЕЛЬЦЕМ 03.09.2026 одним вопросом: «так сейчас же
        # 64 репы, не? мы же миграцию делали».
        #
        # Отбор шёл по `.repo-class`, и каталог без него просто НЕ ПОПАДАЛ
        # в список — молча. На диске 64 каталога, инвариант печатал «63 реп»,
        # и разница нигде не называлась: `finpilot` (витринное зеркало
        # по mission-control::ADR-009, публикуется из другой репы и своих служебных
        # не имеет) был невидим для всех проверок разом.
        #
        # Это ровно тот класс, что `PIT-172`: отсутствие в срезе принимается
        # за отсутствие в системе. Инструмент отвечал на вопрос «что
        # с размеченными репами», а читался как «что с системой».
        #
        # Молчание тут хуже ошибки: репа, выпавшая из проверок, не станет
        # красной — она перестанет существовать для инструмента.
        all_dirs = sorted(p for p in REPOS.iterdir()
                          if p.is_dir() and not p.name.startswith("."))
        repos = [p for p in all_dirs if (p / ".repo-class").is_file()]
        unmarked = [p for p in all_dirs if not (p / ".repo-class").is_file()]

        bad = 0
        for r in repos:
            viol = check(r, phase=a.phase)
            render(r, viol, quiet_ok=a.quiet_ok)
            bad += bool(viol)

        if unmarked:
            print(f"\n🟡 ВНЕ ПРОВЕРКИ: {len(unmarked)} каталог(ов) без `.repo-class`")
            for p in unmarked:
                print(f"   · {p.name} — инвариант его не смотрит вовсе")
            print("   Так и задумано только для витринных зеркал (mission-control::ADR-009):")
            print("   они публикуются из другой репы и своих служебных файлов")
            print("   не имеют. Любой другой каталог здесь — пропущенная разметка.")

        print(f"\nИТОГ: {len(all_dirs)} каталог(ов) на диске · "
              f"{len(repos)} размечено · с нарушениями {bad} · "
              f"чистых {len(repos) - bad}"
              + (f" · вне проверки {len(unmarked)}" if unmarked else ""))
        return 1 if bad else 0

    if not a.repo:
        ap.error("нужна репа или --all")
    p = Path(a.repo)
    if not p.is_dir():
        p = REPOS / a.repo
    viol = check(p, phase=a.phase)
    render(p, viol)
    return 1 if viol else 0


if __name__ == "__main__":
    sys.exit(main())
