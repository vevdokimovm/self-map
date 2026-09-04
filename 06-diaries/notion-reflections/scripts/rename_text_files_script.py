"""rename_text_files_script.py — переименовать файлы дневника по дате из «Created».

🔴 ТЕЛО ПОД ГВАРДОМ — добавлено 04.09.2026, логика не менялась ни в строке.
До правки весь код лежал на верхнем уровне: **импорт этого файла запускал
работу**. 🔴 Здесь это не теория, а порча данных: скрипт не читает, а
**ПЕРЕИМЕНОВЫВАЕТ** файлы дневника. Попытка посмотреть код через импорт
переставила бы имена (`base-repo/00-infrastructure/102` §3а).

🔴 ВТОРОЕ, ЧТО НАШЛОСЬ ПО ДОРОГЕ: пути относительные (`MD_FOLDER = "md_files"`),
то есть скрипт работает не «со своими данными», а с тем, что лежит
в ТЕКУЩЕМ каталоге. Рядом со скриптом их нет — значит запускался он
из другого места, и из какого, нигде не записано.
"""
import os
import re


def main() -> None:

    # Папка, где находятся файлы .md
    MD_FOLDER = "md_files"

    # Регулярное выражение для поиска даты в формате "Created: Month DD, YYYY"
    created_pattern = re.compile(r"Created: (\w+ \d{1,2}, \d{4})")

    # Словарь для преобразования названий месяцев в числа
    month_map = {
        "January": "01", "February": "02", "March": "03", "April": "04",
        "May": "05", "June": "06", "July": "07", "August": "08",
        "September": "09", "October": "10", "November": "11", "December": "12"
    }

    # Проходим по всем .md файлам
    for md_file in os.listdir(MD_FOLDER):
        if md_file.endswith(".md"):
            md_path = os.path.join(MD_FOLDER, md_file)

            # Читаем первые строки файла
            with open(md_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Ищем дату в формате "Created: October 21, 2022"
            created_date = None
            for line in lines:
                match = created_pattern.search(line)
                if match:
                    created_date = match.group(1)  # Например, "October 21, 2022"
                    break

            # Если нашли "Created", преобразуем дату в формат YYYY-MM-DD
            if created_date:
                month, day, year = created_date.split()
                day = day.rstrip(",")  # Убираем запятую после числа
                new_filename = f"{year}-{month_map[month]}-{day}.md"

            # Если "Created" не найден, пробуем взять первую дату из заголовка
            elif lines and re.match(r"# \d{2}\.\d{2}\.\d{2}", lines[0]):
                parts = lines[0].strip("# ").split(".")
                new_filename = f"20{parts[2]}-{parts[1]}-{parts[0]}.md"  # Формат YYYY-MM-DD

            else:
                print(f"⚠️ Не удалось найти дату в файле {md_file}, пропускаем.")
                continue

            # Переименовываем файл
            new_path = os.path.join(MD_FOLDER, new_filename)
            os.rename(md_path, new_path)
            print(f"✅ {md_file} → {new_filename}")

    print("🎯 Все файлы успешно переименованы!")


if __name__ == "__main__":
    main()
