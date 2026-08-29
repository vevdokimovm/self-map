#!/usr/bin/env python3
"""tg_import.py — экспорт Telegram в служебные заметки по репам.

🔴 ЗАДАЧА ВЛАДЕЛЬЦА 29.08.2026: *«папка в downloads Telegram Lite — там
экспорт моего основного акка. разбери его по репам. особенно там есть
экспорт чата WAKE UP — её точно материалы все в truth-seeking, а Иисус
Христос в репу christ-walk. остальное сам определи по смыслу»*.

ЗАМЕР ПЕРЕД РАБОТОЙ (29.08.2026): 26 832 файла, 3.5 ГБ, но **весь текст
лежит в одном `result.json`** — папки `chats/chat_NNN/` содержат только
вложения (23 968 из них — `.jpg`, в основном стикеры и мемы).

    чатов в экспорте        : 163
    из них ≥100 сообщений   :  65
    сообщений суммарно      : 53 268

🔴 ЧТО ЭТОТ ИНСТРУМЕНТ ДЕЛАЕТ И ЧЕГО НЕ ДЕЛАЕТ:

  · **не удаляет исходник** — удаление необратимо, а разбор проверяется
    глазами. Чистка — отдельным осознанным действием после проверки;
  · **не тащит вложения** — 24 тысячи картинок это стикеры и пересланные
    мемы; текст ценнее, а вложения умножают вес репы на порядок;
  · **не раскладывает личную переписку по темам.** Диалог с человеком —
    не тематический материал: раскладывать чужие сообщения по предметным
    репам значит терять контекст и разносить приватное. Личные чаты
    сводятся в одно место одним файлом на собеседника;
  · **не решает за владельца, что ценно.** Маршрут по смыслу предлагается,
    но пишется в отчёт, а не применяется молча.

ЗАПУСК
    tg_import.py --list                что в экспорте, по числу сообщений
    tg_import.py --chat "WAKE UP"      один чат в Markdown, на экран
    tg_import.py --plan                куда что пойдёт, без записи
    tg_import.py --apply               записать в репы
    tg_import.py --selftest            канарейка
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402
BASE_REPO, REPOS, FROM_KIT = resolve_roots(__file__)

def _find_export() -> Path:
    """Свежая выгрузка в `~/Downloads/Telegram Lite/`.

    🔴 Путь БОЛЬШЕ НЕ ПРИБИТ. Первая редакция знала одну дату
    (`DataExport_2026-08-29`), и вторая выгрузка — другого аккаунта, того же
    числа — потребовала бы правки кода. Берётся самая свежая папка
    `DataExport_*`, а если её нет — сам каталог выгрузки.
    """
    base = Path.home() / "Downloads" / "Telegram Lite"
    cands = sorted(base.glob("DataExport_*"), key=lambda p: p.name, reverse=True)
    return cands[0] if cands else base


EXPORT = _find_export()
RESULT = EXPORT / "result.json"

# 🔴 Маршрут по СМЫСЛУ. Два первых указаны владельцем прямо, остальные
# выведены из названия чата и предмета репы. Список, а не правило: у чатов
# нет общего проверяемого свойства, по которому репу можно вычислить
# (`PIT-097` — список законен там, где свойства нет, но обязан нести дату).
# Заведён 29.08.2026, пересмотр — при появлении новых чатов.
ROUTE = {
    "WAKE UP. (Rabbit hole)": "truth-seeking",
    "Иисус Христос": "christ-walk",
    "Технологии": "it-base",
    "Computer Science": "it-base",
    "AI": "ml-base",
    "Айтишечка": "it-base",
    "Врываемся в IT": "it-base",
    "Образование": "edu-base",
    "Диплом": "academic-portfolio",
    "Магистратура": "master-admission",
    "НИТУ МИСИС": "master-admission",
    "Вступительные испытания": "master-admission",
    "Юриспруденция": "legal-knowledge-base",
    "Наука": "science",
    "Карьера": "career",
    "Медицина": "health-vault",
    "Кровь": "health-vault",
    "Дневник сна 💤": "health-vault",
    "Кулинария": "nutrition",
    "Инвестиции/Бизнес/Финансы/Стартапы": "money",
    "Бизнес": "business",
    "FINPILOT Product": "finpilot",
    # 🔴 КОЛЛИЗИЯ ИМЁН МЕЖДУ АККАУНТАМИ, разобрана 29.08.2026.
    # У первого аккаунта «Гос. структуры» — про политику и устройство
    # государства. У второго (`@sergastokh`) чат с тем же именем — про
    # задержание, ФЗ «О полиции», права призывника. Проверено чтением.
    #
    # Маршрут по ИМЕНИ различить аккаунты не может. Первая выгрузка уже
    # разобрана и удалена, поэтому маршрут переопределён под содержание
    # второй. Если появится третья с тем же именем и третьей темой —
    # придётся различать по аккаунту, а не по названию чата.
    "Гос. структуры": "legal-knowledge-base",
    "Воспитание характера": "self-map",
    "Семья": "family",
    "Books": "speed-reading",
    "Книги с ботом": "speed-reading",
    "Плейлисты v.5.0": "style",
    "Обществознание": "politics",
    "Заметки": "misc-vault",
    "Приятное что-то 😄": "portrait-of-taste",
    "Плейлисты v.5.0": "portrait-of-taste",
    "Сервол": "business",
    "OplataZabugor.ru - Официальный Аккаунт": "money",
    "7 этаж - лучший этаж": "self-map",
    "Дневник сна 💤": "health-vault",
    # Дозаведено 29.08.2026 — добиваем остаток до нуля без маршрута.
    "516": "self-map",
    "Спорт": "sport",
    "Здоровье": "health-vault",
    "Распознавание аудио": "misc-vault",
    "Academic Weapon": "edu-base",
    "ПЭРЭДАЙС ОРГ": "self-map",
    "Чебурнет": "politics",
    "Экономика/Финансовая грамотность": "money",
    "Протоколы": "health-vault",
    "Право": "legal-knowledge-base",
    "Эволюция": "biology",
    "Ремонт": "misc-vault",
    "Языки": "linguistics",

    # 🔴 ВТОРОЙ АККАУНТ (`@sergastokh`), разобран 29.08.2026. Тема другая:
    # призыв, военкомат, правовая защита, психиатрический учёт. Маршруты
    # заданы по СОДЕРЖАНИЮ, проверенному чтением первых сообщений, а не
    # по названию: «Гос. структуры» у первого аккаунта — про политику,
    # у второго — про задержание, ФЗ «О полиции» и права призывника.
    "Мигалка": "security-forces",
    "Консультант:ка ДСО": "legal-knowledge-base",
    "Азбука призыва: бот юридической поддержки \"Школа призывника\"": "legal-knowledge-base",
    "Первая линия": "legal-knowledge-base",
    "Психиатрия": "health-vault",
    "Сознательный отказ от военной службы в России": "legal-knowledge-base",
    "Идите Лесом Бот": "legal-knowledge-base",
    "ШЕБ [бот]": "security-forces",
    "Путеводитель по военкомату": "legal-knowledge-base",
    "Первый ИИ-Помощник призывника": "legal-knowledge-base",
    "Глаз Бога": "security-forces",
    # Дозаведено по плану второй выгрузки — до нуля без маршрута.
    "Троица GPT": "christ-walk",
    "Помощь в получении израильского гражданства": "nationality",
    "Психологическая поддержка": "self-map",
    "ОВД-Инфо-Бот": "legal-knowledge-base",
    "Вход в Отряд Свободы": "security-forces",
    "Сеть сознательного отказа ДСО": "legal-knowledge-base",
    "Music BOARD | Музыка": "portrait-of-taste",
    "InstVPN": "cybersecurity",
    "FirstLineHelpBot": "legal-knowledge-base",
}

# 🔴 ЛИЧНАЯ ПЕРЕПИСКА — В `self-map`, И ЭТО РЕШЕНИЕ ВЛАДЕЛЬЦА 29.08.2026,
# дословно: «у НАС РЕПЫ ПРИВАТНЫЕ, МЫ ВСЕ РАЗБИРАЕМ АБСОЛЮТНО — для этого
# вся эта система и была создана. Разбирай и заноси их в self-map, потому что
# переписки говорят о том, как я общаюсь, показывают, с кем я общаюсь».
#
# Первая редакция инструмента личные чаты пропускала «чтобы не разносить
# приватное». Довод неверен по построению: **все репы приватны**, и система
# заведена именно для разбора всего. Осторожность вне мандата — это не
# осторожность, а невыполненная работа.
#
# Диалог кладётся в `self-map/06-communication/` — предмет там не собеседник,
# а **способ общения владельца**: с кем, как часто, каким языком.
PERSONAL_DEST = "self-map"
# Учебные семестры — все в одну репу, они одного класса.
SEMESTER_RE = re.compile(r"^(Учеба|Учёба)\s*[\[({]?\s*\d|^\d+\s*семестр")


def account_tag() -> str:
    """Короткая метка аккаунта из выгрузки — для имён файлов.

    🔴 Без неё вторая выгрузка ЗАТИРАЕТ первую: у обеих есть
    `saved_messages` и чаты с одинаковыми именами («Гос. структуры»,
    «Юриспруденция»), и файл лёг бы поверх. Поймано 29.08.2026 планом
    второй выгрузки — до записи, а не после.
    """
    if not RESULT.is_file():
        return ""
    try:
        d = json.loads(RESULT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    pi = d.get("personal_information", {})
    tag = (pi.get("username") or pi.get("first_name") or "").strip()
    return re.sub(r"[^\w-]", "", tag)[:20]


def load_chats() -> list[dict]:
    """Чаты из `result.json`. Текст живёт только здесь, не в папках."""
    if not RESULT.is_file():
        return []
    d = json.loads(RESULT.read_text(encoding="utf-8"))
    return d.get("chats", {}).get("list", [])


def text_of(msg: dict) -> str:
    """Текст сообщения. Telegram хранит его строкой либо списком кусков."""
    t = msg.get("text", "")
    if isinstance(t, str):
        return t
    out = []
    for part in t:
        if isinstance(part, str):
            out.append(part)
        elif isinstance(part, dict):
            out.append(part.get("text", ""))
    return "".join(out)


def route_for(name: str) -> str | None:
    """В какую репу идёт чат. None — личная переписка или неопределённое."""
    if name in ROUTE:
        return ROUTE[name]
    # Имена ботов обрезаются экспортом на разной длине — сверяем по началу.
    for key, dest in ROUTE.items():
        if len(key) > 18 and name.startswith(key[:18]):
            return dest
    if SEMESTER_RE.match(name):
        return "edu-base"
    return None


def is_personal(chat: dict) -> bool:
    """Личный диалог или групповой чат без темы — идёт в `self-map`."""
    return chat.get("type") in ("personal_chat", "saved_messages")


def to_markdown(chat: dict) -> str:
    """Чат в заметку: только текстовые сообщения, с датами и авторами."""
    name = chat.get("name") or "(saved messages)"
    msgs = [m for m in chat.get("messages", []) if text_of(m).strip()]
    if not msgs:
        return ""
    first = msgs[0].get("date", "")[:10]
    last = msgs[-1].get("date", "")[:10]

    head = [
        f"# Telegram · {name}",
        "",
        f"> **Импортировано:** {dt.date.today():%d.%m.%Y} · "
        f"`scripts/tg_import.py` из экспорта `DataExport_2026-08-29`.",
        f"> **Сообщений с текстом:** {len(msgs)} из {len(chat.get('messages', []))} "
        f"· период **{first} — {last}**.",
        ">",
        "> 🔴 Вложения не переносились: в экспорте 24 тысячи изображений, "
        "и это в основном стикеры и пересланные мемы. Здесь только текст.",
        "",
        "---",
        "",
    ]
    body, current_day = [], ""
    for m in msgs:
        day = m.get("date", "")[:10]
        if day != current_day:
            body.append(f"\n## {day}\n")
            current_day = day
        who = m.get("from") or "—"
        txt = text_of(m).strip().replace("\n", "\n  ")
        body.append(f"- **{who}:** {txt}")
    return "\n".join(head) + "\n".join(body) + "\n"


def selftest() -> bool:
    """Проверяется РАЗЛИЧЕНИЕ: маршрут по имени, текст из обеих форм."""
    if route_for("WAKE UP. (Rabbit hole)") != "truth-seeking":
        return False
    if route_for("Иисус Христос") != "christ-walk":
        return False
    if route_for("Учеба {6-ой семестр}") != "edu-base":
        return False
    if route_for("Софья") is not None:      # личный чат маршрута не имеет
        return False
    # Текст приходит и строкой, и списком кусков — обе формы обязаны читаться.
    if text_of({"text": "простой"}) != "простой":
        return False
    return text_of({"text": ["а", {"text": "б"}, "в"]}) == "абв"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--chat")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--min", type=int, default=100,
                    help="порог числа сообщений (по умолчанию 100)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        ok = selftest()
        print("🟢 канарейка: маршруты и обе формы текста читаются"
              if ok else "🔴 канарейка: РАЗЛИЧЕНИЕ СЛОМАНО")
        return 0 if ok else 1

    if not selftest():
        print("🔴 канарейка не прошла — результатам верить нельзя")
        return 1
    chats = load_chats()
    if not chats:
        print(f"🔴 не найден экспорт: {RESULT}")
        return 1

    if a.chat:
        found = [c for c in chats if a.chat.lower() in (c.get("name") or "").lower()]
        if not found:
            print(f"🔴 чат не найден: {a.chat}")
            return 1
        print(to_markdown(found[0])[:3000])
        return 0

    rows = sorted(((c.get("name") or "(saved)", len(c.get("messages", [])), c)
                   for c in chats), key=lambda x: -x[1])
    big = [r for r in rows if r[1] >= a.min]

    if a.list:
        print(f"чатов: {len(rows)} · с ≥{a.min} сообщений: {len(big)}\n")
        for n, cnt, _ in big:
            dest = route_for(n)
            mark = dest or "🔴 маршрута нет"
            print(f"  {cnt:>5}  {n[:44]:<44} → {mark}")
        return 0

    # Личные диалоги идут в self-map: решение владельца 29.08.2026.
    # Разбирается ВСЁ — репы приватные, система для того и заведена.
    routed = [(n, c, ch) for n, c, ch in big
              if route_for(n) or is_personal(ch)]
    unrouted = [(n, c) for n, c, ch in big
                if not route_for(n) and not is_personal(ch)]

    print(f"═══ Разбор экспорта Telegram ═══\n")
    print(f"  чатов всего        : {len(rows)}")
    print(f"  значимых (≥{a.min})    : {len(big)}")
    print(f"  с маршрутом        : {len(routed)}")
    print(f"  🔴 без маршрута     : {len(unrouted)} — личные переписки и прочее\n")

    written = 0
    for name, cnt, chat in routed:
        repo = route_for(name) or PERSONAL_DEST
        target = REPOS / repo
        if not target.is_dir():
            print(f"  🔴 {name[:40]}: нет репы `{repo}`")
            continue
        safe = re.sub(r"[^\w\s.()-]", "", name).strip().replace(" ", "-")[:60]
        tag = account_tag()
        if tag:
            safe = f"{tag}-{safe}"
        sub = "communication" if (not route_for(name) and is_personal(chat)) \
            else "imports"
        out = (target / "reports" / sub / f"telegram-{safe}.md"
               if sub == "imports"
               else target / "06-communication" / f"telegram-{safe}.md")
        md = to_markdown(chat)
        if not md:
            continue
        print(f"  {cnt:>5} → {out.relative_to(REPOS)}")
        if a.apply:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(md, encoding="utf-8")
            written += 1

    if unrouted:
        print(f"\n  🔴 Без маршрута ({len(unrouted)}) — решает владелец:")
        for n, c in unrouted[:12]:
            print(f"      {c:>5}  {n[:50]}")
        if len(unrouted) > 12:
            print(f"      … и ещё {len(unrouted) - 12}")

    if a.apply:
        print(f"\n✅ записано файлов: {written}")
    else:
        print("\nЭто план. Записать: --apply")
    print("\n🔴 Исходник НЕ удаляется этим инструментом: удаление необратимо,")
    print("   а разбор проверяется глазами. Чистка — отдельным действием.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
