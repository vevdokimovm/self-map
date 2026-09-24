"""Полный цикл выпуска репы — то, что делал `deploy.sh`, только изнутри.

🔴 ЗАКАЗ ВЛАДЕЛЬЦА 09.09.2026, дословно: «давай сделай этот .git в каждой
репе и будем уже коммитить через тебя напрямую а не скрипт… только
обязательные условия надо чекать и следить: 1. чтобы НЕ было
в контрибьюторах claude 2. описания были как деплой делает 3. ассеты были
как деплой 4. короче все как делал скрипт деплой ты теперь делать будешь.
только сам скрипт не удаляй он важен».

Восемь шагов, каждый проверяется. Паритет с `deploy.sh` сверен построчно
15.09.2026 по заказу владельца: *«сравни паблиш чтобы он делал как деплой!»*

    1. атрибуция     — в истории и настройках только владелец
    2. описание      — парсером ДЕПЛОЙЕРА из секции CHANGELOG
    3. ассет         — архив той версии, той репы и СВЕЖИЙ (VERSION, .repo-id, ключевые файлы = рабочей копии)
    4. предполётные  — WATCHLOG §0 = версии; файлов > 100 МБ нет; место на диске
    5. коммит и тег  — тег стоит на дереве ТОЙ ЖЕ версии (аудит дерева тега)
    6. push          — ретраи как у деплойера + сверка ФАКТИЧЕСКОГО remote
    7. релиз         — создать или привести к стандарту; ассет сверен по sha256
    8. уборка        — описание и топики из .repo-meta; архив удалён после сверки

🔴 `deploy.sh` НЕ УДАЛЯЕТСЯ И НЕ ЗАМЕНЯЕТСЯ. Он остаётся каноном формата
и рабочим путём для случаев, которые здесь не покрыты: раздача по зеркалам,
BACKFILL старых версий, REPAIR чужих релизов, проверка repos-map. Этот
инструмент делает ОДНУ репу за проход, из её рабочей копии.

🔴 ЧЕГО НЕ ДЕЛАЕТ: не поднимает версию (это `close_batch.py`), не собирает
архив (это `pack_release.py`), не решает, что выпускать.

Применение:
    publish.py <репа> [--dry] [--no-release] [--keep-archive]
    publish.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import artifacts_dir, resolve_roots  # noqa: E402

БАЗА = Path(__file__).resolve().parent.parent
OWNER = "vevdokimovm"


def шаг(n: int, всего: int, что: str) -> None:
    print(f"[{n}/{всего}] {что}")


def запуск(cmd: list[str], где: Path | None = None) -> tuple[int, str]:
    res = subprocess.run(cmd, cwd=где, capture_output=True, text=True,
                         encoding="utf-8")
    return res.returncode, (res.stdout + res.stderr).strip()


def версия_репы(корень: Path) -> str:
    ф = корень / "VERSION"
    if not ф.is_file():
        raise SystemExit(f"🔴 нет {ф} — выпускать нечего")
    return ф.read_text(encoding="utf-8").strip()


def проверить_атрибуцию(корень: Path) -> None:
    """🔴 ПЕРВЫМ ШАГОМ, ДО КОММИТА. Условие №1 владельца."""
    код, вывод = запуск([sys.executable, str(БАЗА / "scripts/attribution_check.py"),
                         "--repo", str(корень)])
    if код != 0:
        print(вывод)
        raise SystemExit("🔴 ОСТАНОВЛЕНО: атрибуция нарушена, выпуск не начат")
    print("      " + вывод.splitlines()[0])


def описание(корень: Path, репа: str, версия: str) -> tuple[str, Path]:
    """Заголовок и тело — парсером ДЕПЛОЙЕРА. Условие №2 владельца."""
    куда = Path("/tmp") / f"notes-{репа}-{версия}.md"
    # 🔴 Только stdout: парсер печатает заголовок в stdout, а «тело: <путь>» —
    # в stderr. `запуск` склеивает оба потока, и до 24.09.2026 хвост «тело: …»
    # уходил в заголовок релиза И в сообщение коммита (base-repo v4.211.2–4,
    # academic-portfolio v1.4.0).
    res = subprocess.run([sys.executable, str(БАЗА / "scripts/release_notes.py"),
                          версия, "--repo", репа, "--out", str(куда),
                          "--changelog", str(корень / "CHANGELOG.md")],
                         capture_output=True, text=True, encoding="utf-8")
    строки = [л.strip() for л in res.stdout.splitlines() if л.strip()]
    if res.returncode != 0 or not строки:
        print(res.stdout + res.stderr)
        raise SystemExit(f"🔴 описание не собрано — в CHANGELOG нет секции [{версия}]. "
                         f"Это правило деплойера: релиз без описания не создаётся.")
    return строки[0], куда


def найти_архив(репа: str, версия: str) -> Path | None:
    """Ассет ровно с тем именем, что делает деплойер. Условие №3 владельца."""
    путь = Path(artifacts_dir()) / f"{репа}-v{версия}.zip"
    return путь if путь.is_file() else None


def selftest() -> bool:
    """Канарейка: инструменты на месте и проверки паритета с deploy.sh работают."""
    for имя in ("attribution_check.py", "release_notes.py"):
        ф = БАЗА / "scripts" / имя
        if not ф.is_file():
            return False
        if запуск([sys.executable, str(ф), "--selftest"])[0] != 0:
            return False
    import tempfile
    import zipfile
    with tempfile.TemporaryDirectory() as tmp:
        т = Path(tmp)
        # заголовок релиза — одна строка без служебного хвоста парсера
        (т / "CHANGELOG.md").write_text("# r — CHANGELOG\n\n## [1.2.3] — 2026-09-24 12:00 — тезис канарейки (PATCH)\n\n"
                                        "- пункт\n", encoding="utf-8")
        заголовок, _ = описание(т, "r", "1.2.3")
        if "тело:" in заголовок or "\n" in заголовок or "тезис канарейки" not in заголовок:
            return False
        def арх(имя: str, версия_в: str, rid: str | None, n: int = 6) -> Path:
            путь = т / имя
            with zipfile.ZipFile(путь, "w") as z:
                z.writestr("r-v1/VERSION", версия_в + "\n")
                if rid is not None:
                    z.writestr("r-v1/.repo-id", rid)
                for i in range(n):
                    z.writestr(f"r-v1/f{i}.md", "x")
            return путь
        if проверить_архив(арх("ok.zip", "1.2.3", "r"), "r", "1.2.3"):
            return False
        # реальный формат .repo-id: владелец/имя (так 66 реп из 66)
        if проверить_архив(арх("owner.zip", "1.2.3", "vevdokimovm/r\n"), "r", "1.2.3"):
            return False
        if not any("не туда" in б for б in
                   проверить_архив(арх("owner-alien.zip", "1.2.3", "vevdokimovm/q"), "r", "1.2.3")):
            return False
        if not any("устарел" in б for б in проверить_архив(арх("old.zip", "1.2.2", "r"), "r", "1.2.3")):
            return False
        if not any("не туда" in б for б in проверить_архив(арх("alien.zip", "1.2.3", "q"), "r", "1.2.3")):
            return False
        # свежесть: архив собран до правки CHANGELOG — ловится при совпавшей VERSION
        дерево = т / "tree"
        дерево.mkdir()
        (дерево / "VERSION").write_text("1.2.3\n", encoding="utf-8")
        (дерево / "CHANGELOG.md").write_text("новая запись", encoding="utf-8")
        with zipfile.ZipFile(т / "stale.zip", "w") as z:
            z.writestr("r-v1/VERSION", "1.2.3\n")
            z.writestr("r-v1/CHANGELOG.md", "старая запись")
            for i in range(6):
                z.writestr(f"r-v1/f{i}.md", "x")
        if not any("до последней правки" in б for б in
                   проверить_архив(т / "stale.zip", "r", "1.2.3", дерево)):
            return False
        (дерево / "CHANGELOG.md").write_text("старая запись", encoding="utf-8")
        if проверить_архив(т / "stale.zip", "r", "1.2.3", дерево):
            return False
        (т / "WATCHLOG.md").write_text("# ж\n\n- **Версия:** 1.2.3 · **Дата:** x\n", encoding="utf-8")
        if версия_в_watchlog(т) != "1.2.3":
            return False
        if not (заглушка("") and заглушка("Release v1") and not заглушка("Нормальное описание релиза " * 3)):
            return False
        if not (semver("4.10.0") > semver("4.9.9")):
            return False
    return True


# ── Паритет с deploy.sh: пороги берутся ТЕ ЖЕ, что у деплойера ──────────────
RETRIES = 5
RETRY_SLEEP = 4
GH_TIMEOUT = 120
PUSH_TIMEOUT = 900
UPLOAD_TIMEOUT = 1800
MIN_FREE_MB = 2048
GH_HARD_LIMIT = 100 * 1024 * 1024
GH_SOFT_LIMIT = 50 * 1024 * 1024
# Отказ по содержанию, а не по сети: ретрай не поможет (FATAL_PATTERNS деплойера).
# 🔴 «remote rejected» сюда НЕ входит, хотя у деплойера входит: 15.09.2026
# `cannot lock ref` пришёл с этим словом, а коммит при этом УЕХАЛ. Поэтому
# после любого отказа push сверяется фактическое состояние remote.
FATAL = ("GH001", "exceeds GitHub", "pre-receive hook declined", "Large files detected",
         "Permission denied", "403", "authentication failed", "repository not found",
         "non-fast-forward", "fetch first")


def запуск_т(cmd: list[str], где: Path | None = None, таймаут: int = GH_TIMEOUT) -> tuple[int, str]:
    """`запуск` с таймаутом: вызов gh/git не имеет права висеть бесконечно (GH_TIMEOUT)."""
    try:
        res = subprocess.run(cmd, cwd=где, capture_output=True, text=True,
                             encoding="utf-8", timeout=таймаут)
    except subprocess.TimeoutExpired:
        return 124, f"таймаут {таймаут} с: {' '.join(cmd[:3])}"
    return res.returncode, (res.stdout + res.stderr).strip()


def semver(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (-1,)


# Файлы, которые меняются в КАЖДОМ выпуске. Если их содержимое в архиве
# расходится с рабочей копией — архив собран раньше последней правки.
СВЕЖЕСТЬ = ("VERSION", "CHANGELOG.md", "README.md", "WATCHLOG.md")


def проверить_архив(архив: Path, репа: str, версия: str,
                    корень: Path | None = None) -> list[str]:
    """Архив тот и той версии: VERSION и .repo-id внутри (деплойер §PIT-014, §48).

    Имя файла — не доказательство: архив мог остаться от прошлой сборки
    или уехать не в ту репу при переименовании.
    """
    import zipfile
    беды: list[str] = []
    try:
        with zipfile.ZipFile(архив) as z:
            имена = z.namelist()
            def верхний(имя: str) -> str | None:
                for n in имена:
                    части = n.rstrip("/").split("/")
                    if части[-1] == имя and len(части) <= 2:
                        return n
                return None
            ver = верхний("VERSION")
            if ver is None:
                беды.append("в архиве нет VERSION в корне")
            elif (внутри := z.read(ver).decode("utf-8", "replace").strip()) != версия:
                беды.append(f"VERSION в архиве = {внутри}, выпускается {версия} — архив устарел")
            rid = верхний(".repo-id")
            if rid is not None:
                # Формат `владелец/имя` — у всех 66 реп; деплойер берёт первую
                # строку и отрезает владельца (`find_repo_id`). Первая редакция
                # этого не делала и остановила собственный выпуск ложной тревогой.
                первая = z.read(rid).decode("utf-8", "replace").strip().splitlines()
                чей = первая[0].strip().rsplit("/", 1)[-1] if первая else ""
                if чей and чей != репа:
                    беды.append(f".repo-id в архиве = «{чей}», выпускается «{репа}» — архив не туда")
            if len([n for n in имена if not n.endswith("/")]) < 5:
                беды.append("в архиве меньше 5 файлов — не похоже на репу")
            # 🔴 СВЕЖЕСТЬ, А НЕ ТОЛЬКО ВЕРСИЯ. 15.09.2026 v4.211.2 ушла на GitHub
            # со старым архивом: первая попытка выпуска остановилась, я поправил
            # код и CHANGELOG, а `pack_release.py` при повторе ответил «уже
            # существует — не перезаписываю» (SYN-005) и вернул код 0. VERSION
            # совпал — проверка пропустила. Вложение релиза расходилось с тегом
            # по `CHANGELOG.md` и `publish.py`; найдено сверкой после выпуска.
            if корень is not None:
                for имя in СВЕЖЕСТЬ:
                    внутри_путь = верхний(имя)
                    на_диске = корень / имя
                    if внутри_путь is None or not на_диске.is_file():
                        continue
                    if z.read(внутри_путь) != на_диске.read_bytes():
                        беды.append(f"{имя} в архиве не совпадает с рабочей копией — "
                                    "архив собран до последней правки")
    except zipfile.BadZipFile:
        беды.append("архив битый (BadZipFile)")
    return беды


def версия_в_watchlog(корень: Path) -> str | None:
    """Версия из WATCHLOG §0; короткий WATCHLOG-указатель ведёт в настоящий журнал."""
    import re
    wl = корень / "WATCHLOG.md"
    if not wl.is_file():
        return None
    текст = wl.read_text(encoding="utf-8", errors="replace")
    if текст.count("\n") <= 40:
        m = re.search(r"\(([^)]*WATCHLOG\.md)\)", текст)
        if m and (корень / m.group(1)).is_file():
            текст = (корень / m.group(1)).read_text(encoding="utf-8", errors="replace")
    m = re.search(r"\*\*Версия:\*\*\s*([0-9][0-9.]*[0-9])", текст)
    return m.group(1) if m else None


def тяжёлые_файлы(корень: Path) -> tuple[list[str], list[str]]:
    """Что уйдёт в коммит и упрётся в лимиты GitHub — ДО push (549 МБ, 22.08.2026)."""
    код, вывод = запуск_т(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                          корень, 300)
    отказ: list[str] = []
    предупр: list[str] = []
    for имя in filter(None, вывод.split("\0")) if код == 0 else []:
        ф = корень / имя
        try:
            размер = ф.stat().st_size if ф.is_file() and not ф.is_symlink() else 0
        except OSError:
            continue
        if размер > GH_HARD_LIMIT:
            отказ.append(f"{имя} — {размер / 1048576:.0f} МБ")
        elif размер > GH_SOFT_LIMIT:
            предупр.append(f"{имя} — {размер / 1048576:.0f} МБ")
    return отказ, предупр


def отправить(корень: Path, ссылка: str, ожидание: str) -> None:
    """push с ретраями, как `retry` деплойера, и сверкой ФАКТИЧЕСКОГО remote.

    `ожидание` — sha, который должен оказаться на remote под этой ссылкой.
    """
    пауза = RETRY_SLEEP
    for попытка in range(1, RETRIES + 1):
        # 🔴 `--no-thin` — найдено опытом 13.09.2026 на копии `quick-answers`:
        # в частичной репе нет старых версий для дельт, тонкий пакет падал.
        код, вывод = запуск_т(["git", "push", "-q", "--no-thin", "origin", ссылка],
                              корень, PUSH_TIMEOUT)
        if код == 0:
            return
        цель = ссылка.split(":")[-1]
        цель = цель if цель.startswith("refs/") else (f"refs/heads/{цель}" if not цель.startswith("v")
                                                    else f"refs/tags/{цель}")
        _, есть = запуск_т(["git", "ls-remote", "origin", цель, f"{цель}^{{}}"], корень)
        if ожидание and ожидание in есть:
            print(f"      🟡 push вернул ошибку, но {цель} на remote = локальному — считаю отправленным")
            return
        if any(f in вывод for f in FATAL):
            print(вывод)
            raise SystemExit(f"🔴 push {ссылка}: отказ по содержанию — ретрай не поможет")
        if попытка < RETRIES:
            print(f"      попытка {попытка}/{RETRIES} не прошла — жду {пауза} с (обычно TLS-таймаут)")
            import time
            time.sleep(пауза)
            пауза *= 2
    print(вывод)
    raise SystemExit(f"🔴 push {ссылка} не прошёл за {RETRIES} попыток")


def заглушка(тело: str) -> bool:
    """Описание релиза-заглушка (release_is_stub деплойера)."""
    т = (тело or "").strip()
    return not т or т.startswith(("Release ", "Синхронизация дерева")) or len(т.encode()) < 40


def сверить_ассет(репа: str, версия: str, архив: Path) -> bool:
    """Ассет в релизе совпал с локальным архивом по размеру И sha256."""
    код, вывод = запуск_т(["gh", "api", f"repos/{OWNER}/{репа}/releases/tags/v{версия}",
                           "-q", f'.assets[]|select(.name=="{архив.name}")|"\\(.size) \\(.digest)"'])
    размер, _, дайджест = вывод.strip().partition(" ")
    свой = hashlib.sha256(архив.read_bytes()).hexdigest()
    return код == 0 and размер == str(архив.stat().st_size) and дайджест.removeprefix("sha256:") == свой


def убрать_архив(репа: str, версия: str, архив: Path) -> None:
    """Удалить локальный архив, когда он ДОКАЗАННО лежит в релизе.

    🔴 ПАРИТЕТ С `deploy.sh`: там архив, полностью уехавший на GitHub (тег +
    релиз + ассет), удаляется ПО УМОЛЧАНИЮ. `publish.py` заявлен как «всё как
    делал скрипт деплой», но этот шаг пропустил — 15.09.2026 в `~/Developer`
    скопилось шесть архивов, заметил владелец. Удаление только после сверки
    размера И sha256: имя файла в релизе ещё не значит, что загрузка дошла целиком.
    """
    if сверить_ассет(репа, версия, архив):
        архив.unlink()
        print(f"      архив сверен с релизом (размер и sha256) и удалён: {архив.name}")
    else:
        print(f"      🟡 архив НЕ удалён — не сверился с ассетом релиза: {архив}")


def обновить_метаданные(корень: Path, репа: str) -> None:
    """Описание и топики репы из `.repo-meta` — на КАЖДОМ выпуске, как у деплойера.

    Иначе репа навсегда остаётся с описанием от первого создания.
    """
    мета = корень / ".repo-meta"
    if not мета.is_file():
        return
    поля = dict(line.split("=", 1) for line in мета.read_text(encoding="utf-8").splitlines()
                if "=" in line)
    описание_ = поля.get("description", "").strip()
    темы = [x.strip() for x in поля.get("topics", "").split(",") if x.strip()]
    cmd = ["gh", "repo", "edit", f"{OWNER}/{репа}"]
    if описание_:
        cmd += ["--description", описание_]
    for тема in темы:
        cmd += ["--add-topic", тема]
    if len(cmd) > 4:
        код, вывод = запуск_т(cmd)
        print("      описание и топики обновлены" if код == 0
              else f"      🟡 метаданные не обновлены: {вывод[-120:]}")


def main() -> int:
    р = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    р.add_argument("репа", nargs="?")
    р.add_argument("--dry", action="store_true", help="показать план, ничего не делать")
    р.add_argument("--no-release", action="store_true", help="без релиза на GitHub")
    р.add_argument("--keep-archive", action="store_true",
                   help="не удалять архив после сверки с GitHub (как KEEP_ARCHIVES=1 в deploy.sh)")
    р.add_argument("--selftest", action="store_true")
    a = р.parse_args()

    if a.selftest:
        ок = selftest()
        print("🟢 канарейка: инструменты выпуска на месте и живы, проверки паритета с deploy.sh работают"
              if ок else "🔴 КАНАРЕЙКА УПАЛА — нет или сломан attribution_check/release_notes")
        return 0 if ок else 1

    if not a.репа:
        р.error("нужно имя репы")

    # 🔴 `resolve_roots(__file__)` — сигнатура требует файл вызывающего:
    # она различает запуск из базы и из копии кита внутри репы-наследника.
    _, корень_реп, _ = resolve_roots(__file__)
    корень = корень_реп / a.репа
    if not корень.is_dir():
        raise SystemExit(f"🔴 нет каталога {корень}")
    if not (корень / ".git").exists():
        raise SystemExit(f"🔴 в {a.репа} нет .git — выпуск через git невозможен.\n"
                         f"   Заведите: scripts/git_adopt.py {a.репа}")

    версия = версия_репы(корень)
    всего = 8
    print(f"── выпуск {a.репа} v{версия} ──")

    шаг(1, всего, "атрибуция")
    проверить_атрибуцию(корень)

    шаг(2, всего, "описание из CHANGELOG (парсером деплойера)")
    заголовок, тело = описание(корень, a.репа, версия)
    print(f"      {заголовок[:88]}")

    шаг(3, всего, "ассет: тот ли архив")
    архив = найти_архив(a.репа, версия)
    if архив:
        беды = проверить_архив(архив, a.репа, версия, корень)
        if беды:
            for б in беды:
                print(f"      🔴 {б}")
            raise SystemExit("🔴 архив не соответствует выпуску — удали его и пересобери: "
                             f"rm {архив} && scripts/pack_release.py")
        print(f"      {архив.name} · VERSION и .repo-id внутри сходятся")
    else:
        print("      🔴 архива нет — релиз будет без ассета")

    шаг(4, всего, "предполётные проверки")
    wl = версия_в_watchlog(корень)
    if wl is None:
        print("      🟡 в WATCHLOG нет строки «**Версия:** X.Y.Z» — §0 не читается машиной")
    elif wl != версия:
        raise SystemExit(f"🔴 WATCHLOG §0 = {wl}, выпускается {версия} — точка входа в вахту отстала (PIT-018)")
    else:
        print(f"      WATCHLOG §0 на версии {версия}")
    отказ, предупр = тяжёлые_файлы(корень)
    for пп in предупр:
        print(f"      🟡 тяжелее 50 МБ: {пп}")
    if отказ:
        for пп in отказ:
            print(f"      🔴 тяжелее 100 МБ: {пп}")
        raise SystemExit("🔴 GitHub отклонит push (GH001). Свернуть в служебки: "
                         "07-media-to-text-lab/tools/heavy_media_to_note.py --apply (СТ-001)")
    свободно = shutil.disk_usage("/tmp").free // 1048576
    if свободно < MIN_FREE_MB:
        raise SystemExit(f"🔴 свободно {свободно} МБ (< {MIN_FREE_MB}) — на переполненном диске "
                         "заливается недокачанный ассет")
    print(f"      файлов > 100 МБ нет · свободно {свободно} МБ")

    if a.dry:
        print("\n🟡 --dry: дальше ничего не делаю")
        return 0

    шаг(5, всего, "коммит и тег")
    запуск(["git", "add", "-A"], корень)
    код, вывод = запуск(["git", "commit", "-m", заголовок], корень)
    if код != 0 and "nothing to commit" not in вывод:
        print(вывод)
        raise SystemExit("🔴 коммит не прошёл — вероятно, остановлен хуком")
    код, _ = запуск(["git", "tag", "-a", f"v{версия}", "-m", заголовок], корень)
    # 🔴 АУДИТ ДЕРЕВА ТЕГА (деплойер, PIT-014). «Тег уже был» раньше молча
    # принималось — а он мог стоять на дереве ДРУГОЙ версии.
    _, под_тегом = запуск(["git", "show", f"v{версия}:VERSION"], корень)
    if под_тегом.strip() != версия:
        raise SystemExit(f"🔴 тег v{версия} указывает на дерево с VERSION={под_тегом.strip() or '—'} — "
                         "история тега битая, авто-чинить не буду (решение владельца)")
    print(f"      тег v{версия}{' (уже был)' if код != 0 else ''} · дерево под тегом той же версии")

    шаг(6, всего, "push")
    _, голова = запуск(["git", "rev-parse", "HEAD"], корень)
    _, тег_sha = запуск(["git", "rev-parse", f"v{версия}"], корень)
    отправить(корень, "HEAD:main", голова.strip())
    отправить(корень, f"v{версия}", тег_sha.strip())
    print("      ветка и тег отправлены, remote сверен")

    шаг(7, всего, "релиз")
    if a.no_release:
        print("      пропущен по --no-release")
    else:
        _, теги = запуск(["git", "tag", "-l", "v*"], корень)
        старший = max((t.lstrip("v") for t in теги.split()), key=semver, default=версия)
        последний = "--latest=true" if semver(версия) >= semver(старший) else "--latest=false"
        код, есть = запуск_т(["gh", "release", "view", f"v{версия}", "--repo", f"{OWNER}/{a.репа}",
                              "--json", "name,body,assets"])
        if код != 0:
            код, вывод = запуск_т(["gh", "release", "create", f"v{версия}", "--repo", f"{OWNER}/{a.репа}",
                                   "--title", заголовок, "--notes-file", str(тело), последний])
            if код != 0:
                print(вывод)
                raise SystemExit("🔴 релиз не создан")
            print("      релиз создан" + (" (не помечен последним — есть старшая версия)"
                                          if последний.endswith("false") else ""))
        else:
            import json
            рел = json.loads(есть)
            # АУДИТ существующего релиза — как ensure_release деплойера.
            if заглушка(рел.get("body", "")):
                запуск_т(["gh", "release", "edit", f"v{версия}", "--repo", f"{OWNER}/{a.репа}",
                          "--title", заголовок, "--notes-file", str(тело)])
                print("      релиз был, описание-заглушка заменено описанием из CHANGELOG")
            elif рел.get("name") != заголовок:
                запуск_т(["gh", "release", "edit", f"v{версия}", "--repo", f"{OWNER}/{a.репа}",
                          "--title", заголовок])
                print("      релиз был, заголовок приведён к CHANGELOG")
            else:
                print("      релиз уже был и соответствует стандарту")
        if архив:
            if not сверить_ассет(a.репа, версия, архив):
                код, вывод = запуск_т(["gh", "release", "upload", f"v{версия}", str(архив),
                                       "--repo", f"{OWNER}/{a.репа}", "--clobber"], таймаут=UPLOAD_TIMEOUT)
                if код != 0 or not сверить_ассет(a.репа, версия, архив):
                    print(вывод[-300:])
                    raise SystemExit("🔴 ассет не залился целиком: размер или sha256 не сошлись — перезапусти")
            print(f"      ассет {архив.name} в релизе, размер и sha256 сверены")

    шаг(8, всего, "метаданные и уборка")
    обновить_метаданные(корень, a.репа)
    if архив and not a.no_release and not a.keep_archive:
        убрать_архив(a.репа, версия, архив)

    print(f"\n🟢 {a.репа} v{версия} выпущена")
    return 0


if __name__ == "__main__":
    sys.exit(main())
