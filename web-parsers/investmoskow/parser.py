import requests
import json
import sys
import csv
import time
import re
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
PAGE_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

FIELDNAMES = [
    "url", "номер_лота", "площадь_м²", "начальная_цена_руб", "цена_за_м²",
    "размер_задатка_руб", "шаг_аукциона_руб", "адрес", "кадастровый_номер",
    "метро", "этаж", "этажность", "функциональное_назначение", "тип_входа",
    "форма_проведения", "дата_начала_приёма", "дата_окончания_приёма",
    "дата_проведения_торгов", "platformLink"
]

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

def parse_tender_page(tender_id):
    """Парсим HTML страницу лота для извлечения задатка, шага, кадастрового номера и дат"""
    url = f"https://investmoscow.ru/tenders/tender/{tender_id}"
    result = {
        "кадастровый_номер": "",
        "размер_задатка_руб": "",
        "шаг_аукциона_руб": "",
        "форма_проведения": "",
        "дата_начала_приёма": "",
        "дата_окончания_приёма": "",
        "дата_проведения_торгов": "",
    }

    try:
        resp = requests.get(url, headers=PAGE_HEADERS, timeout=15)
        resp.raise_for_status()
        text = resp.text

        # Извлекаем label-value пары из встроенного JSON
        pattern = r'\{"label":\d+,"value":\d+\},"([^"]*)","([^"]*)"'
        data = {}
        for label, value in re.findall(pattern, text):
            data[label] = value

        # Маппинг полей
        field_mapping = {
            "Кадастровый номер": "кадастровый_номер",
            "Размер задатка": "размер_задатка_руб",
            "Шаг аукциона": "шаг_аукциона_руб",
            "Форма проведения": "форма_проведения",
            "Дата начала приёма заявок": "дата_начала_приёма",
            "Дата окончания приёма заявок": "дата_окончания_приёма",
            "Проведение торгов": "дата_проведения_торгов",
        }

        for src_key, dst_key in field_mapping.items():
            if src_key in data:
                result[dst_key] = data[src_key]

    except Exception as e:
        print(f"   [WARN] Ошибка парсинга страницы {tender_id}: {e}")

    return result


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

def migrate_row(row):
    """Миграция старых записей в новый формат"""
    if "площадь м²" in row:
        row["площадь_м²"] = row.pop("площадь м²")
    if "цена руб." in row:
        row["начальная_цена_руб"] = row.pop("цена руб.")
    # Добавляем отсутствующие поля
    for field in FIELDNAMES:
        if field not in row:
            row[field] = ""
    return row

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Миграция старых записей
        data["results"] = [migrate_row(r) for r in data.get("results", [])]
        return data
    return {"parsed_urls": [], "results": []}

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

def parse_tender(tender, page_data=None):
    этаж = ""
    for param in tender.get("additionalParams", []):
        if param.get("name") == "Этаж":
            этаж = clean_floor(param.get("value", ""))
            break

    тип_входа = ""
    entrance_codes = tender.get("entranceTypeCodes", [])
    if entrance_codes:
        mapping = {
            "nsi:1032:103201":  "Отдельный",                          # опечатка API вместо 1032001
            "nsi:1032:1032004": "Вход через подъезд",
            "nsi:1032:1032005": "Вход через места общего пользования",
            "nsi:1032:1032006": "Вход через подъезд",
            "nsi:1032:9001302": "",                                    # сайт не показывает тип входа
        }
        тип_входа = mapping.get(entrance_codes[0], entrance_codes[0])

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

    # Вычисляемые поля
    area = tender.get("objectArea", 0) or 0
    start_price = tender.get("startPrice", 0) or 0
    price_per_m2 = ""
    if area > 0 and start_price > 0:
        price_per_m2 = f"{(start_price / area):.2f}".replace(".", ",")

    # Форма проведения
    trade_form_id = tender.get("tradeFormId")
    forms = {45001: "Аукцион", 45002: "Публичное предложение"}
    форма_проведения = forms.get(trade_form_id, str(trade_form_id) if trade_form_id else "")

    # Даты из API
    request_start = tender.get("requestStartDate", "")
    request_end = tender.get("requestEndDate", "")
    tender_date = tender.get("tenderDate", "")

    def parse_date_short(iso_str):
        if not iso_str:
            return ""
        return iso_str.split("T")[0] if "T" in iso_str else iso_str

    page_data = page_data or {}

    return {
        "url": f"https://investmoscow.ru/tenders/tender/{tender.get('id', '')}",
        "номер_лота": str(tender.get("id", "")),
        "площадь_м²": format_area(area),
        "начальная_цена_руб": format_price(start_price),
        "цена_за_м²": price_per_m2,
        "размер_задатка_руб": page_data.get("размер_задатка_руб", ""),
        "шаг_аукциона_руб": page_data.get("шаг_аукциона_руб", ""),
        "адрес": formatted_address,
        "кадастровый_номер": page_data.get("кадастровый_номер", ""),
        "метро": метро,
        "этаж": этаж,
        "этажность": format_floors(tender.get("floors")),
        "функциональное_назначение": функциональное_назначение,
        "тип_входа": тип_входа,
        "форма_проведения": page_data.get("форма_проведения") or форма_проведения,
        "дата_начала_приёма": page_data.get("дата_начала_приёма") or parse_date_short(request_start),
        "дата_окончания_приёма": page_data.get("дата_окончания_приёма") or parse_date_short(request_end),
        "дата_проведения_торгов": page_data.get("дата_проведения_торгов") or parse_date_short(tender_date),
        "platformLink": tender.get("platformLink", "")
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

        # Парсим HTML страницу для задатка, шага, кадастрового номера
        tender_id = tender.get("id")
        page_data = parse_tender_page(tender_id) if tender_id else {}

        row = parse_tender(tender, page_data)
        results.append(row)
        parsed_urls.add(url)

        print(f"   [OK] {row['площадь_м²']} м², {row['начальная_цена_руб']} руб., задатк: {row['размер_задатка_руб']}, шаг: {row['шаг_аукциона_руб']}")

        # Сохранение прогресса каждые 10 объявлений (т.к. парсинг страниц медленнее)
        if i % 10 == 0:
            save_progress(parsed_urls, results)
            save_to_csv(results)
            print(f"   [SAVE] Прогресс сохранён ({len(results)} записей)")

        time.sleep(0.5)
    
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
