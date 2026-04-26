"""
Проверка наличия данных за 2022-2023 в API investmoscow.ru
"""
import requests
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

API_URL = "https://api.investmoscow.ru/investmoscow/tender/v2/filtered-tenders/searchtenderobjects"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type": "application/json"
}

# Проверяем несколько диапазонов дат
periods = [
    ("2022", "2022-01-01T00:00:00Z", "2022-12-31T23:59:59Z"),
    ("2023", "2023-01-01T00:00:00Z", "2023-12-31T23:59:59Z"),
    ("2024", "2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"),
]

print("Проверка API investmoscow.ru по годам...\n")

for year, start, end in periods:
    params = {
        "orderBy": "Relevance",
        "orderAsc": False,
        "pageNumber": 1,
        "pageSize": 1,
        "objectKinds": ["nsi:tender_type_portal:13"],
        "objectTypes": ["nsi:41:30011569"],
        # Фильтр по дате окончания приёма заявок
        "requestEndDate": {
            "from": start,
            "to": end
        }
    }

    try:
        resp = requests.post(API_URL, json=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        total = data.get("totalCount", 0)
        entities = data.get("entities", [])
        first_tender = None
        if entities and entities[0].get("tenders"):
            t = entities[0]["tenders"][0]
            first_tender = {
                "id": t.get("id"),
                "startPrice": t.get("startPrice"),
                "objectArea": t.get("objectArea"),
                "address": t.get("address", "")[:50],
                "requestStartDate": t.get("requestStartDate", "")[:10],
                "requestEndDate": t.get("requestEndDate", "")[:10],
            }
        print(f"  {year}: totalCount={total}, entities on page={len(entities)}")
        if first_tender:
            print(f"    Пример: лот #{first_tender['id']}, {first_tender['objectArea']} м², {first_tender['startPrice']:,.0f} руб., {first_tender['address']}, дата окончания: {first_tender['requestEndDate']}")
        print()
    except Exception as e:
        print(f"  {year}: ОШИБКА — {e}\n")

# Попробуем без фильтра даты — сколько всего
print("Без фильтра даты (page 1, pageSize=1):")
params_all = {
    "orderBy": "Relevance",
    "orderAsc": False,
    "pageNumber": 1,
    "pageSize": 1,
    "objectKinds": ["nsi:tender_type_portal:13"],
    "objectTypes": ["nsi:41:30011569"],
}
try:
    resp = requests.post(API_URL, json=params_all, headers=HEADERS, timeout=15)
    data = resp.json()
    print(f"  totalCount={data.get('totalCount', '?')}")
    if data.get("entities"):
        t = data["entities"][0].get("tenders", [{}])[0]
        print(f"  Самый свежий: лот #{t.get('id')}, дата окончания: {t.get('requestEndDate', '')[:10]}")
except Exception as e:
    print(f"  ОШИБКА: {e}")
