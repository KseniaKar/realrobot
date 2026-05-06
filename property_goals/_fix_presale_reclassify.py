"""
Исправляет ошибочную классификацию: new_business лоты, у которых
likely_company был в срезах 2GIS ДО даты покупки → переводит в existing_tenant.

Патчит investmoscow_sold_2022_2026_enriched_geo.csv на месте.
"""
import csv
import re
import math
import shutil
from calendar import monthrange
from datetime import date, datetime
from pathlib import Path
from collections import defaultdict

BASE     = Path(__file__).resolve().parent
ENRICHED = BASE / "investmoscow_sold_2022_2026_enriched_geo.csv"
MOSCOW   = BASE / "moscow"
BACKUP   = BASE / "investmoscow_sold_2022_2026_enriched_geo.csv.bak"

NEW_BIZ_CONF = {"high", "medium", "low"}
MAX_DIST_M   = 250

_K_DIGIT_RE = re.compile(r"\bк(\d+)\b")
_ST_DIGIT_RE = re.compile(r"\bст(\d+[а-яё]?)\b")
_STREET_RE  = re.compile(r"\b(?:улица|переулок|проспект|бульвар|набережная|площадь|шоссе|тупик|проезд|аллея)\b")

def canon_addr(addr):
    addr = _K_DIGIT_RE.sub(r"корп \1", addr)
    addr = _ST_DIGIT_RE.sub(r"стр \1", addr)
    addr = _STREET_RE.sub("", addr)
    return re.sub(r" {2,}", " ", addr).strip()

def norm_company(name):
    return name.split("(")[0].split(",")[0].strip().lower()

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = math.sin(math.radians(lat2-lat1)/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(math.radians(lon2-lon1)/2)**2
    return 2*R*math.atan2(math.sqrt(a), math.sqrt(1-a))

def snapshot_date(label):
    year, month = map(int, label.split("-"))
    return date(year, month, monthrange(year, month)[1])

def parse_date(val):
    val = (val or "").strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(val[:10], fmt).date()
        except ValueError:
            pass
    return None

def to_float(v):
    try:
        return float(str(v).strip().replace(",", "."))
    except Exception:
        return None

# ── 1. Загрузка new_business лотов ───────────────────────────────────────────

print("Шаг 1: загружаем new_business лоты...")
lots = []
with ENRICHED.open(encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        conf = (row.get("match_confidence") or "").strip()
        if conf not in NEW_BIZ_CONF:
            continue
        company = norm_company(row.get("likely_company") or "")
        if not company:
            continue
        pd = parse_date(row.get("дата_подведения_итогов"))
        if not pd:
            continue
        lat = to_float(row.get("latitude"))
        lon = to_float(row.get("longitude"))
        if lat is None or lon is None:
            continue
        lots.append({
            "lot_id":   row["номер_лота"],
            "company":  company,
            "purchase": pd,
            "lat": lat, "lon": lon,
            "addr": canon_addr((row.get("address_norm") or "").strip()),
        })
print(f"  Лотов new_business: {len(lots)}")

# ── 2. Поиск в пресейл срезах ─────────────────────────────────────────────────

print("Шаг 2: проверяем срезы до даты покупки...")
presale_lots: set[str] = set()  # lot_id

snapshots = sorted(MOSCOW.glob("*.with_norm.csv"), key=lambda p: p.stem)
for snap_path in snapshots:
    label  = snap_path.name.replace(".with_norm.csv", "")
    s_date = snapshot_date(label)

    target = [l for l in lots if l["purchase"] > s_date]
    if not target:
        continue

    addr_index: dict[str, list[tuple]] = defaultdict(list)
    with snap_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            a = canon_addr((row.get("address_norm") or "").strip())
            if not a:
                continue
            lat = to_float(row.get("lat"))
            lon = to_float(row.get("lon"))
            if lat is None or lon is None:
                continue
            name = norm_company(row.get("name") or "")
            if name:
                addr_index[a].append((name, lat, lon))

    hits = 0
    for lot in target:
        if lot["lot_id"] in presale_lots:
            continue  # уже найден
        for (ename, elat, elon) in addr_index.get(lot["addr"], []):
            if lot["company"] not in ename and ename not in lot["company"]:
                continue
            if haversine_m(lot["lat"], lot["lon"], elat, elon) <= MAX_DIST_M:
                presale_lots.add(lot["lot_id"])
                hits += 1
                break
    print(f"  {label} ({s_date}): target={len(target)}, new_hits={hits}, total_found={len(presale_lots)}")

print(f"\nИтого лотов для переклассификации: {len(presale_lots)}")

# ── 3. Патч enriched CSV ──────────────────────────────────────────────────────

print("\nШаг 3: резервная копия и патч enriched CSV...")
shutil.copy2(ENRICHED, BACKUP)
print(f"  Бэкап: {BACKUP}")

rows_out = []
fieldnames = None
changed = 0

with ENRICHED.open(encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    for row in reader:
        lot_id = row.get("номер_лота", "")
        if lot_id in presale_lots:
            row["match_confidence"]  = "existing_tenant"
            row["match_time_window"] = "existing_tenant_buyout"
            changed += 1
        rows_out.append(row)

with ENRICHED.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows_out)

print(f"  Изменено строк: {changed}")
print(f"  Файл обновлён: {ENRICHED}")

# ── 4. Итоговая статистика ────────────────────────────────────────────────────

from collections import Counter
conf_counts = Counter()
with ENRICHED.open(encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        conf = (row.get("match_confidence") or "").strip()
        if conf:
            conf_counts[conf] += 1

total = sum(conf_counts.values())
total_lots = 3868
print(f"\n=== Итоговое распределение match_confidence ===")
for k, v in sorted(conf_counts.items()):
    print(f"  {k}: {v}")
print(f"  ИТОГО подобрано: {total}  ({total/total_lots:.1%} от 3868)")
