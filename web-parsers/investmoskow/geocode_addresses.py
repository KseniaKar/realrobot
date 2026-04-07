"""
Геокодирование адресов из CSV investmoscow (активные торги)
Использует Nominatim (OpenStreetMap) с кэшированием и возобновлением
"""
import pandas as pd
import requests
import json
import time
import re
import os
from datetime import datetime

CSV_INPUT = "data/investmoscow_2026-03-04.csv"
GEOCACHE_FILE = "data/geocache_active.json"
CSV_OUTPUT = "data/investmoscow_2026-03-04_geocoded.csv"

def clean_address_for_geocoding(addr):
    """
    Улучшенная очистка адреса для геокодирования.
    Преобразуем формат "Административный округ, Район, Улица, дом X, ..." 
    в формат для Nominatim
    """
    if not addr:
        return ""
    
    # Убираем всё, что связано с этажами, подвалами, помещениями
    floor_patterns = [
        r',?\s*Этаж\s*№\s*\d+',
        r',?\s*этаж\s*№\s*\d+',
        r',?\s*Этаж\s*№\d+',
        r',?\s*этаж\s*№\d+',
        r',?\s*подвал\s*№\s*\d+',
        r',?\s*Подвал\s*№\s*\d+',
        r',?\s*цоколь.*?№\s*\d+',
        r',?\s*Цокольный этаж.*?',
        r',?\s*Технический этаж.*?',
        r',?\s*Техническое подполье.*?',
        r',?\s*Антресоль.*?',
        r',?\s*помещени[ея]\s*[^,;]*',
        r',?\s*пом\.\s*[^,;]*',
        r',?\s*помещение\s*[^,;]*',
        r',?\s*не указано',
        r',?\s*Подвал',
        r';\s*подвал.*',
    ]
    
    for pattern in floor_patterns:
        addr = re.sub(pattern, '', addr, flags=re.IGNORECASE)
    
    # Убираем "административный округ" и его название в начале
    addr = re.sub(r'^[А-Яа-яё\s-]+\s+административный округ,\s*', '', addr)
    
    # Убираем "муниципальный округ" и его название
    addr = re.sub(r',?\s*муниципальный округ[^,]*', '', addr, flags=re.IGNORECASE)
    
    # Убираем "город" перед названием города
    addr = re.sub(r'\bгород\s+', '', addr, flags=re.IGNORECASE)
    
    # Сначала делаем замены сокращений (ДО фильтрации)
    addr = re.sub(r'\bулица\s+', 'ул. ', addr, flags=re.IGNORECASE)
    addr = re.sub(r'\bдом\s+(\d+[А-Яа-яё]?)', r'д.\1', addr, flags=re.IGNORECASE)
    addr = re.sub(r'\bкорпус\s+(\d+[А-Яа-яё]?)', r'корп.\1', addr, flags=re.IGNORECASE)
    addr = re.sub(r'\bстроение\s+(\d+[А-Яа-яё]?)', r'стр.\1', addr, flags=re.IGNORECASE)
    
    # Теперь обрабатываем специальные случаи и убираем район
    parts = [p.strip() for p in addr.split(',')]
    filtered_parts = []
    for part in parts:
        has_street_type = re.search(r'(ул\.|улица|шоссе|переулок|проспект|пл\.|площадь|бульвар|б-р|проезд|набережная)',
                                   part, re.IGNORECASE)
        is_city = bool(re.search(r'(Зеленоград|Щербинка)', part))
        has_house_number = bool(re.search(r'д\.\s*\d+', part, flags=re.IGNORECASE))
        # Для Зеленограда корпус = дом, поэтому тоже сохраняем
        has_building_number = bool(re.search(r'корп\.\s*\d+', part, flags=re.IGNORECASE)) and is_city

        if not has_street_type and not is_city and not has_house_number and not has_building_number and part:
            continue

        filtered_parts.append(part)
    
    addr = ', '.join(filtered_parts)
    addr = re.sub(r',\s*,', ',', addr)
    addr = re.sub(r'^,\s*', '', addr)
    addr = re.sub(r'\s*,\s*$', '', addr)
    addr = re.sub(r'[;\s]+$', '', addr)
    addr = re.sub(r'\s+', ' ', addr)
    
    return addr.strip()


def prepare_query_for_nominatim(cleaned_addr):
    """
    Подготавливаем запрос для Nominatim.
    Убираем 'д.', 'корп.', 'стр.' — Nominatim лучше находит по улице и номеру дома.
    Исключение: для Зеленограда 'корп.' — это основной идентификатор здания.
    Nominatim плохо ищет корпуса Зеленограда, поэтому для запросов только с 
    'Зеленоград + корп.N' оставляем просто 'Зеленоград'.
    """
    if 'Зеленоград' in cleaned_addr:
        # Для Зеленограда: убираем "корп.N" т.к. Nominatim всё равно неточно ищет
        query = re.sub(r'\bкорп\.\s*\d+[А-Яа-яё]?[,\s]*', '', cleaned_addr, flags=re.IGNORECASE)
        query = re.sub(r'\bд\.\s*', '', query)
    else:
        # Убираем "д." для запроса
        query = re.sub(r'\bд\.\s*', '', cleaned_addr)
        # Убираем корпуса и строения (они мешают поиску)
        query = re.sub(r'\bкорп\.\s*\d+[А-Яа-яё]?[,\s]*', '', query, flags=re.IGNORECASE)

    query = re.sub(r'\bстр\.\s*\d+[А-Яа-яё]?[,\s]*', '', query, flags=re.IGNORECASE)
    # Убираем "к" слитно с номером (например "2к2" -> "2")
    query = re.sub(r'(\d)к\d+', r'\1', query)

    query = query.strip(', ')
    return f"{query}, Москва"


def load_geocache():
    """Загружаем кэш геокодирования"""
    if os.path.exists(GEOCACHE_FILE):
        with open(GEOCACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_geocache(cache):
    """Сохраняем кэш геокодирования"""
    with open(GEOCACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def geocode_address(address, cache):
    """
    Геокодируем один адрес с кэшированием.
    Возвращает (lat, lon) или (None, None)
    """
    if not address:
        return None, None

    # Проверяем кэш
    if address in cache:
        result = cache[address]
        if result:
            return result['lat'], result['lon']
        else:
            return None, None  # Уже пытались, не нашли

    # Подготовка запроса
    cleaned = clean_address_for_geocoding(address)
    query = prepare_query_for_nominatim(cleaned)

    # Пропускаем слишком короткие или бессмысленные запросы
    # Убираем "Москва" для проверки содержимого
    query_core = query.replace(', Москва', '').strip().strip(',').strip()
    if len(query_core) < 4 or re.match(r'^\d+$', query_core):
        print(f"  ⏭️  Пропуск (слишком общий запрос: '{query}')")
        cache[address] = None
        return None, None

    print(f"  Запрос: {query}")

    # Запрос к Nominatim
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 5, "countrycodes": "ru",
                    "viewbox": "37.2,56.0,38.0,55.5", "bounded": "0"},
            headers={"User-Agent": "InvestMoscowParser/1.0"},
            timeout=10
        )

        if r.status_code == 200:
            data = r.json()
            # Ищем результат в пределах Москвы (примерные границы)
            for result in data:
                lat = float(result['lat'])
                lon = float(result['lon'])
                # Москва: lat ~55.5-56.0, lon ~37.0-38.0
                if 55.4 <= lat <= 56.1 and 36.8 <= lon <= 38.1:
                    # Сохраняем в кэш
                    cache[address] = {'lat': lat, 'lon': lon}
                    print(f"  ✅ НАЙДЕНО: ({lat:.6f}, {lon:.6f})")
                    return lat, lon
            
            # Если ничего в Москве не найдено
            if data:
                first = data[0]
                lat = float(first['lat'])
                lon = float(first['lon'])
                print(f"  ⚠️  Вне Москвы: ({lat:.6f}, {lon:.6f})")
            
            print(f"  ❌ НЕ НАЙДЕНО (в Москве)")
            cache[address] = None  # Чтобы не пытаться снова
            return None, None
        elif r.status_code == 429:
            print(f"  ⚠️  Rate limit, ждём 5 сек...")
            time.sleep(5)
            return geocode_address(address, cache)  # Повторяем
        else:
            print(f"  ⚠️  HTTP {r.status_code}")
            cache[address] = None
            return None, None

    except Exception as e:
        print(f"  ❌ ОШИБКА: {e}")
        cache[address] = None
        return None, None


import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=0, help='Обработать только N новых адресов (0 = все)')
    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"Геокодирование адресов investmoscow.ru")
    print(f"{'='*60}")

    # Загружаем CSV
    print(f"\n[INFO] Загрузка CSV: {CSV_INPUT}")
    df = pd.read_csv(CSV_INPUT, encoding='utf-8-sig')
    print(f"[INFO] Всего записей: {len(df)}")

    # Загружаем кэш
    cache = load_geocache()
    cached_count = sum(1 for v in cache.values() if v is not None)
    print(f"[INFO] Кэш геокодирования: {len(cache)} запросов, {cached_count} успешных")

    # Геокодируем каждый адрес
    print(f"\n[INFO] Начало геокодирования...")
    if args.limit > 0:
        print(f"[INFO] Лимит: {args.limit} новых запросов")

    lats = []
    lons = []
    success_count = 0
    fail_count = 0
    cached_hits = 0
    new_requests = 0

    for i, addr in enumerate(df['адрес'], 1):
        print(f"\n[{i}/{len(df)}] {addr[:60]}...")

        # Проверяем кэш
        if addr in cache and cache[addr] is not None:
            lats.append(cache[addr]['lat'])
            lons.append(cache[addr]['lon'])
            cached_hits += 1
            success_count += 1
            print(f"  ✅ Из кэша: ({cache[addr]['lat']:.6f}, {cache[addr]['lon']:.6f})")
            continue

        # Проверка лимита
        if args.limit > 0 and new_requests >= args.limit:
            print(f"\n[INFO] Лимит {args.limit} исчерпан. Сохраняем прогресс...")
            # Заполняем остаток None
            remaining = len(df) - len(lats)
            lats.extend([None] * remaining)
            lons.extend([None] * remaining)
            break

        # Геокодируем
        lat, lon = geocode_address(addr, cache)
        lats.append(lat)
        lons.append(lon)
        new_requests += 1

        if lat and lon:
            success_count += 1
        else:
            fail_count += 1

        # Сохраняем кэш каждые 10 записей
        if i % 10 == 0:
            save_geocache(cache)
            print(f"  [SAVE] Кэш сохранён")

        # Задержка между запросами (Nominatim limit: 1 req/sec)
        time.sleep(1.2)
    
    # Финальное сохранение кэша
    save_geocache(cache)
    
    # Добавляем колонки в DataFrame
    df['latitude'] = lats
    df['longitude'] = lons
    
    # Сохраняем результат
    df.to_csv(CSV_OUTPUT, index=False, encoding='utf-8-sig')
    
    print(f"\n{'='*60}")
    print(f"[DONE] Геокодирование завершено")
    print(f"  Успешно: {success_count} ({success_count/len(df)*100:.1f}%)")
    print(f"  Не найдено: {fail_count} ({fail_count/len(df)*100:.1f}%)")
    print(f"  Из кэша: {cached_hits}")
    print(f"[FILE] {CSV_OUTPUT}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
