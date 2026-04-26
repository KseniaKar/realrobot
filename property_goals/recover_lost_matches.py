"""
Recover matches for 2022-2024 lots that were excluded by the 180-365d time window.

These lots have geo-verified candidates (businesses appeared near them in the
2025-09 snapshot), but after_days > 365 so they were dropped.

Since there's a 4-year snapshot gap (2021-10 → 2025-09), this is the ONLY
available "after" data for 2022-2023 lots. We accept the wider window but:
  - Apply the same implausibility + area validation (revalidate_matches logic)
  - Mark with time_window = "first_after_snapshot"
  - Confidence based on geo distance (same as baseline)

Outputs:
  matches/recovered_matches_report.csv  — what was recovered + filtered
  investmoscow_sold_2022_2026_enriched_geo.csv  — updated in-place
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
MATCH_DIR = BASE_DIR / "matches"

ENRICHED_PATH = BASE_DIR / "investmoscow_sold_2022_2026_enriched_geo.csv"
BEST_SRC = MATCH_DIR / "property_usage_before_after_best_high_medium.csv"
GEO_SRC = MATCH_DIR / "property_usage_geo_verified.csv"
CHAINS_PATH = BASE_DIR.parent / "retailstreets_parser" / "data" / "retailstreets_requirements.csv"
REPORT_PATH = MATCH_DIR / "recovered_matches_report.csv"

MIN_AFTER_DAYS = 180        # require at least 180 days (don't match lots from week ago)
KEEP_DISTANCE_BANDS = {"0-30m", "30-100m", "100-250m"}

AREA_MAX_MULTIPLIER = 4.0
AREA_MIN_MULTIPLIER = 0.25

IMPLAUSIBLE_SUBSTRINGS = [
    "Станции зарядки телефонов",
    "Постаматы",
    "Питьевая вода",
    "Кофейные автоматы",
    "Аварийные / справочные / экстренные службы -> Справочные",
    "Жилищно-коммунальные",
    "Правоохранительные органы",
    "Новостройки -> Новостройки",
    "Общественные / политические организации",
]

IMPLAUSIBLE_NAME_SUBSTRINGS = [
    "контейнер для сбора",
    "пункт сбора отработанных",
    "приема батареек",
    "приёма батареек",
]

USAGE_TO_RS_CATEGORY: list[tuple[str, str]] = [
    ("Пункты выдачи интернет-заказов", "Пунк выдачи"),
    ("Супермаркеты",                   "Супермаркет/Гипермаркет"),
    ("Дарксторы",                      "Дарксторы"),
    ("Алкогольные напитки",            "Алкомаркеты"),
    ("Аптеки",                         "Аптеки"),
    ("Медицинские товары",             "Аптеки"),
    ("Быстрое питание",                "Общепит"),
    ("Рестораны",                      "Общепит"),
    ("Кафе",                           "Общепит"),
    ("Бары",                           "Общепит"),
    ("Продуктовые магазины",           "Продукты"),
    ("Доставка продуктов",             "Продукты"),
    ("Барбершопы",                     "Салоны красоты, барбершопы, парикмахерские"),
    ("Парикмахерские",                 "Салоны красоты, барбершопы, парикмахерские"),
    ("Ювелирн",                        "Ювелирный"),
    ("Оптика",                         "Оптика"),
    ("Обувь",                          "Обувь"),
    ("Спортивн",                       "Спорт"),
    ("Товары для дома",                "Товары для дома"),
    ("Мебель",                         "Мебель"),
    ("Стройматериалы",                 "Стройматериалы"),
    ("Натяжные потолки",               "Стройматериалы"),
    ("Электронник",                    "Электронника, бытовая техника"),
    ("Бытовая техника",                "Электронника, бытовая техника"),
    ("Зоомагазин",                     "Зоомагазины"),
    ("Уход за животными",              "Зоомагазины"),
    ("Детские товары",                 "Детские товары"),
    ("Банки",                          "Банки"),
    ("Страхование",                    "Банки"),
    ("Кофе с собой",                   "Кофе с собой"),
    ("Салоны связи",                   "Салоны связи"),
    ("Парфюмери",                      "Парфюмерия и косметика"),
    ("Косметик",                       "Парфюмерия и косметика"),
    ("Фото",                           "Фото/печатные салоны"),
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


def candidate_usage(row: dict) -> str:
    rubric = (row.get("match_rubric") or "").strip()
    subrubric = (row.get("match_subrubric") or "").strip()
    if rubric and subrubric:
        return f"{rubric} -> {subrubric}"
    return rubric or subrubric


def usage_to_rs_category(usage: str) -> str | None:
    lower = usage.lower()
    for keyword, cat in USAGE_TO_RS_CATEGORY:
        if keyword.lower() in lower:
            return cat
    return None


def is_implausible(usage: str) -> bool:
    for pattern in IMPLAUSIBLE_SUBSTRINGS:
        if pattern.lower() in usage.lower():
            return True
    return False


def is_implausible_name(name: str) -> bool:
    lower = name.lower()
    return any(sub.lower() in lower for sub in IMPLAUSIBLE_NAME_SUBSTRINGS)


def area_ok(lot_area: float | None, rs_cat: str | None, limits: dict) -> bool:
    if lot_area is None or rs_cat is None or rs_cat not in limits:
        return True
    hard_min, hard_max = limits[rs_cat]
    return hard_min <= lot_area <= hard_max


def compact(values: list[str], limit: int = 5) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        v = v.strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return " | ".join(out[:limit])


def normalize_confidence(base_conf: str, distance_band: str) -> str:
    if distance_band in {"0-30m", "30-100m"}:
        return base_conf
    if distance_band == "100-250m":
        return "low"
    return ""


def main() -> None:
    rs_limits = build_rs_area_limits(CHAINS_PATH)

    # Load already-matched lots
    with ENRICHED_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    already_matched = {
        row["номер_лота"]
        for row in rows
        if (row.get("match_confidence") or "").strip()
    }
    lot_by_id = {row["номер_лота"]: row for row in rows}

    # Load best candidates (lots with geo matches, possibly outside time window)
    best_by_lot: dict[str, dict] = {}
    with BEST_SRC.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            lot_id = str(row["lot_id"])
            purchase_date = row.get("purchase_date", "")
            after_date = row.get("after_snapshot_date", "")
            if not purchase_date or not after_date:
                continue
            from datetime import date
            try:
                pd_obj = date.fromisoformat(purchase_date[:10])
                ad_obj = date.fromisoformat(after_date[:10])
                after_days = (ad_obj - pd_obj).days
            except Exception:
                continue
            if after_days <= MIN_AFTER_DAYS:
                continue
            if lot_id in already_matched:
                continue
            best_by_lot[lot_id] = dict(row, _after_days=after_days)

    print(f"Unmatched lots with geo candidates (after_days > {MIN_AFTER_DAYS}): {len(best_by_lot)}")

    # Load geo candidates for these lots
    geo_by_lot: dict[str, list[dict]] = {}
    with GEO_SRC.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            lot_id = str(row["lot_id"])
            if lot_id not in best_by_lot:
                continue
            if row.get("distance_band", "") not in KEEP_DISTANCE_BANDS:
                continue
            geo_by_lot.setdefault(lot_id, []).append(row)

    # Get lot areas from enriched data
    lot_areas: dict[str, float | None] = {}
    for row in rows:
        try:
            lot_areas[row["номер_лота"]] = float(str(row.get("площадь_м²", "")).replace(",", "."))
        except Exception:
            lot_areas[row["номер_лота"]] = None

    report_rows = []
    added = 0
    filtered_out = 0

    for lot_id, best in best_by_lot.items():
        candidates = geo_by_lot.get(lot_id, [])
        if not candidates:
            continue

        lot_area = lot_areas.get(lot_id)
        valid_names, valid_usages, dropped_info = [], [], []

        for cand in candidates:
            usage = candidate_usage(cand)
            name = cand.get("match_name", "")
            if is_implausible(usage) or is_implausible_name(name):
                dropped_info.append(f"IMPLAUSIBLE: {name} ({usage[:60]})")
                continue
            rs_cat = usage_to_rs_category(usage)
            if not area_ok(lot_area, rs_cat, rs_limits):
                hard_min, hard_max = rs_limits.get(rs_cat, (0, 0))
                dropped_info.append(f"AREA({lot_area:.0f}m² vs {hard_min:.0f}-{hard_max:.0f}): {cand.get('match_name','')}")
                continue
            valid_names.append(cand.get("match_name", ""))
            valid_usages.append(usage)

        if not valid_names:
            filtered_out += 1
            report_rows.append({
                "lot_id": lot_id,
                "status": "all_filtered",
                "after_days": best["_after_days"],
                "after_snapshot": best.get("after_snapshot_label", ""),
                "confidence": "",
                "likely_company": "",
                "dropped": " || ".join(dropped_info[:3]),
            })
            continue

        # Determine confidence
        best_band = candidates[0].get("distance_band", "")
        base_conf = best.get("confidence", "medium")
        match_conf = normalize_confidence(base_conf, best_band)
        if not match_conf:
            filtered_out += 1
            continue

        # Downgrade wide-window matches: high → medium
        if best["_after_days"] > 365 and match_conf == "high":
            match_conf = "medium"

        if match_conf == "high" and len(valid_names) == 1:
            likely_company = valid_names[0]
            likely_usage = valid_usages[0]
        else:
            likely_company = compact(valid_names, 3)
            likely_usage = compact(valid_usages, 3)

        # Write to enriched row
        lot_row = lot_by_id.get(lot_id)
        if not lot_row:
            continue

        lot_row["match_before_snapshot_label"] = best.get("before_snapshot_label", "")
        lot_row["match_after_snapshot_label"] = best.get("after_snapshot_label", "")
        lot_row["match_before_company_count"] = best.get("before_company_count", "")
        lot_row["match_after_company_count"] = best.get("after_company_count", "")
        lot_row["match_new_company_count"] = best.get("new_company_count", "")
        lot_row["match_after_days"] = str(best["_after_days"])
        lot_row["match_time_window"] = f"first_after_snapshot_{best.get('after_snapshot_label', '')}"
        lot_row["likely_company"] = likely_company
        lot_row["likely_usage"] = likely_usage
        lot_row["match_confidence"] = match_conf
        lot_row["company_candidates_preview"] = compact(valid_names)
        lot_row["usage_candidates_preview"] = compact(valid_usages)

        added += 1
        report_rows.append({
            "lot_id": lot_id,
            "status": "added",
            "after_days": best["_after_days"],
            "after_snapshot": best.get("after_snapshot_label", ""),
            "confidence": match_conf,
            "likely_company": likely_company,
            "dropped": " || ".join(dropped_info[:3]),
        })

    # Save updated enriched
    with ENRICHED_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    MATCH_DIR.mkdir(exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        report_fields = ["lot_id", "status", "after_days", "after_snapshot", "confidence", "likely_company", "dropped"]
        writer = csv.DictWriter(f, fieldnames=report_fields)
        writer.writeheader()
        writer.writerows(report_rows)

    total = added + filtered_out
    print(f"Lots processed (had geo candidates): {total}")
    print(f"  added to matches:    {added}")
    print(f"  filtered out:        {filtered_out}")
    print(f"\nReport: {REPORT_PATH.name}")
    print(f"Enriched CSV updated: {ENRICHED_PATH.name}")


if __name__ == "__main__":
    main()
