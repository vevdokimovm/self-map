# Очередь сырых Telegram-выгрузок по всем репам

> **Заказ владельца, дословно:** «короче просто продолжай обрабатывать всю
> очередь экспорта тг. если сделаешь то найди где еще остался экспорт тг
> сырой в других репах и тоже обработай его».

**Снято:** 16.09.2026, командой по `~/repos/*/reports/imports/telegram-*`,
считаются файлы кроме `.md` и скрытых (то есть **ещё не разобранные исходники**).

🔴 **Чего это число не знает:** часть файлов — **эталоны, оставленные
намеренно** (документы, фото людей, материалы экзаменов в `self-map`),
и они будут стоять в счёте всегда. Очередь «к разбору» меньше таблицы.

## Сводка

| файлов | каталог |
|---:|---|
| 3290 | `self-map/reports/imports/telegram-photos` (в работе: `saved` ≈ 845, `sergastokh` ≈ 1 899, эталоны Алекс/Svetik и прочие) |
| 2893 | `christ-walk/reports/imports/telegram-photos` |
| 2855 | `truth-seeking/reports/imports/telegram-photos` |
| 2607 | `it-base/reports/imports/telegram-photos` |
| 1122 | `legal-knowledge-base/reports/imports/telegram-photos` |
| 980 | `politics/reports/imports/telegram-photos` |
| 937 | `edu-base/reports/imports/telegram-photos` |
| 855 | `academic-portfolio/reports/imports/telegram-photos` |
| 535 | `ml-base/reports/imports/telegram-photos` |
| 381 | `health-vault/reports/imports/telegram-photos` |
| 358 | `nutrition/reports/imports/telegram-photos` |
| 316 | `science/reports/imports/telegram-photos` |
| 267 | `edu-base/reports/imports/telegram-files` |
| 263 | `money/reports/imports/telegram-photos` |
| 207 | `career/reports/imports/telegram-photos` |
| 206 | `master-admission/reports/imports/telegram-photos` |
| 173 | `family/reports/imports/telegram-photos` |
| 112 | `self-map/reports/imports/telegram-files` |
| 90 | `portrait-of-taste/reports/imports/telegram-photos` |
| 89 | `science/reports/imports/telegram-files` |
| 83 | `academic-portfolio/reports/imports/telegram-files` |
| 69 | `misc-vault/reports/imports/telegram-photos` |
| 50 | `legal-knowledge-base/reports/imports/telegram-files` |
| 43 | `self-map/reports/imports/telegram-media` |
| 33 | `portrait-of-taste/reports/imports/telegram-media` |
| 32 | `speed-reading/reports/imports/telegram-photos` |
| 32 | `business/reports/imports/telegram-photos` |
| 28 | `it-base/reports/imports/telegram-files` |
| 23 | `master-admission/reports/imports/telegram-files` |
| 19 | `linguistics/reports/imports/telegram-photos` |
| 12 | `sport/reports/imports/telegram-photos` |
| 9 | `career/reports/imports/telegram-files` |
| ≤ 4 каждый | `politics`, `christ-walk`, `security-forces`, `family`, `biology`, `money`, `cybersecurity`, `truth-seeking`, `speed-reading`, `ml-base`, `legal-knowledge-base/telegram-media`, `health-vault`, `edu-base/telegram-media`, `academic-portfolio/telegram-media` |

**Итого ≈ 19 900 файлов**, из них ≈ 19 000 изображений.

## Прогноз

При измеренной скорости **10–20 с календарного времени на кадр**
(`00-FRAME-RATE.tsv`, медиана последних интервалов) очередь целиком —
**≈ 55–110 часов** работы. 🔴 Это оценка по кадрам `saved`, где много
скриншотов с текстом; серии мемов пойдут быстрее, документы — медленнее.

## Вне этой таблицы — закрыто 15.09.2026

- **Выгрузка FINPILOT-Product из корзины macOS** (удалена другой сессией
  13.09.2026) → разобрана в `personal-finance-dss/reports/photo-notes/`:
  22 банковских файла, 125 кадров, текст чата. Исходники удалены
  по указанию владельца; папка в корзине остаётся до её очистки.

## Порядок работы

1. Дочистить `self-map`: `saved` → `sergastokh` → `telegram-files` (112) → `telegram-media` (43).
2. Дальше по убыванию размера, репа за репой; заметки — в `reports/photo-notes/` **каждой своей репы**.
3. Правила — те же, что в `self-map`: секреты и реквизиты не переносятся, стоп-класс 2 записывается, эталоны не удаляются, расходное — удаляется после разбора.
