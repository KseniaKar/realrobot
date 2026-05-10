from pathlib import Path
import re

import altair as alt
import folium
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

BASE_DIR = Path(__file__).resolve().parent
ANALOGUES_PATH = BASE_DIR / "excel2-30025-1.xlsx"
LOTS_PATH = BASE_DIR.parent / "property_goals" / "investmoscow_sold_2022_2026_enriched_geo.csv"

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
    df = pd.read_excel(ANALOGUES_PATH)
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
    df = df[df["этаж_норм"] != "-2"]  # подземные склады, нерелевантны
    return df.dropna(subset=["lat", "lng", "цена"]).copy()


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
    """LOO-CV: predict each analogue's price from same-floor, similar-area neighbours within radius_m."""
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


analogues = load_analogues()
lots = load_lots()

st.title("Аналоги продажи")
st.caption(
    "Подбор объявлений о продаже коммерческой недвижимости для лотов на торгах "
    "(ЦИАН + Яндекс.Недвижимость, снимок 24–25 февраля 2026, 1 164 объявления)"
)

tab1, tab2 = st.tabs(["Подбор аналогов", "Точность метода"])

# ── Вкладка 1: подбор аналогов ────────────────────────────────────────────────
with tab1:
    lot_labels = (
        "№"
        + lots["номер_лота"].astype(str)
        + " — "
        + lots["адрес"].fillna("")
        + lots["площадь_м²"].apply(lambda x: f" ({x:.0f} м²)" if pd.notna(x) else "")
    )
    label_to_idx = dict(zip(lot_labels, lots.index))

    selected_labels = st.multiselect(
        "Выберите лоты (один или несколько)",
        lot_labels.tolist(),
        max_selections=20,
    )

    if not selected_labels:
        st.info("Выберите хотя бы один лот выше.")
    else:
        selected_lots = lots.loc[[label_to_idx[l] for l in selected_labels]].copy()

        fcol1, fcol2, fcol3 = st.columns(3)
        with fcol1:
            radius_m = st.slider("Радиус поиска, м", 100, 3000, 700, step=100)
        with fcol2:
            use_area_filter = st.checkbox(
                "Фильтр по площади", value=(len(selected_lots) == 1)
            )
        with fcol3:
            if use_area_filter:
                area_pct = st.slider("Диапазон площади ±%", 10, 100, 50, step=10)
            else:
                area_pct = 50

        collected = []
        for _, lot in selected_lots.iterrows():
            lot_lat = float(lot["latitude"])
            lot_lon = float(lot["longitude"])
            lot_area = float(lot["площадь_м²"]) if pd.notna(lot.get("площадь_м²")) else None
            lot_num = lot["номер_лота"]

            ana = analogues.copy()
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

        mc1, mc2, mc3 = st.columns(3)
        mc1.metric("Аналогов найдено", len(all_nearby))
        mc2.metric("Лотов выбрано", len(selected_lots))
        if not all_nearby.empty and all_nearby["цена_за_м²"].notna().any():
            med_pm2 = all_nearby["цена_за_м²"].median()
            mc3.metric("Медиана цены/м² аналогов", f"{med_pm2/1000:.0f} тр/м²")

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
            area_str = f"{row['площадь']:.0f} м²" if pd.notna(row["площадь"]) else "—"
            popup_html = (
                f"<div style='font-family:Arial;min-width:240px;font-size:13px;line-height:1.5;'>"
                f"<b>{row['Адрес']}</b><br>"
                f"Ближайший лот: {row['лот']}<br>"
                f"Площадь: {area_str}<br>"
                f"Цена: {row['цена_млн']:.1f} млн ₽<br>"
                f"Цена/м²: {pm2_str}<br>"
                f"Этаж: {row['этаж'] or '—'}<br>"
                f"Метро/Район: {row['Метро/Район']}<br>"
                f"До метро: {row['Расстояние до метро, км']:.2f} км<br>"
                f"До лота: {row['расстояние_м']:.0f} м<br>"
                f"Источник: {row['Источник']}<br>"
                f"<a href='{row['URL']}' target='_blank'>Открыть объявление →</a>"
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
                "этаж", "вид_объекта", "Метро/Район",
                "Расстояние до метро, км", "расстояние_м", "URL",
            ]].copy()
            table["цена_за_м²_тр"] = table["цена_за_м²"] / 1000

            show_cols = [
                "лот", "Адрес", "площадь", "цена_млн", "цена_за_м²_тр",
                "этаж", "вид_объекта", "Метро/Район",
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

# ── Вкладка 2: LOO-CV ─────────────────────────────────────────────────────────
with tab2:
    st.subheader("Точность метода: leave-one-out кросс-валидация")
    st.caption(
        "Для каждого объявления с известной площадью и этажом предсказываем цену/м² "
        "по медиане соседей того же этажа в заданном радиусе (исключая 100 м вокруг). "
        "Ошибка = (предск. цена − факт. цена) / факт. цена."
    )

    cv_df = compute_loo_cv(analogues, len(analogues), radius_m=700, area_pct=50)

    total_valid = analogues.dropna(subset=["площадь", "цена_за_м²", "этаж_норм"]).shape[0]
    coverage = len(cv_df) / total_valid * 100 if total_valid > 0 else 0
    mape = cv_df["ошибка"].abs().mean() * 100 if not cv_df.empty else 0
    median_err = cv_df["ошибка"].median() * 100 if not cv_df.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Покрытие", f"{coverage:.0f}%",
              help="Доля объектов, для которых нашлось ≥2 соседей того же этажа в 1 км")
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

        # count all objects per floor (not just those in CV)
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
