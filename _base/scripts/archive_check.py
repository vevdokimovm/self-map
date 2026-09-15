#!/usr/bin/env python3
"""archive_check.py — целы ли архивы выпусков и есть ли они вообще.

🔴 ЗАЧЕМ ЭТО ВАЖНЕЕ, ЧЕМ ЗВУЧИТ. У базы **нет `.git`**. Значит zip-архив —
не копия версии, а её **единственный экземпляр** (`06-autonomous-mode-kit`,
правило «архивы не удаляются», отменено владельцем 22.08.2026 именно поэтому).
Битый или отсутствующий архив — это не неудобство, а безвозвратно потерянная
версия.

ЗАМЕРЕНО 29.08.2026 первым же прогоном, и находка неприятная:

    записей в реестрах всех реп : 606
    архивов физически на диске  :   7   (все целы, sha256 сходится)

**Реестр — опись, а не хранилище.** `LEDGER.tsv` честно помнит дату, размер
и sha256 каждого выпуска, но по хешу файл не восстанавливается. **599 версий
существуют только строкой.** Это не дефект реестра — он и не обещал хранить;
это дефект ожидания, будто он хранит. Бо́льшая часть удалена осознанно:
чистка `~/Downloads` — решение владельца, а не сбой. Смысл числа в том, чтобы
это решение принималось **зная цену**, а не по привычке.

🔴 ПОЭТОМУ ИНСТРУМЕНТ ОТВЕЧАЕТ НА ДВА РАЗНЫХ ВОПРОСА, И ВТОРОЙ ВАЖНЕЕ:

  1. **цел ли архив, который есть** — CRC каждого файла внутри (`unzip -t`)
     плюс сверка sha256 со строкой реестра. Ловит тихую порчу диска и
     недописанный при обрыве архив;
  2. **сколько выпусков не подкреплены файлом вовсе** — то есть какая часть
     истории существует только на бумаге.

Первый вопрос — про порчу, второй — про потерю. Инструмент, отвечающий только
на первый, докладывал бы «все архивы целы» при семи файлах из двухсот
пятидесяти четырёх, и это был бы честный по букве и лживый по смыслу ответ.

🔴 ЧЕГО НЕ ДЕЛАЕТ (`71` §7г-бис):

  · **ничего не удаляет и не пересобирает.** Чистка `~/Downloads` — решение
    владельца, а не шаг проверки;
  · **не судит, ЧТО лежит внутри архива** — только что он не повреждён
    и совпадает с записанным хешем. Архив может быть цел и содержать не то;
  · **не может восстановить утраченное** — по хешу файл не воссоздаётся,
    и никакая проверка этого не изменит.

ЗАПУСК
    archive_check.py              проверить всё
    archive_check.py --dir ПУТЬ   другой каталог с архивами
    archive_check.py --selftest   канарейка
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import zipfile
from pathlib import Path

# Корень определяется общим модулем: скрипт может быть запущен и из базы,
# и из копии кита в репе-наследнике (`_base/scripts/`). См. `_roots.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402
BASE_REPO, REPOS, FROM_KIT = resolve_roots(__file__)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import artifacts_dir  # noqa: E402
# Имя переменной сохранено: его читают ниже по коду, и переименование ради
# красоты — правка без предмета. Значение теперь общее с остальными.
DOWNLOADS = artifacts_dir()
NAME_RE = re.compile(r"^(?P<repo>.+)-v(?P<version>\d+\.\d+\.\d+)\.zip$")


def ledger_rows() -> list[tuple[str, str, str, str]]:
    """(репа, дата, версия, sha256) по реестрам ВСЕХ реп.

    🔴 Читается не один реестр, а все. Первая редакция брала только
    `base-repo/reports/releases/LEDGER.tsv` — и объявила
    `mission-control-v2.2.0.zip` «архивом не от этой системы», хотя он был
    собран ритуалом получасом раньше. У каждой репы свой реестр; архивы
    же сваливаются в один каталог. Проверка, знающая один источник из
    шестидесяти, уверенно врёт про остальные пятьдесят девять.
    """
    rows = []
    for repo in sorted(REPOS.iterdir()):
        ledger = repo / "reports" / "releases" / "LEDGER.tsv"
        if not ledger.is_file():
            continue
        for line in ledger.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 5:
                rows.append((repo.name, parts[0], parts[1], parts[4]))
    return rows


def sha256_of(path: Path) -> str:
    """Хеш файла кусками — архив может быть в сотни мегабайт."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def test_archive(path: Path) -> str | None:
    """None — архив цел; иначе строка с причиной.

    Используется `zipfile.testzip()`, а не внешний `unzip -t`: тот же CRC
    каждого элемента, но без зависимости от установленной утилиты — отказ
    из-за отсутствия `unzip` прочитался бы как порча архива.
    """
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            return f"повреждён элемент: {bad}" if bad else None
    except zipfile.BadZipFile as exc:
        return f"не читается как zip: {exc}"
    except OSError as exc:
        return f"ошибка чтения: {exc}"


def selftest() -> bool:
    """Проверяется РАЗЛИЧЕНИЕ: целый архив и битый не должны сливаться."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        good = Path(tmp) / "good.zip"
        with zipfile.ZipFile(good, "w") as zf:
            zf.writestr("a.txt", "содержимое" * 100)
        if test_archive(good) is not None:
            return False                      # целый обязан пройти

        # Портим байт в середине сжатых данных — CRC перестанет сходиться.
        raw = bytearray(good.read_bytes())
        raw[len(raw) // 2] ^= 0xFF
        bad = Path(tmp) / "bad.zip"
        bad.write_bytes(bytes(raw))
        if test_archive(bad) is None:
            return False                      # битый обязан не пройти

        # И совсем не zip — тоже отказ, но с другой причиной.
        junk = Path(tmp) / "junk.zip"
        junk.write_text("это просто текст", encoding="utf-8")
        return test_archive(junk) is not None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default=str(DOWNLOADS))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        ok = selftest()
        print("🟢 канарейка: целый архив проходит, битый — нет"
              if ok else "🔴 канарейка: РАЗЛИЧЕНИЕ СЛОМАНО")
        return 0 if ok else 1

    if not selftest():
        print("🔴 канарейка не прошла — результатам ниже верить нельзя")
        return 1

    folder = Path(a.dir)
    archives = {p.name: p for p in sorted(folder.glob("*.zip"))}
    rows = ledger_rows()

    print(f"═══ Архивы выпусков ═══")
    print(f"  записей в реестре : {len(rows)}")
    print(f"  файлов на диске   : {len(archives)}  ({folder})\n")

    broken, mismatch, ok_count = [], [], 0
    by_hash = {sha: (repo, ver) for repo, _, ver, sha in rows}
    for name, path in archives.items():
        problem = test_archive(path)
        if problem:
            broken.append(f"{name}: {problem}")
            continue
        digest = sha256_of(path)
        if digest not in by_hash:
            mismatch.append(f"{name}: хеша нет в реестре — архив не от этой "
                            f"системы, либо пересобран после записи")
        else:
            ok_count += 1

    if broken:
        print(f"  🔴 повреждённых: {len(broken)}")
        for line in broken:
            print(f"        · {line}")
    if mismatch:
        print(f"  ⚠️  не сходятся с реестром: {len(mismatch)}")
        for line in mismatch:
            print(f"        · {line}")
    if not broken and not mismatch:
        print(f"  🟢 все {ok_count} архивов целы и сходятся с реестром по sha256")

    orphan = len(rows) - ok_count
    print(f"\n🔴 ГЛАВНОЕ ЧИСЛО: **{orphan}** записей реестра не подкреплены "
          f"файлом.")
    print("   Это не порча, а потеря: у базы нет git, поэтому zip — единственный")
    print("   экземпляр версии, и по хешу файл не восстанавливается.")
    print("   `LEDGER.tsv` — опись, а не хранилище: он и не обещал хранить.")
    print("\n🔴 Чего проверка не видит: ЧТО внутри архива. Он может быть цел")
    print("   и содержать не то — сверяется целостность, не содержание.")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
