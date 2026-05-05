"""
Merge existing-tenant buyout candidates into the enriched CSV.

For each unmatched lot that has stable businesses nearby (from detect_tenant_buyout.py):
  1. Filter candidates by area compatibility and floor requirements
  2. Remove implausible types
  3. Write ALL valid candidates (pipe-separated) to the lot
  4. Set match_confidence = "existing_tenant", match_time_window = "existing_tenant_buyout"

Only processes currently UNMATCHED lots — never overwrites existing matches.

Outputs:
  investmoscow_sold_2022_2026_enriched_geo.csv — updated in-place
  matches/tenant_buyout_merge_report.csv        — per-lot summary
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

BASE_DIR   = Path(__file__).resolve().parent
MATCH_DIR  = BASE_DIR / "matches"

ENRICHED_PATH    = BASE_DIR / "investmoscow_sold_2022_2026_enriched_geo.csv"
CANDIDATES_PATH  = MATCH_DIR / "tenant_buyout_candidates.csv"
CHAINS_PATH      = BASE_DIR.parent / "retailstreets_parser" / "data" / "retailstreets_requirements.csv"
REPORT_PATH      = MATCH_DIR / "tenant_buyout_merge_report.csv"

AREA_MAX_MULTIPLIER = 4.0
AREA_MIN_MULTIPLIER = 0.25

IMPLAUSIBLE_SUBSTRINGS = [
    "Станции зарядки телефонов", "Станции зарядки мобильных телефонов",
    "Постаматы", "Питьевая вода", "Кофейные автоматы", "Банкоматы",
    "Терминалы оплаты", "Платёжные терминалы", "Детские развлекательные автоматы",
    "Фотокабины / Автоматы фотопечати", "Копировальные услуги",
    "Государственные дошкольные учреждения", "Общеобразовательные школы",
    "Органы государственной власти", "Многофункциональные центры", "Библиотеки",
    "Аварийные / справочные / экстренные службы", "Жилищно-коммунальные",
    "Правоохранительные органы", "Новостройки", "Общественные / политические организации",
]
IMPLAUSIBLE_NAME_SUBSTRINGS = [
    "банкомат", "5post", "5 post", "qiwi", "киви", "бери заряд",
    "автомат по продаже кофе", "кофейный автомат", "зарядная станция",
    "контейнер для сбора", "пункт сбора отработанных",
    "приема батареек", "приёма батареек", "добрыекрышечки", "немузеймусора",
    "автомат с ", "пункт приёма", "пункт приема", "автомат копировальных",
]
_ADDRESS_LIKE_RE = re.compile(
    r"\b(улица|переулок|проспект|бульвар|шоссе|набережная|площадь|проезд|тупик)\b.{0,30}\d",
    re.IGNORECASE,
)

USAGE_TO_RS_CATEGORY: list[tuple[str, str]] = [
    ("Пункты выдачи интернет-заказов",   "Пунк выдачи"),
    ("Супермаркеты",                      "Супермаркет/Гипермаркет"),
    ("Дарксторы",                         "Дарксторы"),
    ("Алкогольные напитки",               "Алкомаркеты"),
    ("Аптеки",                            "Аптеки"),
    ("Медицинские товары",                "Аптеки"),
    ("Быстрое питание",                   "Общепит"),
    ("Рестораны",                         "Общепит"),
    ("Кафе",                              "Общепит"),
    ("Бары",                              "Общепит"),
    ("Продуктовые магазины",              "Продукты"),
    ("Доставка продуктов",                "Продукты"),
    ("Барбершопы",                        "Салоны красоты, барбершопы, парикмахерские"),
    ("Парикмахерские",                    "Салоны красоты, барбершопы, парикмахерские"),
    ("Ювелирн",                           "Ювелирный"),
    ("Оптика",                            "Оптика"),
    ("Обувь",                             "Обувь"),
    ("Спортивн",                          "Спорт"),
    ("Товары для дома",                   "Товары для дома"),
    ("Мебель",                            "Мебель"),
    ("Стройматериалы",                    "Стройматериалы"),
    ("Электронник",                       "Электронника, бытовая техника"),
    ("Бытовая техника",                   "Электронника, бытовая техника"),
    ("Зоомагазин",                        "Зоомагазины"),
    ("Уход за животными",                 "Зоомагазины"),
    ("Детские товары",                    "Детские товары"),
    ("Банки",                             "Банки"),
    ("Страхование",                       "Банки"),
    ("Кофе с собой",                      "Кофе с собой"),
    ("Салоны связи",                      "Салоны связи"),
    ("Парфюмери",                         "Парфюмерия и косметика"),
    ("Косметик",                          "Парфюмерия и косметика"),
    ("Пункт выдачи",                      "Пунк выдачи"),
]


def build_rs_area_limits(chains_path: Path) -> dict[str, tuple[float, float]]:
    df = pd.read_csv(chains_path)
    limits: dict[str, tuple[float, float]] = {}
    for cat, grp in df.groupby("category"):
        min_vals = grp["area_min_m2"].dropna()
        max_vals = grp["area_max_m2"].dropna()
        if min_vals.empty and max_vals.empty:
            continue
        hard_min = float(min_vals.min()) * AREA_MIN_MULTIPLIER if not min_vals.empty else 0.0
        hard_max = float(max_vals.quantile(0.75)) * AREA_MAX_MULTIPLIER if not max_vals.empty else float("inf")
        limits[str(cat)] = (hard_min, hard_max)
    return limits


def build_first_floor_chains(chains_path: Path) -> set[str]:
    chains: set[str] = set()
    with chains_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            fl = (row.get("floor") or "").lower().strip()
            if not fl:
                continue
            if "подвал" in fl or "цоколь" in fl:
                continue
            if any(x in fl for x in ("1 этаж", "первый этаж", "1-ом", "1-й", "1 эт")):
                chains.add((row.get("name") or "").lower().strip())
    return chains


def is_pure_basement(floor_str: str) -> bool:
    fl = floor_str.lower()
    if "подвал" not in fl:
        return False
    return not re.search(r"[1-9]", fl)


def usage_to_rs_category(usage: str) -> str | None:
    lower = usage.lower()
    for keyword, cat in USAGE_TO_RS_CATEGORY:
        if keyword.lower() in lower:
            return cat
    return None


def is_implausible(name: str, usage: str) -> bool:
    if any(s in usage for s in IMPLAUSIBLE_SUBSTRINGS):
        return True
    n = name.lower()
    if any(s.lower() in n for s in IMPLAUSIBLE_NAME_SUBSTRINGS):
        return True
    return bool(_ADDRESS_LIKE_RE.search(name))


def floor_blocked(company: str, lot_floor: str, first_floor_chains: set[str]) -> bool:
    if not is_pure_basement(lot_floor):
        return False
    comp_lower = company.lower().replace("&", " и ").replace("  ", " ")
    return any(chain in comp_lower for chain in first_floor_chains if chain)


def area_blocked(lot_area: float | None, usage: str, rs_limits: dict) -> bool:
    if lot_area is None:
        return False
    cat = usage_to_rs_category(usage)
    if cat is None or cat not in rs_limits:
        return False
    hard_min, hard_max = rs_limits[cat]
    return lot_area < hard_min or lot_area > hard_max


def compact(items: list[str], limit: int = 10) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for v in items:
        v = v.strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return " | ".join(out[:limit])


def main():
    rs_limits        = build_rs_area_limits(CHAINS_PATH)
    first_floor_chains = build_first_floor_chains(CHAINS_PATH)
    print(f"Area limits: {len(rs_limits)} categories, 1st-floor-only chains: {len(first_floor_chains)}")

    # Load all candidates grouped by lot_id, sorted by distance
    candidates_by_lot: dict[str, list[dict]] = defaultdict(list)
    with CANDIDATES_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            candidates_by_lot[row["lot_id"]].append(row)

    # Sort each lot's candidates by distance
    for lot_id in candidates_by_lot:
        candidates_by_lot[lot_id].sort(key=lambda r: float(r["distance_m"]))

    print(f"Lots with buyout candidates: {len(candidates_by_lot)}")

    # Load enriched CSV
    with ENRICHED_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    added   = 0
    skipped_matched = 0
    skipped_no_valid = 0
    report_rows = []

    for row in rows:
        lot_id = row.get("номер_лота", "").strip()

        # Skip already matched lots
        if row.get("match_confidence", "").strip():
            skipped_matched += 1
            continue

        candidates = candidates_by_lot.get(lot_id, [])
        if not candidates:
            continue

        lot_floor = (row.get("этаж") or "").strip()
        lot_area_raw = (row.get("площадь_м²") or "").replace(",", ".").strip()
        try:
            lot_area: float | None = float(lot_area_raw)
        except ValueError:
            lot_area = None

        # Filter candidates
        valid: list[dict] = []
        dropped: list[str] = []
        for c in candidates:
            name  = c["business_name"]
            usage = c["business_usage"]

            if is_implausible(name, usage):
                dropped.append(f"{name} [implausible]")
                continue
            if floor_blocked(name, lot_floor, first_floor_chains):
                dropped.append(f"{name} [floor]")
                continue
            if area_blocked(lot_area, usage, rs_limits):
                dropped.append(f"{name} [area]")
                continue

            valid.append(c)

        # Deduplicate by name (keep closest)
        seen_names: set[str] = set()
        deduped: list[dict] = []
        for c in valid:
            key = c["business_name"].lower().strip()
            if key not in seen_names:
                seen_names.add(key)
                deduped.append(c)

        if not deduped:
            skipped_no_valid += 1
            report_rows.append({
                "lot_id": lot_id, "status": "no_valid_candidates",
                "candidates_total": len(candidates), "candidates_valid": 0,
                "companies": "", "dropped": compact(dropped, 5),
            })
            continue

        companies = [c["business_name"] for c in deduped]
        usages    = [c["business_usage"] for c in deduped]

        row["likely_company"]            = compact(companies)
        row["likely_usage"]              = compact(usages)
        row["match_confidence"]          = "existing_tenant"
        row["match_time_window"]         = "existing_tenant_buyout"
        row["company_candidates_preview"] = compact(companies)
        row["usage_candidates_preview"]  = compact(usages)
        row["match_after_days"]          = ""
        row["match_before_snapshot_label"] = ""
        row["match_after_snapshot_label"]  = ""

        added += 1
        report_rows.append({
            "lot_id": lot_id, "status": "added",
            "candidates_total": len(candidates), "candidates_valid": len(deduped),
            "companies": compact(companies, 3), "dropped": compact(dropped, 3),
        })

    # Write updated CSV
    with ENRICHED_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Write report
    MATCH_DIR.mkdir(exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["lot_id", "status", "candidates_total", "candidates_valid", "companies", "dropped"])
        w.writeheader()
        w.writerows(report_rows)

    print(f"\n=== Merge complete ===")
    print(f"  Added (existing_tenant):     {added}")
    print(f"  Skipped (no valid cands):    {skipped_no_valid}")
    print(f"  Skipped (already matched):   {skipped_matched}")
    total_matched = sum(1 for r in rows if r.get("match_confidence", "").strip())
    print(f"  Total matched in CSV:        {total_matched}")
    print(f"  Report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
