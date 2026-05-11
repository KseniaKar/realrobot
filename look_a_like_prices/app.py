import json
from pathlib import Path
import re

import altair as alt
import folium
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium
import xgboost as xgb

BASE_DIR = Path(__file__).resolve().parent
ANALOGUES_PATH  = BASE_DIR / "data" / "sale_dedup.csv"
ARENDA_PATH     = BASE_DIR / "data" / "arenda_dedup.csv"
ENTRANCE_PATH   = BASE_DIR / "_entrance_results.csv"
LOTS_PATH       = BASE_DIR.parent / "property_goals" / "investmoscow_sold_2022_2026_enriched_geo.csv"
BUILDINGS_PATH  = BASE_DIR / "data" / "buildings_moscow.parquet"
MODEL_PATH      = BASE_DIR / "data" / "hedonic_xgb.json"
FEATURES_PATH   = BASE_DIR / "data" / "hedonic_features.json"

NORM_ENTRANCE = {
    'отдельный':          'отдельный',
    'общий':              'общий',
    'отдельный с улицы':  'отдельный с улицы', 'separateFromTheStreet': 'отдельный с улицы',
    'separateFromStreet': 'отдельный с улицы',
    'отдельный со двора': 'отдельный со двора', 'separateFromTheYard': 'отдельный со двора',
    'separateFromYard':   'отдельный со двора',
    'общий с улицы':      'общий с улицы',
    'commonFromStreet':   'общий с улицы', 'commonFromTheStreet': 'общий с улицы',
    'общий со двора':     'общий со двора',
    'commonFromYard':     'общий со двора', 'commonFromTheYard': 'общий со двора',
    'через подъезд':      'через подъезд', 'throughEntrance': 'через подъезд',
    'через холл':         'через холл',    'throughHall':     'через холл',
}

XGB_MAPE  = 0.31  # GroupKFold CV, обновлять после переобучения
TERR_MAPE = 0.35  # LOO-CV территориальная медиана (продажа и аренда)

_FLOOR_LOT = {
    "подвал": "цоколь", "цоколь": "цоколь", "-1": "цоколь", "-2": "цоколь",
    "1": "1", "1 этаж": "1",
    "2": "2", "3": "3+", "4": "3+", "5": "3+",
}

def _norm_floor_lot(s):
    if not isinstance(s, str): return None
    s = s.strip().lower()
    if s in _FLOOR_LOT: return _FLOOR_LOT[s]
    try:
        n = int(s)
        return "цоколь" if n <= 0 else ("1" if n == 1 else ("2" if n == 2 else "3+"))
    except ValueError: pass
    return None

_ENTRANCE_LOT = {
    "отдельный":                           "отдельный с улицы",
    "вход через места общего пользования": "общий с улицы",
    "вход через подъезд":                  "общий с улицы",
}

_VID_LOT = {
    "свободное":      "Помещение свободного назначения",
    "бытовые услуги": "Торговое помещение",
}

st.set_page_config(page_title="Аналоги продажи", layout="wide")


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6_371_000
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi, dlam = np.radians(lat2 - lat1), np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
    return R * 2 * np.arcsin(np.sqrt(a))


def haversine_vec(lat1, lon1, lats, lons):
    R = 6_371_000
    phi1 = np.radians(lat1)
    phi2 = np.radians(lats)
    dphi = np.radians(lats - lat1)
    dlam = np.radians(lons - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
    return R * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _parse_param(params_str, key):
    if not isinstance(params_str, str):
        return None
    m = re.search(rf"{re.escape(key)}=([^|]+)", params_str)
    return m.group(1).strip() if m else None


def _get_area(row):
    val = _parse_param(row["Доп.параметры"], "Общая площадь")
    if val:
        try:
            return float(val.replace(",", "."))
        except ValueError:
            pass
    m = re.search(r"\((\d+[\.,]?\d*)\s*м", str(row["Название"]))
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            pass
    return None


def normalize_floor(s):
    if not isinstance(s, str):
        return None
    s = s.strip().lower()
    if s in ("цокольный", "цоколь", "подвальный", "подвал", "-1", "0"):
        return "цоколь"
    if s == "1":
        return "1"
    if s == "2":
        return "2"
    try:
        n = int(s)
        return "3+" if n >= 3 else s
    except ValueError:
        pass
    return s


@st.cache_data
def load_analogues():
    df = pd.read_csv(str(ANALOGUES_PATH), sep=";", encoding="utf-8-sig")
    df["площадь"] = df.apply(_get_area, axis=1)
    df["цена"] = pd.to_numeric(df["Цена"], errors="coerce")
    df["цена_млн"] = df["цена"] / 1_000_000
    df["цена_за_м²"] = np.where(
        df["площадь"].fillna(0) > 0, df["цена"] / df["площадь"], np.nan
    )
    df["этаж"] = df["Доп.параметры"].apply(lambda x: _parse_param(x, "Этаж"))
    df["этаж_норм"] = df["этаж"].apply(normalize_floor)
    df["вид_объекта"] = df["Доп.параметры"].apply(lambda x: _parse_param(x, "Вид объекта"))
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lng"] = pd.to_numeric(df["lng"], errors="coerce")
    if "Расстояние до метро, км" in df.columns:
        df["Расстояние до метро, км"] = pd.to_numeric(df["Расстояние до метро, км"], errors="coerce")
    df = df[df["этаж_норм"] != "-2"]
    df = df[df["площадь"].isna() | (df["площадь"] >= 15)]  # убираем кладовки и ларьки
    df = df.dropna(subset=["lat", "lng", "цена"]).copy()
    df = df[df["цена_за_м²"].isna() | (df["цена_за_м²"].between(50_000, 3_000_000))].copy()
    # джойним тип входа из спарсенных данных
    if ENTRANCE_PATH.exists():
        ent = pd.read_csv(str(ENTRANCE_PATH), encoding="utf-8-sig")
        ent["тип_входа"] = ent["тип_входа_циан"].map(NORM_ENTRANCE)
        df = df.merge(ent[["URL", "тип_входа"]], on="URL", how="left")
    else:
        df["тип_входа"] = None
    return df


@st.cache_data
def load_model():
    booster = xgb.Booster()
    booster.load_model(str(MODEL_PATH))
    with open(FEATURES_PATH, encoding="utf-8") as fh:
        feature_cols = json.load(fh)
    return booster, feature_cols


KREMLIN_LAT, KREMLIN_LON = 55.7520, 37.6175

_ВХОД_ОТДЕЛЬНЫЙ = {'отдельный', 'отдельный с улицы', 'отдельный со двора'}
_ВХОД_ОБЩИЙ     = {'общий', 'общий с улицы', 'через подъезд', 'через холл'}

def predict_price_m2(booster, feature_cols, lot, apt_400, apt_800,
                     median_rent_700m_same_type=np.nan,
                     median_rent_1500m=np.nan, rent_count_700m=0, sale_count_700m=0):
    floor       = _norm_floor_lot(str(lot.get("этаж", "")))
    entrance    = _ENTRANCE_LOT.get(str(lot.get("тип_входа", "")).strip().lower())
    vid         = _VID_LOT.get(str(lot.get("функциональное_назначение", "")).strip().lower())

    row = {c: 0.0 for c in feature_cols}
    row["площадь"] = float(lot["площадь_м²"]) if pd.notna(lot.get("площадь_м²")) else np.nan
    row["до_метро"] = np.nan
    row["apt_400"]  = float(apt_400)
    row["apt_800"]  = float(apt_800)
    if "median_rent_700m_same_type" in row:
        row["median_rent_700m_same_type"] = float(median_rent_700m_same_type) if np.isfinite(median_rent_700m_same_type) else 0.0
    if "median_rent_1500m" in row:
        row["median_rent_1500m"] = float(median_rent_1500m) if np.isfinite(median_rent_1500m) else 0.0
    if "rent_count_700m" in row:
        row["rent_count_700m"] = float(rent_count_700m)
    if "sale_count_700m" in row:
        row["sale_count_700m"] = float(sale_count_700m)
    row["lat"] = float(lot["latitude"])
    row["lng"] = float(lot["longitude"])
    if "dist_kremlin" in row:
        row["dist_kremlin"] = haversine_m(KREMLIN_LAT, KREMLIN_LON,
                                          float(lot["latitude"]), float(lot["longitude"]))
    if floor and f"этаж_{floor}" in row:
        row[f"этаж_{floor}"] = 1.0
    if "вход_отдельный_any" in row and entrance in _ВХОД_ОТДЕЛЬНЫЙ:
        row["вход_отдельный_any"] = 1.0
    if "вход_общий_any" in row and entrance in _ВХОД_ОБЩИЙ:
        row["вход_общий_any"] = 1.0
    if vid and f"вид_{vid}" in row:
        row[f"вид_{vid}"] = 1.0

    X = np.array([[row[c] for c in feature_cols]], dtype=np.float32)
    dm = xgb.DMatrix(X, feature_names=feature_cols)
    log_pred = booster.predict(dm)[0]
    return float(np.exp(log_pred))


@st.cache_data
def load_buildings():
    df = pd.read_parquet(BUILDINGS_PATH, columns=["lat", "lng", "apt_living", "residents_est"])
    return df


def count_residents(lat, lon, radius_m, buildings):
    dists = haversine_vec(lat, lon, buildings["lat"].values, buildings["lng"].values)
    mask = dists <= radius_m
    apts = int(buildings.loc[mask, "apt_living"].sum())
    residents = int(buildings.loc[mask, "residents_est"].sum())
    return apts, residents


def territorial_price(lot_lat, lot_lon, lot_floor_norm, lot_area, lot_entrance, ana_df, radius_m):
    dists = haversine_vec(lot_lat, lot_lon, ana_df["lat"].values, ana_df["lng"].values)
    mask = (dists <= radius_m) & ana_df["цена_за_м²"].notna()
    if lot_floor_norm:
        mask &= ana_df["этаж_норм"].values == lot_floor_norm
    if lot_area and lot_area > 0:
        mask &= (ana_df["площадь"].values >= lot_area * 0.5) & (ana_df["площадь"].values <= lot_area * 1.5)
    # фильтр по типу входа — только если у лота известен вход и есть достаточно аналогов
    if lot_entrance and "тип_входа" in ana_df.columns:
        mask_entrance = mask & (ana_df["тип_входа"].values == lot_entrance)
        if mask_entrance.sum() >= 2:
            mask = mask_entrance
    sub = ana_df[mask]
    if len(sub) < 2:
        return None, len(sub)
    return float(sub["цена_за_м²"].median()), len(sub)


@st.cache_data
def load_lots():
    df = pd.read_csv(LOTS_PATH, encoding="utf-8-sig")
    df = df.dropna(subset=["latitude", "longitude"]).copy()
    df["площадь_м²"] = pd.to_numeric(df["площадь_м²"], errors="coerce")
    df["итоговая_цена_руб"] = pd.to_numeric(
        df["итоговая_цена_руб"].astype(str).str.replace(",", ".", regex=False),
        errors="coerce",
    )
    df["итоговая_цена_млн"] = df["итоговая_цена_руб"] / 1_000_000
    return df


@st.cache_data
def compute_loo_cv(_df, n_rows, radius_m=700, area_pct=50):
    valid = _df.dropna(subset=["площадь", "цена_за_м²", "этаж_норм"]).copy()
    valid = valid[valid["площадь"] > 0].reset_index(drop=True)

    lats = valid["lat"].values
    lons = valid["lng"].values
    pm2 = valid["цена_за_м²"].values
    areas = valid["площадь"].values
    prices = valid["цена"].values
    floors = valid["этаж_норм"].values

    results = []
    for i in range(len(valid)):
        dists = haversine_vec(lats[i], lons[i], lats, lons)
        neighbours = (dists > 100) & (floors == floors[i]) & (dists <= radius_m)
        lo = areas[i] * (1 - area_pct / 100)
        hi = areas[i] * (1 + area_pct / 100)
        neighbours &= (areas >= lo) & (areas <= hi)
        if neighbours.sum() < 2:
            continue
        pred_pm2 = float(np.median(pm2[neighbours]))
        pred_price = pred_pm2 * areas[i]
        rel_err = (pred_price - prices[i]) / prices[i]
        results.append({
            "этаж": floors[i],
            "ошибка": rel_err,
            "предск_цена_м²": pred_pm2,
            "факт_цена_м²": pm2[i],
            "соседей": int(neighbours.sum()),
        })

    return pd.DataFrame(results)


@st.cache_data
def load_rent_analogues():
    df = pd.read_csv(str(ARENDA_PATH), sep=";", encoding="utf-8-sig")
    df["площадь"] = df.apply(_get_area, axis=1)
    df["цена"]    = pd.to_numeric(df["Цена"], errors="coerce")
    df["цена_за_м²_мес"] = np.where(
        df["площадь"].fillna(0) > 0, df["цена"] / df["площадь"], np.nan
    )
    df["этаж"]       = df["Доп.параметры"].apply(lambda x: _parse_param(x, "Этаж"))
    df["этаж_норм"]  = df["этаж"].apply(normalize_floor)
    df["вид_объекта"]= df["Доп.параметры"].apply(lambda x: _parse_param(x, "Вид объекта"))
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lng"] = pd.to_numeric(df["lng"], errors="coerce")
    df = df.dropna(subset=["lat", "lng", "цена", "площадь"]).copy()
    df = df[df["площадь"] >= 15].copy()  # убираем кладовки и ларьки
    exclude = {"Здание", "Коммерческая земля", "Складское помещение",
               "Производственное помещение", "Гостиница"}
    df = df[~df["вид_объекта"].isin(exclude)].copy()
    df = df[(df["цена_за_м²_мес"] >= 200) & (df["цена_за_м²_мес"] <= 100_000)].copy()
    return df.reset_index(drop=True)


def territorial_rent(lot_lat, lot_lon, lot_floor_norm, lot_area, rent_df, radius_m):
    dists = haversine_vec(lot_lat, lot_lon, rent_df["lat"].values, rent_df["lng"].values)
    mask  = (dists <= radius_m) & rent_df["цена_за_м²_мес"].notna()
    if lot_area and lot_area > 0:
        mask &= (rent_df["площадь"].values >= lot_area * 0.5) & \
                (rent_df["площадь"].values <= lot_area * 1.5)
    if lot_floor_norm:
        mask_floor = mask & (rent_df["этаж_норм"].values == lot_floor_norm)
        if mask_floor.sum() >= 2:
            mask = mask_floor
    sub = rent_df[mask]
    if len(sub) < 2:
        return None, len(sub)
    return float(sub["цена_за_м²_мес"].median()), len(sub)


analogues = load_analogues()
rent_analogues = load_rent_analogues()
lots = load_lots()
buildings = load_buildings()
hedge_model, hedge_features = load_model()

st.title("Аналоги недвижимости")

lot_labels = (
    "№" + lots["номер_лота"].astype(str)
    + " — " + lots["адрес"].fillna("")
    + lots["площадь_м²"].apply(lambda x: f" ({x:.0f} м²)" if pd.notna(x) else "")
)
label_to_idx = dict(zip(lot_labels, lots.index))

selected_labels = st.multiselect(
    "Выберите лоты (один или несколько)",
    lot_labels.tolist(),
    max_selections=20,
)

if selected_labels:
    selected_lots = lots.loc[[label_to_idx[l] for l in selected_labels]].copy()

    fcol1, fcol2, fcol3 = st.columns(3)
    with fcol1:
        radius_m = st.slider("Радиус поиска, м", 100, 3000, 700, step=100)
    with fcol2:
        use_area_filter = st.checkbox(
            "Фильтр по площади", value=(len(selected_lots) == 1)
        )
    with fcol3:
        area_pct = st.slider("Диапазон площади ±%", 10, 100, 50, step=10) if use_area_filter else 50

tab1, tab2, tab3 = st.tabs(["Продажа — аналоги", "Аренда + окупаемость", "Точность метода"])

# ── Вкладка 1 ─────────────────────────────────────────────────────────────────
with tab1:
    if not selected_labels:
        st.info("Выберите лот выше.")
    else:
        alpha = st.slider(
            "α (территориальная доля)", 0.0, 1.0, 0.1, step=0.05,
            help="Итоговая цена = α × территориальная медиана + (1−α) × модель XGBoost"
        )

        available_types = sorted(analogues["вид_объекта"].dropna().unique().tolist())
        selected_types = st.multiselect(
            "Тип объекта", available_types, default=available_types,
        )
        sale_ana = analogues[analogues["вид_объекта"].isin(selected_types)] if selected_types else analogues

        collected = []
        for _, lot in selected_lots.iterrows():
            lot_lat = float(lot["latitude"])
            lot_lon = float(lot["longitude"])
            lot_area = float(lot["площадь_м²"]) if pd.notna(lot.get("площадь_м²")) else None
            lot_num = lot["номер_лота"]

            ana = sale_ana.copy()
            ana["расстояние_м"] = ana.apply(
                lambda r: haversine_m(lot_lat, lot_lon, r["lat"], r["lng"]), axis=1
            )
            ana = ana[ana["расстояние_м"] <= radius_m].copy()

            if use_area_filter and lot_area and lot_area > 0:
                lo = lot_area * (1 - area_pct / 100)
                hi = lot_area * (1 + area_pct / 100)
                ana = ana[ana["площадь"].between(lo, hi) | ana["площадь"].isna()]

            ana["лот"] = f"№{lot_num}"
            collected.append(ana)

        if collected:
            all_nearby = pd.concat(collected, ignore_index=True)
            all_nearby = (
                all_nearby.sort_values("расстояние_м")
                .drop_duplicates(subset=["URL"], keep="first")
                .reset_index(drop=True)
            )
        else:
            all_nearby = pd.DataFrame()

        mc1, mc2, mc3, mc4, mc5 = st.columns(5)
        mc1.metric("Аналогов найдено", len(all_nearby))
        mc2.metric("Лотов выбрано", len(selected_lots))
        if not all_nearby.empty and all_nearby["цена_за_м²"].notna().any():
            med_pm2 = all_nearby["цена_за_м²"].median()
            mc3.metric("Медиана цены/м² аналогов", f"{med_pm2/1000:.0f} тр/м²")

        # аудитория + предсказания
        lot_stats = []
        total_apts, total_residents = 0, 0
        for _, lot in selected_lots.iterrows():
            lat_ = float(lot["latitude"])
            lon_ = float(lot["longitude"])
            lot_area = float(lot["площадь_м²"]) if pd.notna(lot.get("площадь_м²")) else None
            lot_floor = _norm_floor_lot(str(lot.get("этаж", "")))

            a, r = count_residents(lat_, lon_, radius_m, buildings)
            a400, _ = count_residents(lat_, lon_, 400, buildings)
            a800, _ = count_residents(lat_, lon_, 800, buildings)
            _, r500 = count_residents(lat_, lon_, 500, buildings)
            total_apts += a
            total_residents += r

            entrance_raw = str(lot.get("тип_входа", "")).strip().lower()
            lot_entrance = _ENTRANCE_LOT.get(entrance_raw)
            rent_dists    = haversine_vec(lat_, lon_, rent_analogues["lat"].values, rent_analogues["lng"].values)
            rent_near_700 = rent_analogues[rent_dists <= 700]["цена_за_м²_мес"].dropna()
            rent_near_1500= rent_analogues[rent_dists <= 1500]["цена_за_м²_мес"].dropna()
            med_rent_700  = float(rent_near_700.median()) if len(rent_near_700) >= 2 else np.nan
            med_rent_1500 = float(rent_near_1500.median()) if len(rent_near_1500) >= 2 else np.nan
            rent_cnt_700  = int((rent_dists <= 700).sum())

            lot_vid_raw = str(lot.get("функциональное_назначение", "")).strip().lower()
            lot_vid     = _VID_LOT.get(lot_vid_raw)
            if lot_vid:
                same_type = rent_analogues[
                    (rent_dists <= 700) & (rent_analogues["вид_объекта"] == lot_vid)
                ]["цена_за_м²_мес"].dropna()
                med_rent_same = float(same_type.median()) if len(same_type) >= 2 else med_rent_700
            else:
                med_rent_same = med_rent_700

            sale_dists   = haversine_vec(lat_, lon_, sale_ana["lat"].values, sale_ana["lng"].values)
            sale_cnt_700 = int((sale_dists <= 700).sum())
            model_pm2 = predict_price_m2(
                hedge_model, hedge_features, lot, a400, a800,
                med_rent_same, med_rent_1500, rent_cnt_700, sale_cnt_700,
            )
            terr_pm2, n_terr = territorial_price(lat_, lon_, lot_floor, lot_area, lot_entrance, sale_ana, radius_m)

            if terr_pm2 and model_pm2:
                final_pm2 = alpha * terr_pm2 + (1 - alpha) * model_pm2
            elif terr_pm2:
                final_pm2 = terr_pm2
            else:
                final_pm2 = model_pm2

            auction_price = float(lot["итоговая_цена_руб"]) if pd.notna(lot.get("итоговая_цена_руб")) else None
            final_price   = final_pm2 * lot_area if (final_pm2 and lot_area) else None
            upside_mln    = (final_price - auction_price) / 1e6 if (final_price and auction_price) else None
            upside_pct    = (final_price - auction_price) / auction_price * 100 if (final_price and auction_price) else None
            pess_price    = final_pm2 * (1 - XGB_MAPE) * lot_area if (final_pm2 and lot_area) else None
            pess_upside_mln = (pess_price - auction_price) / 1e6 if (pess_price and auction_price) else None

            lot_stats.append({
                "лот": f"№{lot['номер_лота']}",
                "площадь": lot_area,
                "apt_400": a400, "apt_800": a800,
                "residents_500": r500,
                "model_pm2": model_pm2,
                "terr_pm2": terr_pm2,
                "n_terr": n_terr,
                "final_pm2": final_pm2,
                "auction_price": auction_price,
                "upside_mln": upside_mln,
                "upside_pct": upside_pct,
                "pess_upside_mln": pess_upside_mln,
            })

        mc4.metric("Квартир в радиусе", f"{total_apts:,}".replace(",", " "))
        res_label = "Жителей (оценка)"
        mc5.metric(res_label, f"{total_residents:,}".replace(",", " "))

        def _fmt_pm2(pm2, area):
            if pm2 is None: return "—"
            s_pm2 = f"{pm2/1000:.0f} тр/м²"
            s_tot = f" ≈ {pm2*area/1e6:.1f} млн ₽" if area else ""
            return s_pm2 + s_tot

        if len(lot_stats) == 1:
            s = lot_stats[0]
            terr_label = (
                f"Территориальная (n={s['n_terr']})" if s["terr_pm2"]
                else f"Территориальная — нет данных (n={s['n_terr']})"
            )
            col_t, col_m, col_f = st.columns(3)
            col_t.metric(terr_label, _fmt_pm2(s["terr_pm2"], s["площадь"]))
            col_m.metric("Модель XGBoost", _fmt_pm2(s["model_pm2"], s["площадь"]))
            col_f.metric(f"Итоговая (α={alpha:.2f})", _fmt_pm2(s["final_pm2"], s["площадь"]))

            # upside и аудитория
            up1, up2, up3, up4 = st.columns(4)
            if s["auction_price"]:
                up1.metric("Цена покупки", f"{s['auction_price']/1e6:.1f} млн ₽")
            if s["upside_mln"] is not None:
                pess = s["pess_upside_mln"]
                pess_str = f"при −{XGB_MAPE*100:.0f}%: {pess:+.1f} млн ₽" if pess is not None else ""
                up2.metric("Upside (рынок − покупка)",
                           f"{s['upside_mln']:+.1f} млн ₽",
                           delta=pess_str,
                           delta_color="normal" if (pess is not None and pess > 0) else "inverse")
            r500 = s["residents_500"]
            pop_ok = r500 >= 10_000
            up3.metric("Жителей в 500м",
                       f"{r500:,}".replace(",", " "),
                       delta="✓ ≥ 10 000" if pop_ok else "✗ < 10 000",
                       delta_color="normal" if pop_ok else "inverse")
            st.caption(f"Квартир в 400м: {s['apt_400']:,} · в 800м: {s['apt_800']:,}".replace(",", " "))
        else:
            price_rows = []
            for s in lot_stats:
                area = s["площадь"]
                r500 = s["residents_500"]
                price_rows.append({
                    "Лот": s["лот"],
                    "Территориальная, тр/м²": round(s["terr_pm2"]/1000, 0) if s["terr_pm2"] else None,
                    "Модель, тр/м²": round(s["model_pm2"]/1000, 0) if s["model_pm2"] else None,
                    f"Итог α={alpha:.2f}, тр/м²": round(s["final_pm2"]/1000, 0) if s["final_pm2"] else None,
                    "Итог всего, млн ₽": round(s["final_pm2"]*area/1e6, 1) if (s["final_pm2"] and area) else None,
                    "Upside, млн ₽": round(s["upside_mln"], 1) if s["upside_mln"] is not None else None,
                    "Upside, %": round(s["upside_pct"], 0) if s["upside_pct"] is not None else None,
                    f"Upside −{XGB_MAPE*100:.0f}%, млн ₽": round(s["pess_upside_mln"], 1) if s["pess_upside_mln"] is not None else None,
                    "Жит. 500м": r500,
                    "≥10k жит.": "✓" if r500 >= 10_000 else "✗",
                })
            st.dataframe(pd.DataFrame(price_rows), hide_index=True, use_container_width=True)

        center_lat = selected_lots["latitude"].mean()
        center_lon = selected_lots["longitude"].mean()
        zoom = 15 if len(selected_lots) == 1 else 12
        m = folium.Map(
            location=[center_lat, center_lon], zoom_start=zoom, tiles="CartoDB positron"
        )

        for _, lot in selected_lots.iterrows():
            lot_lat = float(lot["latitude"])
            lot_lon = float(lot["longitude"])
            lot_area = float(lot["площадь_м²"]) if pd.notna(lot.get("площадь_м²")) else None
            lot_price_mln = (
                float(lot["итоговая_цена_млн"]) if pd.notna(lot.get("итоговая_цена_млн")) else None
            )
            lot_area_str = f"{lot_area:.0f} м²" if lot_area else "—"
            lot_price_str = f"{lot_price_mln:.1f} млн ₽" if lot_price_mln else "—"

            folium.Circle(
                location=[lot_lat, lot_lon],
                radius=radius_m,
                color="#dc2626",
                fill=False,
                weight=1,
                opacity=0.4,
            ).add_to(m)
            folium.Marker(
                location=[lot_lat, lot_lon],
                popup=folium.Popup(
                    f"<b>Лот №{lot['номер_лота']}</b><br>{lot['адрес']}<br>"
                    f"Площадь: {lot_area_str}<br>Цена покупки: {lot_price_str}",
                    max_width=280,
                ),
                icon=folium.Icon(color="red", icon="home"),
            ).add_to(m)

        for _, row in all_nearby.iterrows():
            pm2_str = (
                f"{row['цена_за_м²']/1000:.0f} тр/м²" if pd.notna(row["цена_за_м²"]) else "—"
            )
            area_str  = f"{row['площадь']:.0f} м²" if pd.notna(row["площадь"]) else "—"
            цена_str  = f"{row['цена_млн']:.1f} млн ₽" if pd.notna(row.get("цена_млн")) else "—"
            metro_str = f"{row['Расстояние до метро, км']:.2f} км" if pd.notna(row.get("Расстояние до метро, км")) else "—"
            вход_str  = row.get("тип_входа") or "—"
            popup_html = (
                f"<div style='font-family:Arial;min-width:240px;font-size:13px;line-height:1.5;'>"
                f"<b>{row['Адрес']}</b><br>"
                f"Ближайший лот: {row['лот']}<br>"
                f"Площадь: {area_str}<br>"
                f"Цена: {цена_str}<br>"
                f"Цена/м²: {pm2_str}<br>"
                f"Этаж: {row['этаж'] or '—'}<br>"
                f"Тип входа: {вход_str}<br>"
                f"Метро/Район: {row.get('Метро/Район') or '—'}<br>"
                f"До метро: {metro_str}<br>"
                f"До лота: {row['расстояние_м']:.0f} м<br>"
                f"Источник: {row.get('Источник') or '—'}<br>"
                f"<a href='{row['URL']}' target='_blank'>Открыть объявление</a>"
                f"</div>"
            )
            folium.CircleMarker(
                location=[row["lat"], row["lng"]],
                radius=7,
                color="#2563eb",
                fill=True,
                fill_color="#2563eb",
                fill_opacity=0.7,
                popup=folium.Popup(popup_html, max_width=300),
                weight=1.5,
            ).add_to(m)

        st_folium(m, width=None, height=560, returned_objects=[])

        if not all_nearby.empty:
            table = all_nearby[[
                "лот", "Адрес", "площадь", "цена_млн", "цена_за_м²",
                "этаж", "тип_входа", "вид_объекта", "Метро/Район",
                "Расстояние до метро, км", "расстояние_м", "URL",
            ]].copy()
            table["цена_за_м²_тр"] = table["цена_за_м²"] / 1000
            table = table.sort_values("цена_за_м²").reset_index(drop=True)

            show_cols = [
                "лот", "Адрес", "площадь", "цена_млн", "цена_за_м²_тр",
                "этаж", "тип_входа", "вид_объекта", "Метро/Район",
                "Расстояние до метро, км", "расстояние_м", "URL",
            ]
            if len(selected_lots) == 1:
                show_cols = [c for c in show_cols if c != "лот"]

            st.dataframe(
                table[show_cols],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "лот": "Лот",
                    "Адрес": st.column_config.TextColumn("Адрес", width="large"),
                    "площадь": st.column_config.NumberColumn("Площадь, м²", format="%.0f"),
                    "цена_млн": st.column_config.NumberColumn("Цена, млн ₽", format="%.1f"),
                    "цена_за_м²_тр": st.column_config.NumberColumn("Цена/м², тр", format="%.0f"),
                    "этаж": "Этаж",
                    "тип_входа": "Тип входа",
                    "вид_объекта": "Вид объекта",
                    "Метро/Район": "Метро/Район",
                    "Расстояние до метро, км": st.column_config.NumberColumn(
                        "До метро, км", format="%.2f"
                    ),
                    "расстояние_м": st.column_config.NumberColumn("До лота, м", format="%.0f"),
                    "URL": st.column_config.LinkColumn("Объявление", width="small"),
                },
            )
        else:
            st.info("Аналогов не найдено. Увеличьте радиус или снимите фильтр по площади.")

# ── Вкладка 2: Аренда + окупаемость ──────────────────────────────────────────
with tab2:
    if not selected_labels:
        st.info("Выберите лот выше.")
    else:
        rent_collected = []
        for _, lot in selected_lots.iterrows():
            lot_lat = float(lot["latitude"])
            lot_lon = float(lot["longitude"])
            lot_area = float(lot["площадь_м²"]) if pd.notna(lot.get("площадь_м²")) else None
            lot_num = lot["номер_лота"]

            rana = rent_analogues.copy()
            rana["расстояние_м"] = haversine_vec(
                lot_lat, lot_lon, rana["lat"].values, rana["lng"].values
            )
            rana = rana[rana["расстояние_м"] <= radius_m].copy()

            if use_area_filter and lot_area and lot_area > 0:
                lo = lot_area * (1 - area_pct / 100)
                hi = lot_area * (1 + area_pct / 100)
                rana = rana[rana["площадь"].between(lo, hi) | rana["площадь"].isna()]

            rana["лот"] = f"№{lot_num}"
            rent_collected.append(rana)

        if rent_collected:
            all_rent_nearby = pd.concat(rent_collected, ignore_index=True)
            all_rent_nearby = (
                all_rent_nearby.sort_values("расстояние_м")
                .drop_duplicates(subset=["URL"], keep="first")
                .reset_index(drop=True)
            )
        else:
            all_rent_nearby = pd.DataFrame()

        rent_stats = []
        for _, lot in selected_lots.iterrows():
            lot_lat = float(lot["latitude"])
            lot_lon = float(lot["longitude"])
            lot_area = float(lot["площадь_м²"]) if pd.notna(lot.get("площадь_м²")) else None
            lot_floor = _norm_floor_lot(str(lot.get("этаж", "")))
            terr_rent_pm2, n_rent = territorial_rent(
                lot_lat, lot_lon, lot_floor,
                lot_area if use_area_filter else None,
                rent_analogues, radius_m,
            )
            rent_stats.append({
                "лот": f"№{lot['номер_лота']}",
                "площадь": lot_area,
                "аукцион_руб": float(lot["итоговая_цена_руб"]) if pd.notna(lot.get("итоговая_цена_руб")) else None,
                "terr_rent_pm2": terr_rent_pm2,
                "n_rent": n_rent,
            })

        rm1, rm2, rm3 = st.columns(3)
        rm1.metric("Аналогов аренды", len(all_rent_nearby))
        if not all_rent_nearby.empty and all_rent_nearby["цена_за_м²_мес"].notna().any():
            med_rent = all_rent_nearby["цена_за_м²_мес"].median()
            rm2.metric("Медиана аренды/м²/мес", f"{med_rent:.0f} руб/м²/мес")
        if len(rent_stats) == 1:
            s = rent_stats[0]
            label_n = f"Территориальная ставка (n={s['n_rent']})"
            rm3.metric(label_n, f"{s['terr_rent_pm2']:.0f} руб/м²/мес" if s["terr_rent_pm2"] else "—")

        # Окупаемость
        st.divider()
        st.subheader("Окупаемость")

        if len(rent_stats) == 1:
            s = rent_stats[0]
            reno_col, _ = st.columns([1, 2])
            with reno_col:
                reno_tr_pm2 = st.slider("Себестоимость ремонта, тр/м²", 0, 500, 300, step=50)
            area = s["площадь"]
            auction_price = s["аукцион_руб"]
            rent_pm2 = s["terr_rent_pm2"]
            if area and auction_price and rent_pm2:
                reno_total = reno_tr_pm2 * 1_000 * area
                total_invest = auction_price + reno_total
                annual_rent = rent_pm2 * area * 12
                payback_yrs = total_invest / annual_rent if annual_rent > 0 else None
                pess_rent = rent_pm2 * (1 - TERR_MAPE)
                pess_payback = total_invest / (pess_rent * area * 12) if pess_rent > 0 else None
                pc1, pc2, pc3, pc4 = st.columns(4)
                pc1.metric("Цена покупки", f"{auction_price/1e6:.1f} млн руб")
                pc2.metric("Ремонт", f"{reno_total/1e6:.1f} млн руб")
                pc3.metric("Итого инвестиций", f"{total_invest/1e6:.1f} млн руб")
                pess_delta = f"при −{TERR_MAPE*100:.0f}%: {pess_payback:.1f} лет" if pess_payback else None
                pc4.metric("Срок окупаемости", f"{payback_yrs:.1f} лет" if payback_yrs else "—",
                           delta=pess_delta, delta_color="inverse")
                st.caption(
                    f"Годовой доход от аренды: {annual_rent/1e6:.2f} млн руб "
                    f"({rent_pm2:.0f} руб/м²/мес x {area:.0f} м2 x 12 мес)"
                )
            else:
                missing = []
                if not area: missing.append("площадь лота")
                if not auction_price: missing.append("цена покупки")
                if not rent_pm2: missing.append("ставка аренды")
                st.info(f"Недостаточно данных: {', '.join(missing)}.")
        else:
            reno_tr_pm2 = st.slider("Себестоимость ремонта, тр/м²", 0, 500, 300, step=50)
            payback_rows = []
            for s in rent_stats:
                area = s["площадь"]
                auction_price = s["аукцион_руб"]
                rent_pm2 = s["terr_rent_pm2"]
                if area and auction_price and rent_pm2:
                    reno_total = reno_tr_pm2 * 1_000 * area
                    total_invest = auction_price + reno_total
                    annual_rent = rent_pm2 * area * 12
                    payback_yrs = total_invest / annual_rent if annual_rent > 0 else None
                    pess_rent = rent_pm2 * (1 - TERR_MAPE)
                    pess_payback = total_invest / (pess_rent * area * 12) if pess_rent > 0 else None
                else:
                    reno_total = total_invest = annual_rent = payback_yrs = pess_payback = None
                payback_rows.append({
                    "Лот": s["лот"],
                    "Площадь, м²": round(area, 0) if area else None,
                    "Цена покупки, млн": round(auction_price / 1e6, 1) if auction_price else None,
                    "Ремонт, млн": round(reno_total / 1e6, 1) if reno_total else None,
                    "Инвестиции, млн": round(total_invest / 1e6, 1) if total_invest else None,
                    "Аренда/м²/мес": round(rent_pm2, 0) if rent_pm2 else None,
                    "Окупаемость, лет": round(payback_yrs, 1) if payback_yrs else None,
                    f"Окупаемость −{TERR_MAPE*100:.0f}%, лет": round(pess_payback, 1) if pess_payback else None,
                })
            st.dataframe(pd.DataFrame(payback_rows), hide_index=True, use_container_width=True)

        # Карта аренды
        st.divider()
        center_lat = selected_lots["latitude"].mean()
        center_lon = selected_lots["longitude"].mean()
        zoom = 15 if len(selected_lots) == 1 else 12
        m_rent = folium.Map(
            location=[center_lat, center_lon], zoom_start=zoom, tiles="CartoDB positron"
        )
        for _, lot in selected_lots.iterrows():
            lot_lat = float(lot["latitude"])
            lot_lon = float(lot["longitude"])
            folium.Circle(
                location=[lot_lat, lot_lon],
                radius=radius_m,
                color="#dc2626", fill=False, weight=1, opacity=0.4,
            ).add_to(m_rent)
            folium.Marker(
                location=[lot_lat, lot_lon],
                popup=folium.Popup(
                    f"<b>Лот #{lot['номер_лота']}</b><br>{lot['адрес']}", max_width=280
                ),
                icon=folium.Icon(color="red", icon="home"),
            ).add_to(m_rent)

        if not all_rent_nearby.empty:
            for _, row in all_rent_nearby.iterrows():
                pm2_str = f"{row['цена_за_м²_мес']:.0f} руб/м²/мес" if pd.notna(row["цена_за_м²_мес"]) else "—"
                area_str = f"{row['площадь']:.0f} м²" if pd.notna(row["площадь"]) else "—"
                цена_str = f"{row['цена']/1000:.0f} тр/мес" if pd.notna(row.get("цена")) else "—"
                addr_str = row.get("Адрес", row.get("Название", "—")) or "—"
                popup_html = (
                    f"<div style='font-family:Arial;min-width:220px;font-size:13px;line-height:1.5;'>"
                    f"<b>{addr_str}</b><br>"
                    f"Площадь: {area_str}<br>"
                    f"Аренда: {цена_str}<br>"
                    f"Ставка: {pm2_str}<br>"
                    f"Этаж: {row['этаж'] or '—'}<br>"
                    f"До лота: {row['расстояние_м']:.0f} м<br>"
                    f"<a href='{row['URL']}' target='_blank'>Открыть</a>"
                    f"</div>"
                )
                folium.CircleMarker(
                    location=[row["lat"], row["lng"]],
                    radius=7,
                    color="#16a34a", fill=True, fill_color="#16a34a", fill_opacity=0.7,
                    popup=folium.Popup(popup_html, max_width=300),
                    weight=1.5,
                ).add_to(m_rent)

        st_folium(m_rent, width=None, height=520, returned_objects=[])

        # Таблица аренды
        if not all_rent_nearby.empty:
            rent_show_cols = [c for c in [
                "лот", "Адрес", "площадь", "цена", "цена_за_м²_мес",
                "этаж", "вид_объекта", "расстояние_м", "URL",
            ] if c in all_rent_nearby.columns]
            if len(selected_lots) == 1 and "лот" in rent_show_cols:
                rent_show_cols = [c for c in rent_show_cols if c != "лот"]
            st.dataframe(
                all_rent_nearby[rent_show_cols],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "лот": "Лот",
                    "Адрес": st.column_config.TextColumn("Адрес", width="large"),
                    "площадь": st.column_config.NumberColumn("Площадь, м²", format="%.0f"),
                    "цена": st.column_config.NumberColumn("Аренда/мес, руб", format="%.0f"),
                    "цена_за_м²_мес": st.column_config.NumberColumn("руб/м²/мес", format="%.0f"),
                    "этаж": "Этаж",
                    "вид_объекта": "Вид объекта",
                    "расстояние_м": st.column_config.NumberColumn("До лота, м", format="%.0f"),
                    "URL": st.column_config.LinkColumn("Объявление", width="small"),
                },
            )
        else:
            st.info("Аналогов аренды не найдено. Увеличьте радиус или снимите фильтр по площади.")


# ── Вкладка 3: Точность метода ────────────────────────────────────────────────
with tab3:
    st.subheader("Точность метода")

    st.markdown("**XGBoost — 5-fold GroupKFold** (объекты одного здания+этажа всегда в одном фолде)")
    xm1, xm2, xm3 = st.columns(3)
    xm1.metric("MAPE XGBoost", "31%", help="Честная оценка: утечка по зданию исключена")
    xm2.metric("MAPE Combined (α=0.05)", "27%")
    xm3.metric("MAPE Территориальный", "35%")

    st.divider()
    st.markdown("**Территориальная медиана — LOO-CV** (каждый объект предсказывается соседями, "
                "исключая 100 м вокруг себя)")
    st.caption(
        "Для каждого объявления с известной площадью и этажом предсказываем цену/м² "
        "по медиане соседей того же этажа в радиусе 700 м. "
        "Ошибка = (предск. цена - факт. цена) / факт. цена."
    )

    cv_df = compute_loo_cv(analogues, len(analogues), radius_m=700, area_pct=50)

    total_valid = analogues.dropna(subset=["площадь", "цена_за_м²", "этаж_норм"]).shape[0]
    coverage = len(cv_df) / total_valid * 100 if total_valid > 0 else 0
    mape = cv_df["ошибка"].abs().mean() * 100 if not cv_df.empty else 0
    median_err = cv_df["ошибка"].median() * 100 if not cv_df.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Покрытие", f"{coverage:.0f}%",
              help="Доля объектов, для которых нашлось >= 2 соседей того же этажа в 700 м")
    c2.metric("MAPE", f"{mape:.0f}%")
    c3.metric("Медиана ошибки", f"{median_err:+.0f}%")
    c4.metric("Объектов в CV", len(cv_df))

    if not cv_df.empty:
        err_pct = (cv_df["ошибка"] * 100).clip(-100, 150)

        chart = (
            alt.Chart(pd.DataFrame({"ошибка_%": err_pct}))
            .mark_bar(color="#2563eb", opacity=0.8)
            .encode(
                alt.X("ошибка_%:Q", bin=alt.Bin(step=10), title="Ошибка, %"),
                alt.Y("count()", title="Количество объектов"),
            )
            .properties(title="Распределение ошибок предсказания", height=320)
        )
        st.altair_chart(chart, use_container_width=True)

        st.subheader("По этажам")

        floor_order = ["цоколь", "1", "2", "3+"]

        def floor_agg(grp):
            e = grp["ошибка"]
            return pd.Series({
                "Объектов в CV": len(e),
                "MAPE, %": round(e.abs().mean() * 100, 0),
                "Медиана, %": round(e.median() * 100, 0),
                "P25, %": round(e.quantile(0.25) * 100, 0),
                "P75, %": round(e.quantile(0.75) * 100, 0),
            })

        total_by_floor = (
            analogues.dropna(subset=["площадь", "цена_за_м²", "этаж_норм"])
            .groupby("этаж_норм").size().rename("Всего")
            .reset_index().rename(columns={"этаж_норм": "Этаж"})
        )

        if cv_df.empty or "этаж" not in cv_df.columns:
            cv_stats = pd.DataFrame(columns=["Этаж", "Объектов в CV", "MAPE, %", "Медиана, %", "P25, %", "P75, %"])
        else:
            cv_stats = (
                cv_df.groupby("этаж")
                .apply(floor_agg)
                .reset_index()
                .rename(columns={"этаж": "Этаж"})
            )

        floor_stats = (
            pd.DataFrame({"Этаж": floor_order})
            .merge(total_by_floor, on="Этаж", how="left")
            .merge(cv_stats, on="Этаж", how="left")
        )
        floor_stats["Всего"] = floor_stats["Всего"].fillna(0).astype(int)
        floor_stats["Объектов в CV"] = floor_stats["Объектов в CV"].fillna(0).astype(int)

        st.dataframe(
            floor_stats,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Всего": st.column_config.NumberColumn("Всего объявл."),
                "Объектов в CV": st.column_config.NumberColumn("В CV"),
                "MAPE, %": st.column_config.NumberColumn(format="%.0f"),
                "Медиана, %": st.column_config.NumberColumn(format="%+.0f"),
                "P25, %": st.column_config.NumberColumn(format="%+.0f"),
                "P75, %": st.column_config.NumberColumn(format="%+.0f"),
            },
        )
