"""
Match unmatched (and first_after_snapshot_2025-09) lots against the new gap snapshots.

For each snapshot pair (prev -> curr) in chronological order, find businesses that
are NEW in curr (not present in prev) and appear near a lot address within 250 m.
For each lot, keep only the best match (smallest after_days + best confidence).

Outputs:
  matches/gap_matches_summary.csv — one row per matched lot (best match)
"""

from __future__ import annotations

import csv
import math
from calendar import monthrange
from collections import Counter
from datetime import date, datetime
from pathlib import Path


BASE_DIR   = Path(__file__).resolve().parent
MOSCOW_DIR = BASE_DIR / "moscow"
MATCH_DIR  = BASE_DIR / "matches"

LOTS_SRC     = BASE_DIR / "investmoscow_sold_2022_2026_clean.with_norm.csv"
ENRICHED_PATH = BASE_DIR / "investmoscow_sold_2022_2026_enriched_geo.csv"
SUMMARY_OUT  = MATCH_DIR / "gap_matches_summary.csv"

MIN_AFTER_DAYS = 60     # require at least 60 days after purchase
MAX_AFTER_DAYS = 365    # cap at 1 year — beyond this use first_after_snapshot
MAX_DISTANCE_M = 250

# Snapshot pairs in chronological order: (prev_label, curr_label)
# All gaps + recent snapshots through 2026-04, covering lots from 2022 to late 2025.
SNAPSHOT_PAIRS = [
    ("2021-10", "2022-01"),
    ("2022-01", "2022-05"),
    ("2022-05", "2022-08"),
    ("2022-08", "2022-12"),
    ("2022-12", "2023-12"),
    ("2023-12", "2024-05"),
    ("2024-05", "2024-09"),
    ("2024-09", "2024-10"),
    ("2024-10", "2025-09"),
    ("2025-09", "2025-11"),
    ("2025-11", "2026-02"),
    ("2026-02", "2026-03"),
    ("2026-03", "2026-04"),
]

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

CONF_RANK = {"high": 0, "medium": 1, "low": 2, "": 9}


# ── Utilities ─────────────────────────────────────────────────────────────────

def month_end(label: str) -> date:
    year, month = map(int, label.split("-"))
    return date(year, month, monthrange(year, month)[1])


def parse_lot_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%d.%m.%Y").date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def to_float(value: object) -> float | None:
    try:
        return float(str(value).strip().replace(",", "."))
    except Exception:
        return None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def distance_band(d: float) -> str:
    if d <= 30:  return "0-30m"
    if d <= 100: return "30-100m"
    if d <= 250: return "100-250m"
    return "250m+"


def usage_str(row: dict) -> str:
    rubric    = (row.get("rubric")    or "").strip()
    subrubric = (row.get("subrubric") or "").strip()
    if rubric and subrubric:
        return f"{rubric} -> {subrubric}"
    return rubric or subrubric


def is_implausible(u: str) -> bool:
    return any(s in u for s in IMPLAUSIBLE_SUBSTRINGS)


def is_implausible_name(name: str) -> bool:
    lower = name.lower()
    return any(s.lower() in lower for s in IMPLAUSIBLE_NAME_SUBSTRINGS)


def confidence_for(candidates: list[dict]) -> str:
    if not candidates:
        return ""
    best_band = candidates[0]["distance_band"]
    if len(candidates) == 1 and best_band == "0-30m":
        return "high"
    if len(candidates) <= 3 and best_band in {"0-30m", "30-100m"}:
        return "medium"
    return "low"


def compact(values: list[str], limit: int = 5) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        v = v.strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return " | ".join(out[:limit])


# ── Data loading ──────────────────────────────────────────────────────────────

def load_existing_matches() -> dict[str, str]:
    """Returns {lot_id: match_time_window} for lots that already have a match."""
    result: dict[str, str] = {}
    with ENRICHED_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            conf = (row.get("match_confidence") or "").strip()
            if not conf:
                continue
            lot_id = str(row.get("номер_лота", "")).strip()
            result[lot_id] = (row.get("match_time_window") or "").strip()
    return result


def load_target_lots(existing: dict[str, str]) -> list[dict]:
    """Lots eligible for gap matching: unmatched or first_after_snapshot (upgradeable)."""
    SKIP_WINDOWS = {"180-365d", "0-180d_recent_2026-04"}
    lots: list[dict] = []
    with LOTS_SRC.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            lot_id = str(row.get("номер_лота", "")).strip()
            existing_tw = existing.get(lot_id, "")

            if existing_tw in SKIP_WINDOWS:
                continue  # already has a good match — don't disturb

            purchase_date = parse_lot_date(row.get("дата_подведения_итогов", ""))
            if not purchase_date:
                continue
            addr = (row.get("address_norm") or "").strip()
            if not addr:
                continue
            lat = to_float(row.get("latitude"))
            lon = to_float(row.get("longitude"))
            if lat is None or lon is None:
                continue

            row["_lot_id"]       = lot_id
            row["_purchase_date"] = purchase_date
            row["_lat"]           = lat
            row["_lon"]           = lon
            row["_existing_tw"]   = existing_tw
            lots.append(row)
    return lots


def _composite_key(row: dict) -> str:
    addr = (row.get("address_norm") or "").strip()
    name = (row.get("name") or "").strip().lower()
    return f"{addr}|{name}"


def load_snapshot_keys(label: str) -> set[str]:
    """Returns composite address_norm|name keys for all orgs in the snapshot."""
    path = MOSCOW_DIR / f"{label}.with_norm.csv"
    if not path.exists():
        return set()
    keys: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            k = _composite_key(row)
            if k and k != "|":
                keys.add(k)
    return keys


def load_new_orgs(curr_label: str, prev_keys: set[str]) -> dict[str, list[dict]]:
    """Returns {address_norm: [org]} for organisations new in curr_label vs prev."""
    path = MOSCOW_DIR / f"{curr_label}.with_norm.csv"
    if not path.exists():
        print(f"    WARNING: {curr_label}.with_norm.csv not found")
        return {}
    by_addr: dict[str, list[dict]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = _composite_key(row)
            if key and key in prev_keys:
                continue  # was already present in prev snapshot
            addr = (row.get("address_norm") or "").strip()
            if not addr:
                continue
            lat = to_float(row.get("lat"))
            lon = to_float(row.get("lon"))
            if lat is None or lon is None:
                continue
            by_addr.setdefault(addr, []).append(row)
    return by_addr


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    MATCH_DIR.mkdir(exist_ok=True)

    existing = load_existing_matches()
    lots     = load_target_lots(existing)
    print(f"Target lots (unmatched + first_after_snapshot upgradeable): {len(lots)}")

    # best_by_lot: lot_id -> best match summary dict
    best_by_lot: dict[str, dict] = {}

    for prev_label, curr_label in SNAPSHOT_PAIRS:
        curr_date = month_end(curr_label)
        print(f"\n{prev_label} -> {curr_label}  (snapshot date {curr_date})")

        prev_ids = load_snapshot_keys(prev_label)
        print(f"  prev keys loaded: {len(prev_ids)}")

        new_orgs = load_new_orgs(curr_label, prev_ids)
        if not new_orgs:
            print("  no new orgs or file missing — skipping")
            continue
        print(f"  new orgs: {sum(len(v) for v in new_orgs.values())} at {len(new_orgs)} addresses")

        candidates_by_lot: dict[str, list[dict]] = {}

        for lot in lots:
            lot_id       = lot["_lot_id"]
            purchase_date = lot["_purchase_date"]
            after_days   = (curr_date - purchase_date).days

            if after_days < MIN_AFTER_DAYS or after_days > MAX_AFTER_DAYS:
                continue

            addr  = (lot.get("address_norm") or "").strip()
            orgs  = new_orgs.get(addr, [])
            if not orgs:
                continue

            lot_lat = lot["_lat"]
            lot_lon = lot["_lon"]

            for org in orgs:
                org_lat = to_float(org.get("lat"))
                org_lon = to_float(org.get("lon"))
                if org_lat is None or org_lon is None:
                    continue
                dist = haversine_m(lot_lat, lot_lon, org_lat, org_lon)
                if dist > MAX_DISTANCE_M:
                    continue
                u = usage_str(org)
                if is_implausible(u) or is_implausible_name(org.get("name", "")):
                    continue
                candidates_by_lot.setdefault(lot_id, []).append({
                    "org":           org,
                    "distance_m":    dist,
                    "distance_band": distance_band(dist),
                    "after_days":    after_days,
                })

        # Shared-building deduplication
        best_mid_by_lot:  dict[str, str] = {}
        addr_norm_by_lot: dict[str, str] = {}
        for lot_id, cands in candidates_by_lot.items():
            cands.sort(key=lambda c: c["distance_m"])
            best_mid_by_lot[lot_id]  = _composite_key(cands[0]["org"])
            addr_norm_by_lot[lot_id] = next(
                (l.get("address_norm", "") for l in lots if l["_lot_id"] == lot_id), ""
            )
        shared = Counter(
            (addr_norm_by_lot[lid], mid) for lid, mid in best_mid_by_lot.items()
        )

        lot_lookup = {lot["_lot_id"]: lot for lot in lots}

        matched_count = 0
        for lot_id, cands in candidates_by_lot.items():
            cands.sort(key=lambda c: c["distance_m"])
            conf = confidence_for(cands)

            best_mid  = best_mid_by_lot[lot_id]
            addr_norm = addr_norm_by_lot[lot_id]
            if shared[(addr_norm, best_mid)] > 1:
                conf = "low"
            if conf == "high" and cands[0]["after_days"] > 365:
                conf = "medium"

            companies = [c["org"].get("name", "") for c in cands]
            usages    = [usage_str(c["org"]) for c in cands]

            if conf == "high":
                likely_company = companies[0]
                likely_usage   = usages[0]
            else:
                likely_company = compact(companies, 3)
                likely_usage   = compact(usages, 3)

            lot = lot_lookup[lot_id]
            after_days = cands[0]["after_days"]
            curr_match = {
                "lot_id":               lot_id,
                "url":                  lot.get("url", ""),
                "purchase_date":        cands[0]["after_days"] and lot["_purchase_date"].isoformat(),
                "prev_snapshot_label":  prev_label,
                "snapshot_label":       curr_label,
                "snapshot_date":        curr_date.isoformat(),
                "days_after_purchase":  str(after_days),
                "lot_address":          lot.get("адрес", ""),
                "lot_address_norm":     addr_norm,
                "candidate_count":      str(len(cands)),
                "confidence":           conf,
                "likely_company":       likely_company,
                "likely_usage":         likely_usage,
                "company_candidates_preview": compact(companies, 5),
                "usage_candidates_preview":   compact(usages, 5),
            }
            # Fix purchase_date correctly
            curr_match["purchase_date"] = lot["_purchase_date"].isoformat()

            existing_best = best_by_lot.get(lot_id)
            if existing_best is None:
                best_by_lot[lot_id] = curr_match
                matched_count += 1
            else:
                # Prefer smaller after_days; tie-break on confidence
                ex_days = int(existing_best["days_after_purchase"])
                if after_days < ex_days or (
                    after_days == ex_days
                    and CONF_RANK.get(conf, 9) < CONF_RANK.get(existing_best["confidence"], 9)
                ):
                    best_by_lot[lot_id] = curr_match

        print(f"  lots with candidates in this snapshot: {len(candidates_by_lot)}")

    # Write output
    summary_fields = [
        "lot_id", "url", "purchase_date",
        "prev_snapshot_label", "snapshot_label", "snapshot_date",
        "days_after_purchase",
        "lot_address", "lot_address_norm",
        "candidate_count", "confidence",
        "likely_company", "likely_usage",
        "company_candidates_preview", "usage_candidates_preview",
    ]
    with SUMMARY_OUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=summary_fields)
        writer.writeheader()
        for match in sorted(best_by_lot.values(), key=lambda r: str(r["lot_id"])):
            writer.writerow(match)

    high_med = sum(1 for m in best_by_lot.values() if m["confidence"] in {"high", "medium"})
    print(f"\n=== Gap matching complete ===")
    print(f"  Total lots with gap match:    {len(best_by_lot)}")
    print(f"  High/medium confidence:       {high_med}")
    print(f"  Output: {SUMMARY_OUT}")


if __name__ == "__main__":
    main()
