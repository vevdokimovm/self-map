#!/usr/bin/env python3
"""asr_timing_log.py — реестр времени распознавания речи: сколько заняло и при чём.

🔴 ЗАКАЗ ВЛАДЕЛЬЦА 15.09.2026: «введи реестр времени обработки видео звука».

ПОЧЕМУ ОТДЕЛЬНО ОТ `measurements.csv`. Тот меряет объём (было МБ → стало МБ,
какая доля текста извлечена). Время распознавания — другая величина: она зависит
от модели, числа потоков и того, что ещё грузило машину в ту минуту. Смешивать
их в одной таблице значит потерять обе.

🔴 ГЛАВНОЕ, ЧЕМУ УЧИТ РЕЕСТР. Замер без зафиксированной конкуренции за процессор
бесполезен: один и тот же `large-v3-turbo` на одном и том же i5 дал от 0.64× до
3.27× длительности — разница в пять раз, и вся она не про модель. Поэтому скрипт
снимает loadavg и число параллельных whisper САМ, а не просит вписать руками.

ЗАПУСК
    asr_timing_log.py --source <файл> --model base --wall 760
    asr_timing_log.py --source <файл> --model base --wall 760 --threads 8
    asr_timing_log.py --import-progress <progress.log> --src-dir <папка> --model X
    asr_timing_log.py --selftest

`--import-progress` разбирает журнал батча вида «964s имя/файла.ogg»: длительность
каждого источника берётся ffprobe из `--src-dir`, коэффициент считается сам.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
import unicodedata
from datetime import date
from pathlib import Path

REGISTRY = Path(__file__).resolve().parent.parent / "asr-timings.csv"
FIELDS = [
    "date", "source", "kind", "duration_s", "model", "threads",
    "wall_s", "ratio", "loadavg", "parallel_asr", "tool", "note",
]
PROGRESS_LINE = re.compile(r"^(\d+)s\s+(.+)$")
AUDIO_EXT = {".mp3", ".m4a", ".ogg", ".wav", ".opus", ".flac", ".aac"}


def probe_duration(path: Path) -> float:
    """Длительность медиафайла в секундах; 0.0, если ffprobe не прочитал."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def parallel_asr() -> int:
    """Сколько процессов whisper-cli крутится прямо сейчас."""
    r = subprocess.run(["pgrep", "-f", "whisper-cli"], capture_output=True, text=True)
    return len([ln for ln in r.stdout.splitlines() if ln.strip()])


def kind_of(path: Path) -> str:
    return "audio" if path.suffix.lower() in AUDIO_EXT else "video"


class TimingRegistry:
    """Реестр замеров времени распознавания."""

    def __init__(self, path: Path = REGISTRY) -> None:
        self.path = path

    def rows(self) -> list[dict]:
        if not self.path.is_file():
            return []
        with self.path.open(encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def append(self, rows: list[dict]) -> int:
        """Дописать замеры, пропустив уже записанные (source + model + wall_s)."""
        seen = {(r["source"], r["model"], r["wall_s"]) for r in self.rows()}
        fresh = [r for r in rows
                 if (r["source"], r["model"], r["wall_s"]) not in seen]
        if not fresh:
            return 0
        is_new = not self.path.is_file()
        with self.path.open("a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            if is_new:
                w.writeheader()
            w.writerows(fresh)
        return len(fresh)

    @staticmethod
    def measure(source: str, duration: float, model: str, threads: int,
                wall: float, tool: str, note: str, kind: str = "",
                when: str = "", live: bool = True) -> dict:
        load = os.getloadavg()[0] if live else ""
        return {
            "date": when or date.today().isoformat(),
            "source": source,
            "kind": kind or kind_of(Path(source)),
            "duration_s": f"{duration:.0f}",
            "model": model,
            "threads": threads,
            "wall_s": f"{wall:.0f}",
            "ratio": f"{wall / duration:.2f}" if duration else "",
            "loadavg": f"{load:.1f}" if live else "",
            "parallel_asr": parallel_asr() if live else "",
            "tool": tool,
            "note": note,
        }


def import_progress(log: Path, src_dir: Path, model: str, threads: int,
                    tool: str, note: str, when: str) -> list[dict]:
    """Разобрать журнал батча «964s путь/файл.ogg» в строки реестра.

    Имена сверяются в NFC: macOS отдаёт пути в NFD, и точное сравнение
    строки с кириллицей иначе не находит существующий файл (PIT — грабли zip).
    """
    by_nfc = {unicodedata.normalize("NFC", str(p.relative_to(src_dir))): p
              for p in src_dir.rglob("*") if p.is_file()}
    rows = []
    for line in log.read_text(encoding="utf-8").splitlines():
        m = PROGRESS_LINE.match(line.strip())
        if not m:
            continue
        wall, rel = int(m.group(1)), unicodedata.normalize("NFC", m.group(2))
        src = by_nfc.get(rel)
        if src is None:
            print(f"   🟡 нет исходника, пропущен: {rel}")
            continue
        rows.append(TimingRegistry.measure(
            source=rel, duration=probe_duration(src), model=model,
            threads=threads, wall=wall, tool=tool, note=note,
            kind=kind_of(src), when=when, live=False))
    return rows


def selftest() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "src"
        src.mkdir()
        wav = src / "тест.wav"
        r = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=10", str(wav)],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert 9.5 < probe_duration(wav) < 10.5
        assert probe_duration(src / "нет.wav") == 0.0

        log = tmp / "progress.log"
        log.write_text("20s тест.wav\nALLDONE\n15s пропал.wav\n", encoding="utf-8")
        rows = import_progress(log, src, "base", 8, "t", "n", "2026-09-15")
        assert len(rows) == 1, rows
        assert rows[0]["ratio"] == "2.00", rows[0]
        assert rows[0]["kind"] == "audio"

        reg = TimingRegistry(tmp / "reg.csv")
        assert reg.append(rows) == 1
        assert reg.append(rows) == 0, "повтор должен отсекаться"
        assert len(reg.rows()) == 1
    print("🟢 selftest: длительность читается, NFC-имена находятся, "
          "коэффициент 20с/10с = 2.00, повторная запись отсекается")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path)
    ap.add_argument("--wall", type=float, help="время обработки, секунд")
    ap.add_argument("--duration", type=float, help="длительность; по умолчанию ffprobe")
    ap.add_argument("--model", default="")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--tool", default="tools/video_to_note.py")
    ap.add_argument("--note", default="")
    ap.add_argument("--date", default="")
    ap.add_argument("--import-progress", type=Path)
    ap.add_argument("--src-dir", type=Path)
    ap.add_argument("--registry", type=Path, default=REGISTRY)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    reg = TimingRegistry(a.registry)
    if a.import_progress:
        if not a.src_dir or not a.src_dir.is_dir():
            sys.exit("🔴 нужен --src-dir с исходниками батча")
        rows = import_progress(a.import_progress, a.src_dir, a.model, a.threads,
                               a.tool, a.note, a.date)
    else:
        if not a.source or a.wall is None:
            ap.error("нужны --source и --wall (или --import-progress)")
        if not a.source.is_file():
            sys.exit(f"🔴 нет файла: {a.source}")
        dur = a.duration if a.duration is not None else probe_duration(a.source)
        if dur <= 0:
            sys.exit(f"🔴 ffprobe не прочитал длительность: {a.source}")
        rows = [TimingRegistry.measure(
            source=a.source.name, duration=dur, model=a.model, threads=a.threads,
            wall=a.wall, tool=a.tool, note=a.note, when=a.date)]

    added = reg.append(rows)
    print(f"🟢 в реестр добавлено строк: {added} (из {len(rows)}) → {reg.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
