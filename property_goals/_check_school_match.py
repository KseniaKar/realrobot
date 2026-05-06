import csv
from pathlib import Path

ENRICHED = Path(__file__).resolve().parent / "investmoscow_sold_2022_2026_enriched_geo.csv"

ALCOHOL_NAMES = {
    "красное и белое", "красное&белое", "красное & белое",
    "бристоль", "винлаб", "ароматный мир", "мильстрим",
    "градусы", "winestyle", "wine style", "simple wine", "бутыль",
}

hits = []
with ENRICHED.open(encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        if row.get("near_school_100m", "").strip() != "1":
            continue
        company = row.get("likely_company", "").strip().lower()
        if not company:
            continue
        parts = [p.split("(")[0].strip().lower() for p in company.split("|")]
        matched_alco = [p for p in parts if any(a in p or p in a for a in ALCOHOL_NAMES)]
        if matched_alco:
            hits.append({
                "лот":     row["номер_лота"],
                "company": row["likely_company"],
                "conf":    row["match_confidence"],
                "dist_m":  row.get("nearest_school_m", ""),
                "school":  row.get("nearest_school_name", "")[:70],
                "адрес":   row.get("адрес", "")[:70],
            })

print(f"Лотов near_school + алко-арендатор в likely_company: {len(hits)}")
for h in hits:
    print(f"  лот {h['лот']}  conf={h['conf']}  dist={h['dist_m']}м")
    print(f"    company: {h['company']}")
    print(f"    адрес:   {h['адрес']}")
    print(f"    школа:   {h['school']}")
