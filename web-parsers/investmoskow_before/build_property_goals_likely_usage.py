from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(r"C:\git\realrobot\property_goals")
MATCH_DIR = ROOT / "matches"
BEST_SRC = MATCH_DIR / "property_usage_before_after_best_high_medium.csv"
CANDIDATES_SRC = MATCH_DIR / "property_usage_top_candidates_high_medium.csv"
OUT_PATH = MATCH_DIR / "property_usage_likely_summary.csv"


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


def main() -> None:
    lot_candidates: dict[str, list[dict[str, str]]] = {}
    with CANDIDATES_SRC.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            lot_candidates.setdefault(row["lot_id"], []).append(row)

    with BEST_SRC.open("r", encoding="utf-8-sig", newline="") as best_f, OUT_PATH.open(
        "w", encoding="utf-8-sig", newline=""
    ) as out_f:
        reader = csv.DictReader(best_f)
        fieldnames = list(reader.fieldnames or []) + [
            "likely_company",
            "likely_usage",
            "company_candidates_preview",
            "usage_candidates_preview",
        ]
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        writer.writeheader()

        for row in reader:
            candidates = lot_candidates.get(row["lot_id"], [])
            company_names = [c.get("match_name", "") for c in candidates]
            usages = []
            for candidate in candidates:
                rubric = (candidate.get("match_rubric") or "").strip()
                subrubric = (candidate.get("match_subrubric") or "").strip()
                if rubric and subrubric:
                    usages.append(f"{rubric} -> {subrubric}")
                elif rubric:
                    usages.append(rubric)
                elif subrubric:
                    usages.append(subrubric)

            confidence = row.get("confidence", "")
            if confidence == "high":
                likely_company = company_names[0] if company_names else ""
                likely_usage = usages[0] if usages else ""
            else:
                likely_company = compact_values(company_names, 3)
                likely_usage = compact_values(usages, 3)

            row["likely_company"] = likely_company
            row["likely_usage"] = likely_usage
            row["company_candidates_preview"] = compact_values(company_names, 5)
            row["usage_candidates_preview"] = compact_values(usages, 5)
            writer.writerow(row)

    print({"out": str(OUT_PATH)})


if __name__ == "__main__":
    main()
