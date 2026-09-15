#!/usr/bin/env python3
"""video_to_note.py — видео в текстовую заметку: речь с таймкодами + ключевые кадры.

🔴 ЗАКАЗ ВЛАДЕЛЬЦА 14.09.2026: «мб можно также замутить … с распознаванием видео?»
→ «да делай конечно … и протестируй сразу на видео».

ПОЧЕМУ БЕЗ ОТДЕЛЬНОЙ МОДЕЛИ. Видео раскладывается на две вещи, которые уже
работают локально:
    звук   → whisper.cpp (`whisper-cli`) — речь в текст с таймкодами, офлайн;
    кадры  → ffmpeg: кадр при смене сцены (порог `--scene`), не чаще раза в
             `--min-gap` секунд, не больше `--max-frames`; кадры читает вахта
             глазами и дописывает описание в заметку.

🔴 ГРАНИЦА. Скрипт кадров НЕ видит. Он кладёт в заметку таймкод и путь
к каждому кадру с пометкой «описание не заполнено». Заполняет вахта после
просмотра — иначе заметка притворялась бы полной (`71` §7г-бис).

ЗАПУСК
    video_to_note.py <видео> --out <заметка.md>             речь + кадры
    video_to_note.py <видео> --out <заметка.md> --no-frames только речь
    video_to_note.py --selftest

Модель: ~/.cache/whisper/ggml-<--model>.bin (по умолчанию `base`, мультиязычная).
Нет файла — скачивается с huggingface.co/ggerganov/whisper.cpp при `--download`.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

MODEL_DIR = Path.home() / ".cache" / "whisper"
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{}.bin"


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def fmt(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 \
        else f"{sec // 60:02d}:{sec % 60:02d}"


class VideoNote:
    """Сборка заметки по одному видео."""

    def __init__(self, video: Path, model: str, lang: str) -> None:
        self.video = video
        self.model = model
        self.lang = lang
        self.work = Path(tempfile.mkdtemp(prefix="video_to_note_"))

    def duration(self) -> float:
        r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(self.video)])
        return float(r.stdout.strip() or 0)

    def model_path(self, download: bool) -> Path:
        path = MODEL_DIR / f"ggml-{self.model}.bin"
        if path.is_file():
            return path
        if not download:
            sys.exit(f"🔴 нет модели {path}. Запусти с --download "
                     f"(~{ {'base': 142, 'small': 466, 'medium': 1500}.get(self.model, '?') } МБ)")
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        print(f"   скачиваю модель {self.model} …", flush=True)
        urllib.request.urlretrieve(MODEL_URL.format(self.model), path)
        return path

    def transcribe(self, model_path: Path) -> list[tuple[float, float, str]]:
        wav = self.work / "audio.wav"
        r = run(["ffmpeg", "-y", "-v", "error", "-i", str(self.video),
                 "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)])
        if r.returncode != 0 or not wav.is_file():
            print(f"   🟡 звуковой дорожки нет или не извлеклась: {r.stderr[-200:]}")
            return []
        base = self.work / "speech"
        cli = shutil.which("whisper-cli") or shutil.which("whisper-cpp")
        if not cli:
            sys.exit("🔴 нет whisper-cli: brew install whisper-cpp")
        r = run([cli, "-m", str(model_path), "-l", self.lang, "-f", str(wav),
                 "-oj", "-of", str(base), "-np"])
        js = base.with_suffix(".json")
        if r.returncode != 0 or not js.is_file():
            sys.exit(f"🔴 whisper-cli упал: {r.stderr[-400:]}")
        data = json.loads(js.read_text(encoding="utf-8", errors="replace"))
        segs = []
        for s in data.get("transcription", []):
            off = s.get("offsets", {})
            text = s.get("text", "").strip()
            if text:
                segs.append((off.get("from", 0) / 1000, off.get("to", 0) / 1000, text))
        return segs

    def frames(self, out_dir: Path, scene: float, min_gap: float,
               max_frames: int, every: float = 60.0) -> list[tuple[float, Path]]:
        out_dir.mkdir(parents=True, exist_ok=True)
        r = run(["ffmpeg", "-v", "info", "-i", str(self.video), "-vf",
                 f"select='gt(scene,{scene})',showinfo", "-vsync", "vfr",
                 "-f", "null", "-"])
        times = [float(t) for t in re.findall(r"pts_time:([\d.]+)", r.stderr)]
        picked: list[float] = [0.0]
        for t in times:
            if t - picked[-1] >= min_gap:
                picked.append(t)
        # 14.09.2026, первый прогон: 11 мин видео с неподвижной камерой дали
        # 2 кадра — смены сцены нет, а действие есть. Паузы длиннее `every`
        # досеваются кадрами через равный шаг.
        dur = self.duration()
        filled: list[float] = []
        for a, b in zip(picked, picked[1:] + [dur]):
            filled.append(a)
            t = a + every
            while b - t >= min_gap:
                filled.append(t)
                t += every
        picked = filled
        if len(picked) > max_frames:
            step = len(picked) / max_frames
            picked = [picked[int(i * step)] for i in range(max_frames)]
        result = []
        for i, t in enumerate(picked, 1):
            jpg = out_dir / f"frame-{i:03d}-{fmt(t).replace(':', '-')}.jpg"
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(self.video),
                 "-frames:v", "1", "-vf", "scale=768:-2", "-q:v", "4", str(jpg)])
            if jpg.is_file():
                result.append((t, jpg))
        return result


def log_timing(video: Path, dur: float, model: str, wall: float, segments: int) -> None:
    """Замер распознавания — в реестр `asr-timings.csv` сразу, без участия вахты.

    Реестр заведён 15.09.2026 и пополнялся руками; замер, который надо не забыть
    записать, записывают через раз. Сбой записи прогон не роняет: заметка
    ценнее строки в реестре.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from asr_timing_log import TimingRegistry
        row = TimingRegistry.measure(
            source=video.name, duration=dur, model=model, threads=4, wall=wall,
            tool="tools/video_to_note.py", note=f"сегментов {segments}")
        TimingRegistry().append([row])
        print(f"   замер → asr-timings.csv: {row['ratio']}× длительности, "
              f"loadavg {row['loadavg']}, параллельных whisper {row['parallel_asr']}")
    except Exception as exc:  # noqa: BLE001 — реестр не должен ронять распознавание
        print(f"   🟡 замер не записан: {exc}")


def render(video: Path, dur: float, model: str, segs, frames, secs: float) -> str:
    words = sum(len(s[2].split()) for s in segs)
    lines = [
        f"# {video.stem} — текст видео",
        "",
        "## Паспорт извлечения",
        "",
        "| | |",
        "|---|---|",
        f"| источник | `{video}` |",
        f"| длительность | {fmt(dur)} |",
        f"| речь | whisper.cpp, модель `{model}` · сегментов {len(segs)} · слов {words} |",
        f"| кадры | {len(frames)} (смена сцены + не реже раза в минуту) |",
        f"| время обработки | {secs:.0f} с |",
        "| 🔴 описание кадров | **не заполнено** — заполняет вахта после просмотра |",
        "",
        "## Ключевые кадры",
        "",
    ]
    if frames:
        lines += ["| время | кадр | что на экране |", "|---|---|---|"]
        lines += [f"| {fmt(t)} | `{p.name}` | _не заполнено_ |" for t, p in frames]
    else:
        lines.append("_кадры не извлекались_")
    lines += ["", "## Речь с таймкодами", ""]
    if segs:
        lines += [f"**{fmt(a)}** {t}  " for a, _, t in segs]
    else:
        lines.append("_речи не распознано_")
    return "\n".join(lines) + "\n"


def selftest() -> int:
    for tool in ("ffmpeg", "ffprobe"):
        assert shutil.which(tool), f"нет {tool}"
    assert fmt(75) == "01:15" and fmt(3725) == "01:02:05"
    with tempfile.TemporaryDirectory() as tmp:
        v = Path(tmp) / "t.mp4"
        r = run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                 "color=c=red:s=320x240:d=2", "-f", "lavfi", "-i",
                 "color=c=blue:s=320x240:d=2", "-filter_complex",
                 "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", str(v)])
        assert r.returncode == 0, r.stderr
        vn = VideoNote(v, "base", "ru")
        assert 3.5 < vn.duration() < 4.5
        fr = vn.frames(Path(tmp) / "fr", 0.3, 1.0, 10)
        assert len(fr) == 2 and fr[1][0] > 1.5, fr
        dense = vn.frames(Path(tmp) / "fr2", 0.99, 0.5, 10, every=1.0)
        assert len(dense) >= 3, dense
        md = render(v, vn.duration(), "base", [], fr, 1)
        assert "не заполнено" in md and "02" in md
    print("🟢 selftest: ffmpeg есть, смена сцены красный→синий найдена (2 кадра), досев паузы работает, заметка честно пустая")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", nargs="?", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--model", default="base")
    ap.add_argument("--lang", default="ru")
    ap.add_argument("--scene", type=float, default=0.3)
    ap.add_argument("--min-gap", type=float, default=10.0)
    ap.add_argument("--max-frames", type=int, default=30)
    ap.add_argument("--every", type=float, default=60.0)
    ap.add_argument("--frames-dir", type=Path)
    ap.add_argument("--no-frames", action="store_true")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.video or not a.out:
        ap.error("нужны видео и --out")
    if not a.video.is_file():
        sys.exit(f"🔴 нет файла: {a.video}")
    start = time.time()
    vn = VideoNote(a.video, a.model, a.lang)
    dur = vn.duration()
    if dur <= 0:
        sys.exit(f"🔴 ffprobe не прочитал длительность: {a.video}")
    print(f"── {a.video.name}: {fmt(dur)}", flush=True)
    asr_start = time.time()
    segs = vn.transcribe(vn.model_path(a.download))
    asr_wall = time.time() - asr_start
    print(f"   речь: {len(segs)} сегментов за {asr_wall:.0f} с", flush=True)
    log_timing(a.video, dur, a.model, asr_wall, len(segs))
    frames = []
    if not a.no_frames:
        fdir = a.frames_dir or a.out.with_suffix(".frames")
        frames = vn.frames(fdir, a.scene, a.min_gap, a.max_frames, a.every)
        print(f"   кадры: {len(frames)} → {fdir}", flush=True)
    a.out.write_text(render(a.video, dur, a.model, segs, frames, time.time() - start),
                     encoding="utf-8")
    shutil.rmtree(vn.work, ignore_errors=True)
    print(f"🟢 заметка: {a.out} · {time.time() - start:.0f} с")
    return 0


if __name__ == "__main__":
    sys.exit(main())
