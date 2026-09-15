#!/usr/bin/env python3
"""gen_image_local.py — картинка локально, без сети и без кредитов: stable-diffusion.cpp + SD-Turbo.

🔴 ЗАКАЗ ВЛАДЕЛЬЦА 14.09.2026: «так может что то для изображения скачать через brew???
или с гита? по любому должно быть». Ресерч сказал «хорошего локального пути нет»;
замер 15.09.2026 на этом маке показал, что рабочий путь есть — медленный, но годный.

ЗАМЕР 15.09.2026 (i5-8259U, 8 ГБ, CPU, 512×512, 1 шаг, seed 42):
    без TAESD   244 с  (выборка 35 с, VAE-декодер 199 с)
    с TAESD     133 с  (выборка 77 с, декодер 26 с) — качество на глаз то же
    Metal на Iris Plus 655 — 🔴 GPU Timeout на декодере, поэтому сборка ТОЛЬКО CPU

УСТАНОВКА (однократно, ~2 ГБ):
    git clone --recursive --depth 1 https://github.com/leejet/stable-diffusion.cpp ~/Developer/stable-diffusion.cpp
    cmake -B build-cpu -DCMAKE_BUILD_TYPE=Release -DGGML_METAL=OFF && cmake --build build-cpu -j4 --target sd-cli
    ~/Developer/sd-models/sd_turbo-f16-q8_0.gguf   ← huggingface.co/Green-Sky/SD-Turbo-GGUF
    ~/Developer/sd-models/taesd.safetensors         ← huggingface.co/madebyollin/taesd

ЗАПУСК
    gen_image_local.py "prompt" --out x.png [--size 512] [--seed 42] [--steps 1]
    gen_image_local.py --selftest     # проверка, что бинарник и модели на месте
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
SD_CLI = HOME / "Developer" / "stable-diffusion.cpp" / "build-cpu" / "bin" / "sd-cli"
MODEL = HOME / "Developer" / "sd-models" / "sd_turbo-f16-q8_0.gguf"
TAESD = HOME / "Developer" / "sd-models" / "taesd.safetensors"


def check() -> list[str]:
    return [f"нет {p}" for p in (SD_CLI, MODEL, TAESD) if not p.is_file()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompt", nargs="?")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--steps", type=int, default=1)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    missing = check()
    if a.selftest:
        if missing:
            print("🔴 " + "; ".join(missing))
            return 1
        print("🟢 selftest: sd-cli, SD-Turbo и TAESD на месте")
        return 0
    if missing:
        sys.exit("🔴 " + "; ".join(missing) + " — см. УСТАНОВКА в шапке")
    if not a.prompt or not a.out:
        ap.error("нужны prompt и --out")
    start = time.time()
    r = subprocess.run([str(SD_CLI), "-m", str(MODEL), "--taesd", str(TAESD),
                        "-p", a.prompt, "--steps", str(a.steps), "--cfg-scale", "1",
                        "-W", str(a.size), "-H", str(a.size), "-t", "4",
                        "--seed", str(a.seed), "-o", str(a.out)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not a.out.is_file():
        sys.exit(f"🔴 sd-cli упал: {r.stderr[-500:]}")
    print(f"🟢 {a.out} · {time.time() - start:.0f} с — посмотреть глазами до отдачи")
    return 0


if __name__ == "__main__":
    sys.exit(main())
