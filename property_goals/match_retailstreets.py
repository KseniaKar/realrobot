"""
Match investmoscow lots with retailstreets chain requirements.

Outputs:
  matches/property_retailstreets_candidates.csv  — all (lot, chain) pairs
  matches/property_retailstreets_summary.csv     — per lot: chain count, top category, chain list
"""

import re
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
LOTS_PATH = BASE_DIR / "investmoscow_sold_2022_2026_enriched_geo.csv"
CHAINS_PATH = BASE_DIR.parent / "retailstreets_parser" / "data" / "retailstreets_requirements.csv"
OUT_DIR = BASE_DIR / "matches"
OUT_CANDIDATES = OUT_DIR / "property_retailstreets_candidates.csv"
OUT_SUMMARY = OUT_DIR / "property_retailstreets_summary.csv"


def normalize_floor(value: object) -> str:
    if pd.isna(value):
        return "Не указано"
    raw = str(value).replace("\xa0", " ").strip()
    if not raw:
        return "Не указано"
    lower = raw.lower()
    if "," in lower or " и выше" in lower:
        return "Многоуровневый"
    if "подвал" in lower or re.fullmatch(r"-\d+", lower):
        return "Подвал"
    if "цок" in lower:
        return "Цоколь"
    if "антрес" in lower:
        return "Антресоль"
    if "мансард" in lower:
        return "Мансарда"
    if "чердак" in lower:
        return "Чердак"
    if "тех" in lower:
        return "Техэтаж"
    if "мезонин" in lower:
        return "Мезонин"
    m = re.search(r"\d+", lower)
    if m:
        n = int(m.group())
        if n == 0:
            return "0 этаж"
        if n >= 5:
            return "5+ этаж"
        return f"{n} этаж"
    return raw


def parse_chain_floor_flags(floor_str: object) -> tuple[bool, bool, bool, bool]:
    """
    Returns (any_floor, allow_1st, allow_basement, allow_cellar).
    any_floor=True means no restriction.
    """
    if pd.isna(floor_str) or str(floor_str).strip() == "":
        return True, True, True, True

    raw = str(floor_str).lower()
    parts = [p.strip() for p in re.split(r"[;,]", raw) if p.strip()]

    allow_1st = False
    allow_basement = False
    allow_cellar = False

    for part in parts:
        if "подвал" in part or re.search(r"-\d+", part):
            allow_basement = True
        elif "цок" in part:
            allow_cellar = True
        elif re.search(r"\b1\b", part) or "перв" in part:
            allow_1st = True

    if not allow_1st and not allow_basement and not allow_cellar:
        return True, True, True, True

    return False, allow_1st, allow_basement, allow_cellar


def main():
    lots = pd.read_csv(LOTS_PATH, encoding="utf-8-sig")
    chains = pd.read_csv(CHAINS_PATH)

    lots["этаж_норм"] = lots["этаж"].apply(normalize_floor)
    lots["площадь_м²"] = pd.to_numeric(
        lots["площадь_м²"].astype(str).str.replace(",", ".").str.strip(), errors="coerce"
    )
    lots["_sep"] = lots["тип_входа"].fillna("").astype(str).str.lower().str.contains("отдельный")
    lots["_near_school"] = (
        pd.to_numeric(lots["near_school_100m"], errors="coerce").fillna(0) == 1
        if "near_school_100m" in lots.columns else False
    )

    # Алкомаркеты запрещены в 100м от образовательных учреждений (171-ФЗ, ст. 16)
    ALCOHOL_CATEGORY = "Алкомаркеты"
    chains["_is_alcohol"] = chains["category"].str.strip() == ALCOHOL_CATEGORY

    floor_flags = chains["floor"].apply(parse_chain_floor_flags)
    chains["_any_floor"] = floor_flags.apply(lambda x: x[0])
    chains["_allow_1st"] = floor_flags.apply(lambda x: x[1])
    chains["_allow_base"] = floor_flags.apply(lambda x: x[2])
    chains["_allow_cel"] = floor_flags.apply(lambda x: x[3])
    chains["_sep_req"] = chains["separate_entrance"].astype(str).str.lower().isin(["true", "1"])

    lot_cols = ["номер_лота", "адрес", "площадь_м²", "этаж_норм", "_sep", "_near_school"]
    chain_cols = ["name", "category", "area_min_m2", "area_max_m2", "contacts_email",
                  "_any_floor", "_allow_1st", "_allow_base", "_allow_cel", "_sep_req", "_is_alcohol"]

    lots_s = lots[lot_cols].copy()
    chains_s = chains[chain_cols].copy()

    lots_s["_k"] = 1
    chains_s["_k"] = 1
    cross = lots_s.merge(chains_s, on="_k").drop(columns="_k")

    area_ok = (
        cross["площадь_м²"].notna()
        & (cross["area_min_m2"].isna() | (cross["площадь_м²"] >= cross["area_min_m2"]))
        & (cross["area_max_m2"].isna() | (cross["площадь_м²"] <= cross["area_max_m2"]))
    )

    floor_ok = (
        cross["_any_floor"]
        | ((cross["этаж_норм"] == "1 этаж") & cross["_allow_1st"])
        | ((cross["этаж_норм"] == "Подвал") & cross["_allow_base"])
        | ((cross["этаж_норм"] == "Цоколь") & cross["_allow_cel"])
    )

    entrance_ok = ~cross["_sep_req"] | cross["_sep"]

    # Алкомаркеты запрещены в 100м от образовательных учреждений (171-ФЗ)
    alcohol_ok = ~(cross["_is_alcohol"] & cross["_near_school"])

    matched = cross[area_ok & floor_ok & entrance_ok & alcohol_ok].copy()
    matched = matched.drop(columns=["_sep", "_near_school", "_any_floor", "_allow_1st",
                                     "_allow_base", "_allow_cel", "_sep_req", "_is_alcohol"])
    matched = matched.rename(columns={"name": "chain_name"})

    OUT_DIR.mkdir(exist_ok=True)
    matched.to_csv(OUT_CANDIDATES, index=False, encoding="utf-8-sig")
    print(f"Candidates: {len(matched):,} matches across {matched['номер_лота'].nunique():,} lots")

    if matched.empty:
        print("No matches found.")
        return

    summary = (
        matched.groupby("номер_лота")
        .agg(
            rs_chains_count=("chain_name", "count"),
            rs_categories=("category", lambda x: ", ".join(sorted(set(x)))),
            rs_top_chains=("chain_name", lambda x: "; ".join(list(dict.fromkeys(x))[:8])),
        )
        .reset_index()
    )

    top_cat = (
        matched.groupby(["номер_лота", "category"])
        .size()
        .reset_index(name="n")
        .sort_values("n", ascending=False)
        .drop_duplicates("номер_лота")[["номер_лота", "category"]]
        .rename(columns={"category": "rs_top_category"})
    )
    summary = summary.merge(top_cat, on="номер_лота", how="left")
    summary.to_csv(OUT_SUMMARY, index=False, encoding="utf-8-sig")
    print(f"Summary: {len(summary):,} lots with at least one matching chain")

    print("\nTop categories by match count:")
    print(matched["category"].value_counts().head(15).to_string())
    print("\nFloor breakdown of matched lots:")
    print(matched["этаж_норм"].value_counts().head(10).to_string())


if __name__ == "__main__":
    main()
