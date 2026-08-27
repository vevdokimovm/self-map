#!/usr/bin/env python3
"""git_limits_check.py — пройдёт ли это в git и на GitHub.

ЗАКАЗ ВЛАДЕЛЬЦА 23.08.2026: *«сделай ресёрч по ограничениям гита и проверки этого»*.

ПОВОД. Деплой встал: `git push` в `edu-base` отклонялся `pre-receive` хуком — файл
**207.75 МБ** при жёстком лимите **100 МБ**. Скрипт счёл отказ сетевым и ретраил пять
раз по 549 МБ (`PIT-129`). Ограничения были известны и записаны
(`00-infrastructure/06-volume-compression.md` §«Что физически умеет GitHub»), но
**проверялись только глазами** — то есть не проверялись.

---

## Ограничения, которые проверяет этот скрипт

| Ограничение | Порог | Что делает GitHub |
|---|---|---|
| размер файла | **100 МиБ** | 🔴 **отклоняет push**: `GH001`, `pre-receive hook declined` |
| размер файла | 50 МиБ | предупреждает в выводе push |
| размер репозитория | 5 ГБ рекомендуемый | письмо о превышении, просьба сократить |
| размер push за раз | 2 ГБ | обрыв соединения |
| рендер `.md` на сайте | ~1 МБ | файл не отрисовывается, только «view raw» |
| файлов в дереве | десятки тысяч | клон и статус деградируют, `git status` заметно медленнее |

🔴 **Git LFS для knowledge-репы — не решение, а сигнал.** Он снимает лимит на файл,
но добавляет квоту (1 ГБ бесплатно), ломает «скачал zip — получил репу» и требует
установленного клиента у каждого, кто клонирует. Для репы знаний тяжёлый бинарник —
признак, что файл вообще не туда (`06-volume-compression.md`).

## Отдельная проверка: целостность архива

Найдено 23.08.2026 тем же прогоном: `misc-vault-v0.1.0.zip` (1.43 ГБ) и
`it-base-v1.2.0.zip` (70 МБ) — **недописаны**. `file` показывает «Zip archive data»,
размер выглядит правдоподобно, а центральной директории нет: упаковку убил таймаут.

> **Оборванный архив неотличим от готового по имени и размеру.** Отличим он только
> попыткой прочитать оглавление — поэтому проверка здесь, а не в глазах.

ЗАПУСК
    git_limits_check.py                     репы системы + архивы в ~/Downloads
    git_limits_check.py --repo ИМЯ          одна репа
    git_limits_check.py --archives          только архивы
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

BASE_REPO = Path(__file__).resolve().parent.parent
REPOS = BASE_REPO.parent
DOWNLOADS = Path.home() / "Downloads"

HARD_FILE = 100 * 2**20      # push отклоняется
WARN_FILE = 50 * 2**20       # предупреждение GitHub
SOFT_REPO = 5 * 2**30        # рекомендуемый максимум репы (лимит GitHub, не наш)
MD_RENDER = 1 * 2**20        # выше — GitHub не рендерит .md
MANY_FILES = 20_000          # деградация клона и git status

# 🔴 Наш норматив (01-repo-standard.md §4, 06-volume-compression.md) — СТРОЖЕ,
# чем лимит GitHub (5 ГБ), и про другое: не «примет ли git», а «возьмёт ли Claude
# архив целиком». Добавлено 26.08.2026: misc-vault (674 МБ) и academic-portfolio
# (1018 МБ) прошли git-лимиты чисто (оба ≪ 5 ГБ) и ушли в архив без единого
# предупреждения — этот скрипт проверял только «пройдёт ли в git», не «уложились
# ли в наш норматив». pack_release.py получил тот же порог отдельно (PIT-146);
# здесь — тот же норматив для системной сверки по всем репам разом.
OUR_TARGET = 50 * 2**20      # 🟢 цель
OUR_SOFT = 100 * 2**20       # 🟡 мягкий
OUR_HARD = 500 * 2**20       # 🔴 жёсткий — Claude не берёт архив целиком

SKIP_PARTS = {".git", "_base", "node_modules", ".venv", "__pycache__"}


def check_repo(repo: Path) -> list[str]:
    problems: list[str] = []
    total = 0
    count = 0
    for p in repo.rglob("*"):
        if not p.is_file() or any(x in p.parts for x in SKIP_PARTS):
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        total += size
        count += 1
        rel = p.relative_to(repo)
        if size > HARD_FILE:
            problems.append(f"🔴 БЛОК {size / 2**20:7.1f} МБ  {rel}")
        elif size > WARN_FILE:
            problems.append(f"⚠️  warn {size / 2**20:7.1f} МБ  {rel}")
        elif p.suffix.lower() == ".md" and size > MD_RENDER:
            problems.append(f"⚠️  .md не отрендерится ({size / 2**20:.1f} МБ)  {rel}")
    if total > SOFT_REPO:
        problems.append(f"⚠️  репа {total / 2**30:.1f} ГБ — выше рекомендуемых GitHub 5 ГБ")
    if total > OUR_HARD:
        _exc = repo / ".size-exception"
        if _exc.is_file():
            problems.append(f"🟡 {total / 2**20:.0f} МБ — выше нашего жёсткого 500 МБ, но есть "
                             f".size-exception: {_exc.read_text(encoding='utf-8').strip()[:100]}")
        else:
            problems.append(f"🔴 {total / 2**20:.0f} МБ — выше НАШЕГО жёсткого потолка 500 МБ "
                             f"(01-repo-standard.md §4) — Claude не возьмёт архив целиком")
    elif total > OUR_SOFT:
        problems.append(f"🟡 {total / 2**20:.0f} МБ — выше нашего мягкого 100 МБ")
    elif total > OUR_TARGET:
        problems.append(f"🟡 {total / 2**20:.0f} МБ — выше нашей цели 50 МБ")
    if count > MANY_FILES:
        problems.append(f"⚠️  файлов {count} — клон и `git status` деградируют")
    return problems


def check_archive(z: Path) -> list[str]:
    """Целостность и содержимое архива: недописанный zip выглядит как готовый."""
    try:
        zf = zipfile.ZipFile(z)
        infos = zf.infolist()
    except zipfile.BadZipFile:
        # 🔴 Различать «битый» и «ещё пишется». Признак у них ОДИН — нет центральной
        # директории, она дописывается последней. Отличает только замок упаковщика
        # (`PIT-131`). Без этой ветки проверка объявляла битым архив, который
        # в тот момент нормально собирался, — и я дважды удалял живую работу.
        if z.with_suffix(".zip.lock").exists():
            return [f"⏳ ПИШЕТСЯ прямо сейчас (есть замок), "
                    f"{z.stat().st_size / 2**20:.0f} МБ — проверить после завершения"]
        return [f"🔴 БИТЫЙ — нет центральной директории, замка нет: упаковка оборвана "
                f"или шла гонка ({z.stat().st_size / 2**20:.0f} МБ на диске)"]
    except OSError as exc:
        return [f"🔴 не читается: {exc}"]
    out = []
    for i in infos:
        if i.file_size > HARD_FILE:
            out.append(f"🔴 БЛОК внутри {i.file_size / 2**20:7.1f} МБ  {i.filename[:70]}")
        elif i.file_size > WARN_FILE:
            out.append(f"⚠️  warn внутри {i.file_size / 2**20:7.1f} МБ  {i.filename[:70]}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--archives", action="store_true")
    a = ap.parse_args()

    bad = 0

    if not a.archives:
        targets = [REPOS / a.repo] if a.repo else sorted(d for d in REPOS.iterdir() if d.is_dir())
        print("── РЕПЫ")
        for t in targets:
            if not t.is_dir():
                continue
            pr = check_repo(t)
            if pr:
                print(f"\n  {t.name}")
                for line in pr[:8]:
                    print(f"      {line}")
                if len(pr) > 8:
                    print(f"      … и ещё {len(pr) - 8}")
                bad += sum(1 for x in pr if x.startswith("🔴"))

    if not a.repo:
        print("\n── АРХИВЫ в ~/Downloads")
        for z in sorted(DOWNLOADS.glob("*.zip")):
            pr = check_archive(z)
            if pr:
                print(f"\n  {z.name}")
                for line in pr[:5]:
                    print(f"      {line}")
                bad += sum(1 for x in pr if x.startswith("🔴"))

    print(f"\n  блокирующих находок: {bad}")
    if not bad:
        print("  ИТОГ: ограничения git и GitHub соблюдены")
    else:
        print("  Тяжёлое: python3 07-media-to-text-lab/tools/heavy_media_to_note.py --all --apply")
        print("  Битый архив: удалить и собрать заново `pack_release.py <путь-репы>`")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
