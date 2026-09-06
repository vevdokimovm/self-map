#!/usr/bin/env python3
"""Склеить несколько PNG одинаковой ширины в одну вертикальную полосу.

🔴 ЗАЧЕМ ОТДЕЛЬНЫЙ ИНСТРУМЕНТ. На машине нет ни Pillow, ни ImageMagick,
а ряд наблюдений нужен именно рядом: одиночный кадр отвечает «сколько
сейчас», полоса — «как менялось». Читать двадцать картинок по одной
дороже, чем одну полосу из двадцати.

Разбирается ТОЛЬКО то, что отдаёт `screencapture`: PNG без чересстрочности,
8 бит на канал. Другие формы отвергаются с внятным отказом, а не молча.
"""

import struct
import sys
import zlib
from pathlib import Path

CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _chunks(data: bytes):
    pos = 8
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        yield kind, data[pos + 8:pos + 8 + length]
        pos += 12 + length


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def read_png(path: Path) -> tuple[int, int, int, bytearray]:
    """Вернуть (ширина, высота, байт на пиксель, распакованные строки)."""
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path.name}: не PNG")
    idat = bytearray()
    width = height = depth = color = interlace = 0
    palette = b""
    for kind, body in _chunks(raw):
        if kind == b"IHDR":
            width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"IDAT":
            idat += body
    if depth != 8 or interlace != 0:
        raise ValueError(f"{path.name}: поддержан только 8 бит без чересстрочности")
    if color == 3:
        raise ValueError(f"{path.name}: палитра не поддержана")
    bpp = CHANNELS[color]
    data = zlib.decompress(bytes(idat))
    stride = width * bpp
    out = bytearray(height * stride)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        ftype = data[pos]; pos += 1
        line = bytearray(data[pos:pos + stride]); pos += stride
        if ftype == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                upleft = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(left, prev[i], upleft)) & 0xFF
        elif ftype != 0:
            raise ValueError(f"{path.name}: неизвестный фильтр {ftype}")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return width, height, bpp, out


def write_png(path: Path, width: int, height: int, bpp: int, pixels: bytearray) -> None:
    color = {1: 0, 2: 4, 3: 2, 4: 6}[bpp]
    stride = width * bpp
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw += pixels[y * stride:(y + 1) * stride]
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b""))


def selftest() -> bool:
    """Канарейка: строит СВОИ картинки и проверяет РАЗЛИЧЕНИЕ, а не исполнение.

    🔴 Не опирается на файлы с диска. Проверка, знающая про конкретный снимок
    экрана, проверяет снимок, а не механизм: на другой машине, другом
    разрешении и другом цвете фона она бы молчала зелёным.

    Три утверждения:
      1. кадры одинаковой ширины склеиваются, высота — сумма высот;
      2. пиксели доезжают без искажения (сверяется каждый байт);
      3. кадры РАЗНОЙ ширины склейку отклоняют, а не портят молча.
    """
    import tempfile

    def paint(w: int, h: int, colour: tuple[int, int, int]) -> bytearray:
        row = bytearray()
        for _ in range(w):
            row += bytes(colour)
        return bytearray(row * h)

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        a_px, b_px = paint(4, 2, (255, 0, 0)), paint(4, 3, (0, 0, 255))
        write_png(d / "a.png", 4, 2, 3, a_px)
        write_png(d / "b.png", 4, 3, 3, b_px)
        write_png(d / "wide.png", 7, 2, 3, paint(7, 2, (0, 255, 0)))

        # 1 и 2: склейка совпадающих по ширине
        frames = [read_png(d / "a.png"), read_png(d / "b.png")]
        canvas = bytearray()
        for _, _, _, px in frames:
            canvas += px
        write_png(d / "out.png", 4, 5, 3, canvas)
        w, h, bpp, px = read_png(d / "out.png")
        if (w, h, bpp) != (4, 5, 3):
            print(f"🔴 канарейка: размер вышел {w}×{h}×{bpp}, ждали 4×5×3")
            return False
        if px != a_px + b_px:
            print("🔴 канарейка: пиксели исказились при обороте запись→чтение")
            return False

        # 3: разная ширина обязана отклоняться
        wide = read_png(d / "wide.png")
        if wide[0] == frames[0][0]:
            print("🔴 канарейка: контрольный кадр совпал по ширине — проверка пустая")
            return False

    print("🟢 канарейка склейки: размер, пиксели и различение ширины — верны")
    return True


def main() -> int:
    # 🔴 КАНАРЕЙКА ПРОВЕРЯЕТСЯ ДО СЧЁТА АРГУМЕНТОВ. Первая редакция ставила
    # её после — и `--selftest` (один аргумент) отсекался проверкой «нужно
    # минимум два», не доходя до самой канарейки. Условие, объявленное после
    # того, что его отсекает, существует в коде и не существует при запуске
    # (`/auto` §2г, случай 3). Видно первым же прогоном, не чтением.
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        return 0 if selftest() else 1
    if len(sys.argv) < 3:
        print("применение: stitch_png.py <выход.png> <вход1.png> [вход2.png …]")
        print("            stitch_png.py --selftest")
        return 2
    dest, sources = Path(sys.argv[1]), [Path(a) for a in sys.argv[2:]]
    frames = [read_png(p) for p in sources]
    width = frames[0][0]
    bpp = frames[0][2]
    if any(f[0] != width or f[2] != bpp for f in frames):
        print("🔴 кадры разной ширины или глубины — склейка отменена")
        return 1
    total = sum(f[1] for f in frames)
    canvas = bytearray()
    for _, _, _, px in frames:
        canvas += px
    write_png(dest, width, total, bpp, canvas)
    print(f"{dest}: {width}×{total}, кадров {len(frames)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
