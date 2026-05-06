import csv
from pathlib import Path

ENRICHED = Path(__file__).resolve().parent / "investmoscow_sold_2022_2026_enriched_geo.csv"

NEW_BIZ_CONF = {"high", "medium", "low"}

def normalize(name):
    return name.split("(")[0].split(",")[0].strip().lower()

def in_pipe(field_val, company):
    entries = [normalize(e) for e in (field_val or "").split("|")]
    return any(company in e or e in company for e in entries if e)

total_new_biz = 0
overlap_history = 0
overlap_were    = 0
overlap_now     = 0
examples_were = []
examples_now  = []

with ENRICHED.open(encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        conf = (row.get("match_confidence") or "").strip()
        if conf not in NEW_BIZ_CONF:
            continue
        total_new_biz += 1

        company = normalize(row.get("likely_company") or "")
        if not company:
            continue

        hist = row.get("история_бизнесов", "")
        were = row.get("были_в_здании", "")
        now  = row.get("сейчас_в_здании", "")

        if in_pipe(hist, company):  overlap_history += 1
        if in_pipe(were, company):
            overlap_were += 1
            if len(examples_were) < 8:
                examples_were.append(row)
        if in_pipe(now, company):   overlap_now     += 1

print(f"Всего new_business: {total_new_biz}")
print(f"likely_company в история_бизнесов: {overlap_history}  ({overlap_history/total_new_biz:.1%})")
print(f"likely_company в сейчас_в_здании:  {overlap_now}  ({overlap_now/total_new_biz:.1%})")
print(f"likely_company в были_в_здании:    {overlap_were}  ({overlap_were/total_new_biz:.1%})")

print("\n=== Примеры: likely_company в были_в_здании ===")
for r in examples_were:
    print(f"  лот {r['номер_лота']}  дата={r.get('дата_подведения_итогов','')[:10]}"
          f"  conf={r['match_confidence']}  company={r['likely_company']}")
    print(f"    были: {r.get('были_в_здании','')[:150]}")
