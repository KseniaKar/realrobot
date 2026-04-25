from __future__ import annotations

import csv
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
MATCH_DIR = BASE_DIR / "matches"

ENRICHED_PATH = BASE_DIR / "investmoscow_sold_2022_2026_enriched_geo.csv"
RECENT_SUMMARY_PATH = MATCH_DIR / "property_usage_recent_2026_04_summary.csv"
COMBINED_SUMMARY_PATH = MATCH_DIR / "property_usage_combined_summary.csv"

RECENT_ALLOWED_CONFIDENCE = {"high", "medium"}


def load_recent_matches() -> dict[str, dict[str, str]]:
    matches: dict[str, dict[str, str]] = {}
    with RECENT_SUMMARY_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            confidence = (row.get("confidence") or "").strip()
            if confidence not in RECENT_ALLOWED_CONFIDENCE:
                continue
            matches[row["lot_id"]] = row
    return matches


RECENT_TIME_WINDOW = "0-180d_recent_2026-04"

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


def main() -> None:
    recent = load_recent_matches()
    added = 0
    cleared = 0
    existing_other = 0

    with ENRICHED_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    for row in rows:
        lot_id = row.get("номер_лота", "")
        existing_tw = (row.get("match_time_window") or "").strip()
        existing_conf = (row.get("match_confidence") or "").strip()

        # Clear previous recent matches so we can re-apply with updated confidence.
        if existing_conf and existing_tw == RECENT_TIME_WINDOW:
            for field in MATCH_FIELDS:
                row[field] = ""
            cleared += 1

        if (row.get("match_confidence") or "").strip():
            existing_other += 1
            continue
        match = recent.get(lot_id)
        if not match:
            continue
        row["match_before_snapshot_label"] = "2026-03"
        row["match_after_snapshot_label"] = match.get("snapshot_label", "2026-04")
        row["match_before_company_count"] = ""
        row["match_after_company_count"] = match.get("candidate_count", "")
        row["match_new_company_count"] = match.get("candidate_count", "")
        row["match_after_days"] = match.get("days_after_purchase", "")
        row["match_time_window"] = RECENT_TIME_WINDOW
        row["likely_company"] = match.get("likely_company", "")
        row["likely_usage"] = match.get("likely_usage", "")
        row["match_confidence"] = match.get("confidence", "")
        row["company_candidates_preview"] = match.get("company_candidates_preview", "")
        row["usage_candidates_preview"] = match.get("usage_candidates_preview", "")
        added += 1

    with ENRICHED_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    with COMBINED_SUMMARY_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        summary_fields = [
            "lot_id",
            "url",
            "source",
            "purchase_date",
            "snapshot_label",
            "days_after_purchase",
            "confidence",
            "likely_company",
            "likely_usage",
            "candidate_count",
        ]
        writer = csv.DictWriter(f, fieldnames=summary_fields)
        writer.writeheader()
        for row in rows:
            confidence = (row.get("match_confidence") or "").strip()
            if not confidence:
                continue
            source = "recent_2026_04" if row.get("match_time_window") == "0-180d_recent_2026-04" else "baseline"
            writer.writerow(
                {
                    "lot_id": row.get("номер_лота", ""),
                    "url": row.get("url", ""),
                    "source": source,
                    "purchase_date": row.get("дата_подведения_итогов", ""),
                    "snapshot_label": row.get("match_after_snapshot_label", ""),
                    "days_after_purchase": row.get("match_after_days", ""),
                    "confidence": confidence,
                    "likely_company": row.get("likely_company", ""),
                    "likely_usage": row.get("likely_usage", ""),
                    "candidate_count": row.get("match_new_company_count", ""),
                }
            )

    print(
        {
            "cleared_old_recent_matches": cleared,
            "existing_other_matches": existing_other,
            "recent_high_medium_available": len(recent),
            "recent_added_to_enriched": added,
            "enriched": str(ENRICHED_PATH),
            "combined_summary": str(COMBINED_SUMMARY_PATH),
        }
    )


if __name__ == "__main__":
    main()
