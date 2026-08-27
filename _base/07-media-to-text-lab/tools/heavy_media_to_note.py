#!/usr/bin/env python3
"""heavy_media_to_note.py — свернуть тяжёлое медиа в служебку рядом с местом.

ПОВОД, ИЗМЕРЕННЫЙ 22.08.2026. Кампания переноса свалила файлы в репы «как есть»,
и деплой встал: `git push` в `edu-base` отклонялся `pre-receive` хуком — `ч1.mp4`
весит **207.75 МБ** при жёстком лимите GitHub **100 МБ**. Скрипт деплоя счёл отказ
сетевым и ретраил пять раз по 549 МБ; отказ был детерминированным и не прошёл бы никогда.

🔴 **Правило владельца по эталонам:** *«эталон надо сохранить однозначно, но их надо
перевести по механизму медиа-файла в служебную заметку»* — **«и», а не «или»**.
Поэтому по умолчанию оригинал **остаётся на диске**, но выносится из-под git:
в репе — служебка, рядом с репой — файл.

ЧТО ДЕЛАЕТ

  1. Находит файлы тяжелее порога (по умолчанию 50 МБ — граница предупреждения GitHub).
  2. Снимает с них паспорт: размер, sha256, тип, длительность (если есть `ffprobe`),
     дата, откуда пришёл.
  3. Пишет `<имя>.md` **на место файла** — со всем, что нужно, чтобы понять и найти.
  4. Переносит оригинал в `~/Documents/_heavy-originals/<репа>/<путь>` — вне git,
     но на диске.

ГРАНИЦА (`71` §7г-бис): содержимое видео и сканов скрипт **не читает**. Он делает
паспорт и переносит; расшифровка звука и распознавание текста — работа лабораторий
`ai-relay` (аудио/видео) и будущего `PDF → md`. Служебка честно говорит, что содержание
не извлечено, а не притворяется выжимкой.

ЗАПУСК
    heavy_media_to_note.py --repo edu-base            что будет сделано
    heavy_media_to_note.py --repo edu-base --apply    сделать
    heavy_media_to_note.py --all --limit-mb 100       по всем репам, только блокирующие
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import shutil
import subprocess
from pathlib import Path

BASE_REPO = Path(__file__).resolve().parent.parent.parent
REPOS = BASE_REPO.parent
VAULT = Path.home() / "Documents" / "_heavy-originals"
SKIP_PARTS = {"_base", ".git", "node_modules", ".venv", "__pycache__"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def probe(p: Path) -> str:
    """Длительность через ffprobe, если он есть. Нет — так и сказать."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(p)],
            capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            sec = float(r.stdout.strip())
            return f"{int(sec // 60)} мин {int(sec % 60)} с"
    except Exception:
        pass
    return "не измерена (нет `ffprobe`)"


KIND = {".mp4": "видео", ".mov": "видео", ".avi": "видео", ".mkv": "видео",
        ".mp3": "аудио", ".wav": "аудио", ".m4a": "аудио",
        ".pdf": "документ (скан или вёрстка)", ".json": "выгрузка данных",
        ".zip": "архив", ".dmg": "дистрибутив"}


def note_text(p: Path, repo: Path, mb: float, digest: str, dest: Path) -> str:
    ext = p.suffix.lower()
    kind = KIND.get(ext, "файл")
    dur = probe(p) if kind in ("видео", "аудио") else "—"
    rel = p.relative_to(repo)
    lab = ("`_base/07-media-to-text-lab/` → для видео и аудио маршрут через `ai-relay`"
           if kind in ("видео", "аудио") else "`_base/07-media-to-text-lab/`")
    return f"""# {p.stem} — служебка вместо файла

> Оригинал вынесен из репы {dt.date.today().isoformat()}: **{mb:.1f} МБ** при жёстком
> лимите GitHub **100 МБ** (предупреждение — с 50 МБ). Файл **не удалён**: он лежит
> на диске вне git. Правило владельца — эталон сохраняется, рядом появляется заметка.

## Паспорт файла

| | |
|---|---|
| было по пути | `{rel}` |
| тип | {kind} (`{ext}`) |
| размер | **{mb:.1f} МБ** |
| длительность | {dur} |
| sha256 | `{digest}` |
| оригинал сейчас | `{dest}` |

## Что внутри

🔴 **Содержание не извлечено.** Этот файл — паспорт и указатель, а не выжимка:
скрипт переносит и описывает, но не читает видео и не распознаёт сканы.

Извлечение — работа лаборатории: {lab}.
До него заметка честно говорит «материал есть, разбора нет» — и это состояние,
а не недоделка.

## Как получить файл обратно

```bash
cp "{dest}" "{repo.name}/{rel}"
```

Проверить, что это он: `shasum -a 256` должен дать `{digest[:16]}…`.

## Почему не в git

GitHub блокирует push файла тяжелее 100 МБ (`GH001`, `pre-receive hook declined`)
и предупреждает с 50 МБ. Git LFS для knowledge-репы — сигнал, что файл вообще не туда
(`_base/00-infrastructure/06-volume-compression.md`).

Замер 22.08.2026: пять ретраев push по 549 МБ ушли впустую, потому что отказ был
**детерминированным**, а скрипт деплоя счёл его сетевым.
"""


def process(repo: Path, limit_mb: float, apply: bool) -> tuple[int, float]:
    n = 0
    freed = 0.0
    for p in sorted(repo.rglob("*")):
        if not p.is_file() or any(x in p.parts for x in SKIP_PARTS):
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        mb = size / 2**20
        if mb < limit_mb:
            continue
        dest = VAULT / repo.name / p.relative_to(repo)
        print(f"  {mb:7.1f} МБ  {p.relative_to(repo)}")
        if not apply:
            n += 1
            freed += mb
            continue
        digest = sha256(p)
        dest.parent.mkdir(parents=True, exist_ok=True)
        note = p.with_suffix(p.suffix + ".md")
        note.write_text(note_text(p, repo, mb, digest, dest), encoding="utf-8")
        shutil.move(str(p), str(dest))
        n += 1
        freed += mb
    return n, freed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit-mb", type=float, default=50.0)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    targets = ([REPOS / a.repo] if a.repo
               else sorted(d for d in REPOS.iterdir() if d.is_dir()) if a.all else [])
    if not targets:
        ap.error("нужен --repo ИМЯ или --all")

    total = 0
    freed = 0.0
    for t in targets:
        if not t.is_dir():
            continue
        print(f"\n── {t.name}")
        n, f = process(t, a.limit_mb, a.apply)
        if not n:
            print("  (нет файлов тяжелее порога)")
        total += n
        freed += f

    print(f"\n  файлов: {total} · объём: {freed:.0f} МБ")
    if not a.apply:
        print("  (сухой прогон; --apply чтобы вынести и написать служебки)")
    else:
        print(f"  оригиналы: {VAULT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
