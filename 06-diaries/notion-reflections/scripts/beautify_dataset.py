import pandas as pd

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
