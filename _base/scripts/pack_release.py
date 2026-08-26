#!/usr/bin/env python3
"""Упаковка релиза base-repo по канону 43-archive-naming-and-packaging.md.

Правила, закодированные здесь:
  · имя `<repo>-vX.Y.Z.zip`, версия через ТОЧКИ (не подчёркивания);
  · ОДНА папка-обёртка `<repo>-vX.Y.Z/` в корне архива;
  · внутри обязательны README.md и VERSION, VERSION == версии из имени;
  · мусор macOS (.DS_Store, __MACOSX, ._*) не попадает — иначе обёртка не развернётся;
  · точечные файлы (.repo-id, .gitignore, .githooks) НЕ исключаются (PIT: `zip -x '.*'`);
  · UTF-8-флаг (0x800) выставляется ЯВНО на каждой записи — системный `zip` ставит его
    по локали окружения, и при POSIX кириллические имена бьются (PIT-025).
"""
import datetime
import hashlib
import atexit
import os
import sys
import time
import zipfile
from pathlib import Path

# Путь репы — аргументом, база по умолчанию. Захардкоженный путь означал, что
# для любой другой репы пришлось бы писать ВТОРОЙ упаковщик — ровно то, чем
# кончились восемь скриптов деплоя до консолидации (templates/README.md).
# Имя берётся из каталога, а не из константы: имя каталога и имя репы обязаны
# совпадать, и если не совпали — это дефект, который лучше увидеть здесь.
REPO = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 \
    else Path(os.environ.get("BASE_REPO", Path(__file__).resolve().parent.parent)).expanduser()
OUT_DIR = Path.home() / "Downloads"
NAME = REPO.name

JUNK_NAMES = {".DS_Store", "Thumbs.db"}
JUNK_DIRS = {".git", "__MACOSX", "__pycache__", ".ipynb_checkpoints", ".pytest_cache"}


def collect():
    files = []
    for dp, dn, fns in os.walk(REPO):
        dn[:] = [d for d in dn if d not in JUNK_DIRS]
        for fn in sorted(fns):
            if fn in JUNK_NAMES or fn.startswith("._"):
                continue
            p = Path(dp) / fn
            if p.is_symlink() or not p.is_file():
                continue
            files.append(p)
    return sorted(files)


def main():
    version = (REPO / "VERSION").read_text().strip()
    # 🔴 ПРОВЕРКА РАЗМЕРОВ ДО СБОРКИ. Найдено владельцем 23.08.2026: архивы были
    # собраны ДО выноса тяжёлого медиа и несли внутри файлы по 208 и 365 МБ.
    # Такой архив разворачивается в репу, push отклоняется `pre-receive` (GH001),
    # и деплой пропускает репу — то есть архив бесполезен по построению.
    # Дешевле не собрать его, чем обнаружить это на деплое.
    # 🔴 ЗАГЛУШКИ iCloud ПЕРЕД УПАКОВКОЙ (`PIT-135`). Упаковка ЧИТАЕТ каждый файл,
    # поэтому каждая заглушка — сетевой запрос с ожиданием. Замер 23.08.2026: `science`
    # имел 144 заглушки из 232 (62 %), и упаковщик встал на 0.0 % CPU — он не считал,
    # а ждал сеть. Снаружи это неотличимо от зависания.
    _files = collect()
    # 🔴 Пустой файл (0 байт, напр. `__init__.py`) даёт st_blocks == 0 НЕЗАВИСИМО
    # от того, заглушка это или нет — у него просто нечего материализовать. Без
    # фильтра по size > 0 такие файлы ложно считались заглушками (найдено 25.08.2026
    # на `vk-graph`: 4 пустых `__init__.py` = 17 % «заглушек», упаковка отказывала).
    _stubs = sum(1 for f in _files if f.stat().st_size > 0 and f.stat().st_blocks == 0)
    if _stubs:
        _share = _stubs / len(_files) * 100 if _files else 0
        print(f"!! {NAME}: {_stubs} из {len(_files)} файлов ({_share:.0f} %) — заглушки iCloud")
        print("   Упаковка читает каждый файл и потянет их из сети. Сначала материализовать:")
        print(f"     brctl download {REPO}")
        print("   Готовность: st_blocks > 0 у всех файлов.")
        if _share > 10:
            print("   ⏭  НЕ ПАКУЮ — доля заглушек выше 10 %, архив собирался бы часами")
            sys.exit(1)

    _over = [(f, f.stat().st_size) for f in _files if f.stat().st_size > 100 * 2**20]
    if _over:
        print(f"!! в {NAME} есть файлы тяжелее 100 МБ — GitHub отклонит push (GH001):")
        for f, s in sorted(_over, key=lambda x: -x[1])[:5]:
            print(f"     {s / 2**20:7.1f} МБ  {f.relative_to(REPO)}")
        print("   Свернуть в служебки и собрать снова:")
        print(f"     python3 07-media-to-text-lab/tools/heavy_media_to_note.py --repo {NAME} --apply")
        sys.exit(1)

    wrapper = f"{NAME}-v{version}"
    out = OUT_DIR / f"{wrapper}.zip"

    if out.exists():
        print(f"!! уже существует: {out} — не перезаписываю (SYN-005)")
        sys.exit(1)

    # 🔴 БЛОКИРОВКА ОТ ПАРАЛЛЕЛЬНОЙ СБОРКИ ОДНОЙ РЕПЫ (`PIT-131`).
    # Найдено 23.08.2026: три запуска паковали одни и те же репы одновременно и писали
    # в ОДИН файл. На выходе — архив с сигнатурой zip, правдоподобным размером и без
    # центральной директории: неотличим от готового по имени, размеру и `file`.
    # Проверка `out.exists()` выше от этого не спасает — файла ещё нет, когда оба
    # процесса стартуют, и оба видят «свободно».
    lock = out.with_suffix(".zip.lock")
    if lock.exists():
        age = time.time() - lock.stat().st_mtime
        # 🔴 Сначала спросить, ЖИВ ли процесс из замка, и только потом смотреть на возраст.
        # Возраст — догадка о смерти; PID даёт ответ. Найдено 23.08.2026: упаковка была
        # оборвана таймаутом, замок остался, и следующий запуск отказывался 20 минут,
        # ожидая часа. Ожидание на мёртвом процессе — чистая потеря времени.
        try:
            os.kill(int(lock.read_text(encoding="utf-8").strip()), 0)
            alive = True
        except (ValueError, ProcessLookupError, OSError):
            alive = False
        if not alive:
            print(f"   (замок от мёртвого процесса — снимаю и продолжаю)")
            lock.unlink(missing_ok=True)
        elif age < 3600:
            print(f"!! {NAME} уже пакуется другим процессом ({age / 60:.0f} мин назад).")
            print("   Параллельная сборка одной репы даёт БИТЫЙ архив — жду завершения.")
            sys.exit(1)
        print(f"   (замок старше часа — вероятно, процесс убит; продолжаю)")
        lock.unlink()
    lock.write_text(str(os.getpid()), encoding="utf-8")
    # 🔴 Снятие замка через atexit, а не строкой в конце удачного пути.
    # Найдено владельцем 23.08.2026: в загрузках накопилось **14** файлов `*.zip.lock`.
    # Замок ставился здесь, снимался в самом низу main() — и любой `sys.exit` между
    # ними (проверка размеров, ошибка сборки) оставлял его навсегда. Следующий запуск
    # видел чужой замок и отказывался паковать репу, пока тому не исполнится час.
    #
    # `atexit` срабатывает на ЛЮБОМ выходе, включая исключение и sys.exit —
    # ровно то, что требуется от замка: он живёт не дольше процесса.
    atexit.register(lambda: lock.unlink(missing_ok=True))

    files = collect()
    assert len(files) > 5, "мало файлов, деплойер сочтёт что это не репа"

    # Пять служебок в корне, а не две. Деплойер без них не падает — он тихо ведёт себя
    # иначе: без .repo-id угадывает репу по имени файла, без CHANGELOG.md может вовсе
    # не создать релиз. Разбор — 00-infrastructure/43-archive-naming-and-packaging.md §3а.
    missing = [f for f in (".repo-id", ".repo-class", "VERSION",
                           "CHANGELOG.md", "README.md")
               if not (REPO / f).is_file()]
    if missing:
        print(f"!! нет служебных файлов в корне: {', '.join(missing)}")
        print("   деплойер не упадёт, но поведёт себя иначе — см. канон 43 §3а")
        sys.exit(1)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for p in files:
            arc = f"{wrapper}/{p.relative_to(REPO).as_posix()}"
            zi = zipfile.ZipInfo.from_file(p, arc)
            zi.flag_bits |= 0x800          # UTF-8, явно (PIT-025)
            zi.compress_type = zipfile.ZIP_DEFLATED
            with open(p, "rb") as fh:
                zf.writestr(zi, fh.read())

    size = out.stat().st_size
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"собран: {out}")
    print(f"файлов: {len(files)} · размер: {size/1e6:.2f} МБ")
    print(f"sha256: {sha}")

    # --- ЖУРНАЛ ВЫПУСКОВ ---------------------------------------------------
    # ЗАЧЕМ. Ритуал закрытия батча требует удалять предыдущий архив, чтобы в `~/Downloads`
    # не копилось два десятка почти одинаковых zip. Побочный эффект нашёл владелец
    # 22.08.2026: раз старый стёрт, от него НЕ ОСТАЁТСЯ СЛЕДА — проверить задним числом,
    # собирался ли архив на версии 2.05.0, нечем. Утверждение «архив собран» было
    # непроверяемым тридцать версий подряд, и опровергнуть его было так же нечем.
    #
    # Строка журнала стоит сотню байт и ПЕРЕЖИВАЕТ удаление файла. Удалять архивы можно
    # по-прежнему: доказательство выпуска переезжает из файла в журнал.
    ledger = REPO / "reports" / "releases" / "LEDGER.tsv"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    if not ledger.exists():
        ledger.write_text("# дата\tверсия\tфайлов\tбайт\tsha256\n", encoding="utf-8")
    prev = ledger.read_text(encoding="utf-8")
    if f"\t{version}\t" not in prev:          # пересборка той же версии строку не двоит
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.date.today():%Y-%m-%d}\t{version}\t{len(files)}\t"
                     f"{size}\t{sha}\n")
    n_rel = sum(1 for ln in ledger.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#"))
    print(f"журнал: {ledger.relative_to(REPO)} — выпусков записано: {n_rel}")

    return out, wrapper, version


if __name__ == "__main__":
    main()
