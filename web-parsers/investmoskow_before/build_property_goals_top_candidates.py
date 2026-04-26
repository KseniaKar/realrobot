from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(r"C:\git\realrobot\property_goals")
MATCH_DIR = ROOT / "matches"
BEST_SRC = MATCH_DIR / "property_usage_before_after_best.csv"
ALL_SRC = MATCH_DIR / "property_usage_before_after_new_companies.csv"


def main() -> None:
    filtered_best = MATCH_DIR / "property_usage_before_after_best_high_medium.csv"
    filtered_candidates = MATCH_DIR / "property_usage_top_candidates_high_medium.csv"

    allowed = {"high", "medium"}
    keep_lots: set[str] = set()

    with BEST_SRC.open("r", encoding="utf-8-sig", newline="") as src_f, filtered_best.open(
        "w", encoding="utf-8-sig", newline=""
    ) as dst_f:
        reader = csv.DictReader(src_f)
        writer = csv.DictWriter(dst_f, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            if row.get("confidence") in allowed and int(row.get("new_company_count") or "0") > 0:
                keep_lots.add(row["lot_id"])
                writer.writerow(row)

    with ALL_SRC.open("r", encoding="utf-8-sig", newline="") as src_f, filtered_candidates.open(
        "w", encoding="utf-8-sig", newline=""
    ) as dst_f:
        reader = csv.DictReader(src_f)
        out_fields = list(reader.fieldnames or []) + ["company_rank_on_lot"]
        writer = csv.DictWriter(dst_f, fieldnames=out_fields)
        writer.writeheader()

        current_lot = None
        rank = 0
        for row in reader:
            lot_id = row.get("lot_id", "")
            if lot_id not in keep_lots:
                continue
            if lot_id != current_lot:
                current_lot = lot_id
                rank = 1
            else:
                rank += 1
            row["company_rank_on_lot"] = str(rank)
            writer.writerow(row)

    print(
        {
            "filtered_best": str(filtered_best),
            "filtered_candidates": str(filtered_candidates),
            "kept_lots": len(keep_lots),
        }
    )


if __name__ == "__main__":
    main()
