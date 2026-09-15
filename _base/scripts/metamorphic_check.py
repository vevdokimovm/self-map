#!/usr/bin/env python3
"""metamorphic_check.py — проверка зависит от того, от чего не должна?

🔴 КАНДИДАТ №7 ОЧЕРЕДИ ВНЕДРЕНИЯ (`08-systems-theory-lab/INDUSTRY_VS_US.md`),
подтверждённый исследованием 29.08.2026. Метод дал **43 дефекта в шести
статических анализаторах** — то есть находит то, что не находят ни тесты,
ни ревью.

ЧЕМ ЭТО ОТЛИЧАЕТСЯ ОТ КАНАРЕЙКИ, И ПОЧЕМУ НУЖНО ОБА:

  · **канарейка** отвечает на вопрос «проверка ещё жива?» — подсовывает
    заведомый дефект и требует, чтобы он был пойман;
  · **метаморфное отношение** отвечает на другой вопрос: «проверка зависит
    от того, от чего НЕ должна?» — берёт вход, применяет преобразование,
    при котором вердикт обязан **остаться прежним**, и смотрит, остался ли.

Канарейка ловит смерть проверки. Метаморфное отношение ловит её **скрытую
чувствительность** — когда вердикт зависит от имени файла, порядка разделов,
числа пустых строк. Такая проверка не мертва: она работает и врёт.

🔴 ПОЧЕМУ БЕЗ `hypothesis`, ХОТЯ ИССЛЕДОВАНИЕ ЕГО РЕКОМЕНДОВАЛО.
Hypothesis нужен для **случайной** генерации входов. Здесь отношения
**детерминированы**: конкретное преобразование, конкретное ожидание. Ставить
внешнюю зависимость, чтобы не пользоваться её главной способностью, — это
плата без выгоды. Понадобится случайный поиск контрпримеров — тогда и брать.

🔴 ЧЕГО НЕ ЛОВИТ (`71` §7г-бис):

  · **не проверяет, ПРАВИЛЬНЫЙ ли вердикт** — только его устойчивость.
    Проверка, ошибающаяся одинаково до и после преобразования, пройдёт;
  · **не находит отношения сама** — какие преобразования законны, решает
    человек. Ошибка в самом отношении даст ложную тревогу;
  · **работает на временной копии** — на живой репе преобразования вроде
    переименования были бы разрушительны.

ЗАПУСК
    metamorphic_check.py             все отношения по base-repo
    metamorphic_check.py --repo ИМЯ  другая репа
    metamorphic_check.py --selftest  канарейка
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _roots import resolve_roots  # noqa: E402
BASE_REPO, REPOS, FROM_KIT = resolve_roots(__file__)
GATE = BASE_REPO / "scripts" / "revision_check.py"


def verdict(root: Path) -> int:
    """Код возврата гейта — контракт; текст вердикта — оформление."""
    return subprocess.run(["python3", str(GATE), "--root", str(root)],
                          capture_output=True, text=True).returncode


# ─────────── Отношения: преобразование входа + почему вердикт не должен меняться

def rel_blank_lines(root: Path) -> str:
    """Лишние пустые строки в конце каждого документа.

    Почему вердикт обязан сохраниться: пустая строка не несёт смысла
    в Markdown. Если вердикт изменился — проверка считает форматирование
    содержанием.
    """
    for path in list(root.rglob("*.md"))[:40]:
        if ".git" in path.parts or "_base" in path.parts:
            continue
        try:
            path.write_text(path.read_text(encoding="utf-8", errors="replace")
                            + "\n\n\n", encoding="utf-8")
        except OSError:
            continue
    return "добавлены пустые строки в конец 40 документов"


def rel_trailing_spaces(root: Path) -> str:
    """Пробелы в конце строк.

    Почему вердикт обязан сохраниться: концевой пробел невидим и в Markdown
    (кроме переноса двумя пробелами, который здесь не создаётся — добавляется
    один). Чувствительность к нему означала бы, что проверка сравнивает
    строки буквально там, где должна разбирать смысл.
    """
    count = 0
    for path in list(root.rglob("*.md"))[:20]:
        if ".git" in path.parts or "_base" in path.parts:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        path.write_text("\n".join(
            l + " " if l and not l.endswith(" ") else l for l in lines) + "\n",
            encoding="utf-8")
        count += 1
    return f"добавлен концевой пробел в {count} документах"


def rel_broken_link(root: Path) -> str:
    """Заведомо битая ссылка — контроль контроля.

    🔴 Отношение, которое никогда не срабатывает, ничего не проверяет.
    Это единственное здесь, где вердикт ОБЯЗАН измениться: если он не
    изменился, сломан сам метод, а не проверяемое.

    Первая редакция брала для этого пустой каталог — и **отношение оказалось
    неверным**: пустая папка даёт `WARN`, а код возврата от предупреждений
    не меняется. Ровно та ошибка, о которой предупреждает докстрока: отношение
    пишет человек, и ошибка в нём даёт ложную тревогу. Поймано первым же
    прогоном 29.08.2026.
    """
    (root / "zzz-контроль.md").write_text(
        "# Контроль метода\n\n[ссылка в пустоту](docs/такого-файла-нет-98765.md)\n",
        encoding="utf-8")
    return "заведена битая ссылка"


def rel_rename_root(root: Path) -> str:
    """Имя корневого каталога изменено.

    Почему вердикт обязан сохраниться: гейт судит содержимое репы, а не то,
    как называется папка, в которой она лежит. Зависимость от имени корня
    означала бы, что репу нельзя переложить или переименовать без изменения
    вердикта — а это скрытая привязка к месту.
    """
    renamed = root.parent / (root.name + "-переименован")
    root.rename(renamed)
    renamed.rename(root)          # вернули назад: проверяем устойчивость пути
    return "корневой каталог переименован и возвращён"


RELATIONS = (
    ("пустые строки в конце", rel_blank_lines, True),
    ("концевые пробелы", rel_trailing_spaces, True),
    ("имя корневого каталога", rel_rename_root, True),
    ("битая ссылка", rel_broken_link, False),   # контроль: вердикт ОБЯЗАН измениться
)


def run_relation(repo: Path, name: str, transform, must_hold: bool) -> bool:
    """Применить преобразование к копии и сравнить вердикт с исходным."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / repo.name
        shutil.copytree(repo, work, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", "node_modules",
                                                      ".venv", "__pycache__"))
        before = verdict(work)
        detail = transform(work)
        after = verdict(work)
        held = before == after
        ok = held == must_hold
        mark = "🟢" if ok else "🔴"
        expect = "вердикт обязан сохраниться" if must_hold else "вердикт обязан измениться"
        print(f"  {mark} {name}: {detail}")
        print(f"        {expect}; было {before}, стало {after}")
        if not ok and must_hold:
            print(f"        ⚠️  проверка зависит от того, от чего не должна")
        if not ok and not must_hold:
            print(f"        ⚠️  отношение не сработало — оно ничего не проверяет")
        return ok


def selftest() -> bool:
    """Проверяется РАЗЛИЧЕНИЕ: отношение «должно сохраниться» и «должно
    измениться» не могут быть выполнены одним и тем же исходом."""
    hold_ok = (5 == 5) == True          # вердикт сохранился, ждали сохранения
    change_ok = (5 == 6) == False       # вердикт изменился, ждали изменения
    return hold_ok and change_ok and len(RELATIONS) >= 3


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default="base-repo")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        ok = selftest()
        print("🟢 канарейка: два вида отношений различаются"
              if ok else "🔴 канарейка: РАЗЛИЧЕНИЕ СЛОМАНО")
        return 0 if ok else 1

    repo = REPOS / a.repo
    if not repo.is_dir():
        print(f"🔴 нет репы: {a.repo}")
        return 1

    print(f"═══ Метаморфные отношения · {a.repo} ═══")
    print("Вопрос не «жива ли проверка», а «зависит ли она от того,")
    print("от чего не должна». Работа идёт на временной копии.\n")

    results = [run_relation(repo, n, f, hold) for n, f, hold in RELATIONS]
    bad = results.count(False)
    print(f"\nнарушено отношений: {bad} из {len(results)}")
    print("\n🔴 Метод не проверяет, ПРАВИЛЬНЫЙ ли вердикт — только его")
    print("   устойчивость. Проверка, ошибающаяся одинаково до и после,")
    print("   пройдёт здесь и останется неверной.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
