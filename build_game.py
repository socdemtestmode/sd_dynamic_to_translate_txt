import pandas as pd
import json
import re
import sys
import os
from datetime import datetime

CSV_URL = os.environ.get("SECRET_CSV_URL")

if not CSV_URL:
    print("❌ Ошибка: SECRET_CSV_URL не найден!")
    sys.exit(1)

def set_value_by_path(obj, path, value):
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
    
    try:
        with open('core_original.js', 'r', encoding='utf-8') as f:
            js_content = f.read()
    except FileNotFoundError:
        print("❌ Файл 'core_original.js' не найден в репозитории!")
        sys.exit(1)

    match = re.search(r'window\.game\s*=\s*\{"compiled"\s*:\s*"(.+?)"\s*\};', js_content, re.DOTALL)
    json_str = match.group(1).replace('\\"', '"').replace('\\\\', '\\')
    game_data = json.loads(json_str)

    # --- ЛОГИКА ПАМЯТИ ПЕРЕВОДОВ ---
    STATE_FILE = 'translation_state.json'
    CHANGELOG_FILE = 'changelog.txt' # Изменен на .txt для надежности отображения

    # Проверяем, первый ли это запуск
    is_first_run = not os.path.exists(STATE_FILE)
    
    if not is_first_run:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            try:
                prev_state = json.load(f)
            except json.JSONDecodeError:
                prev_state = {}
                is_first_run = True
    else:
        prev_state = {}

    current_state = {}
    new_translations = []
    updated_translations =[]
    # ------------------------

    successful, skipped, failed = 0, 0, 0

    print("⚙️ Встраиваю переводы в код...")
    for index, row in df.iterrows():
        trans_id = str(row.get('ID', ''))
        original_text = str(row.get('Original', '')) if pd.notna(row.get('Original')) else ''
        translation_text = str(row.get('Translation', '')) if pd.notna(row.get('Translation')) else ''
        path = str(row.get('Path', ''))

        if not path: continue

        # Логика для структур (JSON)
        if translation_text.strip().startswith('[') or translation_text.strip().startswith('{'):
            try:
                parsed_struct = json.loads(translation_text)
                set_value_by_path(game_data, path, parsed_struct)
                successful += 1
                
                if trans_id:
                    current_state[trans_id] = translation_text
                    if not is_first_run:
                        old_val = prev_state.get(trans_id)
                        if old_val is None:
                            new_translations.append((path, "[Структура JSON]", translation_text))
                        elif old_val != translation_text:
                            updated_translations.append((path, old_val, translation_text))
                continue
            except json.JSONDecodeError:
                pass

        # Логика для обычного текста
        is_article = (original_text.strip() in ["The", "the"]) and (not translation_text.strip())
        
        if translation_text.strip() or is_article:
            value_to_set = "" if is_article else translation_text
            try:
                set_value_by_path(game_data, path, value_to_set)
                successful += 1

                if trans_id:
                    current_state[trans_id] = value_to_set
                    if not is_first_run:
                        old_val = prev_state.get(trans_id)
                        if old_val is None:
                            new_translations.append((path, original_text, value_to_set))
                        elif old_val != value_to_set:
                            updated_translations.append((path, old_val, value_to_set))

            except Exception as e:
                failed += 1
        else:
            skipped += 1

    print(f"📊 Статистика: Успешно: {successful} | Пропущено: {skipped} | Ошибок путей: {failed}")

    # --- ЗАПИСЬ СОСТОЯНИЯ И CHANGELOG ---
    # Всегда сохраняем состояние для следующего раза
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(current_state, f, ensure_ascii=False, indent=2)

    # Записываем чейнджлог (только если были реальные изменения и это не первый запуск)
    if not is_first_run and (new_translations or updated_translations):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(CHANGELOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"\n========================================\n")
            f.write(f"СБОРКА: {timestamp}\n")
            f.write(f"========================================\n\n")
            
            if new_translations:
                f.write("--- 🆕 НОВЫЕ ПЕРЕВОДЫ ---\n\n")
                for p, orig, new_t in new_translations:
                    f.write(f"Путь: {p}\nОригинал: {orig}\nПеревод:  {new_t}\n\n")
            
            if updated_translations:
                f.write("--- 🔄 ОБНОВЛЕННЫЕ ПЕРЕВОДЫ ---\n\n")
                for p, old_t, new_t in updated_translations:
                    f.write(f"Путь: {p}\nБыло:  {old_t}\nСтало: {new_t}\n\n")
                    
        print(f"📝 Обновлен changelog.txt (Новых: {len(new_translations)}, Обновлено: {len(updated_translations)})")
    else:
        if is_first_run:
            print("📝 Первый запуск: создана база переводов. Changelog не заполняется, чтобы избежать спама.")
        else:
            print("📝 Новых изменений для changelog.txt не найдено.")

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
