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
import os
import sys
import zipfile
from pathlib import Path

# Путь репы — аргументом, база по умолчанию. Захардкоженный путь означал, что
# для любой другой репы пришлось бы писать ВТОРОЙ упаковщик — ровно то, чем
# кончились восемь скриптов деплоя до консолидации (templates/README.md).
# Имя берётся из каталога, а не из константы: имя каталога и имя репы обязаны
# совпадать, и если не совпали — это дефект, который лучше увидеть здесь.
REPO = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 \
    else Path("/Users/vasyaevdokimov/Documents/base-repo")
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
    wrapper = f"{NAME}-v{version}"
    out = OUT_DIR / f"{wrapper}.zip"

    if out.exists():
        print(f"!! уже существует: {out} — не перезаписываю (SYN-005)")
        sys.exit(1)

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
