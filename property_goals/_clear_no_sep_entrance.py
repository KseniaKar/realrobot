"""
Очищаем матчи, где likely_company — алкомаркет, а тип входа не является
отдельным входом с улицы.

Основание: 171-ФЗ ст. 16 + СП 54.13330 — алкомаркет в жилом доме требует
отдельного входа с улицы (не через подъезд и не через места общего пользования).

match_confidence → cleared_no_sep_entrance, likely_company / likely_usage /
company_candidates_preview / match_time_window → "".
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
    if not company_raw:
        return False
    parts = [p.split("(")[0].strip().lower() for p in company_raw.split("|")]
    return any(a in p or p in a for p in parts for a in ALCOHOL_NAMES)


def has_separate_entrance(tip_vhoda_raw):
    """True если вход отдельный с улицы."""
    return "отдельный" in tip_vhoda_raw.lower()


bak = ENRICHED.with_suffix(".csv.bak_nosep")
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
        tip_vhoda = row.get("тип_входа", "").strip()

        if (
            conf in ALL_MATCH_CONF
            and company
            and is_alcohol(company)
            and not has_separate_entrance(tip_vhoda)
        ):
            cleared.append({
                "lot_id":    row["номер_лота"],
                "conf":      conf,
                "company":   company[:60],
                "tip_vhoda": tip_vhoda,
                "addr":      row.get("адрес", "")[:60],
            })
            row["match_confidence"]           = "cleared_no_sep_entrance"
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
    print(f"  лот {c['lot_id']}  conf={c['conf']}  вход: {c['tip_vhoda']}")
    print(f"    {c['company']}")
    print(f"    {c['addr']}")
