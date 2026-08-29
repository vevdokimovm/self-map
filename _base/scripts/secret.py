#!/usr/bin/env python3
"""secret.py — единое хранилище секретов системы: связка ключей macOS.

РЕШЕНИЕ ВЛАДЕЛЬЦА, 29.08.2026, вопрос дословно: *«что по итогу какое решение
по секретам, мы так и не решили как в системе их хранить — репа? или что?»*

ОТВЕТ: **связка ключей macOS. НЕ репа, НЕ файл, НЕ база.**

🔴 ПОЧЕМУ НЕ РЕПА — довод не вкусовой, а замеренный на этой системе:

  · У рабочих реп **нет `.git`**, и каждый закрытый батч пакует репу целиком
    в zip (`pack_release.py` → `~/Downloads`). Репа с секретами означает
    секреты в архивах — по одному экземпляру на каждую версию, навсегда,
    потому что архивы **намеренно не удаляются** (решение владельца 22.08.2026:
    пока нет git, архив — не копия, а оригинал).
  · Это не гипотеза. В `mission-control/TASKS.md` висит открытым:
    «🔴 Отозвать токен VK — `.env` в `vk-graph.zip`, 220 символов».
    Механизм уже один раз вынес живой токен наружу ровно так.
  · База раздаётся в 54 репы (`sync_base_local.py`). Всё, что лежит в
    `base-repo`, размножается ×54. Секрет в базе — это 54 копии секрета,
    и отзывать пришлось бы после каждой раздачи.

🔴 ПОЧЕМУ НЕ GPG/SOPS/AGE: `sops`, `age`, `op` на машине **не установлены**
(проверено 29.08.2026 через `command -v`), `gpg` есть — но требует управления
ключом и парольной фразой, то есть **ещё одного секрета, который надо где-то
хранить**. Рекурсия. Связка ключей эту рекурсию обрывает: её ключ — пароль
входа в macOS, он уже существует и уже защищает всё остальное на машине.

🔴 РЕЕСТР — НЕ НОВЫЙ ФАЙЛ, А `.env.example`, КОТОРЫЕ УЖЕ ЕСТЬ.
Это `PIT-097` в чистом виде: **список — намерение, свойство объекта — факт.**
`.env.example` говорит, какие ключи репе НУЖНЫ (намерение, лежит в репе,
коммитится). Связка говорит, у каких ключей ЕСТЬ значение (факт, лежит вне
репы). Третий файл-реестр был бы четвёртым местом для расхождения — а два
существующих источника расходиться не могут по построению.

ЗАПУСК
    secret.py list                  какие ключи нужны системе и что из них есть
    secret.py set VK_TOKEN          завести/обновить (значение вводится вслепую)
    secret.py get VK_TOKEN          прочитать (для подстановки в окружение)
    secret.py env <репа>            собрать `.env` репы из связки
    secret.py run <репа> -- cmd…    выполнить команду с секретами в окружении
    secret.py --selftest            канарейка

🔴 ЗНАЧЕНИЕ НИКОГДА НЕ ПРИНИМАЕТСЯ АРГУМЕНТОМ. Ни `--value`, ни позиционным.
Причина — `32-git-hooks-and-secret-scanning.md`, раздел «Секрет в аргументе
командной строки виден всей машине»: argv виден любому процессу через `ps aux`
и попадает в `~/.zsh_history`. Флага для значения нет **вовсе** — иначе им
воспользуются. `set` отдаёт ввод самой `security`, которая читает с терминала
вслепую и с подтверждением.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

REPOS = Path(__file__).resolve().parent.parent.parent
ACCOUNT = os.environ.get("USER", "vasyaevdokimov")

# Префикс службы в связке. Один на всю систему: ключи в разных репах с одним
# именем (`VK_TOKEN` в `vk-graph` и в `academic-portfolio/…/vk-bot`) — это
# ОДИН секрет одного провайдера, и хранить его дважды значит отзывать дважды
# и однажды забыть про вторую копию.
SERVICE_PREFIX = "repos"

KEY_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")

# Ключи, которые секретами НЕ являются: пути, флаги, публичные идентификаторы.
# Пустое значение в `.env.example` — конвенция «сюда подставляется секрет»
# (см. шапку `personal-finance-dss/.env.example`), но не всякий пустой ключ
# секрет: `VAULT_ROOT=` пуст потому, что путь у каждого свой.
NOT_SECRET = re.compile(
    r"(_ROOT|_DIR|_FILE|_PATH|_REPO|_URL|_HOST|_PORT|_FROM|_USERNAME"
    r"|_ID|_INN|_ADDRESS|_DATE|_ENV|_MODE|_LEVEL)$")


# Положительный признак секрета ПО ИМЕНИ. Нужен там, где судить по пустоте
# значения нельзя: в живом `.env` значения как раз заполнены, и правило
# «пусто = секрет» (верное для `.env.example`) там даёт ровно обратный ответ.
# Найдено 29.08.2026 на канарейке: проверка гигиены молчала на `.env` с живым
# токеном именно потому, что применяла к нему правило для образца.
SECRET_NAME = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|_KEY$|_KEYS$|APIKEY|API_KEY|CREDENTIAL"
    r"|PRIVATE|DSN|SALT|CERT|SIGNATURE)")


def is_secret_name(name: str) -> bool:
    """Секрет ли ключ, судя ТОЛЬКО по имени.

    Грубее, чем `keys_of` (та опирается на конвенцию образца), и применяется
    там, где образца нет. Ошибка в сторону «секрет» дешевле: лишний разговор
    против незамеченного токена.
    """
    return bool(SECRET_NAME.search(name)) and not NOT_SECRET.search(name)


def secret_names_for(env_file: Path) -> set[str] | None:
    """Какие ключи этого `.env` — секреты, по СОСЕДНЕМУ `.env.example`.

    Образец — источник правды: он для того и коммитится. Нет образца — None,
    и звать надо `is_secret_name`.
    """
    example = env_file.parent / ".env.example"
    if not example.is_file():
        return None
    return {n for n, is_secret in keys_of(example) if is_secret}


def env_examples() -> list[Path]:
    """Все `.env.example` системы — они и есть реестр намерений."""
    out = []
    for path in REPOS.rglob(".env.example"):
        parts = path.parts
        if any(p in {"node_modules", ".venv", "venv", "_base", ".git"} for p in parts):
            continue
        out.append(path)
    return sorted(out)


def keys_of(example: Path) -> list[tuple[str, bool]]:
    """(имя, секрет ли) для каждого ключа файла-образца."""
    keys = []
    for line in example.read_text(encoding="utf-8", errors="replace").splitlines():
        m = KEY_RE.match(line.strip())
        if not m:
            continue
        name, value = m.group(1), m.group(2).strip()
        # Секрет = пустое значение И имя не из списка «это не секрет».
        # Непустое значение в образце — заведомо болванка или дефолт, не тайна.
        keys.append((name, value == "" and not NOT_SECRET.search(name)))
    return keys


def service(name: str) -> str:
    return f"{SERVICE_PREFIX}:{name}"


def kc_get(name: str) -> str | None:
    p = subprocess.run(
        ["security", "find-generic-password", "-s", service(name), "-a", ACCOUNT, "-w"],
        capture_output=True, text=True)
    return p.stdout.rstrip("\n") if p.returncode == 0 else None


def kc_has(name: str) -> bool:
    p = subprocess.run(
        ["security", "find-generic-password", "-s", service(name), "-a", ACCOUNT],
        capture_output=True, text=True)
    return p.returncode == 0


def cmd_list(args) -> int:
    rows: dict[str, list[str]] = {}
    for ex in env_examples():
        rel = ex.relative_to(REPOS).as_posix()
        for name, is_secret in keys_of(ex):
            if is_secret:
                rows.setdefault(name, []).append(rel)
    if not rows:
        print("Ни одного секретного ключа в `.env.example` системы не объявлено.")
        return 0
    print(f"Секретных ключей объявлено: {len(rows)}  ·  связка: {SERVICE_PREFIX}:*\n")
    missing = 0
    for name in sorted(rows):
        here = kc_has(name)
        if not here:
            missing += 1
        mark = "🟢 есть  " if here else "⚪️ нет   "
        print(f"  {mark} {name}")
        for rel in rows[name]:
            print(f"            ← {rel}")
    print(f"\nВ связке нет: {missing} из {len(rows)}.")
    if missing:
        print("Завести:  secret.py set <ИМЯ>   (значение вводится вслепую, не аргументом)")
    return 0


def cmd_set(args) -> int:
    if not sys.stdin.isatty():
        print("🔴 `set` требует терминала: значение вводится вслепую самой `security`,")
        print("   чтобы не попасть ни в argv (`ps aux`), ни в историю оболочки.")
        return 1
    name = args.name
    print(f"Секрет `{name}` → связка ключей, служба `{service(name)}`.")
    print("Ввод не отображается, потребуется подтверждение.")
    # `-U` — обновить, если запись уже есть. `-w` БЕЗ значения: `security`
    # спрашивает сама, с терминала, дважды. Значение не проходит ни через
    # argv, ни через stdin этого процесса — то есть его тут негде перехватить.
    p = subprocess.run(["security", "add-generic-password", "-U",
                        "-s", service(name), "-a", ACCOUNT,
                        "-D", "секрет репозиториев", "-w"])
    if p.returncode != 0:
        print("🔴 не записано")
        return 1
    print(f"✓ записано. Проверка: secret.py list")
    return 0


def cmd_get(args) -> int:
    value = kc_get(args.name)
    if value is None:
        print(f"🔴 в связке нет `{args.name}`. Завести: secret.py set {args.name}",
              file=sys.stderr)
        return 1
    # Печатается БЕЗ перевода строки и только в stdout — чтобы подстановка
    # `TOKEN=$(secret.py get X) команда` не тащила лишний символ.
    sys.stdout.write(value)
    return 0


def cmd_env(args) -> int:
    repo = REPOS / args.repo
    example = repo / ".env.example"
    if not example.is_file():
        # `.env.example` может лежать глубже — у подпроектов внутри репы.
        found = [p for p in env_examples() if args.repo in p.parts]
        if len(found) == 1:
            example = found[0]
        else:
            print(f"🔴 `{args.repo}`: `.env.example` не найден"
                  + (f" (кандидатов: {len(found)})" if found else ""))
            return 1
    target = example.parent / ".env"
    lines, missing = [], []
    for name, is_secret in keys_of(example):
        if is_secret:
            value = kc_get(name)
            if value is None:
                missing.append(name)
                value = ""
            lines.append(f"{name}={value}")
    if not lines:
        print(f"{example.relative_to(REPOS)}: секретных ключей нет — `.env` не нужен")
        return 0
    if missing:
        print(f"🔴 в связке нет: {', '.join(missing)}")
        print("   `.env` НЕ записан — половинчатый файл хуже отсутствующего:")
        print("   приложение стартует и падает позже, в непонятном месте.")
        return 1
    if target.exists() and not args.force:
        print(f"🔴 {target.relative_to(REPOS)} уже есть. Перезаписать: --force")
        return 1
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(target, 0o600)
    print(f"✓ {target.relative_to(REPOS)} собран из связки ({len(lines)} ключей, режим 600)")
    print("   🔴 Он в `.gitignore` и исключён из архивов (`pack_release.py`).")
    return 0


def cmd_run(args) -> int:
    """Секреты в окружении дочернего процесса — и нигде больше.

    Это ПРЕДПОЧТИТЕЛЬНЕЕ `env`: файла не возникает вовсе, значит нечему
    попасть в архив, в бэкап Time Machine или в чужие руки при `zip`.
    """
    if not args.cmd:
        print("🔴 нечего запускать: secret.py run <репа> -- команда…")
        return 1
    found = [p for p in env_examples() if args.repo in p.parts]
    if not found:
        print(f"🔴 `{args.repo}`: `.env.example` не найден — какие ключи нужны, неизвестно")
        return 1
    env = dict(os.environ)
    missing = []
    for example in found:
        for name, is_secret in keys_of(example):
            if not is_secret:
                continue
            value = kc_get(name)
            if value is None:
                missing.append(name)
            else:
                env[name] = value
    if missing:
        print(f"🔴 в связке нет: {', '.join(sorted(set(missing)))}")
        return 1
    return subprocess.run(args.cmd, env=env).returncode


def selftest() -> bool:
    """Проверяется РАЗЛИЧЕНИЕ, а не то, что код исполняется.

    Ключевое умение инструмента — отличить секрет от настройки. Ошибка в эту
    сторону дорога обоюдно: принять `VAULT_ROOT` за секрет значит требовать
    от владельца завести в связке путь; пропустить `VK_TOKEN` значит оставить
    его в файле, который уедет в архив.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        ex = Path(tmp) / ".env.example"
        ex.write_text(
            "# комментарий\n"
            "VK_TOKEN=\n"
            "SMTP_PASSWORD=\n"
            "TOKEN_ENCRYPTION_KEY=\n"
            "VAULT_ROOT=\n"
            "PLANNER_REPO=\n"
            "TELEGRAM_BOT_USERNAME=\n"
            "APP_PORT=8000\n"
            "не_ключ = что-то\n",
            encoding="utf-8")
        got = keys_of(ex)
        secrets = {n for n, s in got if s}
        plain = {n for n, s in got if not s}
        ok_secrets = secrets == {"VK_TOKEN", "SMTP_PASSWORD", "TOKEN_ENCRYPTION_KEY"}
        ok_plain = plain == {"VAULT_ROOT", "PLANNER_REPO",
                             "TELEGRAM_BOT_USERNAME", "APP_PORT"}
        # Ключ с непустым значением — заведомо дефолт, не тайна.
        ok_default = ("APP_PORT", False) in got
        return ok_secrets and ok_plain and ok_default


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selftest", action="store_true")
    # 🔴 dest="action", НЕ "cmd": у подкоманды `run` есть свой позиционный
    # аргумент `cmd` (остаток строки), и одинаковый dest молча затирает имя
    # подкоманды её же аргументами — `run` перестаёт опознаваться.
    sub = ap.add_subparsers(dest="action")

    sub.add_parser("list", help="какие ключи нужны системе и что из них в связке")

    s = sub.add_parser("set", help="завести/обновить (значение вводится вслепую)")
    s.add_argument("name")

    g = sub.add_parser("get", help="прочитать значение")
    g.add_argument("name")

    e = sub.add_parser("env", help="собрать `.env` репы из связки")
    e.add_argument("repo")
    e.add_argument("--force", action="store_true", help="перезаписать существующий")

    r = sub.add_parser("run", help="выполнить команду с секретами в окружении")
    r.add_argument("repo")
    r.add_argument("cmd", nargs=argparse.REMAINDER)

    a = ap.parse_args()

    if a.selftest:
        ok = selftest()
        print("🟢 канарейка: секрет отличается от настройки" if ok
              else "🔴 канарейка: РАЗЛИЧЕНИЕ СЛОМАНО")
        return 0 if ok else 1

    handlers = {"list": cmd_list, "set": cmd_set, "get": cmd_get, "env": cmd_env}
    if a.action in handlers:
        return handlers[a.action](a)
    if a.action == "run":
        a.cmd = [c for c in a.cmd if c != "--"]
        return cmd_run(a)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
