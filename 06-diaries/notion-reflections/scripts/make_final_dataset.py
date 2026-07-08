import os
import pandas as pd

# Пути к файлам
CSV_FILE = "Дневник_all_cleaned.csv"  # Очищенный CSV с правильными датами
MD_FOLDER = "md_files"  # Папка с текстами дневника
OUTPUT_CSV = "Объединённый_дневник.csv"  # Итоговый файл

# Загружаем CSV
df = pd.read_csv(CSV_FILE)

# Проверяем, есть ли колонка "date"
if "date" not in df.columns:
    raise ValueError("❌ В CSV нет колонки 'date'! Проверь заголовки.")

# Добавляем колонку для текста дневника
df["text"] = ""

# Пробегаем по всем .md файлам
for md_file in os.listdir(MD_FOLDER):
    if md_file.endswith(".md"):
        md_path = os.path.join(MD_FOLDER, md_file)
        
        # Извлекаем дату из названия файла (YYYY-MM-DD.md → YYYY-MM-DD)
        date_str = md_file.replace(".md", "")

        # Читаем содержимое .md
        with open(md_path, "r", encoding="utf-8") as f:
            text = f.read().strip()

        # Записываем текст в соответствующую строку CSV
        if date_str in df["date"].dropna().values:
            df.loc[df["date"] == date_str, "text"] = text

# Сохраняем обновленный CSV
df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")

print(f"✅ Файл '{OUTPUT_CSV}' создан! Теперь всё объединено.")
