"""
Merge gap-snapshot matches into investmoscow_sold_2022_2026_enriched_geo.csv.

Applies gap matches to:
  1. Lots with no existing match.
  2. Lots with first_after_snapshot_* match where the gap match is closer
     (smaller days_after_purchase) and confidence is not worse.

Idempotent: clears all existing gap_snapshot_* matches before re-applying.
Does NOT touch baseline (180-365d) or recent (0-180d_recent_2026-04) matches.

Outputs:
  investmoscow_sold_2022_2026_enriched_geo.csv — updated in-place
  matches/gap_matches_report.csv               — per-lot summary of changes
"""

from __future__ import annotations

import csv
from pathlib import Path


BASE_DIR     = Path(__file__).resolve().parent
MATCH_DIR    = BASE_DIR / "matches"
ENRICHED_PATH = BASE_DIR / "investmoscow_sold_2022_2026_enriched_geo.csv"
SUMMARY_PATH  = MATCH_DIR / "gap_matches_summary.csv"
REPORT_PATH   = MATCH_DIR / "gap_matches_report.csv"

ALLOWED_CONFIDENCE = {"high", "medium"}

CONF_RANK = {"high": 0, "medium": 1, "low": 2, "": 9}

MATCH_FIELDS = [
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


def load_gap_matches() -> dict[str, dict]:
    matches: dict[str, dict] = {}
    with SUMMARY_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            conf = (row.get("confidence") or "").strip()
            if conf not in ALLOWED_CONFIDENCE:
                continue
            lot_id = str(row.get("lot_id", "")).strip()
            matches[lot_id] = row
    return matches


def apply_match(row: dict, match: dict, time_window: str) -> None:
    row["match_before_snapshot_label"] = match.get("prev_snapshot_label", "")
    row["match_after_snapshot_label"]  = match.get("snapshot_label", "")
    row["match_before_company_count"]  = ""
    row["match_after_company_count"]   = match.get("candidate_count", "")
    row["match_new_company_count"]     = match.get("candidate_count", "")
    row["match_after_days"]            = match.get("days_after_purchase", "")
    row["match_time_window"]           = time_window
    row["likely_company"]              = match.get("likely_company", "")
    row["likely_usage"]                = match.get("likely_usage", "")
    row["match_confidence"]            = match.get("confidence", "")
    row["company_candidates_preview"]  = match.get("company_candidates_preview", "")
    row["usage_candidates_preview"]    = match.get("usage_candidates_preview", "")


def clear_match(row: dict) -> None:
    for field in MATCH_FIELDS:
        row[field] = ""


def main() -> None:
    gap_matches = load_gap_matches()
    print(f"Gap matches available (high/medium): {len(gap_matches)}")

    with ENRICHED_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader    = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows       = list(reader)

    added    = 0
    upgraded = 0
    cleared  = 0
    skipped  = 0

    report_rows: list[dict] = []

    for row in rows:
        lot_id    = str(row.get("номер_лота", "")).strip()
        existing_tw   = (row.get("match_time_window")  or "").strip()
        existing_conf = (row.get("match_confidence")   or "").strip()

        # ── Step 1: clear any stale gap_snapshot_* match (idempotency) ──────
        if existing_conf and existing_tw.startswith("gap_snapshot_"):
            clear_match(row)
            cleared += 1
            existing_tw   = ""
            existing_conf = ""

        # ── Step 2: decide whether to apply new gap match ───────────────────
        gap = gap_matches.get(lot_id)

        if not gap:
            skipped += 1
            continue

        gap_days = int(gap.get("days_after_purchase", 0) or 0)
        gap_conf = gap.get("confidence", "")
        time_window = f"gap_snapshot_{gap['snapshot_label']}"

        # Case A: lot has no match at all
        if not existing_conf:
            apply_match(row, gap, time_window)
            added += 1
            report_rows.append({
                "lot_id":  lot_id, "action": "added",
                "old_tw":  "",      "new_tw": time_window,
                "old_conf": "",     "new_conf": gap_conf,
                "gap_days": gap_days, "company": gap.get("likely_company", ""),
            })
            continue

        # Case B: lot has first_after_snapshot match — upgrade if closer
        if existing_tw.startswith("first_after_snapshot_"):
            existing_days = int(float(row.get("match_after_days") or 0))
            existing_conf_rank = CONF_RANK.get(existing_conf, 9)
            gap_conf_rank      = CONF_RANK.get(gap_conf, 9)

            if gap_days < existing_days or (
                gap_days == existing_days and gap_conf_rank <= existing_conf_rank
            ):
                old_tw   = existing_tw
                old_conf = existing_conf
                apply_match(row, gap, time_window)
                upgraded += 1
                report_rows.append({
                    "lot_id":   lot_id, "action": "upgraded",
                    "old_tw":   old_tw,  "new_tw": time_window,
                    "old_conf": old_conf, "new_conf": gap_conf,
                    "gap_days": gap_days, "company": gap.get("likely_company", ""),
                })
                continue

        skipped += 1

    # Write enriched CSV back
    with ENRICHED_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Write report
    MATCH_DIR.mkdir(exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        report_fields = ["lot_id", "action", "old_tw", "new_tw", "old_conf", "new_conf", "gap_days", "company"]
        writer = csv.DictWriter(f, fieldnames=report_fields)
        writer.writeheader()
        writer.writerows(report_rows)

    total_matched = sum(
        1 for row in rows if (row.get("match_confidence") or "").strip()
    )

    print(f"\n=== Merge complete ===")
    print(f"  Cleared old gap_snapshot_* matches: {cleared}")
    print(f"  Added (previously unmatched):       {added}")
    print(f"  Upgraded (first_after_snapshot->gap): {upgraded}")
    print(f"  Skipped (already has better match): {skipped}")
    print(f"  Total matched lots in enriched CSV: {total_matched}")
    print(f"  Report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
