#!/usr/bin/env python3
"""
prep.py v3 — автоподготовка визуальной сессии. РЕЖИМ A.

Картинки берутся в НАТИВНОМ разрешении, БЕЗ сжатия: vision Opus 4.8 держит
до 2576 px по длинной стороне, а весь корпус нативно меньше. Сжимать не нужно.
Токены = ceil(w/28) * ceil(h/28).

Запуск:
    python3 prep.py <источник> [<от> <до>] [--no-ocr] [--crop x0,y0,x1,y1] [--fit N]

Примеры:
    python3 prep.py priyatnoe 13 89
    python3 prep.py diary 1 162
    python3 prep.py dima2 1 61 --crop 0,0.06,1,1

Источники: priyatnoe · priyatnoe2 · dima1 · dima2 · instagram · vk · diary · pozdrav
Результат: /home/claude/READY/<источник>/p001.png ... + ocr.txt
Печатает ОДНУ строку — контекст не жжёт.

ВАЖНО: читает архивы, приложенные к чату. Файлы в /mnt/project пережаты в 1.8-1.9 раза,
использовать их как источник нельзя (кроме fallback для рукописного дневника).
"""
import os, sys, subprocess, zipfile, io, glob, math, unicodedata
from PIL import Image

UP, PROJ, WORK, READY = '/mnt/user-data/uploads', '/mnt/project', '/home/claude/work', '/home/claude/READY'
TESS = '/home/claude/tessdata'

SOURCES = {
  # crop = доли (x0,y0,x1,y1) от размера страницы; None = страница целиком
  'priyatnoe':  dict(pdfs=['Приятное-1-30.pdf', 'Приятное-31-60.pdf', 'Приятное-61-89.pdf'],
                     crop=(0.335, 0.085, 0.79, 0.955)),   # 2560x1600 -> лента 1165x1392 = 2100 ток
  'priyatnoe2': dict(pdfs=['Приятное 2.pdf'], crop=None),                    # 591x1280
  'dima1':      dict(pdfs=['Дима-ментор ч. 1.pdf'], crop=None),              # 1240x775 = 1260 ток
  'dima2':      dict(pdfs=['Дима-ментор ч.2.pdf'], crop=None),               # 2560x1600 = 5336 ток -> нужен кроп
  'instagram':  dict(pdfs=['first half (1-150).pdf', 'second half (151-309).pdf'], crop=None),  # 1170x2532
  'vk':         dict(pdfs=['VK 1-140.pdf', 'VK 141-280.pdf', 'VK 281-420.pdf', 'VK 421-488.pdf'], crop=None),
  'pozdrav':    dict(pdfs=['поздравление 20 лет.pdf'], crop=None),
  # Рукописный дневник: оригиналы 960x1280 = 1610 ток. Fallback - /mnt/project (924x1316, почти то же).
  'diary':      dict(pdfs=['Дневник материальный155.pdf', 'Дневник материальный56109.pdf',
                           'Дневник материальный110162.pdf'],
                     zips=['Дневник_материальный155.pdf', 'Дневник_материальный56109.pdf',
                           'Дневник_материальный110162.pdf'], crop=None),
}

# Notion-дневник — ТЕКСТ, не картинки. 321 .md-файл. Для текстового чата:
#   python3 prep.py notion   -> печатает список файлов и общий объём
# ВНИМАНИЕ: Объединённый_дневник.csv БИТЫЙ (потерял 150k симв). Читать только .md!

def toks(w, h): return math.ceil(w / 28) * math.ceil(h / 28)
def nfc(x): return unicodedata.normalize('NFC', x)

def unpack():
    """Распаковывает ЛЮБОЙ .zip из uploads + подхватывает PDF, приложенные напрямую."""
    os.makedirs(WORK, exist_ok=True)
    for z in glob.glob(os.path.join(UP, '*.zip')):
        d = os.path.join(WORK, os.path.splitext(os.path.basename(z))[0])
        if not os.path.exists(d):
            subprocess.run(['unzip', '-q', '-o', z, '-x', '__MACOSX/*', '-d', d], capture_output=True)
    for f in glob.glob(os.path.join(UP, '*.pdf')):
        dst = os.path.join(WORK, os.path.basename(f))
        if not os.path.exists(dst):
            subprocess.run(['cp', f, dst], capture_output=True)

def find_pdf(name):
    """macOS хранит имена в NFD, Python-строки в NFC -> сравнивать ТОЛЬКО через нормализацию."""
    target = nfc(name)
    for root, _, files in os.walk(WORK):
        for f in files:
            if nfc(f) == target:
                return os.path.join(root, f)
    return None

def build(src, first, last, crop, fit):
    cfg = SOURCES[src]
    out = os.path.join(READY, src)
    os.makedirs(out, exist_ok=True)
    crop = crop or cfg['crop']

    found = [find_pdf(n) for n in cfg.get('pdfs', [])]
    have_pdfs = any(found)

    idx, pages = 0, []
    if have_pdfs:
        for p in found:
            if not p:
                continue
            info = subprocess.run(['pdfinfo', p], capture_output=True, text=True).stdout
            n = int([l for l in info.splitlines() if l.startswith('Pages')][0].split()[-1])
            for i in range(1, n + 1):
                idx += 1
                if (first and idx < first) or (last and idx > last):
                    continue
                pages.append(('pdf', p, i, idx))
    elif 'zips' in cfg:
        for zn in cfg['zips']:
            zp = os.path.join(PROJ, zn)
            if not os.path.exists(zp) or os.path.getsize(zp) == 0:
                continue
            z = zipfile.ZipFile(zp)
            for i in range(1, len([x for x in z.namelist() if x.endswith('.jpeg')]) + 1):
                idx += 1
                if (first and idx < first) or (last and idx > last):
                    continue
                pages.append(('zip', z, f'{i}.jpeg', idx))

    size = None
    for kind, a, b, num in pages:
        dst = os.path.join(out, f'p{num:03d}.png')
        if os.path.exists(dst):
            size = Image.open(dst).size
            continue
        if kind == 'zip':
            im = Image.open(io.BytesIO(a.read(b)))
        else:
            subprocess.run(['pdfimages', '-png', '-f', str(b), '-l', str(b), a, '/tmp/pg'], capture_output=True)
            g = glob.glob('/tmp/pg-*.png')
            if not g:
                continue
            im = Image.open(max(g, key=os.path.getsize))
            for x in g:
                os.remove(x)
        if crop:
            w, h = im.size
            x0, y0, x1, y1 = crop
            im = im.crop((int(w * x0), int(h * y0), int(w * x1), int(h * y1)))
        if fit and max(im.size) > fit:
            r = fit / max(im.size)
            im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
        im.save(dst)
        size = im.size

    kind = 'ОРИГИНАЛ' if have_pdfs else 'fallback /mnt/project (пережато)'
    n = len(glob.glob(os.path.join(out, 'p*.png')))
    return out, n, size, kind

def ocr(out):
    env = {**os.environ, 'TESSDATA_PREFIX': TESS}
    with open(os.path.join(out, 'ocr.txt'), 'w') as f:
        for p in sorted(glob.glob(os.path.join(out, 'p*.png'))):
            r = subprocess.run(['tesseract', p, '-', '-l', 'rus+eng', '--psm', '6'],
                               capture_output=True, text=True, env=env)
            f.write(f'===== {os.path.basename(p)} =====\n' +
                    '\n'.join(l for l in r.stdout.splitlines() if l.strip()) + '\n\n')

def notion_report():
    fs = sorted(glob.glob(os.path.join(WORK, '**', '*.md'), recursive=True))
    fs = [f for f in fs if os.path.basename(f)[:4].isdigit()]
    tot = sum(os.path.getsize(f) for f in fs)
    print(f'NOTION: {len(fs)} записей | {tot//1024} KB | {os.path.dirname(fs[0]) if fs else "НЕ НАЙДЕНО"}')
    print('⚠️ CSV-версию НЕ использовать — битая (потеряно ~150 000 симв).')

if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    src = args[0]
    if src == 'notion':
        unpack(); notion_report(); sys.exit(0)
    first = int(args[1]) if len(args) > 1 else None
    last = int(args[2]) if len(args) > 2 else None
    crop = fit = None
    for i, a in enumerate(sys.argv):
        if a == '--crop':
            crop = tuple(float(x) for x in sys.argv[i + 1].split(','))
        if a == '--fit':
            fit = int(sys.argv[i + 1])
    unpack()
    out, n, size, kind = build(src, first, last, crop, fit)
    if size is None:
        print(f'❌ ИСТОЧНИК НЕ НАЙДЕН: {src}. Нужные файлы: {SOURCES[src].get("pdfs")}')
        print('   Приложи нужный архив к чату: 1_ПРИЯТНОЕ · 2_ПРИЯТНОЕ2 · 3_ДИМА · 4_INSTAGRAM · 5_ПОЗДРАВЛЕНИЕ · 6_VK · Archive_дневник')
        sys.exit(1)
    if '--no-ocr' not in sys.argv:
        ocr(out)
    print(f'ГОТОВО: {n} стр. | {size[0]}x{size[1]} = {toks(*size)} ток/стр | {kind} | {out}')
