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
import re
import sys
import time
import zipfile
from pathlib import Path

# Путь репы — аргументом, база по умолчанию. Захардкоженный путь означал, что
# для любой другой репы пришлось бы писать ВТОРОЙ упаковщик — ровно то, чем
# кончились восемь скриптов деплоя до консолидации (templates/README.md).
# Имя берётся из каталога, а не из константы: имя каталога и имя репы обязаны
# совпадать, и если не совпали — это дефект, который лучше увидеть здесь.
# 🔴 `--force-stubs` (PIT-145): порог 10% предполагает, что заглушка = данных
# нет НИГДЕ рядом и тянуть их часы. Найдено 26.08.2026: при почти полном диске
# (свободно ~9 ГБ) macOS «Optimize Mac Storage» вытесняет содержимое СРАЗУ ПОСЛЕ
# чтения — файл материализуется за миллисекунды, но st_blocks==0 остаётся, будто
# не тронут. Порог в этом режиме ложно блокирует репы, которые на самом деле
# упаковались бы быстро: упаковка читает-и-сразу-пишет в zip, повторное
# вытеснение УЖЕ ЗАПИСАННОГО байта не страшно.
FORCE_STUBS = "--force-stubs" in sys.argv
if FORCE_STUBS:
    sys.argv.remove("--force-stubs")
REPO = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 \
    else Path(os.environ.get("BASE_REPO", Path(__file__).resolve().parent.parent)).expanduser()
OUT_DIR = Path.home() / "Downloads"
NAME = REPO.name

JUNK_NAMES = {".DS_Store", "Thumbs.db"}
# 🔴 `node_modules`/`dist`/`.venv` (найдено 27.08.2026, первый JS-проект внутри
# репы — `family/web/`): упаковщик не читает `.gitignore`, и без явного списка
# зависимости npm (тысячи файлов, сотни МБ) уехали бы в архив целиком — то же,
# что `.git`/`__pycache__` уже решают для других экосистем. Правило то же:
# сборочный/зависимостный мусор не публикуется, исходники — да.
JUNK_DIRS = {
    ".git", "__MACOSX", "__pycache__", ".ipynb_checkpoints", ".pytest_cache",
    "node_modules", "dist", "build", ".venv", "venv", ".next", ".turbo",
    # 🔴 Импортированные изображения — в репе остаются, в архив НЕ идут.
    # Заведено 29.08.2026 при разборе экспорта Telegram: 17 364 фото на
    # 1595 МБ разложены по репам по мандату владельца («разбирай всё»),
    # и три репы вышли за жёсткий порог 500 МБ.
    #
    # Порог наш, не GitHub (у того 5 ГБ): он про то, чтобы **Claude мог
    # взять архив целиком**. Значит лечится не выбрасыванием материала,
    # а исключением его из архива: скриншоты и мемы — это хранилище,
    # к ним не обращаются при работе с контекстом.
    #
    # Сжатие проверено и отвергнуто: Telegram уже сжал, `sips` с качеством
    # 60 дал **0 % выигрыша** на пробном файле.
    # Тот же довод — для любого импортированного медиа-хранилища.
    # Свойство общее: это не рабочий материал, к нему не обращаются
    # при работе с контекстом, и оно умножает вес архива на порядок.
    "telegram-photos", "telegram-media", "photo-archive",
    # 🔴 `heavy-originals` — по определению то, что вынесено из репы ради веса.
    # Возвращено на место 29.08.2026, но в архив не идёт: там нашёлся файл
    # **208 МБ** (видео), а у GitHub жёсткий лимит **100 MiB на ОДИН файл**.
    # Такой файл сломал бы push, а не просто раздул архив.
    "heavy-originals",
}


# 🔴 СЕКРЕТЫ НЕ УПАКОВЫВАЮТСЯ. Найдено 29.08.2026 при выработке решения по
# хранению секретов (`00-infrastructure/94-secret-storage.md`): упаковщик не
# читает `.gitignore` и клал в архив ЛЮБОЙ файл, включая `.env` с живыми
# значениями. Архивы намеренно не удаляются (решение владельца 22.08.2026),
# то есть один такой архив хранит секрет вечно — и это уже случалось:
# «Отозвать токен VK — `.env` в `vk-graph.zip`, 220 символов»
# (`mission-control/TASKS.md`). Отозвать секрет из десятков zip нельзя;
# отозвать его у провайдера — можно, но это уже потеря.
# `.env.example` (болванки, без значений) — наоборот, ОБЯЗАН попасть в архив:
# без него непонятно, что вообще нужно для запуска.
def is_secret_file(name: str) -> bool:
    if name.endswith(".example") or name.endswith(".template") or name.endswith(".sample"):
        return False
    return name == ".env" or name.startswith(".env.") or name in {
        ".envrc", ".netrc", ".pgpass", ".htpasswd",
        "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
    } or name.endswith((".pem", ".key", ".p12", ".pfx", ".keystore", ".jks"))


def selftest_secret_files() -> bool:
    """Секрет исключается, ОБРАЗЕЦ — нет. Проверяется различение."""
    drop = [".env", ".env.local", ".env.production", ".envrc", ".netrc",
            "id_rsa", "server.key", "cert.pem", "store.p12"]
    keep = [".env.example", ".env.template", ".env.sample", "README.md",
            "config.py", "environment.md", "keys.md"]
    return (all(is_secret_file(n) for n in drop)
            and not any(is_secret_file(n) for n in keep))


_secrets_reported = False


def collect():
    if not selftest_secret_files():
        raise SystemExit("🔴 канарейка секретов сломана: упаковщик перестал "
                         "отличать `.env` от `.env.example` — сборка отменена")
    files = []
    skipped_secrets = []
    for dp, dn, fns in os.walk(REPO):
        dn[:] = [d for d in dn if d not in JUNK_DIRS]
        for fn in sorted(fns):
            if fn in JUNK_NAMES or fn.startswith("._"):
                continue
            # 🔴 Исключение ГРОМКОЕ, а не тихое. Тихо пропущенный `.env`
            # означал бы, что развёрнутый из архива проект не стартует, и
            # причина неочевидна. Строка в выводе называет, чего в архиве нет
            # и чем это собрать обратно.
            if is_secret_file(fn):
                skipped_secrets.append(str((Path(dp) / fn).relative_to(REPO)))
                continue
            p = Path(dp) / fn
            if p.is_symlink() or not p.is_file():
                continue
            files.append(p)
    # `collect()` вызывается дважды — на проверке размеров и на самой сборке.
    # Печатать список дважды значит приучить не читать его вовсе.
    global _secrets_reported
    if skipped_secrets and not _secrets_reported:
        _secrets_reported = True
        print(f"🔒 в архив НЕ вошли секреты ({len(skipped_secrets)}):")
        for rel in skipped_secrets:
            print(f"    · {rel}")
        print("    Собрать обратно: python3 base-repo/scripts/secret.py env <репа>")
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
        if _share > 10 and not FORCE_STUBS:
            print("   ⏭  НЕ ПАКУЮ — доля заглушек выше 10 %, архив собирался бы часами")
            print("      (если диск почти полон и это ложные — PIT-145 — есть --force-stubs)")
            sys.exit(1)
        elif FORCE_STUBS:
            print("   --force-stubs: пакую несмотря на порог (PIT-145)")

    _over = [(f, f.stat().st_size) for f in _files if f.stat().st_size > 100 * 2**20]
    if _over:
        print(f"!! в {NAME} есть файлы тяжелее 100 МБ — GitHub отклонит push (GH001):")
        for f, s in sorted(_over, key=lambda x: -x[1])[:5]:
            print(f"     {s / 2**20:7.1f} МБ  {f.relative_to(REPO)}")
        print("   Свернуть в служебки и собрать снова:")
        print(f"     python3 07-media-to-text-lab/tools/heavy_media_to_note.py --repo {NAME} --apply")
        sys.exit(1)

    # 🔴 Суммарный вес репы — порог из 01-repo-standard.md §4, не проверялся здесь
    # ДО 26.08.2026, из-за чего misc-vault (674 МБ) и academic-portfolio (1018 МБ)
    # ушли в архив без единого предупреждения. Найдено владельцем при разборе
    # деплоя: «у нас же есть правило максимум 500 МБ на репу??».
    # Пороги те же, что для самой базы (06-volume-compression.md):
    # 🟢 ≤50 МБ цель · 🟡 100 МБ мягкий · 🟡 500 МБ ещё мягче с явным обоснованием ·
    # 🔴 >500 МБ жёсткий потолок — Claude физически не берёт архив целиком.
    # Исключение — файл `.size-exception` в корне репы с обоснованием (образец:
    # portrait-of-taste — эталоны фото нужны по существу задачи, не мусор).
    _total = sum(f.stat().st_size for f in _files)
    _total_mb = _total / 2**20
    _exception = REPO / ".size-exception"
    if _total_mb > 500:
        if _exception.is_file():
            print(f"🟡 {NAME}: {_total_mb:.0f} МБ — выше жёсткого потолка 500 МБ, но есть обоснование:")
            print(f"   {_exception.read_text(encoding='utf-8').strip()}")
        else:
            print(f"🔴 {NAME}: {_total_mb:.0f} МБ — выше жёсткого потолка 500 МБ (01-repo-standard.md §4).")
            print("   Свернуть тяжёлое в служебки через лабу медиа→текст:")
            print(f"     python3 07-media-to-text-lab/tools/heavy_media_to_note.py --repo {NAME} --apply")
            print("   Если вес обоснован (нужны сами эталоны, не мусор) — завести")
            print(f"     {_exception} с обоснованием одной строкой, по образцу portrait-of-taste.")
            sys.exit(1)
    elif _total_mb > 100:
        print(f"🟡 {NAME}: {_total_mb:.0f} МБ — выше мягкого порога 100 МБ, пакую, но стоит разобрать")
    elif _total_mb > 50:
        print(f"🟡 {NAME}: {_total_mb:.0f} МБ — выше цели 50 МБ, пакую")

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
        else:
            print(f"   (замок старше часа — вероятно, процесс убит; продолжаю)")
            lock.unlink(missing_ok=True)
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

    # 🔴 PIT-152: WATCHLOG.md правился ПОСЛЕ вызова pack_release.py — архив
    # зафиксировал §0 ещё со старой версией, деплой поймал рассинхрон только на
    # публикации и потребовал полной переупаковки. Дешевле поймать здесь, до того
    # как секунды уйдут на zip: те же два формата строки §0, что revision_check.py
    # (`**Версия:**`) и легаси base-repo (`текущая точка:`), см. PIT-148.
    watchlog = REPO / "WATCHLOG.md"
    if watchlog.is_file():
        wl_text = watchlog.read_text(encoding="utf-8", errors="replace")
        wl_found = re.findall(r"\*\*Версия:\*\*\s*v?(\d+\.\d+\.\d+)", wl_text) \
            or re.findall(r"[Тт]екущая точка:\s*\**v?(\d+\.\d+\.\d+)", wl_text)
        if wl_found and wl_found[0] != version:
            print(f"!! WATCHLOG §0 говорит v{wl_found[0]}, а VERSION — {version} (PIT-152)")
            print("   поправь WATCHLOG.md §0 ДО упаковки — иначе архив зафиксирует старую точку входа")
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
