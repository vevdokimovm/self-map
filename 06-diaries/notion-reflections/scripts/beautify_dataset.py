"""beautify_dataset.py — почистить выгрузку дневника из Notion.

🔴 ТЕЛО ПОД ГВАРДОМ — добавлено 04.09.2026, логика не менялась ни в строке.
До правки весь код лежал на верхнем уровне: **импорт этого файла запускал
работу**. Для скрипта, читающего CSV, это не теория, а порча данных при попытке
посмотреть код (`base-repo/00-infrastructure/102` §3а).

🔴 ВТОРОЕ, ЧТО НАШЛОСЬ ПО ДОРОГЕ: пути относительные (`CSV_FILE = "Дневник_all.csv"`),
то есть скрипт работает не «со своими данными», а с тем, что лежит
в ТЕКУЩЕМ каталоге. Рядом со скриптом их нет — значит запускался он
из другого места, и из какого, нигде не записано.
"""
import pandas as pd


def main() -> None:

    # Загружаем CSV
    CSV_FILE = "Дневник_all.csv"
    df = pd.read_csv(CSV_FILE)

    # Удаляем ненужные колонки, если они есть
    columns_to_remove = ["Property", "Дневник"]
    df = df.drop(columns=[col for col in columns_to_remove if col in df.columns], errors="ignore")

    # Преобразуем "Created" в формат YYYY-MM-DD
    df["Created"] = pd.to_datetime(df["Created"], format="%B %d, %Y %I:%M %p", errors="coerce").dt.strftime("%Y-%m-%d")

    # Переименовываем колонку "Created" в "date"
    df.rename(columns={"Created": "date"}, inplace=True)

    # Сохраняем изменённый CSV
    OUTPUT_CSV = "Дневник_all_cleaned.csv"
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")

    print(f"✅ Файл '{OUTPUT_CSV}' создан! Теперь даты в правильном формате и колонки удалены.")


if __name__ == "__main__":
    main()
