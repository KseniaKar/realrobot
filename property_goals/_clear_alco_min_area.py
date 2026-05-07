"""
Очищаем матчи, где likely_company — алкомаркет (первый в списке),
а площадь лота < 50 кв.м.

Основание: 171-ФЗ ст. 18 + Постановление Правительства Москвы —
для розничной торговли алкоголем в Москве площадь помещения не менее 50 кв.м.

match_confidence → cleared_area_mismatch.
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
MIN_AREA = 50.0


def primary_is_alcohol(company_raw):
    """True если ПЕРВЫЙ кандидат в pipe-списке — алкомаркет."""
    if not company_raw:
        return False
    first = company_raw.split("|")[0].split("(")[0].strip().lower()
    return any(a in first or first in a for a in ALCOHOL_NAMES)


def parse_area(raw):
    try:
        return float(str(raw).replace(",", ".").strip())
    except (ValueError, TypeError):
        return None


bak = ENRICHED.with_suffix(".csv.bak_alcoarea")
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
        company = row.get("likely_company", "").strip()
        area = parse_area(row.get("площадь_м²", ""))

        if (
            conf in ALL_MATCH_CONF
            and company
            and primary_is_alcohol(company)
            and area is not None
            and area < MIN_AREA
        ):
            cleared.append({
                "lot_id":  row["номер_лота"],
                "conf":    conf,
                "company": company[:60],
                "area":    area,
                "addr":    row.get("адрес", "")[:60],
            })
            row["match_confidence"]           = "cleared_area_mismatch"
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
    print(f"  Лот {c['lot_id']}  conf={c['conf']}  {c['area']} m2  {c['company']}")
    print(f"    {c['addr']}")
