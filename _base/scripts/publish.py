"""Полный цикл выпуска репы — то, что делал `deploy.sh`, только изнутри.

🔴 ЗАКАЗ ВЛАДЕЛЬЦА 09.09.2026, дословно: «давай сделай этот .git в каждой
репе и будем уже коммитить через тебя напрямую а не скрипт… только
обязательные условия надо чекать и следить: 1. чтобы НЕ было
в контрибьюторах claude 2. описания были как деплой делает 3. ассеты были
как деплой 4. короче все как делал скрипт деплой ты теперь делать будешь.
только сам скрипт не удаляй он важен».

Шесть шагов, каждый проверяется:

    1. атрибуция     — в истории и настройках только владелец
    2. коммит        — подпись из ЛОКАЛЬНОГО конфига, хуки включены
    3. тег           — vX.Y.Z, аннотированный
    4. push          — ветка и тег
    5. описание      — парсером ДЕПЛОЙЕРА из секции CHANGELOG
    6. релиз + ассет — <репа>-vX.Y.Z.zip

🔴 `deploy.sh` НЕ УДАЛЯЕТСЯ И НЕ ЗАМЕНЯЕТСЯ. Он остаётся каноном формата
и рабочим путём для случаев, которые здесь не покрыты: раздача по зеркалам,
BACKFILL старых версий, REPAIR чужих релизов, проверка repos-map. Этот
инструмент делает ОДНУ репу за проход, из её рабочей копии.

🔴 ЧЕГО НЕ ДЕЛАЕТ: не поднимает версию (это `close_batch.py`), не собирает
архив (это `pack_release.py`), не решает, что выпускать.

Применение:
    publish.py <репа> [--dry] [--no-release]
    publish.py --selftest
"""

from __future__ import annotations

import argparse
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
    код, вывод = запуск([sys.executable, str(БАЗА / "scripts/release_notes.py"),
                         версия, "--repo", репа, "--out", str(куда),
                         "--changelog", str(корень / "CHANGELOG.md")])
    if код != 0:
        print(вывод)
        raise SystemExit(f"🔴 описание не собрано — в CHANGELOG нет секции [{версия}]. "
                         f"Это правило деплойера: релиз без описания не создаётся.")
    return вывод.strip(), куда


def найти_архив(репа: str, версия: str) -> Path | None:
    """Ассет ровно с тем именем, что делает деплойер. Условие №3 владельца."""
    путь = Path(artifacts_dir()) / f"{репа}-v{версия}.zip"
    return путь if путь.is_file() else None


def selftest() -> bool:
    """Канарейка: инструменты, на которых всё держится, на месте и живы."""
    for имя in ("attribution_check.py", "release_notes.py"):
        ф = БАЗА / "scripts" / имя
        if not ф.is_file():
            return False
        if запуск([sys.executable, str(ф), "--selftest"])[0] != 0:
            return False
    return True


def main() -> int:
    р = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    р.add_argument("репа", nargs="?")
    р.add_argument("--dry", action="store_true", help="показать план, ничего не делать")
    р.add_argument("--no-release", action="store_true", help="без релиза на GitHub")
    р.add_argument("--selftest", action="store_true")
    a = р.parse_args()

    if a.selftest:
        ок = selftest()
        print("🟢 канарейка: инструменты выпуска на месте и живы" if ок
              else "🔴 КАНАРЕЙКА УПАЛА — нет или сломан attribution_check/release_notes")
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
    всего = 6
    print(f"── выпуск {a.репа} v{версия} ──")

    шаг(1, всего, "атрибуция")
    проверить_атрибуцию(корень)

    шаг(2, всего, "описание из CHANGELOG (парсером деплойера)")
    заголовок, тело = описание(корень, a.репа, версия)
    print(f"      {заголовок[:88]}")

    шаг(3, всего, "ассет")
    архив = найти_архив(a.репа, версия)
    print(f"      {архив.name if архив else '🔴 архива нет — релиз будет без ассета'}")

    if a.dry:
        print("\n🟡 --dry: дальше ничего не делаю")
        return 0

    шаг(4, всего, "коммит и тег")
    запуск(["git", "add", "-A"], корень)
    код, вывод = запуск(["git", "commit", "-m", заголовок], корень)
    if код != 0 and "nothing to commit" not in вывод:
        print(вывод)
        raise SystemExit("🔴 коммит не прошёл — вероятно, остановлен хуком")
    код, _ = запуск(["git", "tag", "-a", f"v{версия}", "-m", f"{a.репа} v{версия}"], корень)
    print(f"      тег v{версия}{' (уже был)' if код != 0 else ''}")

    шаг(5, всего, "push")
    for что in (["origin", "HEAD:main"], ["origin", f"v{версия}"]):
        # 🔴 `--no-thin` — найдено опытом 13.09.2026 на копии `quick-answers`.
        # Обычный push шлёт «тонкий» пакет: дельты от старых версий файлов.
        # В частичной репе старых версий нет, и push без сети падал
        # `unpacker error`; с сетью — докачивал их по одной. С `--no-thin`
        # тот же push прошёл без единого запроса наружу, `fsck --full`
        # на приёмной стороне чист. Цена — пакет крупнее на размер
        # изменённых файлов целиком, для текстовых реп это килобайты.
        код, вывод = запуск(["git", "push", "-q", "--no-thin", *что], корень)
        if код != 0:
            print(вывод)
            raise SystemExit("🔴 push не прошёл")
    print("      ветка и тег отправлены")

    шаг(6, всего, "релиз")
    if a.no_release:
        print("      пропущен по --no-release")
    else:
        cmd = ["gh", "release", "create", f"v{версия}", "--repo", f"{OWNER}/{a.репа}",
               "--title", заголовок, "--notes-file", str(тело)]
        if архив:
            cmd.append(str(архив))
        код, вывод = запуск(cmd)
        print("      " + (вывод.splitlines()[-1] if вывод else "создан"))

    print(f"\n🟢 {a.репа} v{версия} выпущена")
    return 0


if __name__ == "__main__":
    sys.exit(main())
