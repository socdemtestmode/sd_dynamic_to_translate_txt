import pandas as pd
import json
import re
import sys
import os

CSV_URL = os.environ.get("SECRET_CSV_URL")

if not CSV_URL:
    print("❌ Ошибка: CCSV_URL не найден!")
    sys.exit(1)

def set_value_by_path(obj, path, value):
    """Умная функция вставки текста по путям с поддержкой массивов и фиксов движка"""
    parts = path.split('.')
    final_key_str = parts.pop()
    path_to_parent = parts
    current_obj = obj
    i = 0

    while i < len(path_to_parent):
        found_match = False
        for j in range(len(path_to_parent), i, -1):
            potential_key = ".".join(path_to_parent[i:j])
            array_match = re.match(r'(.+)\[(\d+)\]$', potential_key)

            if array_match:
                key_part = array_match.group(1)
                index_part = int(array_match.group(2))
                if isinstance(current_obj, dict) and key_part in current_obj:
                    val = current_obj[key_part]
                    if isinstance(val, dict) and key_part in val and isinstance(val[key_part], list):
                        current_obj = val[key_part][index_part]
                        i = j
                        found_match = True
                        break
                    elif isinstance(val, list):
                        current_obj = val[index_part]
                        i = j
                        found_match = True
                        break

            if isinstance(current_obj, dict) and potential_key in current_obj:
                current_obj = current_obj[potential_key]
                i = j
                found_match = True
                break

        if not found_match:
            raise KeyError(f"Не удалось найти путь: '{path}'")

    final_array_match = re.match(r'(.+)\[(\d+)\]$', final_key_str)
    if final_array_match:
        key_part = final_array_match.group(1)
        index_part = int(final_array_match.group(2))
        if isinstance(current_obj, dict) and key_part in current_obj:
            val = current_obj[key_part]
            if isinstance(val, dict) and key_part in val and isinstance(val[key_part], list):
                val[key_part][index_part] = value
            elif isinstance(val, list):
                val[index_part] = value
            else:
                 current_obj[final_key_str] = value
    elif final_key_str.isdigit() and isinstance(current_obj, list):
        current_obj[int(final_key_str)] = value
    else:
        current_obj[final_key_str] = value

def build():
    print("📥 Скачиваю переводы из Google Sheets...")
    try:
        df = pd.read_csv(CSV_URL)
        print(f"✅ Скачано строк: {len(df)}")
    except Exception as e:
        print(f"❌ Ошибка скачивания CSV: {e}")
        sys.exit(1)
    
    # Читаем оригинальный код игры
    try:
        with open('core_original.js', 'r', encoding='utf-8') as f:
            js_content = f.read()
    except FileNotFoundError:
        print("❌ Файл 'core_original.js' не найден в репозитории!")
        sys.exit(1)

    match = re.search(r'window\.game\s*=\s*\{"compiled"\s*:\s*"(.+?)"\s*\};', js_content, re.DOTALL)
    json_str = match.group(1).replace('\\"', '"').replace('\\\\', '\\')
    game_data = json.loads(json_str)

    successful, skipped, failed = 0, 0, 0

    print("⚙️ Встраиваю переводы в код...")
    for index, row in df.iterrows():
        # Безопасное чтение ячеек (даже если они пустые)
        original_text = str(row.get('Original', '')) if pd.notna(row.get('Original')) else ''
        translation_text = str(row.get('Translation', '')) if pd.notna(row.get('Translation')) else ''
        path = str(row.get('Path', ''))

        if not path: continue

        # Логика для структур (массивов) - если перевод починен через JSON-вставку
        if translation_text.strip().startswith('[') or translation_text.strip().startswith('{'):
            try:
                parsed_struct = json.loads(translation_text)
                set_value_by_path(game_data, path, parsed_struct)
                successful += 1
                continue
            except json.JSONDecodeError:
                pass # Если это просто текст, начинающийся со скобки, идем дальше

        # Исключение для артиклей "the" / "The"
        is_article = (original_text.strip() in["The", "the"]) and (not translation_text.strip())

        if translation_text.strip() or is_article:
            value_to_set = "" if is_article else translation_text
            try:
                set_value_by_path(game_data, path, value_to_set)
                successful += 1
            except Exception as e:
                failed += 1
        else:
            skipped += 1

    print(f"📊 Статистика: Успешно: {successful} | Пропущено (нет перевода): {skipped} | Ошибок путей: {failed}")

    # Упаковываем обратно
    updated_json = json.dumps(game_data, ensure_ascii=False, separators=(',', ':'))
    updated_json = updated_json.replace('\\', '\\\\').replace('"', '\\"')
    updated_js = re.sub(
        r'(window\.game\s*=\s*\{"compiled"\s*:\s*")(.+?)("\s*\};)',
        lambda m: m.group(1) + updated_json + m.group(3),
        js_content,
        flags=re.DOTALL
    )

    with open('core.js', 'w', encoding='utf-8') as f:
        f.write(updated_js)
    print("🚀 Файл 'core.js' успешно создан!")

if __name__ == "__main__":
    build()
