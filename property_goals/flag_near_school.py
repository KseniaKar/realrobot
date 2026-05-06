"""
Для каждого лота проверяет: есть ли образовательное учреждение в радиусе 100м.
Добавляет колонку near_school_100m в enriched_geo.csv.

Алкомаркеты (171-ФЗ): запрещены в 100м от школ, детсадов, колледжей, вузов.
"""
import csv
import math
from pathlib import Path

BASE     = Path(__file__).resolve().parent
ENRICHED = BASE / "investmoscow_sold_2022_2026_enriched_geo.csv"
SCHOOLS  = BASE / "data" / "schools_moscow.csv"
RADIUS_M = 100

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = math.sin(math.radians(lat2-lat1)/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(math.radians(lon2-lon1)/2)**2
    return 2*R*math.atan2(math.sqrt(a), math.sqrt(1-a))

def to_float(v):
    try: return float(str(v).strip())
    except: return None

# Загружаем школы
print("Загружаем школы...")
schools = []
with SCHOOLS.open(encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        lat = to_float(row["lat"])
        lon = to_float(row["lon"])
        if lat and lon:
            schools.append((lat, lon, row["type"], row["name"]))
print(f"  {len(schools)} учреждений")

# Строим грубую сетку для ускорения: ячейка ~0.001 градус ≈ 100м
# Для каждой ячейки храним список школ
from collections import defaultdict
GRID_STEP = 0.001  # ~111м
grid = defaultdict(list)
for s in schools:
    gx = int(s[0] / GRID_STEP)
    gy = int(s[1] / GRID_STEP)
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            grid[(gx+dx, gy+dy)].append(s)

def nearest_school(lat, lon):
    gx = int(lat / GRID_STEP)
    gy = int(lon / GRID_STEP)
    candidates = grid.get((gx, gy), [])
    best_dist = float("inf")
    best_name = ""
    for (slat, slon, stype, sname) in candidates:
        d = haversine_m(lat, lon, slat, slon)
        if d < best_dist:
            best_dist = d
            best_name = f"{sname} ({stype})"
    return best_dist, best_name

# Читаем enriched, добавляем колонку
print("Проверяем лоты...")
rows = []
fieldnames = None
near_count = 0

with ENRICHED.open(encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    for row in reader:
        lat = to_float(row.get("latitude"))
        lon = to_float(row.get("longitude"))
        if lat and lon:
            dist, name = nearest_school(lat, lon)
            row["near_school_100m"] = "1" if dist <= RADIUS_M else ""
            row["nearest_school_m"] = f"{dist:.0f}" if dist <= 300 else ""
            row["nearest_school_name"] = name if dist <= 300 else ""
            if dist <= RADIUS_M:
                near_count += 1
        else:
            row["near_school_100m"] = ""
            row["nearest_school_m"] = ""
            row["nearest_school_name"] = ""
        rows.append(row)

print(f"  Лотов в 100м от учреждения: {near_count} из {len(rows)}")

# Пишем обратно
new_fields = ["near_school_100m", "nearest_school_m", "nearest_school_name"]
all_fields = list(fieldnames) + [f for f in new_fields if f not in fieldnames]

with ENRICHED.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=all_fields)
    writer.writeheader()
    writer.writerows(rows)

print(f"Обновлено: {ENRICHED}")
print(f"Новые колонки: near_school_100m, nearest_school_m, nearest_school_name")
