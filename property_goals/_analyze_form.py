import csv
from pathlib import Path
from collections import defaultdict

ENRICHED = Path(__file__).resolve().parent / "investmoscow_sold_2022_2026_enriched_geo.csv"

buckets = defaultdict(lambda: {"total": 0, "new_biz": 0, "existing": 0, "unmatched": 0})

with ENRICHED.open(encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        forma = (row.get("форма_проведения") or "").strip()
        conf  = (row.get("match_confidence") or "").strip()

        # упрощаем до 3 категорий
        if "публичн" in forma.lower():
            key = "Публичное предложение"
        elif "аукцион" in forma.lower():
            key = "Аукцион"
        else:
            key = "Другое"

        buckets[key]["total"] += 1
        if conf in ("high", "medium", "low"):
            buckets[key]["new_biz"] += 1
        elif conf == "existing_tenant":
            buckets[key]["existing"] += 1
        else:
            buckets[key]["unmatched"] += 1

print(f"{'Форма':<30} {'Всего':>6} {'Новый':>8} {'Действ.':>8} {'Не найден':>10}  {'%новый':>7} {'%действ.':>9} {'%матч':>7}")
print("-" * 90)
for key in ["Аукцион", "Публичное предложение", "Другое"]:
    b = buckets[key]
    t = b["total"]
    if t == 0:
        continue
    pct_new  = b["new_biz"]   / t * 100
    pct_ex   = b["existing"]  / t * 100
    pct_match = (b["new_biz"] + b["existing"]) / t * 100
    print(f"{key:<30} {t:>6} {b['new_biz']:>8} {b['existing']:>8} {b['unmatched']:>10}  {pct_new:>6.1f}% {pct_ex:>8.1f}% {pct_match:>6.1f}%")

# Итого
print("-" * 90)
total_all = sum(b["total"] for b in buckets.values())
total_new = sum(b["new_biz"] for b in buckets.values())
total_ex  = sum(b["existing"] for b in buckets.values())
total_un  = sum(b["unmatched"] for b in buckets.values())
print(f"{'ИТОГО':<30} {total_all:>6} {total_new:>8} {total_ex:>8} {total_un:>10}  {total_new/total_all*100:>6.1f}% {total_ex/total_all*100:>8.1f}% {(total_new+total_ex)/total_all*100:>6.1f}%")

# Дополнительно: по годам × форма
print("\n\nДействующий арендатор (%) по году и форме:")
year_form = defaultdict(lambda: {"total": 0, "existing": 0})
with ENRICHED.open(encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        forma = (row.get("форма_проведения") or "").strip()
        conf  = (row.get("match_confidence") or "").strip()
        year  = (row.get("год_торгов") or "").strip()
        key = "Публ." if "публичн" in forma.lower() else "Аукцион"
        year_form[(year, key)]["total"] += 1
        if conf == "existing_tenant":
            year_form[(year, key)]["existing"] += 1

years = sorted(set(k[0] for k in year_form))
print(f"{'Год':<6} {'Аукцион %действ.':>18} {'Публ. %действ.':>16}")
for yr in years:
    auc = year_form.get((yr, "Аукцион"), {"total":0,"existing":0})
    pub = year_form.get((yr, "Публ."), {"total":0,"existing":0})
    auc_pct = auc["existing"]/auc["total"]*100 if auc["total"] else 0
    pub_pct = pub["existing"]/pub["total"]*100 if pub["total"] else 0
    print(f"{yr:<6} {auc_pct:>14.1f}%   (n={auc['total']:4})  {pub_pct:>10.1f}%  (n={pub['total']:4})")
