"""
Detect "existing tenant buyout" pattern for unmatched lots.

A lot qualifies if a business was present near it (≤50m) in ≥3 snapshots
BEFORE the sale date and remains in ≥1 snapshot AFTER the sale date.
This suggests the existing tenant bought the premises they were already renting.

Uses geographic grid bucketing to avoid O(lots × snaps × orgs) brute force.

Outputs:
  matches/tenant_buyout_candidates.csv — candidate lots with flagged businesses
  matches/tenant_buyout_summary.csv    — count summary
"""

from __future__ import annotations

import csv
import math
import re
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

BASE_DIR    = Path(__file__).resolve().parent
MOSCOW_DIR  = BASE_DIR / "moscow"
MATCH_DIR   = BASE_DIR / "matches"
ENRICHED    = BASE_DIR / "investmoscow_sold_2022_2026_enriched_geo.csv"

MATCH_DIR.mkdir(exist_ok=True)

CANDIDATES_OUT = MATCH_DIR / "tenant_buyout_candidates.csv"
SUMMARY_OUT    = MATCH_DIR / "tenant_buyout_summary.csv"

MAX_DISTANCE_M   = 50
MIN_SNAPS_BEFORE = 3
MIN_SNAPS_AFTER  = 1

# ~50m in degrees at Moscow latitude (55.7°N)
GRID_STEP = 0.001

SNAPSHOT_LABELS = [
    "2020-04", "2020-08", "2021-03", "2021-10",
    "2022-01", "2022-05", "2022-08", "2022-12",
    "2023-12", "2024-05", "2024-09", "2024-10",
    "2025-09", "2025-11",
    "2026-02", "2026-03", "2026-04",
]

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


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def to_float(v):
    try:
        return float(str(v).strip().replace(",", "."))
    except Exception:
        return None


def month_end(label: str) -> date:
    year, month = map(int, label.split("-"))
    return date(year, month, monthrange(year, month)[1])


def parse_date(s: str) -> date | None:
    s = (s or "").strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            pass
    return None


def is_implausible(name: str, usage: str) -> bool:
    if any(s in usage for s in IMPLAUSIBLE_SUBSTRINGS):
        return True
    n = name.lower()
    if any(s.lower() in n for s in IMPLAUSIBLE_NAME_SUBSTRINGS):
        return True
    return bool(_ADDRESS_LIKE_RE.search(name))


def grid_key(lat: float, lon: float) -> tuple[int, int]:
    return (int(lat / GRID_STEP), int(lon / GRID_STEP))


def grid_neighbors(lat: float, lon: float) -> list[tuple[int, int]]:
    """3×3 grid cells around the point to ensure we don't miss orgs on cell boundaries."""
    r = int(lat / GRID_STEP)
    c = int(lon / GRID_STEP)
    return [(r + dr, c + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1)]


def load_snapshot_grid(label: str) -> dict[tuple[int, int], list[dict]]:
    """Load snapshot into a spatial grid for fast proximity lookup."""
    path = MOSCOW_DIR / f"{label}.with_norm.csv"
    if not path.exists():
        return {}
    grid: dict[tuple[int, int], list[dict]] = defaultdict(list)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            lat = to_float(row.get("lat"))
            lon = to_float(row.get("lon"))
            if lat is None or lon is None:
                continue
            name  = (row.get("name") or "").strip()
            rubric = (row.get("rubric") or "").strip()
            sub    = (row.get("subrubric") or "").strip()
            usage  = f"{rubric} ->{sub}" if rubric and sub else rubric or sub
            if is_implausible(name, usage):
                continue
            grid[grid_key(lat, lon)].append({
                "name": name, "usage": usage, "lat": lat, "lon": lon,
            })
    return dict(grid)


def find_nearby(grid: dict, lat: float, lon: float) -> list[dict]:
    """Return all orgs within MAX_DISTANCE_M of (lat, lon) using grid."""
    candidates = []
    for cell in grid_neighbors(lat, lon):
        for org in grid.get(cell, []):
            dist = haversine_m(lat, lon, org["lat"], org["lon"])
            if dist <= MAX_DISTANCE_M:
                candidates.append({**org, "dist": dist})
    return candidates


def main():
    # Load unmatched lots
    unmatched_lots = []
    with ENRICHED.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("match_confidence", "").strip():
                continue
            lat = to_float(row.get("latitude"))
            lon = to_float(row.get("longitude"))
            if lat is None or lon is None:
                continue
            sale_date = parse_date(row.get("дата_подведения_итогов", ""))
            if not sale_date:
                continue
            unmatched_lots.append({
                "lot_id":    row.get("номер_лота", "").strip(),
                "address":   row.get("адрес", "").strip(),
                "lat":       lat,
                "lon":       lon,
                "sale_date": sale_date,
                "area":      row.get("площадь_кв_м", "").strip(),
                "floor":     row.get("этаж", "").strip(),
                "форма":     row.get("форма_проведения", "").strip(),
            })

    print(f"Unmatched lots to check: {len(unmatched_lots)}")

    snap_dates = {label: month_end(label) for label in SNAPSHOT_LABELS}

    # Load all snapshots into spatial grids
    print("Loading snapshots into spatial grids...")
    snap_grids: dict[str, dict] = {}
    for label in SNAPSHOT_LABELS:
        grid = load_snapshot_grid(label)
        snap_grids[label] = grid
        cell_count = len(grid)
        print(f"  {label}: {sum(len(v) for v in grid.values()):,} orgs in {cell_count:,} grid cells")

    print("Searching for existing tenants...")
    results = []

    for i, lot in enumerate(unmatched_lots):
        if i % 500 == 0:
            print(f"  Processing lot {i}/{len(unmatched_lots)}...")

        lot_lat   = lot["lat"]
        lot_lon   = lot["lon"]
        sale_date = lot["sale_date"]

        # For this lot, collect appearances per business name across snapshots
        # key: business name lower → {label: (date, usage, dist)}
        business_appearances: dict[str, dict] = defaultdict(dict)
        business_info: dict[str, dict] = {}

        for label, grid in snap_grids.items():
            snap_date = snap_dates[label]
            nearby = find_nearby(grid, lot_lat, lot_lon)
            for org in nearby:
                key = org["name"].lower().strip()
                if not key:
                    continue
                business_appearances[key][label] = snap_date
                if key not in business_info or org["dist"] < business_info[key]["dist"]:
                    business_info[key] = {
                        "name": org["name"], "usage": org["usage"], "dist": org["dist"],
                    }

        # Apply buyout pattern filter
        for key, appearances in business_appearances.items():
            snaps_before = [l for l, d in appearances.items() if d <= sale_date]
            snaps_after  = [l for l, d in appearances.items() if d > sale_date]

            if len(snaps_before) >= MIN_SNAPS_BEFORE and len(snaps_after) >= MIN_SNAPS_AFTER:
                info = business_info[key]
                results.append({
                    "lot_id":           lot["lot_id"],
                    "lot_address":      lot["address"],
                    "sale_date":        sale_date.isoformat(),
                    "area_m2":          lot["area"],
                    "floor":            lot["floor"],
                    "форма_проведения": lot["форма"],
                    "business_name":    info["name"],
                    "business_usage":   info["usage"],
                    "distance_m":       f"{info['dist']:.1f}",
                    "snapshots_before": len(snaps_before),
                    "snapshots_after":  len(snaps_after),
                    "first_seen":       min(appearances.values()).isoformat(),
                    "last_seen":        max(appearances.values()).isoformat(),
                    "before_labels":    " | ".join(sorted(snaps_before)),
                    "after_labels":     " | ".join(sorted(snaps_after)),
                })

    unique_lots = len({r["lot_id"] for r in results})
    print(f"\nCandidates found: {len(results)} businesses across {unique_lots} lots")

    if results:
        fields = list(results[0].keys())
        with CANDIDATES_OUT.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(results)
        print(f"Candidates: {CANDIDATES_OUT}")

    # Summary by форма_проведения
    форма_cands: dict[str, int] = defaultdict(int)
    for r in results:
        форма_cands[r["форма_проведения"]] += 1

    форма_total: dict[str, int] = defaultdict(int)
    for lot in unmatched_lots:
        форма_total[lot["форма"]] += 1

    print("\n--- Buyout candidates by форма_проведения ---")
    print(f"  {'Форма':<40} {'Лотов-кандидатов':>17} {'Всего unmatched':>16} {'%':>6}")
    for форма in sorted(форма_total, key=lambda x: -форма_total[x]):
        cands_lots = len({r["lot_id"] for r in results if r["форма_проведения"] == форма})
        total      = форма_total[форма]
        pct        = cands_lots / total * 100 if total else 0
        print(f"  {форма:<40} {cands_lots:>17} {total:>16} {pct:>5.1f}%")

    with SUMMARY_OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["форма_проведения", "buyout_lots", "total_unmatched", "pct"])
        w.writeheader()
        for форма in sorted(форма_total, key=lambda x: -форма_total[x]):
            cands_lots = len({r["lot_id"] for r in results if r["форма_проведения"] == форма})
            total      = форма_total[форма]
            w.writerow({
                "форма_проведения": форма,
                "buyout_lots":     cands_lots,
                "total_unmatched": total,
                "pct":             f"{cands_lots/total*100:.1f}" if total else "0",
            })
    print(f"Summary: {SUMMARY_OUT}")


if __name__ == "__main__":
    main()
