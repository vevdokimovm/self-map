#!/usr/bin/env python3
"""release_check.py — готова ли репа к публикации? Семь требований `101`.

🔴 ПОВОД. `deploy-SPEC.md` описывает гарантии ДЕПЛОЙЕРА: чего он не сделает
и почему. Обратной половины не было — что обязана предъявить РЕПА. Половина
инвариантов деплойера (`И2`, `И13`, `И16`, `И18`) это отказы из-за репы,
и каждый обнаруживался **в момент публикации**, когда чинить дороже всего.

ЧТО ПРОВЕРЯЕТСЯ — `00-infrastructure/101-release-readiness.md` §2:

    Г1  VERSION есть и разбирается как X.Y.Z
    Г2  README.md есть и непуст
    Г3  CHANGELOG содержит секцию текущей версии
    Г4  WATCHLOG §0 называет ту же версию
    Г5  .repo-id есть и совпадает с именем каталога
    Г6  файлов в дереве больше порога
    Г7  для реп с зеркалом — .publicinclude

🔴 ЧЕГО ОН НЕ ДЕЛАЕТ И ПОЧЕМУ:

  · **не чинит найденное.** `Г3` и `Г4` создаёт ритуал `close_batch.py`;
    остальное — суждение о репе. Молча дописать значило бы покрасить гейт
    зелёным при нерешённой задаче (`PIT-158`);
  · **не судит о смысле.** `CHANGELOG` с пустой секцией пройдёт `Г3`:
    проверяется форма, потому что гейт умеет только её;
  · **не ищет секреты.** Это `secrets_scan.py` — отдельный класс, и смешивать
    нельзя: секрет опаснее непубликации.

ЗАПУСК:
    python3 templates/release_check.py <репа>
    python3 templates/release_check.py --all
    python3 templates/release_check.py --selftest
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from _roots import resolve_roots  # noqa: E402

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
MIN_FILES = 5

# 🔴 СПИСОК ЗЕРКАЛ ЧИТАЕТСЯ У ДЕПЛОЙЕРА, А НЕ УГАДЫВАЕТСЯ ПО МЕТА-ФАЙЛУ.
#
# Первая редакция искала признак в `.repo-meta` — «по свойству, а не списком»,
# и это звучало правильно. Замер 04.09.2026 показал обратное: признак нашёлся
# **у одной репы из 65**, тогда как `MIRRORS` в `deploy.sh` перечисляет **десять**.
# Проверка была бы слепа на девять зеркал из десяти и молчала бы зелёным.
#
# Правило «свойство, а не список» (`PIT-097`) здесь не нарушено, а применено
# точнее: свойство «у репы есть зеркало» **уже объявлено** — в том самом месте,
# которое публикацией и управляет. Читать его оттуда — это один источник правды,
# а завести второй в `.repo-meta` значило бы развести их.


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


_MIRRORS: set[str] | None = None


def mirrors(base: Path) -> set[str]:
    """Имена реп-зеркал — умолчание деплойера плюс его `deploy-repos.conf`.

    🔴 Регулярка обязана переживать вложенное умолчание. С v4.26.0 строка
    выглядит так: `MIRRORS="${MIRRORS:-${CONF_MIRRORS:-имя …}}"`, и жадное
    `[^}]*` прежней редакции не совпало бы вовсе — проверка молча получила бы
    ПУСТОЙ набор зеркал и стала бы зелёной на всех десяти. Это `PIT-165`:
    правка в одном файле, отказ в другом, и оба выглядят исправными.
    """
    global _MIRRORS
    if _MIRRORS is None:
        deploy = base / "templates" / "deploy.sh"
        m = re.search(r'^MIRRORS="\$\{MIRRORS:-(.*)\}"$',
                      read(deploy), re.M)
        raw = m.group(1) if m else ""
        inner = re.match(r'^\$\{CONF_MIRRORS:-(.*)\}$', raw)
        if inner:
            raw = inner.group(1)
        names = set(raw.split())
        # Конфиг рядом со скриптом ДОПОЛНЯЕТ умолчание, а не заменяет его.
        # Здесь вопрос не «что применится на прогоне», а «какая репа вообще
        # является зеркалом»: репу, убранную из конфига, всё ещё нельзя
        # публиковать как обычную, пока она открыта в public.
        conf = read(deploy.parent / "deploy-repos.conf")
        for line in conf.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key.strip() == "MIRRORS":
                names |= set(val.strip().strip('"\'').split())
        _MIRRORS = names
    return _MIRRORS


def has_mirror(repo: Path, base: Path) -> bool:
    return repo.name in mirrors(base)


def watchlog_text(repo: Path) -> tuple[str, str]:
    """Текст журнала вахты — СЛЕДУЯ УКАЗАТЕЛЮ, если корневой файл им является.

    🔴 ПОВОД, 04.09.2026. Первая редакция читала только `WATCHLOG.md` в корне
    и объявила `personal-finance-dss` нарушителем `Г4`. Репа была права:
    в корне у неё **указатель**

        > 🔴 Здесь журнала нет намеренно — он в `docs/WATCHLOG.md`

    а сам журнал — в `docs/`, со строкой «**Версия:** 8.42.0», совпадающей
    с `VERSION`. То есть требование выполнено, а проверка этого не видела.

    Схема «указатель в корне + журнал глубже» законна: у крупной репы
    документация живёт в `docs/`, и корневой файл честно на неё показывает.
    Подстраиваться должна проверка, а не репа.

    🔴 Класс `PIT-187`: проверка отвечала на СВОЙ вопрос («есть ли строка
    в корневом файле») вместо заданного («называет ли точка входа репы
    верную версию»). Вторая вахта уже собиралась потратить батч на правку,
    которая была не нужна.

    Возвращает (текст, откуда) — второе для внятного сообщения об отказе.
    """
    root = repo / "WATCHLOG.md"
    txt = read(root)
    if not txt:
        return "", "WATCHLOG.md"

    # Указатель узнаётся по свойству: сам версии не называет, но ссылается
    # на другой WATCHLOG. Ссылка ищется markdown-формой `(путь)`.
    if "**Версия:**" not in txt:
        for m in re.finditer(r"\(([^)]*WATCHLOG\.md)\)", txt):
            target = repo / m.group(1).lstrip("./")
            if target.is_file() and target != root:
                inner = read(target)
                if "**Версия:**" in inner:
                    return inner, m.group(1)
    return txt, "WATCHLOG.md"


def check(repo: Path, base: Path) -> list[tuple[str, str, str]]:
    """[(требование, что не так, как чинить)]."""
    bad: list[tuple[str, str, str]] = []

    ver = read(repo / "VERSION").strip()
    if not ver:
        bad.append(("Г1", "VERSION отсутствует или пуст",
                    "завести файл VERSION с X.Y.Z"))
    elif not SEMVER.match(ver):
        bad.append(("Г1", f"VERSION = {ver!r} — не X.Y.Z",
                    "привести к виду 1.2.3"))

    readme = read(repo / "README.md").strip()
    if not readme:
        bad.append(("Г2", "README.md отсутствует или пуст",
                    "деплойер не тронет дерево без маркера корня (И2)"))

    if ver and SEMVER.match(ver):
        chlog = read(repo / "CHANGELOG.md")
        if f"[{ver}]" not in chlog:
            bad.append(("Г3", f"в CHANGELOG нет секции [{ver}]",
                        "закрыть батч ритуалом close_batch.py"))

        wl, wl_where = watchlog_text(repo)
        m = re.search(r"\*\*Версия:\*\*\s*([0-9.]+)", wl)
        if not m:
            bad.append(("Г4", f"в {wl_where} нет строки «**Версия:**»",
                        "точка входа обязана называть версию (04-watchlog-protocol)"))
        elif m.group(1).strip() != ver:
            bad.append(("Г4", f"{wl_where} говорит {m.group(1)}, VERSION — {ver}",
                        "обновить §0: расхождение шапки и тела ловит И18"))

    # 🔴 ФОРМАТ `owner/repo`, А НЕ ГОЛОЕ ИМЯ. Первая редакция сравнивала
    # содержимое с именем каталога и объявила **65 реп из 65** неготовыми:
    # штатное `vevdokimovm/war` не равно `war`.
    #
    # Ошибка того же рода, что весь этот день (`PIT-187`): формат был
    # ПРЕДПОЛОЖЕН по смыслу поля, а не прочитан с диска. Проверка, объявившая
    # нарушителями всех, почти наверняка неверна сама — сто процентов
    # нарушений это диагноз проверяющему, а не проверяемым.
    rid = read(repo / ".repo-id").strip()
    if not rid:
        bad.append(("Г5", ".repo-id отсутствует",
                    "без него карта переписывает цель по имени архива (И16)"))
    elif rid.rsplit("/", 1)[-1] != repo.name:
        bad.append(("Г5", f".repo-id = {rid!r}, каталог — {repo.name!r}",
                    "имя после слэша обязано совпадать с каталогом"))

    n = sum(1 for p in repo.rglob("*")
            if p.is_file() and ".git" not in p.parts and "_base" not in p.parts)
    if n < MIN_FILES:
        bad.append(("Г6", f"файлов всего {n} (порог {MIN_FILES})",
                    "публикация пустышки поверх живой репы необратима"))

    if has_mirror(repo, base) and not (repo / ".publicinclude").exists():
        bad.append(("Г7", "есть зеркало, но нет .publicinclude",
                    "без списка чистка зеркала работает как denylist (59 §1)"))

    return bad


def selftest() -> int:
    """Канарейка: проверка обязана ловить подсаженное нарушение."""
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as d:
        r = Path(d) / "probe-repo"
        r.mkdir()
        # заведомо негодная репа — обязана дать нарушения
        empty = check(r, Path(d))
        got = {c for c, _, _ in empty}
        for need in ("Г1", "Г2", "Г5", "Г6"):
            mark = "✅" if need in got else "🔴"
            print(f"   {mark} пустая репа ловится по {need}")
            ok &= need in got
        # годная репа — обязана пройти
        (r / "VERSION").write_text("1.0.0", encoding="utf-8")
        (r / "README.md").write_text("# probe\n", encoding="utf-8")
        (r / "CHANGELOG.md").write_text("## [1.0.0] — тест\n", encoding="utf-8")
        (r / "WATCHLOG.md").write_text("**Версия:** 1.0.0\n", encoding="utf-8")
        (r / ".repo-id").write_text("probe-repo", encoding="utf-8")
        for i in range(6):
            (r / f"f{i}.md").write_text("x", encoding="utf-8")
        good = check(r, Path(d))
        mark = "✅" if not good else "🔴"
        print(f"   {mark} годная репа проходит "
              f"{'' if not good else '— но найдено: ' + str(good)}")
        ok &= not good
        # 🔴 СЛУЧАЙ С УКАЗАТЕЛЕМ — ради него проверка и правилась 04.09.2026.
        # Корневой WATCHLOG не называет версию, а показывает на другой файл.
        # Без этой канарейки регрессия вернётся молча: обычная репа пройдёт,
        # а репа с указателем снова станет «нарушителем».
        (r / "docs").mkdir()
        (r / "WATCHLOG.md").write_text(
            "# указатель\n> журнала здесь нет, он в [`docs/WATCHLOG.md`](docs/WATCHLOG.md)\n",
            encoding="utf-8")
        (r / "docs" / "WATCHLOG.md").write_text("**Версия:** 1.0.0\n", encoding="utf-8")
        via = check(r, Path(d))
        mark = "✅" if not via else "🔴"
        print(f"   {mark} указатель в корне → журнал в docs/ "
              f"{'' if not via else '— но найдено: ' + str(via)}")
        ok &= not via

        # И обратное: если по указателю версия ДРУГАЯ — обязано ловиться.
        (r / "docs" / "WATCHLOG.md").write_text("**Версия:** 9.9.9\n", encoding="utf-8")
        mism = {c for c, _, _ in check(r, Path(d))}
        mark = "✅" if "Г4" in mism else "🔴"
        print(f"   {mark} расхождение версии ЗА указателем ловится")
        ok &= "Г4" in mism

    print("selftest OK" if ok else "🔴 selftest ПРОВАЛЕН")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", nargs="?", help="имя репы; без него — текущая")
    ap.add_argument("--all", action="store_true", help="все репы системы")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    _base, root, _ = resolve_roots(__file__)
    if a.all:
        repos = [d for d in sorted(root.iterdir())
                 if d.is_dir() and (d / "VERSION").exists()]
    elif a.repo:
        repos = [root / a.repo]
    else:
        repos = [_base]

    total_bad = 0
    for repo in repos:
        if not repo.exists():
            print(f"🔴 нет репы: {repo.name}")
            return 2
        bad = check(repo, _base)
        total_bad += len(bad)
        if bad:
            print(f"\n🔴 {repo.name} — не готова ({len(bad)}):")
            for code, what, how in bad:
                print(f"   {code}  {what}")
                print(f"       → {how}")

    n = len(repos)
    if total_bad:
        print(f"\nИТОГ: {n} реп · нарушений {total_bad} · публиковать нельзя")
        return 1
    print(f"ИТОГ: {n} реп · 🟢 все готовы к публикации")
    return 0


if __name__ == "__main__":
    sys.exit(main())
