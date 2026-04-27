"""
Build full business history for each lot across all 2GIS snapshots.

For every lot, collect all unique businesses that ever appeared at its address
(within 250m) in any snapshot — regardless of date or purchase date.
Businesses are deduplicated by name and filtered for implausible types.

Adds column `история_бизнесов` to investmoscow_sold_2022_2026_enriched_geo.csv.
"""

from __future__ import annotations

import csv
import math
import re
from pathlib import Path

BASE_DIR   = Path(__file__).resolve().parent
MOSCOW_DIR = BASE_DIR / "moscow"
LOTS_SRC   = BASE_DIR / "investmoscow_sold_2022_2026_clean.with_norm.csv"
ENRICHED_PATH = BASE_DIR / "investmoscow_sold_2022_2026_enriched_geo.csv"

MAX_DISTANCE_M = 250

IMPLAUSIBLE_SUBSTRINGS = [
    "Станции зарядки телефонов",
    "Станции зарядки мобильных телефонов",
    "Постаматы",
    "Питьевая вода",
    "Кофейные автоматы",
    "Банкоматы",
    "Терминалы оплаты",
    "Платёжные терминалы",
    "Детские развлекательные автоматы",
    "Фотокабины / Автоматы фотопечати",
    "Аварийные / справочные / экстренные службы -> Справочные",
    "Жилищно-коммунальные",
    "Правоохранительные органы",
    "Новостройки -> Новостройки",
    "Общественные / политические организации",
]

IMPLAUSIBLE_NAME_SUBSTRINGS = [
    "банкомат",
    "5post",
    "5 post",
    "qiwi",
    "киви",
    "бери заряд",
    "автомат по продаже кофе",
    "кофейный автомат",
    "зарядная станция",
    "контейнер для сбора",
    "пункт сбора отработанных",
    "приема батареек",
    "приёма батареек",
    "добрыекрышечки",
    "немузеймусора",
    "автомат с ",
    "пункт приёма",
    "пункт приема",
]

_ADDRESS_LIKE_RE = re.compile(
    r"\b(улица|переулок|проспект|бульвар|шоссе|набережная|площадь|проезд|тупик)\b.{0,30}\d",
    re.IGNORECASE,
)


BRAND_ALIASES = {
    "wildberries": "Wildberries",
    "вайлдберриз": "Wildberries",
    "ozon": "Ozon",
    "озон": "Ozon",
    "яндекс маркет": "Яндекс Маркет",
    "яндекс.маркет": "Яндекс Маркет",
    "сдэк": "СДЭК",
    "cdek": "СДЭК",
    "авито": "Авито",
    "магнит": "Магнит",
    "пятёрочка": "Пятёрочка",
    "пятерочка": "Пятёрочка",
    "вкусвилл": "ВкусВилл",
    "вкус вилл": "ВкусВилл",
    "fix price": "Fix Price",
    "фикс прайс": "Fix Price",
    "красное&белое": "Красное&Белое",
    "красное & белое": "Красное&Белое",
    "винлаб": "Винлаб",
    "dns": "DNS",
    "днс": "DNS",
    "перекрёсток": "Перекрёсток",
    "перекресток": "Перекрёсток",
    "лента": "Лента",
}


KNOWN_BRANDS = set(BRAND_ALIASES.values())


def normalize_name(raw_name: str) -> str:
    """Return canonical brand name: strip suffix after first comma, apply aliases."""
    name = raw_name.split(",")[0].strip()
    key = name.lower().strip()
    return BRAND_ALIASES.get(key, name)


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def to_float(v):
    try:
        return float(str(v).strip().replace(",", "."))
    except Exception:
        return None


def usage_str(row):
    rubric = (row.get("rubric") or "").strip()
    sub = (row.get("subrubric") or "").strip()
    if rubric and sub:
        return f"{rubric} → {sub}"
    return rubric or sub


def is_implausible(name, usage):
    u = usage or ""
    if any(s in u for s in IMPLAUSIBLE_SUBSTRINGS):
        return True
    n = (name or "").lower()
    if any(s.lower() in n for s in IMPLAUSIBLE_NAME_SUBSTRINGS):
        return True
    return bool(_ADDRESS_LIKE_RE.search(name or ""))


def main():
    # Load lots: {address_norm: [(lot_id, lat, lon)]}
    lots_by_addr: dict[str, list[tuple]] = {}
    lot_ids: list[str] = []
    with LOTS_SRC.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            lid = str(row.get("номер_лота", "")).strip()
            addr = (row.get("address_norm") or "").strip()
            lat = to_float(row.get("latitude"))
            lon = to_float(row.get("longitude"))
            if not addr or lat is None or lon is None:
                continue
            lots_by_addr.setdefault(addr, []).append((lid, lat, lon))
            lot_ids.append(lid)

    print(f"Lots loaded: {len(lot_ids)}, unique addresses: {len(lots_by_addr)}")

    # history: lot_id -> set of "Name (Usage)" strings
    history: dict[str, set[str]] = {lid: set() for lid in lot_ids}

    snapshots = sorted(MOSCOW_DIR.glob("*.with_norm.csv"))
    print(f"Snapshots to process: {len(snapshots)}")

    for snap_path in snapshots:
        label = snap_path.stem.replace(".with_norm", "")
        print(f"  {label} ...", end=" ", flush=True)

        # Index snapshot by address_norm
        by_addr: dict[str, list[dict]] = {}
        with snap_path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                addr = (row.get("address_norm") or "").strip()
                if addr and addr in lots_by_addr:
                    by_addr.setdefault(addr, []).append(row)

        for addr, lot_list in lots_by_addr.items():
            orgs = by_addr.get(addr, [])
            if not orgs:
                continue
            # Use first lot's coords to check distance (all lots in building share address)
            _, ref_lat, ref_lon = lot_list[0]
            for org in orgs:
                org_lat = to_float(org.get("lat"))
                org_lon = to_float(org.get("lon"))
                if org_lat is None or org_lon is None:
                    continue
                if haversine_m(ref_lat, ref_lon, org_lat, org_lon) > MAX_DISTANCE_M:
                    continue
                name = (org.get("name") or "").strip()
                u = usage_str(org)
                if is_implausible(name, u):
                    continue
                canonical = normalize_name(name)
                if canonical in KNOWN_BRANDS:
                    entry = canonical
                else:
                    entry = f"{canonical} ({u})" if u else canonical
                for lid, _, __ in lot_list:
                    history[lid].add(entry)

        print(f"done")

    # Write column to enriched CSV
    with ENRICHED_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    col = "история_бизнесов"
    if col not in fieldnames:
        fieldnames.append(col)
        for row in rows:
            row.setdefault(col, "")

    filled = 0
    for row in rows:
        lid = str(row.get("номер_лота", "")).strip()
        entries = sorted(history.get(lid, set()))
        if entries:
            row[col] = " | ".join(entries)
            filled += 1
        else:
            row[col] = ""

    with ENRICHED_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone. Lots with business history: {filled}/{len(rows)}")
    print(f"Column '{col}' added to {ENRICHED_PATH.name}")


if __name__ == "__main__":
    main()
