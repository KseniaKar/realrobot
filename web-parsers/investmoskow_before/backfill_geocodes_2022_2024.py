import json
import os
import re
import sys
import time
import argparse
import ast
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CSV_PATH = DATA_DIR / "investmoscow_completed_2022_2024_geocoded.csv"
LEGACY_CACHE_PATH = DATA_DIR / "geocache_dadata_2022_2024.json"
ACTIVE_CACHE_PATH = DATA_DIR / "geocache_2022_2024.json"
OUTPUT_PATH = DATA_DIR / "investmoscow_completed_2022_2024_geocoded.csv"
SOURCE_CACHE_PATHS = [
    DATA_DIR / "all_tenders_cache_2022_2023.json",
    DATA_DIR / "all_tenders_cache_2024.json",
]

DADATA_TOKEN = "8913d4826729f1ed621003167250e215ac016fd1"
DADATA_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address"
HEADERS = {
    "Authorization": f"Token {DADATA_TOKEN}",
    "Content-Type": "application/json; charset=utf-8",
}

FLOOR_PATTERNS = [
    r",?\s*этаж\s*№?\s*[^,;]*",
    r",?\s*подвал\s*№?\s*[^,;]*",
    r",?\s*цокольн(?:ый|ого)?\s*этаж\s*№?\s*[^,;]*",
    r",?\s*подземн(?:ый|ого)?\s*этаж\s*№?\s*[^,;]*",
    r",?\s*техническ(?:ий|ого)?\s*этаж\s*№?\s*[^,;]*",
    r",?\s*помещени[ея]\s*[^,;]*",
    r",?\s*пом\.\s*[^,;]*",
    r",?\s*не указано",
]
NOISE_PATTERNS = [
    r"\bроссийская федерация\b,?\s*",
    r"\bгород\s+москва\b,?\s*",
    r"\bг\.?\s*москва\b,?\s*",
    r"\bвнутригородская территория\b,?\s*",
    r"\bмуниципальный округ\b,?\s*",
]
AO_PATTERN = re.compile(r"^[А-Яа-яЁё\s-]+административный округ,\s*", re.IGNORECASE)
DISTRICT_HINT_RE = re.compile(
    r"(?:^|,\s*)([А-Яа-яЁё0-9\-\s]+?),\s*(?:ул\.|улица|проспект|пр-кт\.|пр\.|шоссе|ш\.|переулок|пер\.|проезд|бульвар|б-р|аллея|набережная|наб\.|площадь|тупик|микрорайон)",
    re.IGNORECASE,
)
HOUSE_RE = re.compile(r"\b(?:дом|д\.)\s*([0-9]+(?:/[0-9]+)?[А-Яа-яA-Za-z]?)", re.IGNORECASE)
KORP_RE = re.compile(r"\b(?:корпус|к\.)\s*([0-9]+[А-Яа-яA-Za-z]?)", re.IGNORECASE)
STR_RE = re.compile(r"\b(?:строение|стр\.)\s*([0-9]+[А-Яа-яA-Za-z]?)", re.IGNORECASE)
BARE_HOUSE_RE = re.compile(r"(?:,|\s)([0-9]+(?:/[0-9]+)?[А-Яа-яA-Za-z]?)$", re.IGNORECASE)
STREET_RE = re.compile(
    r"((?:(?:улица|ул\.|проспект|пр-кт\.|пр\.|шоссе|ш\.|переулок|пер\.|проезд|бульвар|б-р|аллея|набережная|наб\.|площадь|тупик)\s+[А-Яа-яЁё0-9\-\s]+)|(?:(?:[0-9]+-я\s+)?[А-Яа-яЁё0-9\-\s]+?\s+(?:улица|ул\.|проспект|пр-кт\.|пр\.|шоссе|ш\.|переулок|пер\.|проезд|бульвар|б-р|аллея|набережная|наб\.|площадь|тупик)))",
    re.IGNORECASE,
)
ZELENOGRAD_KORP_RE = re.compile(r"\bкорпус\s*([0-9]+[А-Яа-яA-Za-z]?)\b", re.IGNORECASE)


def normalize_spaces(value: str) -> str:
    return " ".join(str(value).replace("\xa0", " ").replace("\n", " ").split()).strip()


def strip_floor_noise(value: str) -> str:
    value = normalize_spaces(value)
    for pattern in FLOOR_PATTERNS:
        value = re.sub(pattern, "", value, flags=re.IGNORECASE)
    value = re.sub(r",\s*,+", ",", value)
    return value.strip(" ,")


def strip_admin_noise(value: str) -> str:
    value = strip_floor_noise(value)
    value = AO_PATTERN.sub("", value)
    for pattern in NOISE_PATTERNS:
        value = re.sub(pattern, "", value, flags=re.IGNORECASE)
    value = re.sub(r",\s*,+", ",", value)
    return value.strip(" ,")


def canonical_text(value: str) -> str:
    value = strip_admin_noise(value).lower()
    replacements = {
        "улица": "ул.",
        "дом ": "д.",
        "корпус ": "к.",
        "строение ": "стр.",
        "переулок": "пер.",
        "проезд": "пр.",
        "проспект": "пр-кт.",
        "шоссе": "ш.",
        "бульвар": "б-р",
        "набережная": "наб.",
    }
    for src, dst in replacements.items():
        value = value.replace(src, dst)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r",\s*,+", ",", value)
    return value.strip(" ,")


def extract_street(value: str) -> str:
    match = STREET_RE.search(value)
    if not match:
        return ""
    street = match.group(1).lower().strip(" ,")
    street = street.replace("улица", "ул.")
    return re.sub(r"\s+", " ", street)


def extract_building_parts(value: str) -> tuple[str, str, str]:
    house_match = HOUSE_RE.search(value)
    korp_match = KORP_RE.search(value)
    str_match = STR_RE.search(value)
    house = house_match.group(1).lower() if house_match else ""
    if not house:
        bare_match = BARE_HOUSE_RE.search(value.strip())
        house = bare_match.group(1).lower() if bare_match else ""
    korp = korp_match.group(1).lower() if korp_match else ""
    stroenie = str_match.group(1).lower() if str_match else ""
    return house, korp, stroenie


def extract_district_hint(value: str) -> str:
    cleaned = strip_admin_noise(value)
    match = DISTRICT_HINT_RE.search(cleaned)
    if match:
        hint = match.group(1).strip(" ,").lower()
        return re.sub(r"\s+", " ", hint)
    return ""


def building_fingerprint(value: str) -> str:
    cleaned = canonical_text(value)
    street = extract_street(cleaned)
    house, korp, stroenie = extract_building_parts(cleaned)
    if "зеленоград" in cleaned and not street:
        korp_only = ZELENOGRAD_KORP_RE.search(cleaned)
        if korp_only:
            return f"зеленоград|корпус:{korp_only.group(1).lower()}"
    if not street or not house:
        return ""
    return f"{street}|д:{house}|к:{korp}|стр:{stroenie}"


def relaxed_fingerprint(value: str) -> str:
    fp = building_fingerprint(value)
    if not fp:
        return ""
    parts = fp.split("|")
    return "|".join(parts[:2])


def request_dadata(query: str) -> List[dict]:
    payload = {
        "query": query,
        "count": 5,
        "locations": [{"kladr_id": "7700000000000"}],
    }
    try:
        response = requests.post(
            DADATA_URL,
            headers=HEADERS,
            json=payload,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []
    suggestions = data.get("suggestions") or []
    return suggestions


def query_variants(raw_address: str) -> list[str]:
    cleaned = strip_floor_noise(raw_address)
    admin_stripped = strip_admin_noise(raw_address)
    canonical = canonical_text(raw_address)
    street = extract_street(canonical)
    house, korp, stroenie = extract_building_parts(canonical)
    district = extract_district_hint(raw_address)

    variants = []
    if admin_stripped:
        variants.append(f"{admin_stripped}, Москва")
    if district and street and house:
        query = f"{district}, Москва, {street}, дом {house}"
        if korp:
            query += f", корпус {korp}"
        if stroenie:
            query += f", строение {stroenie}"
        variants.append(query)
    if street and house:
        query = f"Москва, {street}, дом {house}"
        if korp:
            query += f", корпус {korp}"
        if stroenie:
            query += f", строение {stroenie}"
        variants.append(query)
    if cleaned:
        variants.append(cleaned)

    unique = []
    seen = set()
    for variant in variants:
        variant = normalize_spaces(variant)
        if variant and variant not in seen:
            seen.add(variant)
            unique.append(variant)
    return unique


def is_valid_match(raw_address: str, suggestion: dict) -> bool:
    if not suggestion:
        return False
    data = suggestion.get("data") or {}
    lat = data.get("geo_lat")
    lon = data.get("geo_lon")
    if not lat or not lon:
        return False

    expected_fp = building_fingerprint(raw_address)
    if not expected_fp:
        return False
    unrestricted = suggestion.get("unrestricted_value") or suggestion.get("value") or ""
    actual_fp = building_fingerprint(unrestricted)
    if not actual_fp:
        return False

    expected_parts = expected_fp.split("|")
    actual_parts = actual_fp.split("|")
    if len(expected_parts) != 4 or len(actual_parts) != 4:
        return False

    expected_street, expected_house, expected_korp, expected_str = expected_parts
    actual_street, actual_house, actual_korp, actual_str = actual_parts

    if expected_street != actual_street or expected_house != actual_house:
        return False
    if expected_korp and actual_korp and expected_korp != actual_korp:
        return False
    if expected_str and actual_str and expected_str != actual_str:
        return False
    return True


def load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_cache(path: Path, cache: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=False, indent=2)


def coords_from_record(record: dict) -> Optional[Tuple[float, float]]:
    if not record:
        return None
    try:
        return float(record["lat"]), float(record["lon"])
    except Exception:
        return None


def load_source_coords() -> Dict[str, Tuple[float, float]]:
    result: Dict[str, Tuple[float, float]] = {}
    for path in SOURCE_CACHE_PATHS:
        if not path.exists():
            continue
        with open(path, "r", encoding="utf-8") as handle:
            items = json.load(handle)
        for item in items:
            coords = item.get("coords")
            if item.get("ignoreCoords") or not coords:
                continue
            if isinstance(coords, str):
                try:
                    coords = ast.literal_eval(coords)
                except Exception:
                    continue
            if not isinstance(coords, (list, tuple)) or len(coords) != 2:
                continue
            try:
                result[str(item.get("id"))] = (float(coords[0]), float(coords[1]))
            except Exception:
                continue
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-api", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
    addr_col = df.columns[9]
    lot_col = df.columns[1]
    cad_col = df.columns[10]
    year_col = df.columns[17]
    mask_missing = df["latitude"].isna() | df["longitude"].isna()

    df["building_fp"] = df[addr_col].apply(building_fingerprint)
    df["relaxed_fp"] = df[addr_col].apply(relaxed_fingerprint)

    coord_sources: Dict[str, Tuple[float, float]] = {}
    cad_sources: Dict[str, Tuple[float, float]] = {}
    relaxed_sources: Dict[str, Tuple[float, float]] = {}
    lot_sources = load_source_coords()

    geocoded_rows = df.loc[~mask_missing & df["building_fp"].ne(""), ["building_fp", "latitude", "longitude"]]
    for row in geocoded_rows.itertuples(index=False):
        coord_sources[row.building_fp] = (float(row.latitude), float(row.longitude))

    geocoded_relaxed = df.loc[
        ~mask_missing & df["relaxed_fp"].ne(""),
        ["relaxed_fp", "latitude", "longitude"],
    ].copy()
    if not geocoded_relaxed.empty:
        grouped = geocoded_relaxed.groupby("relaxed_fp")
        for key, group in grouped:
            if group["latitude"].nunique() == 1 and group["longitude"].nunique() == 1:
                relaxed_sources[key] = (float(group["latitude"].iloc[0]), float(group["longitude"].iloc[0]))

    geocoded_cad = df.loc[
        ~mask_missing & df[cad_col].notna() & (df[cad_col].astype(str).str.strip() != ""),
        [cad_col, "latitude", "longitude"],
    ].drop_duplicates(cad_col)
    for _, row in geocoded_cad.iterrows():
        cad_sources[str(row[cad_col]).strip()] = (float(row["latitude"]), float(row["longitude"]))

    legacy_cache = load_cache(LEGACY_CACHE_PATH)
    for key, value in legacy_cache.items():
        coords = coords_from_record(value)
        if not coords:
            continue
        fp = building_fingerprint(key)
        if fp and fp not in coord_sources:
            coord_sources[fp] = coords

    active_cache = load_cache(ACTIVE_CACHE_PATH)
    for key, value in active_cache.items():
        coords = coords_from_record(value)
        if not coords:
            continue
        fp = building_fingerprint(key)
        if fp and fp not in coord_sources:
            coord_sources[fp] = coords

    filled_from_local = 0
    for idx, row in df.loc[mask_missing].iterrows():
        lot_id = str(row[lot_col]).strip() if pd.notna(row[lot_col]) else ""
        cad = str(row[cad_col]).strip() if pd.notna(row[cad_col]) else ""
        fp = row["building_fp"]
        relaxed_fp = row["relaxed_fp"]
        coords = lot_sources.get(lot_id) if lot_id else None
        if not coords:
            coords = cad_sources.get(cad) if cad else None
        if not coords:
            coords = coord_sources.get(fp)
        if not coords and relaxed_fp:
            coords = relaxed_sources.get(relaxed_fp)
        if coords:
            df.at[idx, "latitude"] = coords[0]
            df.at[idx, "longitude"] = coords[1]
            filled_from_local += 1

    print(f"Filled from source/local matches: {filled_from_local}")

    mask_missing = df["latitude"].isna() | df["longitude"].isna()
    unresolved = df.loc[mask_missing, [addr_col, year_col, "building_fp"]].copy()
    unresolved = unresolved[unresolved["building_fp"].ne("")]
    unresolved = unresolved.drop_duplicates("building_fp")
    if args.limit > 0:
        unresolved = unresolved.head(args.limit)

    print(f"Still unresolved buildings after source backfill: {len(unresolved)}")

    api_success = 0
    api_fail = 0
    if not args.skip_api:
        for i, (_, row) in enumerate(unresolved.iterrows(), 1):
            raw_address = row[addr_col]
            fp = row["building_fp"]
            if fp in coord_sources:
                continue
            best = None
            for query in query_variants(raw_address):
                suggestions = request_dadata(query)
                for suggestion in suggestions:
                    if is_valid_match(raw_address, suggestion):
                        data = suggestion["data"]
                        best = (float(data["geo_lat"]), float(data["geo_lon"]), query)
                        break
                if best:
                    break
                time.sleep(0.15)
            if best:
                coord_sources[fp] = (best[0], best[1])
                active_cache[canonical_text(raw_address)] = {"lat": best[0], "lon": best[1]}
                api_success += 1
            else:
                active_cache[canonical_text(raw_address)] = None
                api_fail += 1
            if i % 50 == 0:
                print(f"API processed {i}/{len(unresolved)} success={api_success} fail={api_fail}")

    save_cache(ACTIVE_CACHE_PATH, active_cache)

    final_filled = 0
    for idx, row in df.loc[df["latitude"].isna() | df["longitude"].isna()].iterrows():
        coords = coord_sources.get(row["building_fp"])
        if coords:
            df.at[idx, "latitude"] = coords[0]
            df.at[idx, "longitude"] = coords[1]
            final_filled += 1

    df = df.drop(columns=["building_fp", "relaxed_fp"])
    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    final_missing = int((df["latitude"].isna() | df["longitude"].isna()).sum())
    print(f"Filled after API fallback: {final_filled}")
    print(f"Final total: {len(df)}")
    print(f"Final geocoded: {int(df['latitude'].notna().sum())}")
    print(f"Final missing: {final_missing}")
    print("By year:")
    summary = (
        df.assign(geocoded=df["latitude"].notna() & df["longitude"].notna())
        .groupby(year_col)
        .agg(total=("geocoded", "size"), geocoded=("geocoded", "sum"))
    )
    summary["missing"] = summary["total"] - summary["geocoded"]
    summary["pct_geocoded"] = (summary["geocoded"] / summary["total"] * 100).round(2)
    print(summary.to_string())


if __name__ == "__main__":
    main()
