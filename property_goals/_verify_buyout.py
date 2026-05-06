"""
Проверяем гипотезу: публичное предложение + действующий арендатор = выкуп арендатором.
Смотрим: цену, скидку, площадь, участников торгов.
"""
import csv
from pathlib import Path
from collections import defaultdict
import statistics

ENRICHED = Path(__file__).resolve().parent / "investmoscow_sold_2022_2026_enriched_geo.csv"
PROTO_JSON = Path(__file__).resolve().parent.parent / "web-parsers" / "investmoskow_before" / "data" / "protocols" / "protocol_cache.json"

import json
participants = {}
if PROTO_JSON.exists():
    with open(PROTO_JSON, encoding="utf-8") as f:
        cache = json.load(f)
    participants = {int(k): v.get("participants_count") for k, v in cache.items()}

def to_float(v):
    try:
        return float(str(v).strip().replace(",", ".").replace("%", ""))
    except Exception:
        return None

def to_int(v):
    try:
        return int(str(v).strip())
    except Exception:
        return None

# 4 группы: (форма) × (тип матча)
groups = {
    "АУК / новый":    {"excess": [], "area": [], "price_m2": [], "participants": []},
    "АУК / действ.":  {"excess": [], "area": [], "price_m2": [], "participants": []},
    "ПУБЛ / новый":   {"excess": [], "area": [], "price_m2": [], "participants": []},
    "ПУБЛ / действ.": {"excess": [], "area": [], "price_m2": [], "participants": []},
}

with ENRICHED.open(encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        forma = (row.get("форма_проведения") or "").strip().lower()
        conf  = (row.get("match_confidence") or "").strip()

        is_pub = "публичн" in forma
        is_new = conf in ("high", "medium", "low")
        is_ex  = conf == "existing_tenant"

        if not (is_new or is_ex):
            continue

        form_key  = "ПУБЛ" if is_pub else "АУК"
        match_key = "действ." if is_ex else "новый"
        key = f"{form_key} / {match_key}"

        excess  = to_float(row.get("превышение_цены_%"))
        area    = to_float(row.get("площадь_м²"))
        start   = to_float(row.get("начальная_цена_руб"))
        final   = to_float(row.get("итоговая_цена_руб"))
        lot_id  = to_int(row.get("номер_лота"))

        # считаем превышение сами для публ. (там на сайте нет)
        if excess is None and start and final and start > 0:
            excess = (final - start) / start * 100

        price_m2 = to_float(row.get("цена_за_м²"))
        if price_m2 is None and area and final and area > 0:
            price_m2 = final / area

        p = participants.get(lot_id)
        if isinstance(p, (int, float)):
            groups[key]["participants"].append(p)

        if excess is not None:  groups[key]["excess"].append(excess)
        if area    is not None: groups[key]["area"].append(area)
        if price_m2 is not None: groups[key]["price_m2"].append(price_m2)

def med(lst):
    return statistics.median(lst) if lst else float("nan")

def pct(lst, threshold):
    return sum(1 for x in lst if x < threshold) / len(lst) * 100 if lst else float("nan")

print(f"\n{'Gruppa':<20} {'n':>5}  {'med.ploshad':>12}  {'med.cena/m2':>13}  "
      f"{'med.prevysh':>12}  {'dolya snizh':>12}  {'med.uchast':>11}")
print("-" * 100)

for key in ["АУК / новый", "АУК / действ.", "ПУБЛ / новый", "ПУБЛ / действ."]:
    g = groups[key]
    n = len(g["excess"])
    pct_neg = pct(g["excess"], 0)
    m_part = med(g["participants"])
    m_part_str = f"{m_part:.1f}" if isinstance(m_part, float) and m_part == m_part else "—"
    print(
        f"{key:<20} {n:>5}  "
        f"{med(g['area']):>10.0f} m2  "
        f"{med(g['price_m2'])/1000:>11.0f} tr  "
        f"{med(g['excess']):>+11.1f}%  "
        f"{pct_neg:>11.0f}%  "
        f"{m_part_str:>11}"
    )

print()
print("=== Интерпретация ===")
pub_ex  = groups["ПУБЛ / действ."]["excess"]
pub_new = groups["ПУБЛ / новый"]["excess"]
auc_ex  = groups["АУК / действ."]["excess"]
auc_new = groups["АУК / новый"]["excess"]

print(f"ПУБЛ/действ. vs ПУБЛ/новый: {med(pub_ex):+.1f}% vs {med(pub_new):+.1f}%")
print(f"АУК/действ.  vs АУК/новый:  {med(auc_ex):+.1f}% vs {med(auc_new):+.1f}%")
print()
print(f"Доля с отрицательным превышением (снижение от старта):")
print(f"  ПУБЛ/действ.: {pct(pub_ex, 0):.0f}%  — ПУБЛ/новый: {pct(pub_new, 0):.0f}%")
print(f"  АУК/действ.:  {pct(auc_ex, 0):.0f}%  — АУК/новый:  {pct(auc_new, 0):.0f}%")

# Участники
print()
print("Медиана участников торгов:")
for key in ["АУК / новый", "АУК / действ.", "ПУБЛ / новый", "ПУБЛ / действ."]:
    p = groups[key]["participants"]
    print(f"  {key}: {med(p):.1f}  (n={len(p)})")
