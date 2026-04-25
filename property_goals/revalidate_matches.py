"""
Re-validate the 185 existing matches using retailstreets area requirements.

For each matched lot:
  1. Parse all candidates from company_candidates_preview / usage_candidates_preview
  2. Drop candidates that are implausible types (vending devices, government, non-tenants)
  3. Drop candidates whose lot area is absurdly outside the retailstreets range for that category
  4. Re-select likely_company from remaining valid candidates
  5. If no valid candidates remain — clear the match

Outputs:
  matches/revalidation_report.csv  — per-lot summary of changes
  investmoscow_sold_2022_2026_enriched_geo.csv  — updated in-place
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
MATCH_DIR = BASE_DIR / "matches"

ENRICHED_PATH = BASE_DIR / "investmoscow_sold_2022_2026_enriched_geo.csv"
CHAINS_PATH = BASE_DIR.parent / "retailstreets_parser" / "data" / "retailstreets_requirements.csv"
REPORT_PATH = MATCH_DIR / "revalidation_report.csv"
BACKUP_PATH = BASE_DIR / "investmoscow_sold_2022_2026_enriched_geo.csv.bak"

# Tolerance multipliers for area check
AREA_MAX_MULTIPLIER = 4.0   # lot can be up to 4x the rs area_max before we flag it
AREA_MIN_MULTIPLIER = 0.25  # lot can be down to 0.25x the rs area_min before we flag it

# --- Implausible types ---
# Patterns matched against the full "rubric -> subrubric" usage string.
# A candidate matching ANY of these is not a standalone commercial tenant.
IMPLAUSIBLE_SUBSTRINGS = [
    "Станции зарядки телефонов",   # Бери заряд etc. — devices, not tenants
    "Постаматы",                    # parcel lockers — devices
    "Питьевая вода",                # water vending machines
    "Кофейные автоматы",            # coffee vending machines
    "Аварийные / справочные / экстренные службы -> Справочные",  # gov hotlines
    "Жилищно-коммунальные",         # HOA dispatch / management
    "Правоохранительные органы",    # police
    "Новостройки -> Новостройки",   # construction projects
    "Общественные / политические организации",  # public orgs
]

# --- Usage string → retailstreets category ---
# Match against substrings of the usage string (case-insensitive).
# First match wins.
USAGE_TO_RS_CATEGORY: list[tuple[str, str]] = [
    ("Пункты выдачи интернет-заказов",   "Пунк выдачи"),
    ("Супермаркеты",                      "Супермаркет/Гипермаркет"),
    ("Дарксторы",                         "Дарксторы"),
    ("Алкогольные напитки",               "Алкомаркеты"),
    ("Аптеки",                            "Аптеки"),
    ("Медицинские товары",                "Аптеки"),       # аптека category often tagged here
    ("Быстрое питание",                   "Общепит"),
    ("Рестораны",                         "Общепит"),
    ("Кафе",                              "Общепит"),
    ("Бары",                              "Общепит"),
    ("Продуктовые магазины",              "Продукты"),
    ("Доставка продуктов",                "Продукты"),
    ("Барбершопы",                        "Салоны красоты, барбершопы, парикмахерские"),
    ("Парикмахерские",                    "Салоны красоты, барбершопы, парикмахерские"),
    ("Ювелирн",                           "Ювелирный"),
    ("Оптика",                            "Оптика"),
    ("Обувь",                             "Обувь"),
    ("Спортивн",                          "Спорт"),
    ("Товары для дома",                   "Товары для дома"),
    ("Мебель",                            "Мебель"),
    ("Стройматериалы",                    "Стройматериалы"),
    ("Натяжные потолки",                  "Стройматериалы"),
    ("Электронник",                       "Электронника, бытовая техника"),
    ("Бытовая техника",                   "Электронника, бытовая техника"),
    ("Зоомагазин",                        "Зоомагазины"),
    ("Уход за животными",                 "Зоомагазины"),
    ("Детские товары",                    "Детские товары"),
    ("Банки",                             "Банки"),
    ("Страхование",                       "Банки"),
    ("Кофе с собой",                      "Кофе с собой"),
    ("Салоны связи",                      "Салоны связи"),
    ("Парфюмери",                         "Парфюмерия и косметика"),
    ("Косметик",                          "Парфюмерия и косметика"),
    ("Фото",                              "Фото/печатные салоны"),
    ("Пункт выдачи",                      "Пунк выдачи"),
]


def build_rs_area_limits(chains_path: Path) -> dict[str, tuple[float, float]]:
    """Returns {category: (hard_min, hard_max)} using stated ranges + tolerance multipliers."""
    df = pd.read_csv(chains_path)
    limits: dict[str, tuple[float, float]] = {}
    for cat, grp in df.groupby("category"):
        min_vals = grp["area_min_m2"].dropna()
        max_vals = grp["area_max_m2"].dropna()
        if min_vals.empty and max_vals.empty:
            continue
        hard_min = float(min_vals.min()) * AREA_MIN_MULTIPLIER if not min_vals.empty else 0.0
        hard_max = float(max_vals.quantile(0.75)) * AREA_MAX_MULTIPLIER if not max_vals.empty else float("inf")
        limits[str(cat)] = (hard_min, hard_max)
    return limits


def usage_to_rs_category(usage: str) -> str | None:
    lower = usage.lower()
    for keyword, cat in USAGE_TO_RS_CATEGORY:
        if keyword.lower() in lower:
            return cat
    return None


def is_implausible(usage: str) -> bool:
    for pattern in IMPLAUSIBLE_SUBSTRINGS:
        if pattern.lower() in usage.lower():
            return True
    return False


def area_mismatch(lot_area: float | None, rs_cat: str | None, limits: dict) -> bool:
    if lot_area is None or rs_cat is None or rs_cat not in limits:
        return False
    hard_min, hard_max = limits[rs_cat]
    return lot_area < hard_min or lot_area > hard_max


def parse_pipe(value: str) -> list[str]:
    return [s.strip() for s in str(value).split("|") if s.strip()] if value and str(value).strip() else []


def reselect(
    company_list: list[str],
    usage_list: list[str],
    lot_area: float | None,
    rs_limits: dict,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """
    Returns (valid_companies, valid_usages, dropped_companies, drop_reasons).
    """
    valid_c, valid_u, dropped_c, reasons = [], [], [], []

    pairs = list(zip(company_list, usage_list))
    # Pad if lists differ in length (shouldn't normally happen)
    for i in range(max(len(company_list), len(usage_list))):
        c = company_list[i] if i < len(company_list) else ""
        u = usage_list[i] if i < len(usage_list) else ""

        if is_implausible(u):
            dropped_c.append(c)
            reasons.append(f"IMPLAUSIBLE_TYPE: {u}")
            continue

        rs_cat = usage_to_rs_category(u)
        if area_mismatch(lot_area, rs_cat, rs_limits):
            hard_min, hard_max = rs_limits[rs_cat]
            dropped_c.append(c)
            reasons.append(f"AREA_MISMATCH({lot_area:.0f}m² vs {hard_min:.0f}-{hard_max:.0f} for {rs_cat}): {c}")
            continue

        valid_c.append(c)
        valid_u.append(u)

    return valid_c, valid_u, dropped_c, reasons


def compact(items: list[str], limit: int = 5) -> str:
    return " | ".join(items[:limit])


def main() -> None:
    rs_limits = build_rs_area_limits(CHAINS_PATH)
    print("Retailstreets area limits loaded:", len(rs_limits), "categories")

    # Backup original
    if not BACKUP_PATH.exists():
        shutil.copyfile(ENRICHED_PATH, BACKUP_PATH)
        print("Backup saved to", BACKUP_PATH.name)

    with ENRICHED_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    report_rows = []
    changed = 0
    cleared = 0
    unchanged = 0

    for row in rows:
        confidence = (row.get("match_confidence") or "").strip()
        if not confidence:
            continue  # not matched, skip

        lot_area_raw = (row.get("площадь_м²") or "").replace(",", ".").strip()
        try:
            lot_area: float | None = float(lot_area_raw)
        except ValueError:
            lot_area = None

        lot_id = row.get("номер_лота", "")
        orig_company = (row.get("likely_company") or "").strip()
        orig_usage = (row.get("likely_usage") or "").strip()

        company_list = parse_pipe(row.get("company_candidates_preview", ""))
        usage_list = parse_pipe(row.get("usage_candidates_preview", ""))

        # If only 1 candidate the preview might be just the likely values
        if not company_list:
            company_list = parse_pipe(orig_company)
        if not usage_list:
            usage_list = parse_pipe(orig_usage)

        valid_c, valid_u, dropped_c, reasons = reselect(company_list, usage_list, lot_area, rs_limits)

        if not dropped_c:
            unchanged += 1
            report_rows.append({
                "номер_лота": lot_id,
                "площадь_м²": lot_area,
                "этаж": row.get("этаж", ""),
                "confidence": confidence,
                "source": row.get("match_time_window", ""),
                "status": "unchanged",
                "orig_company": orig_company,
                "new_company": orig_company,
                "dropped": "",
                "drop_reasons": "",
            })
            continue

        changed += 1
        if valid_c:
            new_confidence = confidence
            if confidence == "high" and len(valid_c) > 1:
                new_confidence = "medium"
            new_company = valid_c[0] if new_confidence == "high" else compact(valid_c, 3)
            new_usage = valid_u[0] if new_confidence == "high" else compact(valid_u, 3)
            status = "filtered_candidates"
        else:
            cleared += 1
            new_company = ""
            new_usage = ""
            new_confidence = ""
            status = "cleared"

        row["likely_company"] = new_company
        row["likely_usage"] = new_usage
        row["match_confidence"] = new_confidence
        row["company_candidates_preview"] = compact(valid_c)
        row["usage_candidates_preview"] = compact(valid_u)

        report_rows.append({
            "номер_лота": lot_id,
            "площадь_м²": lot_area,
            "этаж": row.get("этаж", ""),
            "confidence": confidence,
            "source": row.get("match_time_window", ""),
            "status": status,
            "orig_company": orig_company,
            "new_company": new_company,
            "dropped": compact(dropped_c),
            "drop_reasons": " || ".join(reasons),
        })

    with ENRICHED_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    MATCH_DIR.mkdir(exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        report_fields = [
            "номер_лота", "площадь_м²", "этаж", "confidence", "source",
            "status", "orig_company", "new_company", "dropped", "drop_reasons",
        ]
        writer = csv.DictWriter(f, fieldnames=report_fields)
        writer.writeheader()
        writer.writerows(report_rows)

    total = unchanged + changed
    print(f"\nTotal matched lots processed: {total}")
    print(f"  unchanged:           {unchanged}")
    print(f"  changed (filtered):  {changed - cleared}")
    print(f"  cleared (no valid):  {cleared}")
    print(f"\nReport saved to: {REPORT_PATH.name}")
    print(f"Enriched CSV updated: {ENRICHED_PATH.name}")


if __name__ == "__main__":
    main()
