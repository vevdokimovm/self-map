#!/usr/bin/env python3
"""Выпуск на GitHub изнутри рабочей копии — то, что делал `deploy.sh`.

🔴 ЗАКАЗ ВЛАДЕЛЬЦА 13.09.2026, дословно: «сделай так чтобы ты пушил комитил
релизил описания делал во всех репах также как делал это скрипт деплоя…
в папке девелопер лежат архивы – проведи полную процедуру деплоя сам как
раньше делал скрипт. а затем каждую репу так обнови на гите чтобы было
1 в 1 как у меня эталон».

Два режима:

    --archive <zip>   деплой версии из архива, как `deploy.sh`: дерево архива →
                      коммит «репа vX — тезис» → тег → push → релиз с описанием
                      из CHANGELOG архива и архивом во вложении. Рабочую копию
                      НЕ трогает: коммит строится во временном индексе.
    --sync <репа>     GitHub = рабочая копия 1 в 1 (по правилам `.gitignore`).

🔴 ДВЕ ПРОВЕРКИ ДО ЛЮБОЙ ОТПРАВКИ, и их нельзя отключить флагом:
  · секреты — функцией `scan_secrets` из хука `.githooks/pre-commit` (не копия:
    правило живёт в одном месте, `PIT-G`);
  · атрибуция — `attribution_check.py`: в подписи и сообщении только владелец.
Правила веса и форматов хука здесь НЕ применяются — `deploy.sh` их тоже
не применял, а эталон на диске уже прошёл их при своей сборке.

🔴 ЧТО НЕ ДЕЛАЕТСЯ: `reset`, `checkout`, `clean` — ни одной команды, пишущей
в рабочее дерево. Рабочая копия — ОРИГИНАЛ, история на GitHub — её копия.

Применение:
    github_sync.py --archive ~/Developer/<репа>-vX.Y.Z.zip [--dry]
    github_sync.py --sync <репа> [<репа>…] [--dry]
    github_sync.py --selftest
"""

from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402

БАЗА = Path(__file__).resolve().parent.parent
OWNER = "vevdokimovm"
ЛИМИТ_ФАЙЛА = 100 * 1048576          # GitHub отклоняет весь push
ЛИМИТ_PUSH = 1900 * 1048576          # GitHub: 2 ГиБ на push, берём с запасом
ПАУЗЫ = [0, 10, 30, 60, 120]


def say(*a) -> None:
    # 🔴 flush обязателен: при выводе в файл Python копит строки, и прогресс
    # долгой раскатки 13.09 был не виден до самого конца.
    print(*a, flush=True)


def git(корень: Path, *арг: str, env: dict | None = None,
        cwd: Path | None = None, вход: str | None = None) -> tuple[int, str]:
    r = subprocess.run(["git", *арг], cwd=cwd or корень, env=env,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", input=вход)
    return r.returncode, (r.stdout + r.stderr).strip()


def _сканер():
    """Функция поиска секретов из хука — единственный источник правила."""
    путь = БАЗА / ".githooks" / "pre-commit"
    загрузчик = importlib.machinery.SourceFileLoader("_precommit", str(путь))
    спец = importlib.util.spec_from_loader("_precommit", загрузчик)
    модуль = importlib.util.module_from_spec(спец)
    загрузчик.exec_module(модуль)
    return модуль.scan_secrets


def распаковать(архив: Path, куда: Path) -> int:
    """Распаковать zip С ПРАВАМИ ФАЙЛОВ. Возвращает число файлов с восстановленным +x.

    🔴 `zipfile.extractall` права НЕ восстанавливает: режим лежит в
    `external_attr`, упаковщик его пишет (в архиве есть 755), а распаковка молча
    выдаёт всем 644. Дерево шло в `git add` — и каждый деплой коммитил скрипты
    неисполняемыми. Это и был «периодически слетающий +x» во всех репах:
    найдено 15.09.2026, когда `video_to_note.py` не запустился.
    """
    восстановлено = 0
    with zipfile.ZipFile(архив) as z:
        z.extractall(куда)
        for info in z.infolist():
            режим = (info.external_attr >> 16) & 0o777
            if info.is_dir() or not режим:
                continue
            путь = куда / info.filename
            if путь.is_file() and not путь.is_symlink():
                путь.chmod(режим)
                восстановлено += bool(режим & 0o111)
    return восстановлено


def _исключения_упаковщика() -> set[str]:
    """Каталоги, которые `pack_release.py` НЕ кладёт в архив (единый источник правды)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from pack_release import JUNK_DIRS
        return set(JUNK_DIRS)
    except Exception:  # noqa: BLE001 — список исключений не должен ронять деплой
        return {"telegram-photos", "telegram-media", "photo-archive", "heavy-originals"}


def сохранить_исключённое(корень: Path, env: dict, дерево: Path) -> None:
    """Не удалять из git то, чего в архиве нет ПО ПРАВИЛУ упаковщика.

    🔴 НАЙДЕНО 25.09.2026. Деплой из архива строит коммит по дереву архива:
    чего в архиве нет — то удаляется. А `pack_release.py` намеренно исключает
    тяжёлые хранилища (`telegram-photos`, `telegram-media`, `photo-archive`,
    `heavy-originals`): они раздувают архив на порядок, а у GitHub жёсткий
    лимит 100 MiB на файл.

    Пересечение этих двух правил — молчаливое массовое удаление. Сухой прогон
    публикации `self-map v1.13.0` показал **«удалено 5970»**, из них 3297 —
    телеграм-фото, которые никто не удалял: их просто нет в архиве по правилу.
    На момент находки заряжено во всех репах: `it-base` 2611, `christ-walk`
    2893, `legal-knowledge-base` 1126 файлов в тех же каталогах.

    🔴 РЕАЛЬНОЕ удаление этих файлов деплой из архива больше не переносит —
    и это верно: их удаляет вахта в рабочей копии, а рабочая копия уезжает
    режимом `--sync`, где дерево берётся с диска, а не из архива.

    Делается сбросом ИНДЕКСА на HEAD по этим путям, без выкладки файлов
    на диск: иначе во временное дерево материализовались бы гигабайты.
    """
    имена = _исключения_упаковщика()
    спеки = [f":(glob)**/{имя}/**" for имя in sorted(имена)]
    спеки += [f":(glob){имя}/**" for имя in sorted(имена)]
    код, вывод = git(корень, "reset", "-q", "HEAD", "--", *спеки, env=env, cwd=дерево)
    if код != 0 and "did not match" not in вывод:
        say(f"   🟡 исключённые упаковщиком каталоги не сохранены: {вывод[-160:]}")


def тег_есть(корень: Path, версия: str) -> bool:
    код, вывод = git(корень, "ls-remote", "--tags", "origin", f"refs/tags/v{версия}")
    return код == 0 and bool(вывод.strip())


def проверить_и_показать(корень: Path, дерево: Path, env: dict) -> tuple[int, int] | None:
    """Секреты и лимиты по изменённым файлам. None — отправлять нельзя."""
    код, вывод = git(корень, "diff", "--cached", "--name-only", "--no-renames",
                     "-z", "--diff-filter=ACM", env=env, cwd=дерево)
    пути = [p for p in вывод.split("\0") if p]
    _, удал = git(корень, "diff", "--cached", "--name-only", "--no-renames",
                  "--diff-filter=D", env=env, cwd=дерево)
    n_удал = len([x for x in удал.splitlines() if x])
    скан = _сканер()
    секреты, крупные, объём = [], [], 0
    for p in пути:
        ф = дерево / p
        try:
            размер = ф.stat().st_size
        except OSError:
            continue
        объём += размер
        if размер > ЛИМИТ_ФАЙЛА:
            крупные.append(f"{p} ({размер // 1048576} МБ)")
        секреты += скан(ф)
    say(f"      изменено/новых {len(пути)} · удалено {n_удал} · {объём / 1048576:.1f} МБ")
    if секреты:
        say("      🔴 СЕКРЕТЫ — отправка остановлена:")
        for х in секреты[:10]:
            say(f"         {х}")
        return None
    if крупные:
        say("      🔴 файлы крупнее 100 МБ — GitHub отклонит весь push:")
        for х in крупные:
            say(f"         {х}")
        return None
    if объём > ЛИМИТ_PUSH:
        say(f"      🔴 {объём / 1048576:.0f} МБ — больше лимита одного push")
        return None
    return len(пути) + n_удал, объём


def атрибуция(корень: Path, сообщение: str) -> bool:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as ф:
        ф.write(сообщение)
    r = subprocess.run([sys.executable, str(БАЗА / "scripts/attribution_check.py"),
                        "--message", ф.name, "--ident"], cwd=корень,
                       capture_output=True, text=True)
    os.unlink(ф.name)
    if r.returncode != 0:
        say("      🔴 атрибуция:", r.stdout.strip()[-300:])
    return r.returncode == 0


def описание(репа: str, версия: str, журнал: Path) -> tuple[str, Path] | None:
    куда = Path(tempfile.gettempdir()) / f"notes-{репа}-{версия}.md"
    r = subprocess.run([sys.executable, str(БАЗА / "scripts/release_notes.py"),
                        версия, "--repo", репа, "--out", str(куда),
                        "--changelog", str(журнал)], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return r.stdout.strip(), куда


def отправить(корень: Path, *ссылки: str) -> bool:
    """Все ссылки ОДНОЙ командой — это дешевле по каналу, а не красивее.

    🔴 Раздельный push гонит общие объекты двух версий дважды. У
    `legal-knowledge-base` это 975 МБ за одну версию и 1388 МБ за вторую
    при том, что большая часть файлов у них общая. Одна команда — один
    пакет с дедупликацией, и один обрыв вместо двух на рвущемся канале.
    """
    for i, пауза in enumerate(ПАУЗЫ, 1):
        time.sleep(пауза)
        # 🔴 --no-thin: без него push из частичной репы требует старых
        # версий файлов и падает без сети (опыт Э7, 13.09.2026).
        код, вывод = git(корень, "push", "-q", "--no-thin", "origin", *ссылки)
        if код == 0:
            return True
        say(f"      push: попытка {i} — {вывод.splitlines()[-1][:100] if вывод else '?'}")
    return False


def релиз(репа: str, версия: str, заголовок: str, тело: Path, архив: Path | None) -> bool:
    cmd = ["gh", "release", "create", f"v{версия}", "--repo", f"{OWNER}/{репа}",
           "--title", заголовок, "--notes-file", str(тело)]
    if архив:
        cmd.append(str(архив))
    for пауза in ПАУЗЫ:
        time.sleep(пауза)
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            return True
        if "already exists" in r.stderr:
            return True
        say(f"      релиз: {r.stderr.strip()[-120:]}")
    return False


def зафиксировать(корень: Path, дерево_коммита: str, сообщение: str) -> str:
    """Коммит поверх HEAD без касания рабочего дерева."""
    _, родитель = git(корень, "rev-parse", "HEAD")
    код, коммит = git(корень, "commit-tree", дерево_коммита, "-p", родитель,
                      "-F", "-", вход=сообщение)
    if код != 0:
        raise SystemExit(f"🔴 commit-tree: {коммит}")
    git(корень, "update-ref", "HEAD", коммит)
    return коммит


def подготовить_архив(архив: Path, сухо: bool) -> dict | None:
    """Коммит и тег из дерева архива — ЛОКАЛЬНО, без единого запроса наружу."""
    м = re.match(r"(.+)-v(\d+\.\d+\.\d+)\.zip$", архив.name)
    if not м:
        say(f"🔴 имя архива не по стандарту: {архив.name}")
        return None
    репа, версия = м.group(1), м.group(2)
    _, корень_реп, _ = resolve_roots(__file__)
    корень = корень_реп / репа
    say(f"── {репа} v{версия} из архива")
    if not (корень / ".git").exists():
        say("   🔴 в репе нет .git")
        return None
    if тег_есть(корень, версия):
        say("   тег уже на GitHub — пропускаю (как deploy.sh)")
        return {"репа": репа, "корень": корень, "пропуск": True}

    врем = Path(tempfile.mkdtemp(prefix=f"deploy-{репа}-"))
    try:
        распаковать(архив, врем)
        верх = [p for p in врем.iterdir() if p.name != "__MACOSX"]
        дерево = верх[0] if len(верх) == 1 and верх[0].is_dir() else врем
        индекс = врем / "_index"
        env = dict(os.environ, GIT_DIR=str(корень / ".git"),
                   GIT_WORK_TREE=str(дерево), GIT_INDEX_FILE=str(индекс))
        git(корень, "read-tree", "HEAD", env=env, cwd=дерево)
        код, вывод = git(корень, "add", "-A", env=env, cwd=дерево)
        сохранить_исключённое(корень, env, дерево)
        if код != 0:
            say(f"   🔴 add: {вывод[-200:]}")
            return None
        if проверить_и_показать(корень, дерево, env) is None:
            return None
        оп = описание(репа, версия, дерево / "CHANGELOG.md")
        if оп is None:
            say(f"   🔴 в CHANGELOG архива нет секции [{версия}] — релиз без описания не создаю")
            return None
        заголовок, тело = оп
        say(f"      {заголовок[:100]}")
        if not атрибуция(корень, заголовок):
            return None
        if сухо:
            say("   🟡 --dry: коммит не создаю")
            return {"репа": репа, "корень": корень, "пропуск": True}
        _, t = git(корень, "write-tree", env=env, cwd=дерево)
        коммит = зафиксировать(корень, t, заголовок)
        git(корень, "tag", "-a", f"v{версия}", "-m", f"{репа} v{версия}", коммит)
        git(корень, "read-tree", "HEAD")      # индекс рабочей копии → новый HEAD
        say(f"   🟢 коммит и тег v{версия} готовы локально")
        return {"репа": репа, "корень": корень, "версия": версия,
                "заголовок": заголовок, "тело": тело, "архив": архив}
    finally:
        shutil.rmtree(врем, ignore_errors=True)


def выпустить_подготовленное(корень: Path, репа: str, готовые: list[dict]) -> bool:
    """Один push на все версии репы, затем релизы по порядку."""
    ссылки = ["HEAD:main"] + [f"v{г['версия']}" for г in готовые]
    say(f"── push {репа}: {len(готовые)} версий одной командой")
    if not отправить(корень, *ссылки):
        say("   🔴 push не прошёл — коммиты и теги остались локально, повтор безопасен")
        return False
    ок = True
    for г in готовые:
        if релиз(репа, г["версия"], г["заголовок"], г["тело"], г["архив"]):
            say(f"   🟢 релиз v{г['версия']} с архивом")
        else:
            say(f"   🔴 релиз v{г['версия']} не создан")
            ок = False
    return ок


def синхронизировать(репа: str, сухо: bool) -> bool:
    _, корень_реп, _ = resolve_roots(__file__)
    корень = корень_реп / репа
    say(f"── {репа}")
    if not (корень / ".git").exists():
        say("   🔴 нет .git")
        return False
    замок = корень / ".git" / "index.lock"
    if замок.exists():
        # 15.09.2026: две репы (legal-knowledge-base, self-map) держали замок
        # от синхронизации, убитой 13.09. `add -A` падал, индекс оставался
        # равен HEAD — и скрипт писал «уже 1 в 1» при 902 расходящихся файлах.
        say(f"   🔴 {замок} остался от оборванного git (с {time.strftime('%d.%m %H:%M', time.localtime(замок.stat().st_mtime))});"
            " убедиться, что git в репе не запущен, удалить и `git read-tree HEAD`, если индекс неполон")
        return False
    код, вывод = git(корень, "add", "-A")
    if код != 0:
        say(f"   🔴 git add: {вывод[-300:]}")
        return False
    итог = проверить_и_показать(корень, корень, dict(os.environ))
    if итог is None:
        return False
    if итог[0] == 0:
        say("   🟢 уже 1 в 1")
        return True
    версия = (корень / "VERSION").read_text().strip() if (корень / "VERSION").exists() else ""
    # 🔴 РЕЛИЗ ТОЛЬКО ПРИ НАЛИЧИИ АРХИВА. У `deploy.sh` архив был условием:
    # он и брал версии из архивов. Тег без ассета — выпуск, расходящийся
    # со стандартом (`101-release-readiness`), а догонять его потом нечем:
    # собрать архив прошлой версии из рабочей копии уже нельзя.
    архив = Path.home() / "Developer" / f"{репа}-v{версия}.zip" if версия else None
    новая = bool(версия) and архив.exists() and not тег_есть(корень, версия)
    оп = описание(репа, версия, корень / "CHANGELOG.md") if новая else None
    if оп:
        заголовок, тело = оп
    else:
        # У зеркал файла VERSION может не быть вовсе — тогда без «v»,
        # иначе в заголовке выходит «finpilot v — синхронизация» (13.09.2026).
        хвост = f" v{версия}" if версия else ""
        заголовок, тело = f"{репа}{хвост} — синхронизация с рабочей копией", None
    say(f"      {заголовок[:100]}")
    if not атрибуция(корень, заголовок):
        return False
    if сухо:
        say(f"   🟡 --dry{' · будет релиз v' + версия if оп else ''}")
        return True
    код, вывод = git(корень, "commit", "-q", "--no-verify", "-m", заголовок)
    if код != 0:
        say(f"   🔴 коммит: {вывод[-200:]}")
        return False
    ссылки = ["HEAD:main"]
    if оп:
        git(корень, "tag", "-a", f"v{версия}", "-m", f"{репа} v{версия}")
        ссылки.append(f"v{версия}")
    if not отправить(корень, *ссылки):
        say("   🔴 push не прошёл — коммит остался локально, повтор безопасен")
        return False
    if оп:
        релиз(репа, версия, заголовок, тело, архив)
    say("   🟢 GitHub = рабочая копия")
    return True


def selftest() -> bool:
    """Канарейка: сканер секретов подгружается из хука и ловит ключ."""
    import tempfile as tf
    скан = _сканер()
    with tf.TemporaryDirectory() as td:
        f = Path(td) / "a.py"
        # 🔴 БЕЗ слова example: хук намеренно считает плейсхолдеры безопасными
        # (`SAFE_VALUE`), и первая редакция канарейки упала именно на этом —
        # проверяла не сканер, а список исключений.
        # 🔴 ОБРАЗЕЦ СОБИРАЕТСЯ ИЗ ЧАСТЕЙ, А НЕ ЛЕЖИТ СТРОКОЙ.
        # 13.09.2026 синхронизация 57 реп остановилась на этом самом файле:
        # сканер нашёл в нём «ключ» — тот, что канарейка проверяет. Файл
        # роздан в `_base/` каждой репы, и каждая стала «репой с секретом».
        # > **Проверка, содержащая образец нарушения, сама становится
        # > нарушением, как только её раздают.**
        ключ = "9f3ab72c" + "11d84e0fa5c7"
        f.write_text(f"api_key = '{ключ}'\ntoken = os.getenv('X')\n")
        g = Path(td) / "b.md"
        g.write_text("просто текст про password и token\n")
        сканер_ок = len(скан(f)) >= 1 and скан(g) == []

        # 🔴 КАНАРЕЙКА ЛОВУШКИ 25.09.2026: деплой из архива не имеет права
        # удалять то, чего в архиве нет ПО ПРАВИЛУ упаковщика. Заводится
        # репа, где такой файл в git есть, а в «архиве» его нет.
        репа = Path(td) / "repo"
        (репа / "reports" / "imports" / "telegram-photos").mkdir(parents=True)
        (репа / "README.md").write_text("старое\n", encoding="utf-8")
        (репа / "reports/imports/telegram-photos/p.jpg").write_bytes(b"jpeg")
        for cmd in (["init", "-q", "-b", "main"], ["add", "-A"]):
            subprocess.run(["git", *cmd], cwd=репа, capture_output=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "-m", "первый"], cwd=репа, capture_output=True)
        дерево = Path(td) / "tree"          # «дерево архива»: фото нет по правилу
        дерево.mkdir()
        (дерево / "README.md").write_text("новое\n", encoding="utf-8")
        индекс = Path(td) / "idx"
        env = dict(os.environ, GIT_DIR=str(репа / ".git"), GIT_WORK_TREE=str(дерево),
                   GIT_INDEX_FILE=str(индекс))
        git(репа, "read-tree", "HEAD", env=env, cwd=дерево)
        git(репа, "add", "-A", env=env, cwd=дерево)
        _, до = git(репа, "diff", "--cached", "--name-status", env=env, cwd=дерево)
        сохранить_исключённое(репа, env, дерево)
        _, после = git(репа, "diff", "--cached", "--name-status", env=env, cwd=дерево)
        ловушка_ок = ("D\treports/imports/telegram-photos/p.jpg" in до
                      and "telegram-photos" not in после
                      and "M\tREADME.md" in после)

        # Права переживают упаковку и распаковку: 755 остаётся 755, 644 — 644.
        исх = Path(td) / "src"
        исх.mkdir()
        (исх / "run.py").write_text("#!/usr/bin/env python3\n")
        (исх / "run.py").chmod(0o755)
        (исх / "note.md").write_text("x\n")
        (исх / "note.md").chmod(0o644)
        арх = Path(td) / "a.zip"
        with zipfile.ZipFile(арх, "w") as z:
            for имя in ("run.py", "note.md"):
                z.write(исх / имя, имя)
        вых = Path(td) / "out"
        вых.mkdir()
        n = распаковать(арх, вых)
        права_ок = (n == 1 and (вых / "run.py").stat().st_mode & 0o777 == 0o755
                    and (вых / "note.md").stat().st_mode & 0o777 == 0o644)
        return сканер_ок and права_ок and ловушка_ок


def main() -> int:
    р = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    р.add_argument("--archive", nargs="+", type=Path)
    р.add_argument("--sync", nargs="+")
    р.add_argument("--dry", action="store_true")
    р.add_argument("--selftest", action="store_true")
    a = р.parse_args()
    if a.selftest:
        ок = selftest()
        say("🟢 канарейка: секреты ловятся, права переживают упаковку, исключённое "
            "упаковщиком не удаляется деплоем из архива" if ок else "🔴 КАНАРЕЙКА УПАЛА")
        return 0 if ок else 1
    плохо = []
    по_репам: dict[str, list[dict]] = {}
    корни: dict[str, Path] = {}
    for z in sorted(a.archive or [], key=lambda p: [int(x) for x in re.findall(r"\d+", p.name)[-3:]]):
        г = подготовить_архив(z.expanduser(), a.dry)
        if г is None:
            плохо.append(z.name)
            continue
        корни[г["репа"]] = г["корень"]
        if not г.get("пропуск"):
            по_репам.setdefault(г["репа"], []).append(г)
    for репа, готовые in по_репам.items():
        if not выпустить_подготовленное(корни[репа], репа, готовые):
            плохо.append(репа)
    for репа in a.sync or []:
        if not синхронизировать(репа, a.dry):
            плохо.append(репа)
    say(f"\n{'🟢 всё прошло' if not плохо else '🔴 не прошли: ' + ', '.join(плохо)}")
    return 0 if not плохо else 1


if __name__ == "__main__":
    sys.exit(main())
