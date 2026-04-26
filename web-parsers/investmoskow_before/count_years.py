import json
from datetime import datetime
from collections import Counter

CACHE = r'C:\git\realrobot\web-parsers\investmoskow_before\data\all_tenders_cache.json'

with open(CACHE, encoding='utf-8') as f:
    tenders = json.load(f)

print(f"Всего в кэше: {len(tenders)}")

years = Counter()
for t in tenders:
    end = t.get('requestEndDate', '')
    if end:
        try:
            dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
            years[dt.year] += 1
        except:
            pass

print(f"\nПо годам:")
for y in sorted(years.keys()):
    print(f"  {y}: {years[y]} лотов")
