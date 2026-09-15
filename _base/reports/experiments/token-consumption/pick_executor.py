#!/usr/bin/env python3
"""pick_executor.py — кому отдать задачу: этой сессии или субагенту на дешёвой модели.

🔴 ЗАКАЗ ВЛАДЕЛЬЦА 15.09.2026: *«на основе агента про machine tokens лаб сделать
скилл который учитывает все это и текущую задачу и сам автоматически выбирает
оптимальную модель и усилие… минимизировать трату токенов и максимизировать
качество»*.

🔴 ГЛАВНОЕ ОГРАНИЧЕНИЕ, ИЗ КОТОРОГО ВСЁ СЛЕДУЕТ. Модель ИДУЩЕЙ сессии сменить
нельзя: `--model` и `--effort` — флаги запуска, `/model` — команда владельца.
Значит «автоматически выбрать модель» существует ровно в одной форме —
**отдать работу субагенту**, которому модель назначается при запуске.
Всё остальное скрипт может только посоветовать.

ПОЧЕМУ ДЕЛЕГИРОВАНИЕ ДЕШЕВЛЕ, ЧЕМ КАЖЕТСЯ. Цена хода ≈ 0.1 × контекст + 5 × выход
(`hypothesis.md`, ошибка предсказания −2% на 700–1000K). Субагент стартует
с ЧИСТЫМ контекстом: на зрелой сессии его ход дешевле не только множителем
модели, но и тем, что он не тащит историю. На контексте 700K это даёт
основную часть выигрыша, а вовсе не переход opus→sonnet.

ЧЕГО НЕ ДЕЛАЕТ. Не решает, какая задача перед вахтой — класс задаёт вызывающий.
Не запускает субагента. Не меняет настройки. Считает и объясняет числами.

ЗАПУСК
    pick_executor.py --class mechanical --context 700000
    pick_executor.py --class judgment --context 120000 --parallel 3
    pick_executor.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Множители стоимости хода по моделям (`hypothesis.md` §F1, OFAT-пары).
MODEL_COST = {"opus": 1.0, "sonnet": 0.4, "haiku": 0.15, "fable": 2.0}
# Усилие: high = thinking в выход, medium — втрое дешевле по медиане 44 замеров
# (opus-5/high 997K против opus-5/medium 323K).
EFFORT_COST = {"high": 1.0, "medium": 0.33, "low": 0.2}

# Класс задачи → чем её можно исполнить без потери качества.
# Список растёт по находкам, а не по догадкам: каждая строка — работа,
# которую система уже отдавала субагенту и результат принимался.
CLASSES = {
    "mechanical": {
        "что это": "листинги, grep, sha256, инвентарь, сбор фактов с диска",
        "модель": "haiku", "усилие": "low", "делегировать": True,
        "почему": "ответ проверяется сверкой с диском, суждение не нужно",
        "агенты": ("repo-inventory", "token-probe", "base-coverage-probe"),
    },
    "search": {
        "что это": "найти файл/упоминание по многим репам, широкий обзор",
        "модель": "sonnet", "усилие": "medium", "делегировать": True,
        "почему": "нужен вывод, а не файловые дампы; результат верифицируем",
        "агенты": ("Explore", "general-purpose"),
    },
    "research": {
        "что это": "многошаговое веб-исследование темы",
        "модель": "opus", "усилие": "high", "делегировать": True,
        "почему": "дорого, но в отдельном контексте: не засоряет сессию",
        "агенты": ("researcher",),
    },
    "judgment": {
        "что это": "решение по каталогу М/С, что поднять в базу, разбор ошибки",
        "модель": "opus", "усилие": "high", "делегировать": False,
        "почему": "🔴 требует контекста вахты; субагент его не имеет",
        "агенты": (),
    },
    "writing": {
        "что это": "стандарт, отчёт, выжимка — текст, который останется в базе",
        "модель": "opus", "усилие": "high", "делегировать": False,
        "почему": "🔴 качество текста и есть результат; экономить здесь нечего",
        "агенты": (),
    },
    "verify": {
        "что это": "независимая проверка утверждения по фактам с диска",
        "модель": "sonnet", "усилие": "high", "делегировать": True,
        "почему": "свежий контекст — условие проверки, а не побочный эффект",
        "агенты": ("expert",),
    },
}

CTX_COEF = 0.1        # цена хода: доля контекста (`hypothesis.md`)
OUT_COEF = 5.0        # цена хода: множитель выхода
TYPICAL_OUT = 1500    # типичный выход хода, усл. ед.
CORES = os.cpu_count() or 8


def loadavg() -> float:
    return os.getloadavg()[0]


def session_context() -> int | None:
    """Максимальный контекст текущей сессии по её логу, если он найден.

    Ищется самый свежий `.jsonl` проекта. Отсутствие — не ошибка: скрипт
    вызывается и до появления лога, тогда контекст задаётся флагом.
    """
    root = Path.home() / ".claude" / "projects"
    if not root.is_dir():
        return None
    logs = sorted(root.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for log in logs[:1]:
        best = 0
        try:
            with log.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"usage"' not in line:
                        continue
                    try:
                        u = json.loads(line).get("message", {}).get("usage", {})
                    except (json.JSONDecodeError, AttributeError):
                        continue
                    total = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                             + u.get("cache_creation_input_tokens", 0))
                    best = max(best, total)
        except OSError:
            return None
        return best or None
    return None


def turn_cost(context: int, model: str, effort: str) -> float:
    """Цена одного хода в условных единицах модели расхода."""
    base = CTX_COEF * context + OUT_COEF * TYPICAL_OUT
    return base * MODEL_COST[model] * EFFORT_COST[effort]


class Decision:
    """Решение об исполнителе с обоснованием числами."""

    def __init__(self, task: str, context: int, parallel: int, load: float) -> None:
        self.task = task
        self.spec = CLASSES[task]
        self.context = context
        self.parallel = parallel
        self.load = load

    @property
    def here(self) -> float:
        """Цена хода, если делать в этой сессии: контекст тащится целиком."""
        return turn_cost(self.context, "opus", "medium")

    @property
    def there(self) -> float:
        """Цена хода субагента: чистый контекст + своя модель."""
        return turn_cost(0, self.spec["модель"], self.spec["усилие"])

    @property
    def saving(self) -> float:
        return (1 - self.there / self.here) * 100 if self.here else 0.0

    def machine_warning(self) -> str | None:
        """Параллельные субагенты — нагрузка на ту же машину (`LOAD-CLASSES.md`)."""
        per_core = self.load / CORES
        if self.parallel > 1 and per_core > 2.0:
            return (f"🔴 loadavg {self.load:.1f} ({per_core:.1f}/ядро) — машина в классе "
                    f"«предел»; {self.parallel} параллельных агентов сделают хуже, "
                    f"чем один последовательный")
        if per_core > 2.5:
            return (f"🟡 loadavg {self.load:.1f} ({per_core:.1f}/ядро) — перегруз; "
                    "ответы будут медленнее, расход это не меняет")
        return None

    def render(self) -> str:
        s = self.spec
        lines = [f"задача: {self.task} — {s['что это']}", ""]
        if s["делегировать"]:
            agents = ", ".join(s["агенты"]) or "general-purpose"
            lines += [
                f"🟢 ОТДАТЬ субагенту: {agents} · модель {s['модель']} · усилие {s['усилие']}",
                f"   почему: {s['почему']}",
                f"   цена хода здесь ≈ {self.here:,.0f} · у агента ≈ {self.there:,.0f}"
                f" → дешевле на {self.saving:.0f}%",
            ]
            if self.context > 300_000:
                lines.append(f"   🔴 контекст {self.context:,} — основной выигрыш не от модели,"
                             " а от чистого контекста агента")
        else:
            lines += [
                f"🔴 ДЕЛАТЬ ЗДЕСЬ, не делегировать. {s['почему']}",
                f"   рекомендуемое усилие: {s['усилие']}",
                f"   цена хода ≈ {self.here:,.0f} усл. ед. при контексте {self.context:,}",
            ]
            if self.context > 600_000:
                lines.append("   🟡 контекст выше 600K: до долгой работы дешевле /handoff,"
                             " чем платить за историю каждым ходом")
        warn = self.machine_warning()
        if warn:
            lines += ["", warn]
        return "\n".join(lines)


def selftest() -> int:
    d = Decision("mechanical", 700_000, 1, 1.0)
    assert d.here > d.there, (d.here, d.there)
    assert d.saving > 90, d.saving
    j = Decision("judgment", 100_000, 1, 1.0)
    assert not j.spec["делегировать"]
    assert "ДЕЛАТЬ ЗДЕСЬ" in j.render()
    # на нулевом контексте делегирование механики всё ещё выгодно — но только моделью
    z = Decision("mechanical", 0, 1, 1.0)
    assert 0 < z.saving < 96, z.saving
    assert z.saving < d.saving, "на большом контексте выигрыш обязан быть больше"
    busy = Decision("search", 500_000, 4, CORES * 2.6)
    assert "🔴" in (busy.machine_warning() or ""), busy.machine_warning()
    assert Decision("search", 100_000, 1, 0.5).machine_warning() is None
    for name in CLASSES:
        Decision(name, 50_000, 1, 1.0).render()
    print("🟢 selftest: делегируемое дешевле, суждение остаётся в сессии, "
          "выигрыш растёт с контекстом, перегруз машины ловится, все классы рендерятся")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--class", dest="task", choices=sorted(CLASSES))
    ap.add_argument("--context", type=int, help="токенов контекста; по умолчанию из лога")
    ap.add_argument("--parallel", type=int, default=1)
    ap.add_argument("--list", action="store_true", help="таблица классов")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if a.list or not a.task:
        print(f"{'класс':12} {'исполнитель':22} {'что это'}")
        for name, s in CLASSES.items():
            who = (f"{s['модель']}/{s['усилие']}" if s["делегировать"] else "ЗДЕСЬ")
            print(f"{name:12} {who:22} {s['что это']}")
        return 0 if a.list else 2

    ctx = a.context if a.context is not None else session_context()
    if ctx is None:
        sys.exit("🔴 контекст не определён по логу — задай --context")
    print(Decision(a.task, ctx, a.parallel, loadavg()).render())
    return 0


if __name__ == "__main__":
    sys.exit(main())
