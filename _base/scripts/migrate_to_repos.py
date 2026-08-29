#!/usr/bin/env python3
"""migrate_to_repos.py — перенос материала с диска в систему реп.

ЗАДАЧА (владелец, 22.08.2026): «перенести всю информацию с мака в репы и удалить всё.
Оставить только репы на маке в этих папках. Ну и неопубликованные архивы».

То есть `~/Documents` должен схлопнуться до: `система_репозиториев/`, рабочие папки
git-реп (`finpilot`, `base-repo`), `recovery_kits` (секреты, в репу не идут никогда).
Остальные 24 папки — ~4.4 ГБ, ~48 000 файлов — переносятся по адресам и сносятся.

🔴 ТРИ ПРАВИЛА `00-CLAUDE-STOP.md` §3, нарушение любого = молчаливая потеря данных.
Здесь они не пожелания, а устройство скрипта:

1. **Не перезаписывать.** `dest.exists()` и содержимое иное → кладём рядом с суффиксом
   и пишем в журнал. Скрипт без этой проверки уже съел два файла-варианта 20.08.2026,
   и потеря обнаружилась только пост-диффом.
2. **Доказывать диффом множеств.** Перенос ничего не удаляет. Удаление — отдельный
   прогон `--verify-and-clean`, который сначала сверяет «каждый файл источника имеет
   пару в цели по sha256», и сносит источник ТОЛЬКО при полном совпадении множеств.
3. **Тяжёлое — в служебку, а не в помойку.** Файл, не проходящий по правилам
   `06-volume-compression.md`, не переносится молча: он попадает в отчёт кампании
   с причиной, чтобы решение принял человек.

ПОЧЕМУ ДВА ПРОГОНА, А НЕ ОДИН. Копирование и удаление, слитые в одну операцию, дают
`mv`, у которого нет промежуточного состояния для проверки: если пара не сошлась,
источника уже нет. Разделение стоит удвоенного места на время кампании и покупает
возможность доказать перенос до того, как он станет необратимым.

ЗАПУСК:
    migrate_to_repos.py --plan                 что куда пойдёт, ничего не трогает
    migrate_to_repos.py --copy ИМЯ             скопировать одну папку-источник
    migrate_to_repos.py --verify ИМЯ           сверить множества по sha256
    migrate_to_repos.py --verify-and-clean ИМЯ сверить и снести источник при совпадении
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

DOCS = Path.home() / "Documents"
REPOS = DOCS / "система_репозиториев"

# Карта «папка на диске → репа». Составлена по предмету, а не по имени:
# совпадение имён проверялось, но решало содержимое.
MAP: dict[str, str] = {
    "документы_по_медицине": "health-vault",
    "здоровье": "health-vault",
    "юриспруденция": "legal-knowledge-base",
    "Иисус Христос": "christ-walk",
    "я": "self-map",
    "семья": "family",
    "наука": "science",
    "карьера": "career",
    "IT": "it-base",
    "технологии": "it-base",
    "разное": "misc-vault",
    "магистратура ": "master-admission",
    "researches": "research-craft",
    "books": "misc-vault",
    "notes": "misc-vault",
    "obsidian": "misc-vault",
    # Дозаведено 22.08.2026 по составу, а не по имени папки:
    "аналитика": "self-map",        # 2 из 3 файлов — «Портрет Василий Евдокимов»
    "логика": "research-craft",     # repos-map: «как познавать — логика, научный метод»
    "видео": "legal-knowledge-base",# мастер-класс про общение с военкоматом
    "GitHub": "it-base",            # учебный код CodeSignal
    # Дозаведено 22.08.2026 по содержимому; допущения названы в отчёте кампании:
    "диплом_бакалавра": "academic-portfolio",   # ВКР бакалавра — академическая работа
    "schizophrenic_things": "truth-seeking",    # «Rabbit Hole», ковид-вакцины — предмет разборов
    "education": "edu-base",                    # лингвистика, курс АУ, дикция
    "claude": "claude-usage",                   # методички и обходы ошибок Claude
    "exports": "misc-vault",                    # выгрузки apple notes / notion / remnote
    "Screenshots": "misc-vault",                # транзитный материал
}

# Требуют решения владельца — предмет не сводится к одной репе или нужен разбор.
UNMAPPED_REASON: dict[str, str] = {
}

KEEP = {"система_репозиториев", "finpilot", "base-repo", "recovery_kits"}
SKIP_NAMES = {".DS_Store", ".localized"}

# 🔴 СЕКРЕТЫ НЕ ЕДУТ В РЕПУ НИКОГДА (`00-CLAUDE-STOP.md` §2, PIT-012).
# Заведено 22.08.2026 ПОСЛЕ инцидента: при переносе `IT` файл `vk-graph/.env`
# с живым токеном `vk1.a...` уехал в `it-base/90-imported/`. Спасло только то,
# что у `it-base` нет локального `.git` — до коммита не дошло.
# Секрет опасен самим фактом попадания в файл репы: из git он не удаляется,
# а отзывается у провайдера. Поэтому проверка машинная, а не «не забыть».
SECRET_PATTERNS = (".env", ".envrc", ".netrc", ".pgpass", "id_rsa", "id_ed25519",
                   ".pem", ".p12", ".keystore", "credentials", "secrets.json")

# 🔴 КАТАЛОГИ, КОТОРЫЕ НЕЛЬЗЯ СНОСИТЬ ВМЕСТЕ С ИСТОЧНИКОМ.
# `.git` исключался из ПЕРЕНОСА (в репу чужая история не нужна), но `rmtree`
# сносил источник целиком — вместе с невынесенным. Фильтр, написанный для одной
# операции, молча применился к другой, и это стоило истории клона `vk-graph`.
PRESERVE_DIRS = (".git",)

# 🔴 РЕГЕНЕРИРУЕМОЕ НЕ ПЕРЕНОСИТСЯ, А УДАЛЯЕТСЯ.
# `06-volume-compression.md`: «артефакты сборки — вон, пересобираются».
# `STANDARD.md` §00 п.3: регенерируемое исключается из переписи ПО ОПРЕДЕЛЕНИЮ,
# а не для удобства — оно восстанавливается из того, что в переписи остаётся.
# Найдено 22.08.2026 на переносе `юриспруденция`: в репы поехали `.venv`
# и `node_modules`, то есть чужие библиотеки внутрь knowledge-репы.
REGENERABLE_DIRS = (".venv", "venv", "node_modules", "__pycache__",
                    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".ipynb_checkpoints")


def in_regenerable(p: Path) -> bool:
    return any(d in p.parts for d in REGENERABLE_DIRS)


def is_secret(p: Path) -> bool:
    """Ложное срабатывание внутри библиотек отсекается до проверки имени.

    `pip/_vendor/certifi/cacert.pem` — публичный CA-бандл, а не ключ. Фильтр по
    расширению его ловил и блокировал завершение переноса (найдено 22.08.2026).
    """
    if in_regenerable(p):
        return False
    n = p.name.lower()
    # Шаблон — не секрет: `.env.example` содержит плейсхолдеры и штатно лежит в репе.
    # Ложное срабатывание найдено 22.08.2026 на `диплом_бакалавра/Финалки/finpilot`.
    if any(n.endswith(sfx) for sfx in (".example", ".sample", ".template", ".dist")):
        return False
    return any(n == s or n.endswith(s) or n.startswith(s) for s in SECRET_PATTERNS)


def unmoved_precious(src: Path) -> list[Path]:
    """Что осталось в источнике и НЕ является мусором — до удаления пересчитать."""
    out = []
    for p in src.rglob("*"):
        if p.is_file() and p.name not in SKIP_NAMES and not in_regenerable(p):
            out.append(p)
    return out


def sha(p: Path) -> str | None:
    h = hashlib.sha256()
    try:
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def files_of(root: Path) -> list[Path]:
    return [p for p in root.rglob("*")
            if p.is_file() and p.name not in SKIP_NAMES
            and ".git" not in p.parts and not in_regenerable(p)]


def dest_for(src_root: Path, f: Path, repo: Path) -> Path:
    """Материал ложится в `<репа>/90-imported/<имя источника>/<как лежало>`.

    Отдельный раздел, а не вперемешку с существующим: переносимое не проверено
    ревизией репы, и смешивать непроверенное с проверенным — значит потерять
    границу между ними (`21` §1).
    """
    return repo / "90-imported" / src_root.name / f.relative_to(src_root)


def cmd_plan() -> None:
    print(f"{'источник':<26}{'→ репа':<24}{'файлов':>8}{'объём':>9}")
    print("-" * 68)
    total_f = 0
    for name in sorted(MAP):
        src = DOCS / name
        if not src.is_dir():
            print(f"{name:<26}{'НЕТ НА ДИСКЕ':<24}")
            continue
        fs = files_of(src)
        mb = sum(f.stat().st_size for f in fs) / 2**20
        total_f += len(fs)
        repo_ok = "✓" if (REPOS / MAP[name]).is_dir() else "✗ НЕТ РЕПЫ"
        print(f"{name:<26}{MAP[name] + ' ' + repo_ok:<24}{len(fs):>8}{mb:>8.0f}М")
    print(f"\nвсего к переносу по карте: {total_f} файлов\n")
    print("ТРЕБУЮТ РЕШЕНИЯ ВЛАДЕЛЬЦА (не переносятся автоматически):")
    for name, why in sorted(UNMAPPED_REASON.items()):
        if (DOCS / name).is_dir():
            print(f"  · {name:<24} {why}")
    print("\nОСТАЮТСЯ НА ДИСКЕ:", ", ".join(sorted(KEEP)))


def cmd_copy(name: str) -> None:
    src = DOCS / name
    repo = REPOS / MAP[name]
    if not src.is_dir() or not repo.is_dir():
        sys.exit(f"нет источника или репы: {src} → {repo}")

    copied = skipped = collided = 0
    log: list[str] = []
    for f in files_of(src):
        d = dest_for(src, f, repo)
        d.parent.mkdir(parents=True, exist_ok=True)
        if d.exists():
            if sha(d) == sha(f):
                skipped += 1
                continue
            # ПРАВИЛО 1: не перезаписываем — кладём рядом и логируем
            alt = d.with_name(f"{d.stem}__from-{name}{d.suffix}")
            shutil.copy2(f, alt)
            collided += 1
            log.append(f"КОЛЛИЗИЯ: {f} → {alt} (в цели уже был иной файл)")
            continue
        shutil.copy2(f, d)
        copied += 1

    print(f"{name} → {MAP[name]}: скопировано {copied} · уже было {skipped} · коллизий {collided}")
    for line in log[:20]:
        print("  " + line)
    if len(log) > 20:
        print(f"  … и ещё {len(log) - 20} коллизий")


def is_public(repo_name: str) -> bool:
    """🔴 ПРЕДОХРАНИТЕЛЬ ПО ФАКТУ, а не по списку (`PIT-097`, `PIT-123`).

    22.08.2026 карта переноса разложила материал по 20 репам, из которых пять оказались
    ПУБЛИЧНЫМИ: в `claude-usage` уехали 152 файла личных инструкций, в `vk-graph` —
    проект с `.env`. MAP сопоставляла папку с репой по предмету и о видимости не знала.

    Предохранитель по `isPrivate` в системе уже был — но в `sync-base.sh`, то есть
    на раздаче базы. Новый инструмент воспроизвёл дефект, от которого старый защищён:
    защита была свойством одного скрипта, а не системы. Поэтому спрашиваем сами.
    """
    import subprocess
    try:
        r = subprocess.run(["gh", "repo", "view", f"vevdokimovm/{repo_name}",
                            "--json", "isPrivate", "--jq", ".isPrivate"],
                           capture_output=True, text=True, timeout=20)
        # Не смогли выяснить — считаем ПУБЛИЧНОЙ: отказ в пользу более дорогой ошибки.
        return r.stdout.strip() != "true"
    except Exception:
        return True


def cmd_move(name: str) -> None:
    """Перенос через `os.rename` — когда источник и цель на ОДНОЙ файловой системе.

    🔴 ЗАЧЕМ ОТДЕЛЬНЫЙ РЕЖИМ, И ПОЧЕМУ ЗДЕСЬ ОН ПРАВИЛЬНЕЕ КОПИРОВАНИЯ.
    Замер 22.08.2026: копирование шло **22 файла/мин** — на 7 030 файлов это ≈5 часов.
    Причина не в диске: `~/Documents` синхронизирован с iCloud Drive, и из 4 136 файлов
    в `IT` локально материализовано **27**, остальные 4 109 — заглушки. `shutil.copy2`
    открывает исходник → macOS качает файл из облака → пишет копию в цель, которая тоже
    под iCloud → ставит её в очередь на выгрузку. Скачивание и закачка по сети на каждый
    файл (`PIT-120`).

    `os.rename` в пределах одной ФС — операция над **метаданными**: содержимое не читается,
    заглушка не материализуется, iCloud просто меняет путь. Проверено: `df` даёт
    `/dev/disk1s1` и для источника, и для цели.

    **Почему это не нарушает правило 2 («доказывать диффом»).** Правило написано против
    `mv` между разными носителями, где копия может оказаться неполной, а источника уже нет.
    Здесь копии не существует: rename **атомарен для каждого файла** — он либо по старому
    пути, либо по новому, промежуточного состояния нет. Доказывать нечего, потому что
    нечему разойтись; сверять хеш файла с самим собой бессмысленно.

    **Что остаётся под охраной — правило 1.** Единственный реальный риск здесь: затереть
    файл, уже лежащий в цели. `dest.exists()` проверяется до переноса, коллизия кладётся
    рядом с суффиксом и логируется — ровно как в режиме копирования.
    """
    src = DOCS / name
    repo = REPOS / MAP[name]
    if not src.is_dir() or not repo.is_dir():
        sys.exit(f"нет источника или репы: {src} → {repo}")
    if is_public(MAP[name]):
        sys.exit(f"🔴 СТОП: репа-цель `{MAP[name]}` ПУБЛИЧНАЯ (или её видимость не выяснена).\n"
                 f"   Личный материал туда не кладётся. Выбери приватную цель в MAP.")

    moved = collided = secrets = skipped = 0
    log: list[str] = []
    for f in files_of(src):
        # ПРАВИЛО 0 (сильнее всех): секрет в репу не едет. Уходит в карантин
        # рядом с recovery_kits, вне системы реп.
        if is_secret(f):
            q = Path.home() / "Documents" / "recovery_kits" / "_quarantine-from-migration"
            q.mkdir(parents=True, exist_ok=True)
            target = q / f"{name}__{f.parent.name}__{f.name}"
            if not target.exists():
                f.rename(target)
            secrets += 1
            log.append(f"🔴 СЕКРЕТ в карантин: {f} → {target.name}")
            continue
        d = dest_for(src, f, repo)
        d.parent.mkdir(parents=True, exist_ok=True)
        if d.exists():
            # 🔴 29.08.2026: ЗДЕСЬ НЕ СРАВНИВАЛОСЬ СОДЕРЖИМОЕ — суффикс ставился
            # по одному факту существования файла. Режим копирования (выше)
            # сравнивал хеши и молча пропускал одинаковое; режим переноса —
            # нет, и каждый уже перенесённый файл получал вторую копию.
            #
            # Замер последствий, `legal-knowledge-base/04-reference/raznoe-import/`:
            # **31 пара из 32** оказалась побайтовыми дублями, 15.7 МБ лишнего
            # веса. При этом сам журнал писал «в цели уже был иной файл» — то
            # есть утверждал ровно то, чего не проверял.
            #
            # Тот же класс, что в `74`/`22`: два пути одной операции разошлись
            # в поведении, и разошлись молча, потому что расхождение видно
            # только по весу репы через полгода.
            if sha(d) == sha(f):
                # Файл уже на месте и совпадает побайтово — переносить нечего.
                # Источник удаляется: он и есть лишняя копия.
                f.unlink()
                skipped += 1
                continue
            d = d.with_name(f"{d.stem}__from-{name}{d.suffix}")
            if d.exists():
                log.append(f"ПРОПУЩЕН (занято дважды): {f}")
                continue
            collided += 1
            log.append(f"КОЛЛИЗИЯ: {f} → {d.name} (содержимое сверено, оно ИНОЕ)")
        try:
            f.rename(d)
            moved += 1
        except OSError as exc:
            log.append(f"ОШИБКА: {f} — {exc}")

    print(f"{name} → {MAP[name]}: перенесено {moved} · уже было (побайтово) {skipped} · коллизий {collided} · секретов в карантин {secrets}")
    for line in log[:15]:
        print("  " + line)
    if len(log) > 15:
        print(f"  … и ещё {len(log) - 15} записей журнала")

    # 🔴 ПРОВЕРКА ПЕРЕД УДАЛЕНИЕМ. Считаем НЕ `files_of` (он исключает `.git`),
    # а всё живое. Иначе источник выглядит пустым, будучи непустым, — и `rmtree`
    # уносит то, что фильтр только что защитил от переноса.
    left = unmoved_precious(src)
    if not left:
        shutil.rmtree(src)
        print(f"✓ источник {src} пуст и удалён")
        return

    preserved = [p for p in left if any(d in p.parts for d in PRESERVE_DIRS)]
    if preserved:
        repos_found = sorted({str(p.parents[len(p.parts) - 1 - p.parts.index('.git') - 1])
                              for p in preserved if '.git' in p.parts}) if preserved else []
        print(f"🔴 источник НЕ удалён: в нём {len(left)} файлов, из них {len(preserved)} "
              f"в служебных каталогах {PRESERVE_DIRS}.")
        print("   Это git-история клонов. Решить руками: снести осознанно или перенести репу целиком.")
        for r in repos_found[:5]:
            print(f"   · {r}")
    else:
        print(f"🔴 источник НЕ удалён: осталось {len(left)} файлов — разобрать журнал выше")


def cmd_verify(name: str, clean: bool) -> None:
    """ПРАВИЛО 2: сносим только то, чьё присутствие в цели доказано по хешу."""
    src = DOCS / name
    repo = REPOS / MAP[name]
    target_hashes: set[str] = set()
    imported = repo / "90-imported" / name
    if imported.is_dir():
        target_hashes = {h for h in (sha(p) for p in files_of(imported)) if h}

    missing = [f for f in files_of(src) if sha(f) not in target_hashes]
    total = len(files_of(src))
    print(f"{name}: файлов в источнике {total} · без пары в цели {len(missing)}")
    for f in missing[:15]:
        print(f"  ✗ {f.relative_to(src)}")
    if len(missing) > 15:
        print(f"  … и ещё {len(missing) - 15}")

    if not clean:
        return
    if missing:
        sys.exit("🔴 источник НЕ удалён: множества не сошлись. Сначала --copy, потом снова --verify")
    shutil.rmtree(src)
    print(f"✓ источник {src} удалён — все {total} файлов доказаны в цели")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--plan", action="store_true")
    p.add_argument("--copy", metavar="ИМЯ")
    p.add_argument("--move", metavar="ИМЯ", help="перенос rename-ом: одна ФС, заглушки iCloud не качаются")
    p.add_argument("--verify", metavar="ИМЯ")
    p.add_argument("--verify-and-clean", dest="clean", metavar="ИМЯ")
    a = p.parse_args()

    if a.plan:
        cmd_plan()
    elif a.copy:
        cmd_copy(a.copy)
    elif a.move:
        cmd_move(a.move)
    elif a.verify:
        cmd_verify(a.verify, clean=False)
    elif a.clean:
        cmd_verify(a.clean, clean=True)
    else:
        p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
