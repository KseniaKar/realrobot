"""
Очищаем матчи, где likely_company — алкомаркет, а лот находится ≤100м от школы/детсада.
Основание: 171-ФЗ ст. 16, Постановление Москвы 1069-ПП (запретная зона 100м).

match_confidence → cleared_school_zone, likely_company/likely_usage/company_candidates_preview/match_time_window → "".
"""
import csv
import shutil
from pathlib import Path

ENRICHED = Path(__file__).resolve().parent / "investmoscow_sold_2022_2026_enriched_geo.csv"

ALCOHOL_NAMES = {
    "красное и белое", "красное&белое", "красное & белое",
    "бристоль", "винлаб", "ароматный мир", "мильстрим",
    "градусы", "winestyle", "wine style", "simple wine", "бутыль",
}

ALL_MATCH_CONF = {"high", "medium", "low", "existing_tenant"}


def is_alcohol(company_raw):
    parts = [p.split("(")[0].strip().lower() for p in company_raw.split("|")]
    return any(a in p or p in a for p in parts for a in ALCOHOL_NAMES)


bak = ENRICHED.with_suffix(".csv.bak_school")
if not bak.exists():
    shutil.copy2(ENRICHED, bak)
    print(f"Бэкап: {bak.name}")

rows = []
cleared = []

with ENRICHED.open(encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    for row in reader:
        conf = (row.get("match_confidence") or "").strip()
        near_raw = row.get("near_school_100m", "").strip()
        near = near_raw in ("1", "1.0")
        company = row.get("likely_company", "").strip()
        if conf in ALL_MATCH_CONF and near and company and is_alcohol(company):
            cleared.append({
                "lot_id":  row["номер_лота"],
                "conf":    conf,
                "company": company[:60],
                "dist_m":  row.get("nearest_school_m", ""),
                "school":  row.get("nearest_school_name", "")[:60],
            })
            row["match_confidence"]           = "cleared_school_zone"
            row["match_time_window"]          = ""
            row["likely_company"]             = ""
            row["likely_usage"]               = ""
            row["company_candidates_preview"] = ""
        rows.append(row)

with ENRICHED.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print(f"Очищено матчей: {len(cleared)}")
for c in cleared:
    print(f"  лот {c['lot_id']}  conf={c['conf']}  dist={c['dist_m']}м  {c['company']}")
    print(f"    школа: {c['school']}")
