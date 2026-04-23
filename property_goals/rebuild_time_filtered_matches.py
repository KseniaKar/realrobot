from __future__ import annotations

import csv
import shutil
from calendar import monthrange
from datetime import date
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
MATCH_DIR = BASE_DIR / "matches"
MOSCOW_DIR = BASE_DIR / "moscow"

LOTS_SRC = BASE_DIR / "investmoscow_sold_2022_2026_clean.with_norm.csv"
BEST_SRC = MATCH_DIR / "property_usage_before_after_best_high_medium.csv"
GEO_SRC = MATCH_DIR / "property_usage_geo_verified.csv"
LIKELY_CURRENT = MATCH_DIR / "property_usage_likely_summary_geo.csv"
LIKELY_UNFILTERED = MATCH_DIR / "property_usage_likely_summary_geo_unfiltered.csv"

LIKELY_OUT = MATCH_DIR / "property_usage_likely_summary_geo.csv"
LIKELY_TIME_OUT = MATCH_DIR / "property_usage_likely_summary_geo_time_filtered.csv"
ENRICHED_OUT = BASE_DIR / "investmoscow_sold_2022_2026_enriched_geo.csv"

MIN_AFTER_DAYS = 180
MAX_AFTER_DAYS = 365
KEEP_DISTANCE_BANDS = {"0-30m", "30-100m", "100-250m"}

SNAPSHOT_LABELS = [
    "2020-04",
    "2020-08",
    "2021-03",
    "2021-05",
    "2021-07",
    "2021-10",
    "2025-09",
    "2025-11",
    "2026-02",
    "2026-03",
]


def parse_iso_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    return date.fromisoformat(value[:10])


def month_end(label: str) -> date:
    year, month = map(int, label.split("-"))
    return date(year, month, monthrange(year, month)[1])


SNAPSHOT_DATES = {label: month_end(label) for label in SNAPSHOT_LABELS}


def after_days(row: dict[str, str]) -> int | None:
    purchase_date = parse_iso_date(row.get("purchase_date", ""))
    after_date = parse_iso_date(row.get("after_snapshot_date", ""))
    if not purchase_date or not after_date:
        return None
    return (after_date - purchase_date).days


def in_time_window(row: dict[str, str]) -> bool:
    days = after_days(row)
    return days is not None and MIN_AFTER_DAYS <= days <= MAX_AFTER_DAYS


def compact_values(values: list[str], limit: int) -> str:
    uniq: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = (value or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        uniq.append(clean)
    return " | ".join(uniq[:limit])


def candidate_usage(candidate: dict[str, str]) -> str:
    rubric = (candidate.get("match_rubric") or "").strip()
    subrubric = (candidate.get("match_subrubric") or "").strip()
    if rubric and subrubric:
        return f"{rubric} -> {subrubric}"
    return rubric or subrubric


def normalize_confidence(base_conf: str, distance_band: str) -> str:
    if distance_band in {"0-30m", "30-100m"}:
        return base_conf
    if distance_band == "100-250m":
        return "low"
    return ""


def load_best_rows() -> dict[str, dict[str, str]]:
    with BEST_SRC.open("r", encoding="utf-8-sig", newline="") as f:
        return {row["lot_id"]: row for row in csv.DictReader(f)}


def load_geo_candidates() -> dict[str, list[dict[str, str]]]:
    by_lot: dict[str, list[dict[str, str]]] = {}
    with GEO_SRC.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("distance_band", "") not in KEEP_DISTANCE_BANDS:
                continue
            by_lot.setdefault(row["lot_id"], []).append(row)
    return by_lot


def load_first_seen_dates(candidate_ids: set[str]) -> dict[str, date]:
    first_seen: dict[str, date] = {}
    remaining = set(candidate_ids)
    for label in SNAPSHOT_LABELS:
        if not remaining:
            break
        snapshot_date = SNAPSHOT_DATES[label]
        path = MOSCOW_DIR / f"{label}.with_norm.csv"
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row_id = (row.get("id") or "").strip()
                if row_id not in remaining:
                    continue
                first_seen[row_id] = snapshot_date
                remaining.remove(row_id)
    return first_seen


def build_likely_row(best: dict[str, str], candidates: list[dict[str, str]]) -> dict[str, str] | None:
    if not candidates:
        return None

    days = after_days(best)
    if days is None:
        return None

    best_distance_band = candidates[0].get("distance_band", "")
    match_conf = normalize_confidence(best.get("confidence", ""), best_distance_band)
    if not match_conf:
        return None

    company_names = [candidate.get("match_name", "") for candidate in candidates]
    usages = [candidate_usage(candidate) for candidate in candidates]

    if match_conf == "high":
        likely_company = company_names[0] if company_names else ""
        likely_usage = usages[0] if usages else ""
    else:
        likely_company = compact_values(company_names, 3)
        likely_usage = compact_values(usages, 3)

    return {
        "lot_id": best.get("lot_id", ""),
        "url": best.get("url", ""),
        "purchase_date": best.get("purchase_date", ""),
        "trade_year": best.get("trade_year", ""),
        "form": best.get("form", ""),
        "lot_address": best.get("lot_address", ""),
        "lot_address_norm": best.get("lot_address_norm", ""),
        "before_snapshot_label": best.get("before_snapshot_label", ""),
        "before_snapshot_date": best.get("before_snapshot_date", ""),
        "after_snapshot_label": best.get("after_snapshot_label", ""),
        "after_snapshot_date": best.get("after_snapshot_date", ""),
        "before_company_count": best.get("before_company_count", ""),
        "after_company_count": best.get("after_company_count", ""),
        "new_company_count": str(len(candidates)),
        "new_company_names_preview": compact_values(company_names, 5),
        "confidence": match_conf,
        "likely_company": likely_company,
        "likely_usage": likely_usage,
        "company_candidates_preview": compact_values(company_names, 5),
        "usage_candidates_preview": compact_values(usages, 5),
        "after_days": str(days),
        "time_window": f"{MIN_AFTER_DAYS}-{MAX_AFTER_DAYS}d",
    }


def write_likely_outputs(rows: list[dict[str, str]]) -> None:
    fields = [
        "lot_id",
        "url",
        "purchase_date",
        "trade_year",
        "form",
        "lot_address",
        "lot_address_norm",
        "before_snapshot_label",
        "before_snapshot_date",
        "after_snapshot_label",
        "after_snapshot_date",
        "before_company_count",
        "after_company_count",
        "new_company_count",
        "new_company_names_preview",
        "confidence",
        "likely_company",
        "likely_usage",
        "company_candidates_preview",
        "usage_candidates_preview",
        "after_days",
        "time_window",
    ]
    for output_path in (LIKELY_OUT, LIKELY_TIME_OUT):
        with output_path.open("w", encoding="utf-8-sig", newline="") as out_f:
            writer = csv.DictWriter(out_f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)


def write_enriched_output(likely_rows: list[dict[str, str]]) -> None:
    likely_by_lot = {row["lot_id"]: row for row in likely_rows}

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
            match = likely_by_lot.get(row.get("номер_лота", ""), {})
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


def main() -> None:
    if not LIKELY_UNFILTERED.exists() and LIKELY_CURRENT.exists():
        shutil.copyfile(LIKELY_CURRENT, LIKELY_UNFILTERED)

    best_by_lot = load_best_rows()
    geo_by_lot = load_geo_candidates()

    time_window_lots = {
        lot_id: best
        for lot_id, best in best_by_lot.items()
        if in_time_window(best) and geo_by_lot.get(lot_id)
    }
    candidate_ids = {
        candidate.get("match_id", "").strip()
        for lot_id in time_window_lots
        for candidate in geo_by_lot.get(lot_id, [])
        if candidate.get("match_id", "").strip()
    }
    first_seen_dates = load_first_seen_dates(candidate_ids)

    likely_rows: list[dict[str, str]] = []
    dropped_preexisting_candidates = 0
    dropped_preexisting_lots = 0

    for lot_id, best in time_window_lots.items():
        purchase_date = parse_iso_date(best.get("purchase_date", ""))
        filtered_candidates: list[dict[str, str]] = []
        for candidate in geo_by_lot.get(lot_id, []):
            match_id = (candidate.get("match_id") or "").strip()
            first_seen = first_seen_dates.get(match_id)
            if purchase_date and first_seen and first_seen < purchase_date:
                dropped_preexisting_candidates += 1
                continue
            filtered_candidates.append(candidate)

        likely_row = build_likely_row(best, filtered_candidates)
        if likely_row:
            likely_rows.append(likely_row)
        else:
            dropped_preexisting_lots += 1

    write_likely_outputs(likely_rows)
    write_enriched_output(likely_rows)

    print(
        {
            "time_window_lots_before_preexisting_filter": len(time_window_lots),
            "kept_matches": len(likely_rows),
            "dropped_lots_after_preexisting_filter": dropped_preexisting_lots,
            "dropped_preexisting_candidates": dropped_preexisting_candidates,
            "time_window_days": f"{MIN_AFTER_DAYS}-{MAX_AFTER_DAYS}",
            "likely_out": str(LIKELY_OUT),
            "enriched_out": str(ENRICHED_OUT),
        }
    )


if __name__ == "__main__":
    main()
