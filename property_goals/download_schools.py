"""
Скачивает образовательные учреждения Москвы через OpenStreetMap Overpass API.
Не требует регистрации или API-ключей.

Охватывает: школы, детсады, колледжи, вузы (amenity=school/kindergarten/college/university).
Сохраняет в property_goals/data/schools_moscow.csv.

Запускать один раз; данные относительно стабильны (обновлять раз в год).
"""
import csv
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "data"
OUT_DIR.mkdir(exist_ok=True)
OUT = OUT_DIR / "schools_moscow.csv"

# Ограничивающий прямоугольник Москвы (с запасом)
BBOX = "55.48,36.80,56.02,37.97"

# amenity-теги, создающие 100м зону по 171-ФЗ
# school=общеобразовательные, kindergarten=детсады,
# college=колледжи/техникумы/ПТУ, university=вузы,
# music_school=ДМШ/ДШИ (детские школы искусств, 273-ФЗ ст. 23)
AMENITIES = ["school", "kindergarten", "college", "university", "music_school"]

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def overpass_query(amenity: str) -> list:
    """Возвращает список {name, type, lat, lon} для одного amenity-тега."""
    query = f"""
[out:json][timeout:60];
(
  node["amenity"="{amenity}"]({BBOX});
  way["amenity"="{amenity}"]({BBOX});
  relation["amenity"="{amenity}"]({BBOX});
);
out center tags;
"""
    params = urllib.parse.urlencode({"data": query})
    url = f"{OVERPASS_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "realrobot-project/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.load(resp)

    rows = []
    for el in result.get("elements", []):
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        tags = el.get("tags", {})
        name = tags.get("name:ru") or tags.get("name") or ""
        rows.append({
            "id":      el.get("id", ""),
            "name":    name,
            "type":    amenity,
            "address": tags.get("addr:full") or tags.get("addr:street", ""),
            "lat":     lat,
            "lon":     lon,
        })
    return rows


def main():
    print("Скачиваем образовательные учреждения Москвы через Overpass API (OSM)...")
    all_rows = []
    seen_ids = set()

    for amenity in AMENITIES:
        print(f"  Запрос: amenity={amenity} ...", end=" ", flush=True)
        try:
            rows = overpass_query(amenity)
            new = [r for r in rows if r["id"] not in seen_ids]
            seen_ids.update(r["id"] for r in new)
            all_rows.extend(new)
            print(f"{len(new)} объектов")
        except Exception as e:
            print(f"ОШИБКА: {e}")
        time.sleep(2)  # пауза между запросами к Overpass

    print(f"\nИтого: {len(all_rows)} учреждений с координатами")

    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id","name","type","address","lat","lon"])
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"Сохранено: {OUT}")

    from collections import Counter
    by_type = Counter(r["type"] for r in all_rows)
    for t, n in by_type.most_common():
        print(f"  {t}: {n}")


if __name__ == "__main__":
    main()
