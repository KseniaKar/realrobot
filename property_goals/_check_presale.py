"""
Для каждого new_business лота проверяем: встречается ли likely_company
в срезах 2GIS, датированных РАНЬШЕ даты продажи.

Читаем каждый срез один раз, проверяем все лоты, у которых purchase_date > snapshot_date.
"""
import csv
import re
import math
from calendar import monthrange
from datetime import date, datetime
from pathlib import Path
from collections import defaultdict

BASE    = Path(__file__).resolve().parent
ENRICHED = BASE / "investmoscow_sold_2022_2026_enriched_geo.csv"
MOSCOW  = BASE / "moscow"

NEW_BIZ_CONF = {"high", "medium", "low"}
MAX_DIST_M   = 250

_K_DIGIT_RE  = re.compile(r"\bк(\d+)\b")
_ST_DIGIT_RE = re.compile(r"\bст(\d+[а-яё]?)\b")
_STREET_RE   = re.compile(r"\b(?:улица|переулок|проспект|бульвар|набережная|площадь|шоссе|тупик|проезд|аллея)\b")

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
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
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

# ── Загрузка лотов ────────────────────────────────────────────────────────────

print("Загружаем new_business лоты...")
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
        addr = canon_addr((row.get("address_norm") or "").strip())
        lots.append({
            "lot_id":   row.get("номер_лота", ""),
            "company":  company,
            "raw_co":   row.get("likely_company", ""),
            "purchase": pd,
            "lat":      lat,
            "lon":      lon,
            "addr":     addr,
            "conf":     conf,
            "date_str": (row.get("дата_подведения_итогов") or "")[:10],
            "address":  row.get("адрес", ""),
        })
print(f"  Лотов: {len(lots)}")

# ── Обход срезов ──────────────────────────────────────────────────────────────

# lot_id -> list of snapshot labels where company was found pre-sale
presale_hits: dict[str, list[str]] = defaultdict(list)

snapshots = sorted(
    [p for p in MOSCOW.glob("*.with_norm.csv")],
    key=lambda p: p.stem
)

for snap_path in snapshots:
    label  = snap_path.name.replace(".with_norm.csv", "")
    s_date = snapshot_date(label)

    # Лоты, у которых покупка ПОСЛЕ этого среза (т.е. срез — досрочный)
    target = [l for l in lots if l["purchase"] > s_date]
    if not target:
        print(f"  {label} ({s_date}): нет подходящих лотов")
        continue

    # Строим индекс по адресу из среза: addr -> [(name_norm, lat, lon)]
    addr_index: dict[str, list[tuple]] = defaultdict(list)
    count = 0
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
            count += 1

    hits_this_snap = 0
    for lot in target:
        entries = addr_index.get(lot["addr"], [])
        for (ename, elat, elon) in entries:
            if lot["company"] not in ename and ename not in lot["company"]:
                continue
            dist = haversine_m(lot["lat"], lot["lon"], elat, elon)
            if dist <= MAX_DIST_M:
                presale_hits[lot["lot_id"]].append(label)
                hits_this_snap += 1
                break  # один хит на лот на срез достаточно

    print(f"  {label} ({s_date}): target={len(target)}, hits={hits_this_snap}, snap_rows={count}")

# ── Итог ──────────────────────────────────────────────────────────────────────

print(f"\n=== ИТОГ ===")
print(f"Всего new_business лотов: {len(lots)}")
print(f"Лотов с компанией в досрочных срезах: {len(presale_hits)}  ({len(presale_hits)/len(lots):.1%})")

# Примеры
lot_map = {l["lot_id"]: l for l in lots}
examples = sorted(presale_hits.items(), key=lambda x: lot_map[x[0]]["purchase"])
print(f"\nПримеры (первые 15):")
for lot_id, snap_labels in examples[:15]:
    l = lot_map[lot_id]
    print(f"  лот {lot_id}  куплен={l['date_str']}  conf={l['conf']}")
    print(f"    company: {l['raw_co']}")
    print(f"    адрес:   {l['address'][:80]}")
    print(f"    в срезах до покупки: {', '.join(snap_labels)}")

# Разбивка по количеству пре-sale срезов
from collections import Counter
count_dist = Counter(len(v) for v in presale_hits.values())
print(f"\nРаспределение по числу досрочных срезов:")
for k in sorted(count_dist):
    print(f"  {k} срез(а): {count_dist[k]} лотов")
