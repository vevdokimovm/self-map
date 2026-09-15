#!/usr/bin/env python3
"""
panel_probe.py — Status и Stats панелей Claude Code БЕЗ скриншота.

Найдено эмпирически 25.08.2026: три из четырёх панелей интерфейса (`/status`,
`/usage`, `/config`, `/stats`) НЕ требуют кадра — их данные лежат локально
или доступны штатной командой CLI. Это закрывает половину правила `hypothesis.md`
«панели интерфейса — обязательная часть /tokens»: панель, которую можно снять
командой, снимается командой, а не запросом кадра у владельца.

Что автоматизировано и как проверено:

  Status  — `claude auth status --json`. Сверено 25.08.2026 со скриншотом того же
            дня: поля совпадают (email/orgId/subscriptionType), НО команда читает
            ТЕКУЩЕЕ состояние keychain, а не состояние на момент старта сессии —
            если внутри сессии был `/login`, число разойдётся со скриншотом,
            снятым раньше. Дополняется session_id/effort из окружения процесса.

  Stats   — агрегация ВСЕХ `~/.claude/projects/*/*.jsonl` по `message.usage`.
            Сверено 25.08.2026: скрипт дал Sonnet 65.5% / Opus 34.4% против
            65.3% / 34.6% на панели того же дня — расхождение на десятые доли
            объясняется тем, что скриншот снят раньше, а с тех пор сессия
            продолжалась. Даёт то же самое, что вкладка Stats, но точнее
            (без округления интерфейса) и с историей по каждой модели отдельно.

  Config  — `~/.claude/settings.json` + `~/.claude.json`. ЧАСТИЧНО: часть
            переключателей интерфейса (`Auto-compact`, `Continue automatically
            at usage limit`, `Switch models when a message is flagged`) не были
            найдены дословно ни в одном локальном файле при первой проверке —
            это открытый вопрос, не факт «файла нет».

  Usage   — ✅ АВТОМАТИЗИРОВАНО 25.08.2026. Источник — `GET /api/oauth/usage`
            (найден в бинарнике CLI через `strings`), авторизованный OAuth-
            токеном из macOS keychain. Токен читается узким разрешением
            `Bash(security find-generic-password -s "Claude Code-credentials" -w)`
            в `~/.claude/settings.json` — правило БЕЗ wildcard матчит только
            эту точную команду (подтверждено официальной документацией:
            «a rule with no `*` matches one exact command»), не открывает
            Wi-Fi/другие пароли. Владелец добавил правило вручную (агент не
            может писать себе права — self-modification блокируется отдельно
            от keychain-вопроса, см. `51-autonomous-agent-loop.md`). Ответ
            API сверен с ручным текстовым выводом `/usage` того же момента —
            совпал по всем полям (`five_hour.utilization`, `seven_day.utilization`,
            `resets_at`). Полная история решения — `reports/investigations/
            2026-08-25-usage-api-keychain-decision.md`.

Запуск:
    python3 panel_probe.py            # Status + Stats, человекочитаемо
    python3 panel_probe.py --json     # то же самое, машиночитаемо

Только стандартная библиотека + вызов `claude` через subprocess.
"""
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"

# Прайс-лист $/M токенов — источник 00-infrastructure/49-token-economy-and-prompting.md §1.
# Меняется реже, чем сама сессия; свериться, если сумма выглядит подозрительно.
PRICES = {
    "claude-haiku-4-5": {"in": 1.00, "out": 5.00, "cache_r": 0.10, "cache_w": 1.25},
    "claude-sonnet-5":  {"in": 3.00, "out": 15.00, "cache_r": 0.30, "cache_w": 3.75},
    "claude-opus-5":    {"in": 5.00, "out": 25.00, "cache_r": 0.50, "cache_w": 6.25},
    "claude-opus-4-8":  {"in": 5.00, "out": 25.00, "cache_r": 0.50, "cache_w": 6.25},
    "claude-opus-4-7":  {"in": 5.00, "out": 25.00, "cache_r": 0.50, "cache_w": 6.25},
    "claude-fable-5":   {"in": 10.00, "out": 50.00, "cache_r": 1.00, "cache_w": 12.50},
}


def get_status() -> dict:
    """Эквивалент панели Status — без единого кадра."""
    out = {}
    try:
        r = subprocess.run(
            ["claude", "auth", "status", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            out["auth"] = json.loads(r.stdout)
            out["auth_note"] = (
                "текущее состояние keychain, НЕ обязательно состояние на старте "
                "сессии — если внутри сессии был /login, разойдётся со снятым ранее"
            )
    except Exception as e:
        out["auth_error"] = str(e)

    out["session_id"] = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    out["effort"] = os.environ.get("CLAUDE_EFFORT", "")
    out["cwd"] = os.environ.get("PWD", "")
    out["entrypoint"] = os.environ.get("CLAUDE_CODE_ENTRYPOINT", "")

    claude_json = Path.home() / ".claude.json"
    if claude_json.exists():
        try:
            d = json.loads(claude_json.read_text())
            oauth = d.get("oauthAccount") or {}
            out["oauthAccount"] = {
                "displayName": oauth.get("displayName"),
                "emailAddress": oauth.get("emailAddress"),
                "organizationName": oauth.get("organizationName"),
                "organizationType": oauth.get("organizationType"),
                "billingType": oauth.get("billingType"),
                "hasExtraUsageEnabled": oauth.get("hasExtraUsageEnabled"),
            }
        except Exception as e:
            out["claude_json_error"] = str(e)

    return out


def get_usage() -> dict:
    """Эквивалент панели Usage — реальный лимит/сброс аккаунта, не оценка.

    Требует узкое разрешение в settings.json (см. модульный docstring). Если
    его нет, keychain-чтение упадёт или потребует подтверждения — функция
    сообщает об этом честно, а не подставляет прочерк молча.
    """
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return {"error": "keychain-чтение не удалось (нет разрешения или нет macOS keychain)"}
        token = json.loads(r.stdout).get("claudeAiOauth", {}).get("accessToken", "")
        if not token:
            return {"error": "ключ найден, но accessToken пуст"}
    except Exception as e:
        return {"error": f"не удалось прочитать/распарсить ключ: {e}"}

    try:
        req = subprocess.run(
            [
                "curl", "-s",
                "https://api.anthropic.com/api/oauth/usage",
                "-H", f"Authorization: Bearer {token}",
                "-H", "Content-Type: application/json",
                "-w", "\n%{http_code}",
            ],
            capture_output=True, text=True, timeout=10,
        )
        body, _, code = req.stdout.rpartition("\n")
        if code.strip() != "200":
            return {"error": f"API вернул HTTP {code.strip()}"}
        return json.loads(body)
    except Exception as e:
        return {"error": f"вызов /api/oauth/usage не удался: {e}"}
    finally:
        token = None  # не удерживать токен в памяти дольше необходимого


def get_stats() -> dict:
    """Эквивалент панели Stats — агрегация ВСЕХ логов, не одной сессии."""
    by_model = defaultdict(lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0})
    sessions = 0
    files = list(PROJECTS.glob("*/*.jsonl"))
    for f in files:
        sessions += 1
        try:
            with open(f, errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    msg = d.get("message") or {}
                    usage = msg.get("usage")
                    if not usage:
                        continue
                    model = msg.get("model", "unknown")
                    by_model[model]["input"] += usage.get("input_tokens", 0) or 0
                    by_model[model]["output"] += usage.get("output_tokens", 0) or 0
                    by_model[model]["cache_read"] += usage.get("cache_read_input_tokens", 0) or 0
                    by_model[model]["cache_write"] += usage.get("cache_creation_input_tokens", 0) or 0
        except Exception:
            continue

    grand_total_tokens = sum(sum(v.values()) for v in by_model.values())
    grand_total_cost = 0.0
    per_model_out = {}
    for model, v in by_model.items():
        tok_total = sum(v.values())
        pct = 100 * tok_total / grand_total_tokens if grand_total_tokens else 0
        price = PRICES.get(model)
        cost = None
        if price:
            cost = (
                v["input"] * price["in"]
                + v["output"] * price["out"]
                + v["cache_read"] * price["cache_r"]
                + v["cache_write"] * price["cache_w"]
            ) / 1_000_000
            grand_total_cost += cost
        per_model_out[model] = {
            **v,
            "total_tokens": tok_total,
            "pct_of_all_time": round(pct, 1),
            "estimated_cost_usd": round(cost, 2) if cost is not None else None,
        }

    return {
        "sessions_scanned": sessions,
        "grand_total_tokens": grand_total_tokens,
        "grand_total_estimated_cost_usd": round(grand_total_cost, 2),
        "by_model": per_model_out,
        "note": (
            "estimated_cost_usd считается по прайс-листу 49-token-economy-and-prompting.md §1 "
            "как API-цена — НЕ равно тому, что показывает панель Usage (та считает по подписке "
            "с недельным лимитом, не по API-биллингу; расходятся по методике, не по ошибке)"
        ),
    }


def main() -> int:
    as_json = "--json" in sys.argv
    status = get_status()
    stats = get_stats()
    usage = get_usage()

    if as_json:
        print(json.dumps({"status": status, "stats": stats, "usage": usage}, ensure_ascii=False, indent=2))
        return 0

    print("=== Status (эквивалент /status, без кадра) ===")
    auth = status.get("auth", {})
    print(f"  email:            {auth.get('email', '?')}")
    print(f"  orgName:          {auth.get('orgName', '?')}")
    print(f"  subscriptionType: {auth.get('subscriptionType', '?')}")
    print(f"  session_id:       {status.get('session_id', '?')}")
    print(f"  effort:           {status.get('effort', '?')}")
    print(f"  ⚠ {status.get('auth_note', '')}")

    print("\n=== Stats (эквивалент /stats, все сессии на диске) ===")
    print(f"  логов просканировано: {stats['sessions_scanned']}")
    print(f"  всего токенов:        {stats['grand_total_tokens']:,}")
    print(f"  оценка стоимости API: ${stats['grand_total_estimated_cost_usd']:,.2f}")
    for model, v in sorted(stats["by_model"].items(), key=lambda kv: -kv[1]["total_tokens"]):
        cost = v["estimated_cost_usd"]
        cost_s = f"${cost:,.2f}" if cost is not None else "нет прайса"
        print(f"    {model:20s} {v['pct_of_all_time']:5.1f}%  {v['total_tokens']:>15,} ток.  {cost_s}")
    print(f"\n  {stats['note']}")

    print("\n=== Usage (эквивалент /usage, реальный лимит аккаунта) ===")
    if "error" in usage:
        print(f"  ⚠ {usage['error']}")
    else:
        limits = {l["kind"]: l for l in usage.get("limits", [])}
        sess = limits.get("session", {})
        week = limits.get("weekly_all", {})
        print(f"  session (5h):  {sess.get('percent', '?')}% used, resets {sess.get('resets_at', '?')}")
        print(f"  week (7d, all): {week.get('percent', '?')}% used, resets {week.get('resets_at', '?')}")
        extra = usage.get("extra_usage", {})
        print(f"  extra_usage enabled: {extra.get('is_enabled')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
