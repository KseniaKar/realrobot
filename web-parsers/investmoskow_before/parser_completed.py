"""
Парсер investmoscow.ru — завершенные торги за 2025-2026 год
Сбор всех доступных данных: цены, даты, итоги
"""
import requests
import json
import csv
import time
import re
import os
import sys
from datetime import datetime, timezone
from bs4 import BeautifulSoup

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

API_URL = "https://api.investmoscow.ru/investmoscow/tender/v2/filtered-tenders/searchtenderobjects"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type": "application/json"
}
PAGE_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

DATA_DIR = "data"
CACHE_FILE = os.path.join(DATA_DIR, "all_tenders_cache.json")
PAGE_CACHE_FILE = os.path.join(DATA_DIR, "page_cache.json")
PROGRESS_FILE = os.path.join(DATA_DIR, "parser_progress.json")
PROTOCOL_CACHE_FILE = os.path.join(DATA_DIR, "protocols", "protocol_cache.json")
CSV_FILE = os.path.join(DATA_DIR, f"investmoscow_completed_{datetime.now().strftime('%Y-%m-%d')}.csv")

FIELDNAMES = [
    "url",
    "номер_лота",
    "площадь_м²",
    "начальная_цена_руб",
    "цена_за_м²",
    "размер_задатка_руб",
    "шаг_аукциона_руб",
    "итоговая_цена_руб",
    "превышение_цены_%",
    "адрес",
    "кадастровый_номер",
    "метро",
    "этаж",
    "этажность",
    "функциональное_назначение",
    "тип_входа",
    "форма_проведения",
    "год_торгов",
    "статус",
    "дата_начала_приёма",
    "дата_окончания_приёма",
    "дата_отбора_участников",
    "дата_проведения_торгов",
    "дата_подведения_итогов",
    "platformLink",
    "ссылка_на_протокол",
    "источник_итоговой_цены",
    "итоговая_цена_подтверждена",
]


def get_all_tenders_cached():
    """Скачиваем все записи с кэшированием"""
    if os.path.exists(CACHE_FILE):
        print(f"[INFO] Загрузка из кэша: {CACHE_FILE}")
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    print("[INFO] Скачиваем все записи с API...")
    all_tenders = []
    page = 1

    while True:
        params = {
            "orderBy": "Relevance",
            "orderAsc": False,
            "pageNumber": page,
            "pageSize": 100,
            "objectKinds": ["nsi:tender_type_portal:13"],
            "objectTypes": ["nsi:41:30011569"],
        }

        try:
            resp = requests.post(API_URL, json=params, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            entities = data.get("entities", [])
            if not entities:
                break

            for entity in entities:
                for tender in entity.get("tenders", []):
                    all_tenders.append(tender)

            print(f"  Страница {page}: {len(entities)} сущностей, всего: {len(all_tenders)}")

            if len(entities) < 100:
                break

            page += 1
            time.sleep(0.2)

        except Exception as e:
            print(f"  [ERROR] Страница {page}: {e}")
            break

    os.makedirs(DATA_DIR, exist_ok=True)
    print(f"[INFO] Сохранение кэша: {len(all_tenders)} записей")
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(all_tenders, f, ensure_ascii=False)

    return all_tenders


def parse_date_iso(date_str):
    """Парсим ISO дату"""
    if not date_str:
        return None
    try:
        cleaned = date_str.replace('Z', '+00:00')
        parts = cleaned.split('.')
        if len(parts) == 2:
            tz_part = parts[1][-6:]
            micro = parts[1][:-6].ljust(6, '0')[:6]
            cleaned = parts[0] + '.' + micro + tz_part
        return datetime.fromisoformat(cleaned)
    except:
        return None


def load_page_cache():
    """Загружаем кэш распарсенных страниц"""
    if os.path.exists(PAGE_CACHE_FILE):
        with open(PAGE_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_page_cache(cache):
    """Сохраняем кэш страниц"""
    with open(PAGE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


def load_progress():
    """Загружаем прогресс парсера"""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"processed_ids": [], "results_count": 0}


def save_progress(processed_ids, results_count):
    """Сохраняем прогресс"""
    data = {"processed_ids": processed_ids, "results_count": results_count}
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def save_csv(results):
    """Сохраняем результаты в CSV"""
    try:
        with open(CSV_FILE, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(results)
        return True
    except PermissionError:
        print(f"   [WARN] Не удалось сохранить CSV — файл открыт")
        return False


def parse_tender_page_cached(tender_id, page_cache):
    """Парсим страницу тендера с кэшированием"""
    if str(tender_id) in page_cache:
        return page_cache[str(tender_id)]

    result = parse_tender_page(tender_id)
    page_cache[str(tender_id)] = result
    return result


def parse_tender_page(tender_id):
    """Парсим страницу тендера для получения доп. данных"""
    url = f"https://investmoscow.ru/tenders/tender/{tender_id}"
    result = {
        "кадастровый_номер": "",
        "размер_задатка_руб": "",
        "шаг_аукциона_руб": "",
        "итоговая_цена_руб": "",
        "форма_проведения": "",
        "дата_начала_приёма": "",
        "дата_окончания_приёма": "",
        "дата_отбора_участников": "",
        "дата_проведения_торгов": "",
        "дата_подведения_итогов": "",
        "ссылка_на_протокол": "",
    }

    try:
        resp = requests.get(url, headers=PAGE_HEADERS, timeout=15)
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
            "Итоговая цена": "итоговая_цена_руб",
            "Форма проведения": "форма_проведения",
            "Дата начала приёма заявок": "дата_начала_приёма",
            "Дата окончания приёма заявок": "дата_окончания_приёма",
            "Отбор участников": "дата_отбора_участников",
            "Проведение торгов": "дата_проведения_торгов",
            "Подведение итогов": "дата_подведения_итогов",
        }

        for src_key, dst_key in field_mapping.items():
            if src_key in data:
                result[dst_key] = data[src_key]

        # Ищем ссылку на протокол
        soup = BeautifulSoup(text, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href']
            txt = a.get_text(strip=True).lower()
            if 'протокол' in txt or 'протокол' in href.lower():
                full_href = href if href.startswith('http') else f"https://investmoscow.ru{href}"
                result["ссылка_на_протокол"] = full_href
                break

        return result

    except Exception as e:
        print(f"   [WARN] Ошибка парсинга страницы {tender_id}: {e}")
        return result


def get_metro(subway_stations):
    if not subway_stations:
        return ""
    stations = []
    for st in subway_stations:
        name = st.get("subwayStationName", "")
        walk = st.get("walkingTime", "")
        if name:
            stations.append(f"{name} ({walk} мин)")
    return "; ".join(stations)


def get_floor(additional_params):
    for param in additional_params:
        if param.get("name") == "Этаж":
            return param.get("value", "")
    return ""


def get_entrance_type(entrance_type_codes):
    """Расшифровка типа входа по коду"""
    mapping = {
        "nsi:1032:103201": "Отдельный",
        "nsi:1032:1032005": "Вход через места общего пользования",
        "nsi:1032:1032006": "Вход через подъезд",
    }
    if not entrance_type_codes:
        return ""
    code = entrance_type_codes[0]
    return mapping.get(code, code)


def get_trade_form_name(trade_form_id):
    forms = {
        45001: "Аукцион",
        45002: "Публичное предложение",
    }
    return forms.get(trade_form_id, str(trade_form_id) if trade_form_id else "")


EXCLUDED_EXCEEDANCE_FORMS = {
    "Публичное предложение",
    "Без объявления цены",
}


def parse_money(value):
    try:
        cleaned = str(value).replace('\xa0', '').replace(' ', '').replace(',', '.')
        return float(cleaned)
    except:
        return None


def normalize_final_price(final_price, trade_form=""):
    """Для восходящих аукционов нулевая/отрицательная итоговая цена считается отсутствующей."""
    form = str(trade_form).strip()
    final_num = parse_money(final_price)
    if form == "Открытый аукцион в электронной форме" and final_num is not None and final_num <= 0:
        return ""
    return final_price


def load_protocol_cache():
    if not os.path.exists(PROTOCOL_CACHE_FILE):
        return {}
    try:
        with open(PROTOCOL_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def format_money_ru(value):
    return f"{float(value):.2f}".replace(".", ",")


def get_final_price_from_protocol(tender_id, protocol_cache):
    item = protocol_cache.get(str(tender_id), {})
    if not isinstance(item, dict) or item.get("error"):
        return ""
    winner_price_num = item.get("winner_price_num")
    if winner_price_num in (None, ""):
        return ""
    try:
        return format_money_ru(winner_price_num)
    except Exception:
        return ""


def get_final_price_source(protocol_final_price, page_final_price):
    if str(protocol_final_price).strip():
        return "protocol"
    if str(page_final_price).strip():
        return "page"
    return "missing"


def calc_price_exceedance(start_price, final_price, trade_form=""):
    """Рассчитываем превышение цены в % только для восходящих торгов."""
    form = str(trade_form).strip()
    if form in EXCLUDED_EXCEEDANCE_FORMS:
        return ""
    try:
        start = float(str(start_price).replace(',', '.').replace(' ', ''))
        final = float(str(final_price).replace(',', '.').replace(' ', ''))
        if start > 0:
            if form == "Открытый аукцион в электронной форме" and final < start:
                return ""
            return f"{((final - start) / start * 100):.1f}%"
    except:
        pass
    return ""


def main():
    print(f"{'='*60}")
    print(f"Парсер investmoscow.ru — завершенные торги 2025-2026")
    print(f"{'='*60}")

    os.makedirs(DATA_DIR, exist_ok=True)

    # 1. Скачиваем данные из API
    tenders = get_all_tenders_cached()
    print(f"\n[INFO] Всего в кэше: {len(tenders)} записей")

    # 2. Фильтруем: 2025-2026, завершенные
    now = datetime.now(timezone.utc)
    filtered = []

    for t in tenders:
        end_date = parse_date_iso(t.get("requestEndDate"))
        if not end_date:
            continue
        if end_date.year not in [2025, 2026]:
            continue
        if end_date >= now:
            continue

        filtered.append(t)

    print(f"[INFO] Завершённых за 2025-2026: {len(filtered)}")

    if not filtered:
        print("[WARN] Нет завершенных записей")
        return

    # 3. Загружаем кэш страниц и прогресс
    page_cache = load_page_cache()
    progress = load_progress()
    protocol_cache = load_protocol_cache()
    processed_ids = set(progress.get("processed_ids", []))
    
    print(f"[INFO] Кэш страниц: {len(page_cache)} записей")
    print(f"[INFO] Прогресс: {len(processed_ids)} обработано")

    # 4. Парсим каждую страницу для получения доп. данных
    print(f"\n[INFO] Парсинг страниц тендеров...")
    results = []
    skip_count = 0
    
    for i, t in enumerate(filtered, 1):
        tender_id = t.get("id")
        url = f"https://investmoscow.ru/tenders/tender/{tender_id}"
        
        # Пропускаем уже обработанные
        if str(tender_id) in processed_ids:
            skip_count += 1
            continue
        
        print(f"[{i}/{len(filtered)}] {url} (пропущено ранее: {skip_count})")
        
        # Получаем доп. данные со страницы (из кэша или парсим)
        page_data = parse_tender_page_cached(tender_id, page_cache)
        
        # Базовые данные из API
        region = t.get("regionName", "")
        district = t.get("districtName", "")
        address = t.get("address", "")
        if region and district:
            district_short = district.replace("район", "р-н").strip()
            full_address = f"{region}, {district_short}, {address}"
        else:
            full_address = address

        end_date = parse_date_iso(t.get("requestEndDate"))
        
        trade_form = page_data["форма_проведения"] or get_trade_form_name(t.get("tradeFormId"))

        protocol_final_price = get_final_price_from_protocol(tender_id, protocol_cache)
        page_final_price = page_data["итоговая_цена_руб"]
        final_price_source = get_final_price_source(protocol_final_price, page_final_price)
        final_price = protocol_final_price or page_final_price
        final_price = normalize_final_price(final_price, trade_form)

        row = {
            "url": url,
            "номер_лота": str(tender_id),
            "площадь_м²": t.get("objectArea", ""),
            "начальная_цена_руб": t.get("startPrice", ""),
            "цена_за_м²": t.get("pricePerSquare", ""),
            "адрес": full_address,
            "кадастровый_номер": page_data["кадастровый_номер"],
            "метро": get_metro(t.get("subwayStations", [])),
            "этаж": get_floor(t.get("additionalParams", [])),
            "этажность": t.get("floors", ""),
            "функциональное_назначение": "; ".join(t.get("functionalityPurposes", [])),
            "тип_входа": get_entrance_type(t.get("entranceTypeCodes", [])),
            "форма_проведения": trade_form,
            "год_торгов": end_date.year if end_date else "",
            "статус": "Завершено",
            "дата_начала_приёма": page_data["дата_начала_приёма"],
            "дата_окончания_приёма": page_data["дата_окончания_приёма"],
            "дата_отбора_участников": page_data["дата_отбора_участников"],
            "дата_проведения_торгов": page_data["дата_проведения_торгов"],
            "дата_подведения_итогов": page_data["дата_подведения_итогов"],
            "размер_задатка_руб": page_data["размер_задатка_руб"],
            "шаг_аукциона_руб": page_data["шаг_аукциона_руб"],
            "итоговая_цена_руб": final_price,
            "превышение_цены_%": calc_price_exceedance(
                t.get("startPrice", ""), 
                final_price,
                trade_form,
            ),
            "platformLink": t.get("platformLink", ""),
            "ссылка_на_протокол": page_data["ссылка_на_протокол"],
            "источник_итоговой_цены": final_price_source,
            "итоговая_цена_подтверждена": "true" if final_price_source == "protocol" else "false",
        }

        results.append(row)
        processed_ids.add(str(tender_id))
        
        print(f"   [OK] {row['площадь_м²']} m2, start={row['начальная_цена_руб']}, "
              f"final={row['итоговая_цена_руб']}, exceed={row['превышение_цены_%']}")

        # Сохраняем прогресс каждые 50
        if i % 50 == 0:
            save_progress(list(processed_ids), len(results))
            save_page_cache(page_cache)
            save_csv(results)
            print(f"   [SAVE] Прогресс: {len(results)} записей, кэш: {len(page_cache)}")

        time.sleep(0.3)

    # Финальное сохранение
    save_progress(list(processed_ids), len(results))
    save_page_cache(page_cache)
    save_csv(results)

    print(f"\n{'='*60}")
    print(f"[DONE] Сохранено: {len(results)} записей")
    print(f"[FILE] {CSV_FILE}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
