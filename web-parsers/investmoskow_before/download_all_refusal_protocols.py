"""
Парсинг всех протоколов отказа со страниц лотов investmoscow.ru
"""
import csv
import json
import os
import re
import shutil
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

CSV_PATH = "data/investmoscow_completed_2022_2026_geocoded_mapped.csv"
OUTPUT_DIR = "data/protocols/refusal_protocols"
os.makedirs(OUTPUT_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

DOC_URL_TMPL = "https://api.investmoscow.ru/investmoscow/tender/v1/tender/getattachedfilebyid?attachmentId={aid}"

lock = Lock()

# Список лотов с протоколом отказа
refusal_lots = set()
refusal_lock = Lock()

def check_lot(lot_id):
    """Проверяем лот на наличие протокола отказа"""
    url = f"https://investmoscow.ru/tenders/tender/{lot_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return lot_id, False, "no_page"

        text = r.text

        # Ищем все attachmentId с "Протокол" в названии
        protocols = re.findall(r'\},\s*(\d{6,})\s*,\s*"([^"]*Протокол[^"]*)"', text)

        # Ищем протокол отказа
        for aid, name in protocols:
            if "отказ" in name.lower():
                # Скачиваем файл
                doc_url = DOC_URL_TMPL.format(aid=aid)
                r2 = requests.get(doc_url, headers=HEADERS, timeout=15)
                
                if r2.status_code == 200:
                    content_start = r2.content[:8]
                    if content_start[:4] == b'PK\x03\x04':
                        ext = 'docx'
                    elif content_start[:5] == b'%PDF-':
                        ext = 'pdf'
                    else:
                        ext = 'unknown'

                    filename = os.path.join(OUTPUT_DIR, f"{lot_id}_refusal.{ext}")
                    with open(filename, "wb") as f:
                        f.write(r2.content)

                    return lot_id, True, f"saved_{ext}"

        return lot_id, False, "no_refusal"

    except Exception as e:
        return lot_id, False, f"error_{str(e)[:50]}"

def main():
    print("=== ЗАГРУЗКА СПИСКА ЛОТОВ ===")
    
    # Читаем все lot_id из CSV
    lot_ids = []
    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            lot_id = row.get('номер_лота', '').strip()
            if lot_id:
                lot_ids.append(lot_id)

    print(f"Всего лотов: {len(lot_ids)}")

    # Фильтруем те, где уже есть протокол отказа
    existing = set(f.split('_')[0] for f in os.listdir(OUTPUT_DIR) if f.endswith(('.docx', '.pdf')))
    lots_to_check = [lid for lid in lot_ids if lid not in existing]
    print(f"Осталось проверить: {len(lots_to_check)}")

    # Многопоточная проверка
    print("\n=== ПАРСИНГ ===")
    processed = 0
    found_count = 0
    import time
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_lot = {
            executor.submit(check_lot, lot_id): lot_id
            for lot_id in lots_to_check
        }

        for future in as_completed(future_to_lot):
            lot_id, has_refusal, status = future.result()
            processed += 1

            if has_refusal:
                found_count += 1
                with refusal_lock:
                    refusal_lots.add(lot_id)
                print(f"[{processed}/{len(lots_to_check)}] ✅ #{lot_id} — {status}")
            elif status.startswith("error"):
                print(f"[{processed}/{len(lots_to_check)}] ⚠️ #{lot_id} — {status}")
            elif processed % 100 == 0:
                elapsed = time.time() - start_time
                speed = processed / elapsed if elapsed > 0 else 0
                remaining = len(lots_to_check) - processed
                est = remaining / (speed * 60) if speed > 0 else 0
                print(f"[{processed}/{len(lots_to_check)}] Найдено отказов: {found_count} | Скорость: {speed:.1f} лотов/с | ~{est:.0f} мин")

    # Сохраняем список лотов
    with open(os.path.join(OUTPUT_DIR, "refusal_lots.txt"), "w", encoding="utf-8") as f:
        for lot_id in sorted(refusal_lots):
            f.write(f"{lot_id}\n")

    print(f"\n{'='*60}")
    print(f"ГОТОВО")
    print(f"Найдено лотов с протоколом отказа: {found_count}")
    print(f"Файлов в папке: {len(os.listdir(OUTPUT_DIR)) - 1}")  # минус refusal_lots.txt
    print(f"Список: {OUTPUT_DIR}/refusal_lots.txt")

    # Добавляем колонку в CSV
    print("\n=== ОБНОВЛЕНИЕ CSV ===")
    temp_csv = CSV_PATH.replace(".csv", "_with_refusal.csv")
    
    with open(CSV_PATH, "r", encoding="utf-8-sig") as f_in:
        reader = csv.DictReader(f_in)
        fieldnames = reader.fieldnames + ["есть_протокол_отказа"]
        
        with open(temp_csv, "w", encoding="utf-8-sig", newline="") as f_out:
            writer = csv.DictWriter(f_out, fieldnames=fieldnames)
            writer.writeheader()
            
            for row in reader:
                lot_id = row.get('номер_лота', '').strip()
                row["есть_протокол_отказа"] = "Да" if lot_id in refusal_lots else ""
                writer.writerow(row)

    # Заменяем оригинал
    shutil.move(temp_csv, CSV_PATH)
    print(f"CSV обновлён: {CSV_PATH}")

if __name__ == "__main__":
    main()
