from __future__ import annotations

import csv
import math
from datetime import date, datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
MATCH_DIR = BASE_DIR / "matches"

LOTS_SRC = BASE_DIR / "investmoscow_sold_2022_2026_clean.with_norm.csv"
NEW_ORGS_SRC = MATCH_DIR / "moscow_2026_04_new_organizations.csv"
CANDIDATES_OUT = MATCH_DIR / "property_usage_recent_2026_04_candidates.csv"
SUMMARY_OUT = MATCH_DIR / "property_usage_recent_2026_04_summary.csv"

SNAPSHOT_LABEL = "2026-04"
SNAPSHOT_DATE = date(2026, 4, 30)
MAX_DAYS_AFTER_PURCHASE = 180
MAX_DISTANCE_M = 250

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


def parse_lot_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value[:10], "%d.%m.%Y").date()


def to_float(value: str) -> float | None:
    try:
        text = str(value).strip().replace(",", ".")
        if not text:
            return None
        return float(text)
    except Exception:
        return None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def distance_band(distance_m: float) -> str:
    if distance_m <= 30:
        return "0-30m"
    if distance_m <= 100:
        return "30-100m"
    if distance_m <= 250:
        return "100-250m"
    return "250m+"


def confidence_for_candidates(candidates: list[dict[str, str]]) -> str:
    if not candidates:
        return ""
    best_band = candidates[0]["distance_band"]
    if len(candidates) == 1 and best_band == "0-30m":
        return "high"
    if len(candidates) <= 3 and best_band in {"0-30m", "30-100m"}:
        return "medium"
    return "low"


def compact_values(values: list[str], limit: int) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        clean = (value or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return " | ".join(out[:limit])


def usage(row: dict[str, str]) -> str:
    rubric = (row.get("rubric") or "").strip()
    subrubric = (row.get("subrubric") or "").strip()
    if rubric and subrubric:
        return f"{rubric} -> {subrubric}"
    return rubric or subrubric


def is_implausible(usage_str: str) -> bool:
    return any(sub in usage_str for sub in IMPLAUSIBLE_SUBSTRINGS)


def load_recent_lots() -> list[dict[str, str]]:
    lots: list[dict[str, str]] = []
    with LOTS_SRC.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            purchase_date = parse_lot_date(row.get("дата_подведения_итогов", ""))
            if not purchase_date:
                continue
            days_after = (SNAPSHOT_DATE - purchase_date).days
            if not (0 <= days_after <= MAX_DAYS_AFTER_PURCHASE):
                continue
            if not (row.get("address_norm") or "").strip():
                continue
            lat = to_float(row.get("latitude", ""))
            lon = to_float(row.get("longitude", ""))
            if lat is None or lon is None:
                continue
            row["_purchase_date"] = purchase_date.isoformat()
            row["_days_after"] = str(days_after)
            row["_lat"] = f"{lat:.6f}"
            row["_lon"] = f"{lon:.6f}"
            lots.append(row)
    return lots


def load_new_orgs_by_address() -> dict[str, list[dict[str, str]]]:
    by_address: dict[str, list[dict[str, str]]] = {}
    with NEW_ORGS_SRC.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            address_norm = (row.get("address_norm") or "").strip()
            if not address_norm:
                continue
            lat = to_float(row.get("lat", ""))
            lon = to_float(row.get("lon", ""))
            if lat is None or lon is None:
                continue
            by_address.setdefault(address_norm, []).append(row)
    return by_address


def main() -> None:
    MATCH_DIR.mkdir(parents=True, exist_ok=True)
    lots = load_recent_lots()
    orgs_by_address = load_new_orgs_by_address()

    candidates_by_lot: dict[str, list[dict[str, str]]] = {}
    candidate_fields = [
        "lot_id",
        "url",
        "purchase_date",
        "snapshot_label",
        "snapshot_date",
        "days_after_purchase",
        "lot_address",
        "lot_address_norm",
        "lot_lat",
        "lot_lon",
        "match_id",
        "match_name",
        "match_address",
        "match_rubric",
        "match_subrubric",
        "match_site",
        "match_lat",
        "match_lon",
        "distance_m",
        "distance_band",
    ]

    with CANDIDATES_OUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=candidate_fields)
        writer.writeheader()
        for lot in lots:
            lot_lat = float(lot["_lat"])
            lot_lon = float(lot["_lon"])
            for org in orgs_by_address.get((lot.get("address_norm") or "").strip(), []):
                org_lat = float(str(org.get("lat", "")).replace(",", "."))
                org_lon = float(str(org.get("lon", "")).replace(",", "."))
                distance_m = haversine_m(lot_lat, lot_lon, org_lat, org_lon)
                if distance_m > MAX_DISTANCE_M:
                    continue
                usage_str = usage({"rubric": org.get("rubric", ""), "subrubric": org.get("subrubric", "")})
                if is_implausible(usage_str):
                    continue
                out = {
                    "lot_id": lot.get("номер_лота", ""),
                    "url": lot.get("url", ""),
                    "purchase_date": lot["_purchase_date"],
                    "snapshot_label": SNAPSHOT_LABEL,
                    "snapshot_date": SNAPSHOT_DATE.isoformat(),
                    "days_after_purchase": lot["_days_after"],
                    "lot_address": lot.get("адрес", ""),
                    "lot_address_norm": lot.get("address_norm", ""),
                    "lot_lat": lot["_lat"],
                    "lot_lon": lot["_lon"],
                    "match_id": org.get("id", ""),
                    "match_name": org.get("name", ""),
                    "match_address": org.get("address", ""),
                    "match_rubric": org.get("rubric", ""),
                    "match_subrubric": org.get("subrubric", ""),
                    "match_site": org.get("site", ""),
                    "match_lat": org.get("lat", ""),
                    "match_lon": org.get("lon", ""),
                    "distance_m": f"{distance_m:.1f}",
                    "distance_band": distance_band(distance_m),
                }
                writer.writerow(out)
                candidates_by_lot.setdefault(out["lot_id"], []).append(out)

    summary_fields = [
        "lot_id",
        "url",
        "purchase_date",
        "snapshot_label",
        "snapshot_date",
        "days_after_purchase",
        "lot_address",
        "lot_address_norm",
        "candidate_count",
        "confidence",
        "likely_company",
        "likely_usage",
        "company_candidates_preview",
        "usage_candidates_preview",
    ]
    # Detect: same best match_id shared by multiple lots at the same address_norm.
    # One company can only occupy one premise → downgrade shared-best matches to "low".
    best_match_id_by_lot: dict[str, str] = {}
    address_norm_by_lot: dict[str, str] = {}
    for lot_id, candidates in candidates_by_lot.items():
        cands_sorted = sorted(candidates, key=lambda r: float(r["distance_m"]))
        best_match_id_by_lot[lot_id] = cands_sorted[0]["match_id"]
        address_norm_by_lot[lot_id] = cands_sorted[0]["lot_address_norm"]

    # Count how many lots at each (address_norm, match_id) pair share the same best candidate.
    from collections import Counter
    shared_key_counts: Counter = Counter(
        (address_norm_by_lot[lid], mid)
        for lid, mid in best_match_id_by_lot.items()
    )

    with SUMMARY_OUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=summary_fields)
        writer.writeheader()
        for lot_id, candidates in sorted(candidates_by_lot.items()):
            candidates = sorted(candidates, key=lambda row: float(row["distance_m"]))
            conf = confidence_for_candidates(candidates)
            # Downgrade if the same best candidate is shared by multiple lots in the same building.
            best_mid = candidates[0]["match_id"]
            addr_norm = candidates[0]["lot_address_norm"]
            if shared_key_counts[(addr_norm, best_mid)] > 1:
                conf = "low"
            companies = [row["match_name"] for row in candidates]
            usages = [usage({"rubric": row["match_rubric"], "subrubric": row["match_subrubric"]}) for row in candidates]
            first = candidates[0]
            if conf == "high":
                likely_company = companies[0]
                likely_usage = usages[0]
            else:
                likely_company = compact_values(companies, 3)
                likely_usage = compact_values(usages, 3)
            writer.writerow(
                {
                    "lot_id": lot_id,
                    "url": first["url"],
                    "purchase_date": first["purchase_date"],
                    "snapshot_label": SNAPSHOT_LABEL,
                    "snapshot_date": SNAPSHOT_DATE.isoformat(),
                    "days_after_purchase": first["days_after_purchase"],
                    "lot_address": first["lot_address"],
                    "lot_address_norm": first["lot_address_norm"],
                    "candidate_count": len(candidates),
                    "confidence": conf,
                    "likely_company": likely_company,
                    "likely_usage": likely_usage,
                    "company_candidates_preview": compact_values(companies, 5),
                    "usage_candidates_preview": compact_values(usages, 5),
                }
            )

    print(
        {
            "recent_lots_0_180d": len(lots),
            "new_org_addresses": len(orgs_by_address),
            "matched_lots": len(candidates_by_lot),
            "candidate_rows": sum(len(rows) for rows in candidates_by_lot.values()),
            "candidates_out": str(CANDIDATES_OUT),
            "summary_out": str(SUMMARY_OUT),
        }
    )


if __name__ == "__main__":
    main()
