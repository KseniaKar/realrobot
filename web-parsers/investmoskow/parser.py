import requests
import json
import sys
import csv
import time
import os
from datetime import date
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

API_URL = "https://api.investmoscow.ru/investmoscow/tender/v2/filtered-tenders/searchtenderobjects"
DATA_DIR = "data"
PROGRESS_FILE = os.path.join(DATA_DIR, "progress.json")
CSV_FILE = os.path.join(DATA_DIR, f"investmoscow_{date.today().isoformat()}.csv")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type": "application/json"
}

FIELDNAMES = ["url", "площадь м²", "цена руб.", "адрес", "функциональное_назначение", "тип_входа", "этаж", "этажность", "метро"]

def format_area(value):
    if value is None:
        return ""
    try:
        return f"{float(value):.1f}".replace(".", ",")
    except:
        return str(value)

def format_price(value):
    if value is None:
        return ""
    try:
        price = float(value)
        int_part = int(price)
        formatted = f"{int_part:,d}".replace(",", " ")
        cents = int((price - int_part) * 100)
        return f"{formatted},{cents:02d}"
    except:
        return str(value)

def format_floors(value):
    if value is None:
        return ""
    try:
        return str(int(value))
    except:
        return str(value)

def clean_floor(value):
    if not value:
        return ""
    cleaned = value.lower().replace("этаж", "").replace("этажей", "").strip()
    if cleaned:
        return cleaned
    return value

def get_metro(subway_stations):
    if not subway_stations:
        return ""
    stations = []
    for st in subway_stations:
        name = st.get("subwayStationName", "")
        time_walk = st.get("walkingTime", "")
        if name:
            stations.append(f"{name} ({time_walk} мин)")
    return "; ".join(stations)

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"parsed_urls": set(), "results": []}

def save_progress(parsed_urls, results):
    data = {
        "parsed_urls": list(parsed_urls),
        "results": results
    }
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_all_tenders():
    """Получить все объявления через API с пагинацией"""
    all_tenders = []
    page = 1
    page_size = 100
    
    while True:
        params = {
            "orderBy": "Relevance",
            "orderAsc": False,
            "pageNumber": page,
            "pageSize": page_size,
            "objectKinds": ["nsi:tender_type_portal:13"],
            "objectTypes": ["nsi:41:30011569"],
            "tenderStatus": "nsi:tender_status_tender_filter:1"
        }
        
        try:
            response = requests.post(API_URL, json=params, headers=HEADERS, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            entities = data.get("entities", [])
            if not entities:
                break
            
            for entity in entities:
                for tender in entity.get("tenders", []):
                    all_tenders.append(tender)
            
            print(f"[INFO] Страница {page}: получено {len(entities)} сущностей, всего объявлений: {len(all_tenders)}")
            
            # Проверка: если получили меньше чем page_size, значит это последняя страница
            if len(entities) < page_size:
                break
            
            page += 1
            time.sleep(0.3)
            
        except Exception as e:
            print(f"[ERROR] Ошибка при получении страницы {page}: {e}")
            break
    
    return all_tenders

def parse_tender(tender):
    этаж = ""
    for param in tender.get("additionalParams", []):
        if param.get("name") == "Этаж":
            этаж = clean_floor(param.get("value", ""))
            break
    
    тип_входа = ""
    for param in tender.get("additionalParams", []):
        if param.get("name") == "Тип входа":
            тип_входа = param.get("value", "")
            break
    
    функциональное_назначение = ""
    purposes = tender.get("functionalityPurposes", [])
    if purposes:
        функциональное_назначение = purposes[0]
    
    метро = get_metro(tender.get("subwayStations", []))
    
    region = tender.get("regionName", "")
    district = tender.get("districtName", "")
    address = tender.get("address", "")
    
    if region and district:
        district_short = district.replace("район", "р-н").replace("поселение", "пос.").strip()
        formatted_address = f"{region}, {district_short}, {address}"
    else:
        formatted_address = address
    
    return {
        "url": f"https://investmoscow.ru/tenders/tender/{tender.get('id', '')}",
        "площадь м²": format_area(tender.get("objectArea")),
        "цена руб.": format_price(tender.get("startPrice")),
        "адрес": formatted_address,
        "функциональное_назначение": функциональное_назначение,
        "тип_входа": тип_входа,
        "этаж": этаж,
        "этажность": format_floors(tender.get("floors")),
        "метро": метро
    }

def parse_cadastral_from_browser(url):
    """Получить кадастровый номер через браузер (если понадобится)"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url, timeout=30000)
            page.wait_for_selector("h1", timeout=10000)
            content = page.content()
            # Можно добавить парсинг если понадобится
        except Exception as e:
            print(f"   [WARN] Ошибка браузера: {e}")
        finally:
            browser.close()

def save_to_csv(results):
    with open(CSV_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(results)

def main():
    print("[START] Запуск парсера investmoscow.ru")
    
    # Создание папки data если не существует
    os.makedirs(DATA_DIR, exist_ok=True)
    
    print(f"[INFO] Файл результата: {CSV_FILE}")
    
    # Загрузка прогресса
    progress = load_progress()
    parsed_urls = set(progress.get("parsed_urls", []))
    results = progress.get("results", [])
    
    print(f"[INFO] Восстановлено {len(parsed_urls)} уже распарсенных URL")
    
    # Получение всех объявлений
    print("\n[INFO] Получение списка объявлений через API...")
    tenders = get_all_tenders()
    print(f"[OK] Получено {len(tenders)} объявлений")
    
    # Парсинг
    total = len(tenders)
    for i, tender in enumerate(tenders, 1):
        url = f"https://investmoscow.ru/tenders/tender/{tender.get('id', '')}"
        
        if url in parsed_urls:
            print(f"[{i}/{total}] Пропущено (уже распарсено): {url}")
            continue
        
        print(f"[{i}/{total}] Обработка: {url}")
        
        row = parse_tender(tender)
        results.append(row)
        parsed_urls.add(url)
        
        print(f"   [OK] {row['площадь м²']} м², {row['цена руб.']} руб., {row['этаж']} этаж, {row['этажность']} этажность")
        
        # Сохранение прогресса каждые 20 объявлений
        if i % 20 == 0:
            save_progress(parsed_urls, results)
            save_to_csv(results)
            print(f"   [SAVE] Прогресс сохранён ({len(results)} записей)")
        
        time.sleep(0.3)
    
    # Финальное сохранение
    save_progress(parsed_urls, results)
    save_to_csv(results)
    
    print("\n" + "="*60)
    print(f"[DONE] Парсинг завершён!")
    print(f"[RESULT] Всего распарсено: {len(results)} объявлений")
    print(f"[FILE] {CSV_FILE}")
    print(f"[LOG] progress.json")
    print("="*60)

if __name__ == "__main__":
    main()
