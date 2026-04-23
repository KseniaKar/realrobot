from __future__ import annotations

import csv
import shutil
from datetime import date
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
MATCH_DIR = BASE_DIR / "matches"

LOTS_SRC = BASE_DIR / "investmoscow_sold_2022_2026_clean.with_norm.csv"
LIKELY_CURRENT = MATCH_DIR / "property_usage_likely_summary_geo.csv"
LIKELY_UNFILTERED = MATCH_DIR / "property_usage_likely_summary_geo_unfiltered.csv"

LIKELY_OUT = MATCH_DIR / "property_usage_likely_summary_geo.csv"
LIKELY_TIME_OUT = MATCH_DIR / "property_usage_likely_summary_geo_time_filtered.csv"
ENRICHED_OUT = BASE_DIR / "investmoscow_sold_2022_2026_enriched_geo.csv"

MIN_AFTER_DAYS = 180
MAX_AFTER_DAYS = 365


def parse_iso_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    return date.fromisoformat(value[:10])


def in_time_window(row: dict[str, str]) -> bool:
    purchase_date = parse_iso_date(row.get("purchase_date", ""))
    after_date = parse_iso_date(row.get("after_snapshot_date", ""))
    if not purchase_date or not after_date:
        return False
    after_days = (after_date - purchase_date).days
    return MIN_AFTER_DAYS <= after_days <= MAX_AFTER_DAYS


def after_days(row: dict[str, str]) -> str:
    purchase_date = parse_iso_date(row.get("purchase_date", ""))
    after_date = parse_iso_date(row.get("after_snapshot_date", ""))
    if not purchase_date or not after_date:
        return ""
    return str((after_date - purchase_date).days)


def main() -> None:
    if not LIKELY_UNFILTERED.exists():
        shutil.copyfile(LIKELY_CURRENT, LIKELY_UNFILTERED)

    kept_rows: list[dict[str, str]] = []
    total_rows = 0
    dropped_rows = 0

    with LIKELY_UNFILTERED.open("r", encoding="utf-8-sig", newline="") as src_f:
        reader = csv.DictReader(src_f)
        likely_fields = list(reader.fieldnames or [])
        if "after_days" not in likely_fields:
            likely_fields.append("after_days")
        if "time_window" not in likely_fields:
            likely_fields.append("time_window")

        for row in reader:
            total_rows += 1
            if not in_time_window(row):
                dropped_rows += 1
                continue
            row["after_days"] = after_days(row)
            row["time_window"] = f"{MIN_AFTER_DAYS}-{MAX_AFTER_DAYS}d"
            kept_rows.append(row)

    for output_path in (LIKELY_OUT, LIKELY_TIME_OUT):
        with output_path.open("w", encoding="utf-8-sig", newline="") as out_f:
            writer = csv.DictWriter(out_f, fieldnames=likely_fields)
            writer.writeheader()
            writer.writerows(kept_rows)

    likely_by_lot = {row["lot_id"]: row for row in kept_rows}

    with LOTS_SRC.open("r", encoding="utf-8-sig", newline="") as lots_f, ENRICHED_OUT.open(
        "w", encoding="utf-8-sig", newline=""
    ) as out_f:
        reader = csv.DictReader(lots_f)
        out_fields = list(reader.fieldnames or []) + [
            "match_before_snapshot_label",
            "match_after_snapshot_label",
            "match_before_company_count",
            "match_after_company_count",
            "match_new_company_count",
            "match_after_days",
            "match_time_window",
            "likely_company",
            "likely_usage",
            "match_confidence",
            "company_candidates_preview",
            "usage_candidates_preview",
        ]
        writer = csv.DictWriter(out_f, fieldnames=out_fields)
        writer.writeheader()

        for row in reader:
            lot_id = row.get("номер_лота", "") or row.get("РЅРѕРјРµСЂ_Р»РѕС‚Р°", "")
            match = likely_by_lot.get(lot_id, {})
            row["match_before_snapshot_label"] = match.get("before_snapshot_label", "")
            row["match_after_snapshot_label"] = match.get("after_snapshot_label", "")
            row["match_before_company_count"] = match.get("before_company_count", "")
            row["match_after_company_count"] = match.get("after_company_count", "")
            row["match_new_company_count"] = match.get("new_company_count", "")
            row["match_after_days"] = match.get("after_days", "")
            row["match_time_window"] = match.get("time_window", "")
            row["likely_company"] = match.get("likely_company", "")
            row["likely_usage"] = match.get("likely_usage", "")
            row["match_confidence"] = match.get("confidence", "")
            row["company_candidates_preview"] = match.get("company_candidates_preview", "")
            row["usage_candidates_preview"] = match.get("usage_candidates_preview", "")
            writer.writerow(row)

    print(
        {
            "source_matches": total_rows,
            "kept_matches": len(kept_rows),
            "dropped_matches": dropped_rows,
            "time_window_days": f"{MIN_AFTER_DAYS}-{MAX_AFTER_DAYS}",
            "unfiltered_src": str(LIKELY_UNFILTERED),
            "likely_out": str(LIKELY_OUT),
            "likely_time_out": str(LIKELY_TIME_OUT),
            "enriched_out": str(ENRICHED_OUT),
        }
    )


if __name__ == "__main__":
    main()
