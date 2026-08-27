#!/usr/bin/env python3
"""secrets_scan.py — поиск секретов в репах системы.

ПРАВИЛО — `00-infrastructure/85-secrets-and-recovery-codes.md`. Здесь — его исполнитель.

🔴 ПОЧЕМУ ПРОВЕРКА, А НЕ ДИСЦИПЛИНА. Секрет в репе нельзя «убрать потом»: из git он
не удаляется, а **отзывается у провайдера**. Значит ловить надо до коммита, машиной.
Дважды не поймали: 12.07.2026 живые VK- и Telegram-токены лежали в закоммиченном коде
`academic-portfolio` (`PIT-012`); 22.08.2026 `.env` с токеном `vk1.a…` уехал внутрь
`it-base` при переносе — от коммита спасло **только** отсутствие у неё локального `.git`
(`PIT-123`).

ЧТО ИЩЕТ — по СОДЕРЖИМОМУ, а не по имени файла. Замер 22.08.2026: из пяти `.env`,
снятых кампанией переноса, секрет был в **трёх** (один VK-токен в трёх копиях), а два
оказались dev-конфигами (`sqlite:///./finpilot.db` — путь без пароля). Фильтр по имени
ошибся бы в обе стороны, поэтому здесь сигнатуры значений.

🔴 ГРАНИЦА (`71` §7г-бис): сигнатуры ловят **известные форматы**. Пароль вида
`hunter2` в поле `PASSWORD=` поймается по имени переменной, а тот же пароль в прозе —
нет. Отсутствие находок означает «известных форматов не найдено», а не «секретов нет».

ЗАПУСК:
    secrets_scan.py                 все репы системы
    secrets_scan.py --repo ИМЯ      одна репа
    secrets_scan.py --path PATH     произвольный каталог
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

BASE_REPO = Path(__file__).resolve().parent.parent
REPOS = BASE_REPO.parent
BASE = Path.home() / "Documents" / "base-repo"

# Сигнатуры значений. Ключ — что это, значение — как выглядит.
SIGNATURES: dict[str, re.Pattern] = {
    "VK access token": re.compile(r"\bvk1\.a\.[A-Za-z0-9_-]{50,}"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "Anthropic key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    "OpenAI key": re.compile(r"\bsk-[A-Za-z0-9]{40,}"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "Telegram bot token": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "приватный ключ": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
    "пароль в строке подключения": re.compile(
        r"\b(?:postgres|postgresql|mysql|mongodb|redis|amqp)://[^\s:@/]+:[^\s@/]{3,}@"),
    "пароль в переменной": re.compile(
        r"^[A-Z_]*(?:PASSWORD|PASSWD|SECRET|API_KEY|ACCESS_KEY)[A-Z_]*\s*=\s*['\"]?(?!\s*$)"
        r"(?!<|\{\{|\$|your|xxx|placeholder|changeme|example)[^\s'\"]{8,}", re.M | re.I),
}

# Каталоги, где находка НЕ является дефектом.
SKIP_PARTS = {".git", "node_modules", ".venv", "venv", "__pycache__", "_base"}

# Файлы-шаблоны: плейсхолдеры там штатны (`85` §3).
TEMPLATE_SUFFIX = (".example", ".sample", ".template", ".dist")

TEXT_EXT = {".env", ".envrc", ".py", ".sh", ".js", ".ts", ".json", ".yml", ".yaml",
            ".toml", ".cfg", ".ini", ".md", ".txt", ".conf", ".pem", ".key", ""}


MAX_BYTES = 2_000_000  # переопределяется --max-mb (PIT-124: экспорты чатов легко больше)


def scannable(p: Path) -> bool:
    if any(part in SKIP_PARTS for part in p.parts):
        return False
    if p.name.endswith(TEMPLATE_SUFFIX):
        return False
    if p.suffix.lower() not in TEXT_EXT:
        return False
    try:
        return p.stat().st_size <= MAX_BYTES
    except OSError:
        return False


def scan_file(p: Path) -> list[tuple[str, int]]:
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    hits = []
    for name, rx in SIGNATURES.items():
        m = rx.search(text)
        if m:
            line = text[: m.start()].count("\n") + 1
            hits.append((name, line))
    return hits


def selftest() -> bool:
    """Канарейка (`71` §7в): проверка обязана ловить подсаженный образец.

    Образцы собираются из кусков, иначе сканер найдёт собственный исходник —
    та же анти-самореференция, что у канарейки CJK в `revision_check.py`.
    """
    sample = "VK_ACCESS_TOKEN=" + "vk1" + ".a." + "B" * 60
    clean = "DATABASE_URL=sqlite:///./app.db\nDEBUG=true\n"
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "bad.env").write_text(sample, encoding="utf-8")
        (d / "ok.env").write_text(clean, encoding="utf-8")
        (d / "tpl.env.example").write_text(sample, encoding="utf-8")
        return (bool(scan_file(d / "bad.env"))
                and not scan_file(d / "ok.env")
                and not scannable(d / "tpl.env.example"))


def main() -> int:
    global MAX_BYTES
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--path")
    ap.add_argument("--max-mb", type=float, default=2.0,
                     help="потолок размера сканируемого файла в МБ (по умолчанию 2; "
                          "PIT-124 — экспорты чатов вроде conversations.json легко больше)")
    a = ap.parse_args()
    MAX_BYTES = int(a.max_mb * 1_000_000)

    if not selftest():
        print("🔴 КАНАРЕЙКА НЕ ПРОШЛА — сканер сломан, его молчание ничего не значит")
        return 2
    print("  · канарейка: ловит подсаженный токен, молчит на dev-конфиге и шаблоне\n")

    if a.path:
        roots = [Path(a.path).expanduser()]
    elif a.repo:
        roots = [REPOS / a.repo]
    else:
        roots = [d for d in sorted(REPOS.iterdir()) if d.is_dir()] + [BASE]

    total = files = 0
    for root in roots:
        if not root.exists():
            continue
        found: list[str] = []
        for p in root.rglob("*"):
            if not p.is_file() or not scannable(p):
                continue
            files += 1
            for name, line in scan_file(p):
                found.append(f"      🔴 {name}  {p.relative_to(root)}:{line}")
        if found:
            print(f"  {root.name}")
            for f in found[:10]:
                print(f)
            if len(found) > 10:
                print(f"      … и ещё {len(found) - 10}")
            total += len(found)

    print(f"\n  просмотрено файлов: {files}")
    print(f"  находок: {total}")
    if not total:
        print("\n  ИТОГ: известных форматов секретов не найдено.")
        print("  🔴 Это НЕ значит «секретов нет» — сигнатуры ловят известное (`85` §3).")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
