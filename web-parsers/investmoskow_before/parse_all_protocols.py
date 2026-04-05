"""
Восстановление кэша из уже скачанных .docx файлов + продолжение парсинга
"""
import os
import re
import json
import time
import requests
import pandas as pd
from docx import Document
import io

PROTOCOLS_DIR = "data/protocols"
CACHE_FILE = os.path.join(PROTOCOLS_DIR, "protocol_cache.json")
OUTPUT_CSV = os.path.join(PROTOCOLS_DIR, "participants_data.csv")

LOT_URL_TMPL = "https://investmoscow.ru/tenders/tender/{lot_id}"
DOC_URL_TMPL = "https://api.investmoscow.ru/investmoscow/tender/v1/tender/getattachedfilebyid?attachmentId={aid}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def parse_protocol_docx(filepath):
    """Парсим .docx протокол аукциона"""
    try:
        doc = Document(filepath)
    except Exception as e:
        return {"error": f"Не удалось открыть docx: {e}"}
    
    result = {
        "participants_count": 0,
        "winner": "",
        "winner_price": "",
        "winner_price_num": None,
        "second_place": "",
        "second_price": "",
        "second_price_num": None,
        "start_price": "",
        "auction_date": "",
        "auction_duration": "",
    }
    
    all_text = "\n".join(p.text for p in doc.paragraphs)
    
    # Начальная цена
    m = re.search(r'Начальная цена.*?:\s*([\d\s,]+)', all_text)
    if m:
        result["start_price"] = m.group(1).strip()
    
    # Дата аукциона
    m_start = re.search(r'начала.*?(\d{2}\.\d{2}\.\d{4}\s+в\s+\d{2}:\d{2})', all_text)
    m_end = re.search(r'окончания.*?(\d{2}\.\d{2}\.\d{4}\s+в\s+\d{2}:\d{2})', all_text)
    if m_start and m_end:
        result["auction_duration"] = f"{m_start.group(1)} — {m_end.group(1)}"
    
    # Победитель
    m = re.search(r'Победителем.*?признан\s+(?:участник\s+)?(.+?),\s*предложивш', all_text)
    if m:
        result["winner"] = m.group(1).strip().rstrip('."').strip()
    
    # Цена победителя
    m = re.search(r'наибольшую цену лота в размере\s+([\d\s,]+)', all_text)
    if m:
        price_str = m.group(1).strip().rstrip(').').strip()
        result["winner_price"] = price_str
        price_num = re.sub(r'[^\d.]', '', price_str.replace(',', '.'))
        try:
            result["winner_price_num"] = float(price_num)
        except:
            pass
    
    # Предпоследнее
    m = re.search(r'предпоследнее.*?признан\s+(?:участник\s+)?(.+?),\s*предложивш', all_text, re.DOTALL)
    if m:
        result["second_place"] = m.group(1).strip().rstrip('."').strip()
    
    m = re.search(r'предложивший цену лота в размере\s+([\d\s,]+)', all_text)
    if m:
        price_str = m.group(1).strip().rstrip(').').strip()
        result["second_price"] = price_str
        price_num = re.sub(r'[^\d.]', '', price_str.replace(',', '.'))
        try:
            result["second_price_num"] = float(price_num)
        except:
            pass
    
    # Количество участников из таблицы
    for table in doc.tables:
        if len(table.rows) > 1 and len(table.columns) >= 2:
            header = table.rows[0].cells[0].text.strip().lower()
            if "номер заявки" in header or "порядковый" in header or "№" in header:
                result["participants_count"] = len(table.rows) - 1
                break
    
    return result

def get_protocol_attachment_id(lot_id):
    url = LOT_URL_TMPL.format(lot_id=lot_id)
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        m = re.search(r'\},\s*(\d{6,})\s*,\s*"Протокол\s*аукциона"', r.text)
        if m:
            return int(m.group(1))
    except:
        pass
    return None

def main():
    print("=== ЗАГРУЗКА СУЩЕСТВУЮЩЕГО КЭША ===")
    
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            print(f"Загружен кэш: {len(cache)} записей")
        except json.JSONDecodeError:
            print("Кэш повреждён, начинаем заново")
            cache = {}
    
    # Дополняем кэш из новых .docx файлов
    docx_files = [f for f in os.listdir(PROTOCOLS_DIR) if f.endswith('.docx')]
    new_docx = 0
    for fname in docx_files:
        lot_id = fname.split('_')[0]
        if lot_id not in cache:
            try:
                filepath = os.path.join(PROTOCOLS_DIR, fname)
                parsed = parse_protocol_docx(filepath)
                cache[lot_id] = parsed
                new_docx += 1
            except Exception as e:
                cache[lot_id] = {"error": str(e)}
                new_docx += 1
    
    if new_docx > 0:
        print(f"Добавлено из .docx: {new_docx}")
    
    print(f"Всего в кэше: {len(cache)}")
    
    # Сохраним кэш
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    
    success_count = sum(1 for v in cache.values() if not v.get("error"))
    fail_count = sum(1 for v in cache.values() if v.get("error"))
    
    # 2. Загружаем CSV и продолжаем парсинг
    print("\n=== ПРОДОЛЖЕНИЕ ПАРСИНГА ===")
    df = pd.read_csv("data/investmoscow_completed_2026-04-04_geocoded.csv", encoding="utf-8-sig")
    lots = df[df["platformLink"].notna()]
    
    print(f"В кэше: {len(cache)} (успешно: {success_count}, ошибки: {fail_count})")
    
    for idx, (i, row) in enumerate(lots.iterrows(), 1):
        lot_id = str(int(row["номер_лота"]))
        
        if lot_id in cache:
            continue  # Уже есть в кэше
        
        print(f"[{idx}/{len(lots)}] Лот #{lot_id}", end=" ")
        
        # Находим attachmentId
        attach_id = get_protocol_attachment_id(lot_id)
        if not attach_id:
            print("❌ Нет протокола")
            cache[lot_id] = {"error": "no_protocol"}
            # Сохраняем каждые 10
            if idx % 10 == 0:
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(cache, f, ensure_ascii=False, indent=2)
            continue
        
        # Скачиваем
        doc_url = DOC_URL_TMPL.format(aid=attach_id)
        filename = os.path.join(PROTOCOLS_DIR, f"{lot_id}_protocol.docx")
        
        try:
            r = requests.get(doc_url, headers=HEADERS, timeout=15)
            if r.status_code != 200 or r.content[:4] != b'PK\x03\x04':
                print(f"❌ Не docx")
                cache[lot_id] = {"error": f"not_docx"}
                continue
            
            with open(filename, "wb") as f:
                f.write(r.content)
            
            parsed = parse_protocol_docx(filename)
            
            if parsed.get("error"):
                print(f"❌ {parsed['error']}")
            else:
                print(f"✅ {parsed['participants_count']} уч. — {parsed.get('winner','')[:40]}")
            
            cache[lot_id] = parsed
            
        except Exception as e:
            print(f"❌ {e}")
            cache[lot_id] = {"error": str(e)}
        
        # Сохраняем каждые 10
        if idx % 10 == 0:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        
        time.sleep(0.5)
    
    # Финальное сохранение
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    
    # Статистика
    success_count = sum(1 for v in cache.values() if not v.get("error"))
    fail_count = sum(1 for v in cache.values() if v.get("error"))
    print(f"\n{'='*60}")
    print(f"ГОТОВО")
    print(f"  Всего: {len(cache)}")
    print(f"  Успешно: {success_count}")
    print(f"  Ошибки: {fail_count}")
    
    # Сохраняем CSV
    results = []
    for lot_id, data in cache.items():
        results.append({"lot_id": lot_id, **data})
    res_df = pd.DataFrame(results)
    res_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n[FILE] {OUTPUT_CSV}")
    
    # Статистика по участникам
    ok = res_df[res_df.get("error").isna()] if "error" in res_df.columns else res_df
    if len(ok) > 0 and "participants_count" in ok.columns:
        counts = ok["participants_count"].dropna()
        if len(counts) > 0:
            print(f"\nУчастники: ср={counts.mean():.1f} мед={counts.median():.0f} макс={counts.max()} мин={counts.min()}")

if __name__ == "__main__":
    main()
