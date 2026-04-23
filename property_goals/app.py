from pathlib import Path
import json
import re

import folium
import matplotlib
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

matplotlib.use("Agg")
import matplotlib.pyplot as plt


APP_BUILD = "2026-04-23-property-goals-time-filtered-v1"
BASE_DIR = Path(__file__).resolve().parent
ENRICHED_GEO_DATA_PATH = BASE_DIR / "investmoscow_sold_2022_2026_enriched_geo.csv"
ENRICHED_DATA_PATH = BASE_DIR / "investmoscow_sold_2022_2026_enriched.csv"
CLEAN_DATA_PATH = BASE_DIR / "investmoscow_sold_2022_2026_clean.csv"
PROTO_JSON_PATH = BASE_DIR.parent / "web-parsers" / "investmoskow_before" / "data" / "protocols" / "protocol_cache.json"

OKRUG_SHORT = {
    "Центральный административный округ": "ЦАО",
    "Западный административный округ": "ЗАО",
    "Северо-Западный административный округ": "СЗАО",
    "Северный административный округ": "САО",
    "Северо-Восточный административный округ": "СВАО",
    "Восточный административный округ": "ВАО",
    "Юго-Восточный административный округ": "ЮВАО",
    "Южный административный округ": "ЮАО",
    "Юго-Западный административный округ": "ЮЗАО",
    "Зеленоградский административный округ": "ЗелАО",
    "Новомосковский административный округ": "НАО",
    "Троицкий административный округ": "ТАО",
}

FLOOR_ORDER = [
    "Подвал",
    "Цоколь",
    "0 этаж",
    "1 этаж",
    "2 этаж",
    "3 этаж",
    "4 этаж",
    "5+ этаж",
    "Антресоль",
    "Мансарда",
    "Чердак",
    "Техэтаж",
    "Мезонин",
    "Многоуровневый",
    "Не указано",
]


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
    match = re.search(r"\d+", lower)
    if match:
        floor_num = int(match.group())
        if floor_num == 0:
            return "0 этаж"
        if floor_num >= 5:
            return "5+ этаж"
        return f"{floor_num} этаж"
    return raw


def extract_okrug(address: object) -> str:
    if not isinstance(address, str):
        return "Неизвестно"
    first = address.split(",")[0].strip()
    if "административный округ" in first or "Зеленоградский" in first:
        return first
    return "Неизвестно"


def get_color(excess: float) -> str:
    if pd.isna(excess):
        return "#8f8f8f"
    if excess < 0:
        if excess <= -50:
            return "#2563eb"
        if excess <= -20:
            return "#3b82f6"
        return "#7dd3fc"
    if excess == 0:
        return "#2ecc71"
    if excess <= 50:
        t = excess / 50.0
        r = int(46 + (241 - 46) * t)
        g = int(204 + (214 - 204) * t)
        b = int(113 + (33 - 113) * t)
        return f"#{r:02x}{g:02x}{b:02x}"
    t = min((excess - 50) / 50.0, 1.0)
    r = int(241 + (231 - 241) * t)
    g = int(214 + (76 - 214) * t)
    b = int(33 + (60 - 33) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def format_match_confidence(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "Нет"
    mapping = {"high": "High", "medium": "Medium", "low": "Low", "none": "Нет"}
    return mapping.get(value.strip().lower(), value)


def safe_text(value: object, fallback: str = "—") -> str:
    if not isinstance(value, str):
        return fallback
    clean = value.strip()
    return clean if clean else fallback


st.set_page_config(page_title="Property Goals", layout="wide", initial_sidebar_state="expanded")


@st.cache_data(ttl=3600)
def load_data() -> pd.DataFrame:
    if ENRICHED_GEO_DATA_PATH.exists():
        data_path = ENRICHED_GEO_DATA_PATH
    elif ENRICHED_DATA_PATH.exists():
        data_path = ENRICHED_DATA_PATH
    else:
        data_path = CLEAN_DATA_PATH
    if not data_path.exists():
        raise FileNotFoundError(data_path)

    df = pd.read_csv(data_path, encoding="utf-8-sig")
    df = df.dropna(subset=["latitude", "longitude"]).copy()

    numeric_cols = [
        "итоговая_цена_руб",
        "начальная_цена_руб",
        "цена_за_м²",
        "превышение_цены_%",
        "площадь_м²",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(
            df[col].astype(str).str.replace("%", "", regex=False).str.replace(",", ".", regex=False).str.strip(),
            errors="coerce",
        )

    if PROTO_JSON_PATH.exists():
        with open(PROTO_JSON_PATH, "r", encoding="utf-8") as f:
            cache = json.load(f)
        proto = pd.DataFrame([{"lot_id": int(k), "participants_count": v.get("participants_count")} for k, v in cache.items()])
        df = df.merge(proto, left_on="номер_лота", right_on="lot_id", how="left")
    else:
        df["participants_count"] = np.nan

    df["округ"] = df["адрес"].apply(extract_okrug)
    df["округ_код"] = df["округ"].map(OKRUG_SHORT).fillna("Другое")
    df["этаж_норм"] = df["этаж"].apply(normalize_floor)
    df["начальная_цена_млн"] = df["начальная_цена_руб"] / 1e6
    df["итоговая_цена_млн"] = df["итоговая_цена_руб"] / 1e6
    df["color"] = df["превышение_цены_%"].apply(get_color)
    max_area = max(float(df["площадь_м²"].max()), 1.0)
    df["radius"] = df["площадь_м²"].apply(
        lambda area: 5 if pd.isna(area) or area <= 0 else max(4, min(4 + 6 * np.log1p(area) / np.log1p(max_area), 25))
    )
    df["участники"] = df["participants_count"].apply(lambda x: int(x) if pd.notna(x) else None)

    for col in [
        "likely_company",
        "likely_usage",
        "company_candidates_preview",
        "usage_candidates_preview",
        "match_confidence",
        "match_after_days",
        "match_time_window",
    ]:
        if col not in df.columns:
            df[col] = ""
    df["match_confidence"] = df["match_confidence"].fillna("").astype(str)
    df["match_confidence_label"] = df["match_confidence"].apply(format_match_confidence)
    df["match_after_days"] = pd.to_numeric(df["match_after_days"], errors="coerce")
    return df


df = load_data()

st.title("Property Goals")
st.caption("История реально купленных лотов investmoscow, 2022–2026")
st.caption(f"Build: {APP_BUILD}")

all_forms = sorted(df["форма_проведения"].dropna().unique())
selected_form = st.selectbox("Форма проведения", ["Все"] + all_forms, index=0)
all_match_conf = [item for item in ["High", "Medium", "Low", "Нет"] if item in set(df["match_confidence_label"].dropna().unique())]
selected_match_conf = st.selectbox("Usage match", ["Все"] + all_match_conf, index=0)

st.sidebar.title("Фильтры")

all_years = sorted(df["год_торгов"].dropna().unique())
selected_years = st.sidebar.multiselect("Год торгов", all_years, default=all_years)

all_okrugs = sorted(df["округ_код"].dropna().unique())
selected_okrugs = st.sidebar.multiselect("Округ", all_okrugs, default=all_okrugs)

all_floors = [item for item in FLOOR_ORDER if item in set(df["этаж_норм"].dropna().unique())]
selected_floors = st.sidebar.multiselect("Этаж", all_floors, default=all_floors)

area_range = st.sidebar.slider(
    "Площадь, м²",
    min_value=float(df["площадь_м²"].min()),
    max_value=float(df["площадь_м²"].max()),
    value=(float(df["площадь_м²"].min()), float(df["площадь_м²"].max())),
    step=1.0,
)

price_range = st.sidebar.slider(
    "Итоговая цена, млн ₽",
    min_value=float(df["итоговая_цена_млн"].min()),
    max_value=float(df["итоговая_цена_млн"].max()),
    value=(float(df["итоговая_цена_млн"].min()), float(df["итоговая_цена_млн"].max())),
    step=0.5,
)

excess_range = st.sidebar.slider(
    "Превышение цены, %",
    min_value=float(df["превышение_цены_%"].min()),
    max_value=float(df["превышение_цены_%"].max()),
    value=(float(df["превышение_цены_%"].min()), float(df["превышение_цены_%"].max())),
    step=1.0,
)

filtered = df[
    ((df["форма_проведения"] == selected_form) if selected_form != "Все" else True)
    & df["год_торгов"].isin(selected_years)
    & df["округ_код"].isin(selected_okrugs)
    & df["этаж_норм"].isin(selected_floors)
    & ((df["match_confidence_label"] == selected_match_conf) if selected_match_conf != "Все" else True)
    & df["площадь_м²"].between(area_range[0], area_range[1])
    & df["итоговая_цена_млн"].between(price_range[0], price_range[1])
    & df["превышение_цены_%"].between(excess_range[0], excess_range[1])
].copy()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Купленных лотов", len(filtered))
col2.metric("Ср. превышение", f"{filtered['превышение_цены_%'].mean():+.1f}%")
col3.metric("Ср. итоговая цена", f"{filtered['итоговая_цена_млн'].mean():.1f} млн ₽")
matched_count = int(filtered["likely_company"].fillna("").astype(str).str.strip().ne("").sum())
col4.metric("Usage matched", matched_count)

center_lat = filtered["latitude"].mean() if len(filtered) else 55.7558
center_lon = filtered["longitude"].mean() if len(filtered) else 37.6173
map_obj = folium.Map(location=[center_lat, center_lon], zoom_start=10, tiles="CartoDB positron")

for _, row in filtered.iterrows():
    likely_company = safe_text(row["likely_company"])
    likely_usage = safe_text(row["likely_usage"])
    popup_html = f"""
    <div style="font-family: Arial, sans-serif; min-width: 320px;">
        <h4 style="margin: 0 0 8px; color: #333;">Лот #{row['номер_лота']}</h4>
        <table style="font-size: 13px; line-height: 1.6;">
            <tr><td><b>Адрес:</b></td><td>{safe_text(row['адрес'])}</td></tr>
            <tr><td><b>Площадь:</b></td><td>{row['площадь_м²']:.1f} м²</td></tr>
            <tr><td><b>Старт:</b></td><td>{row['начальная_цена_млн']:.1f} млн ₽</td></tr>
            <tr><td><b>Итог:</b></td><td>{row['итоговая_цена_млн']:.1f} млн ₽</td></tr>
            <tr><td><b>Превышение:</b></td><td>{row['превышение_цены_%']:+.1f}%</td></tr>
            <tr><td><b>Участники:</b></td><td>{row['участники'] if pd.notna(row['участники']) else '—'}</td></tr>
            <tr><td><b>Округ:</b></td><td>{row['округ_код']}</td></tr>
            <tr><td><b>Этаж:</b></td><td>{row['этаж_норм']}</td></tr>
            <tr><td><b>Usage:</b></td><td>{likely_usage}</td></tr>
            <tr><td><b>Company:</b></td><td>{likely_company}</td></tr>
            <tr><td><b>Match:</b></td><td>{row['match_confidence_label']}</td></tr>
        </table>
        <br><a href="{row['url']}" target="_blank" style="color: #1a73e8;">→ Подробнее на investmoscow.ru</a>
    </div>
    """
    folium.CircleMarker(
        location=[row["latitude"], row["longitude"]],
        radius=row["radius"],
        color=row["color"],
        fill=True,
        fill_color=row["color"],
        fill_opacity=0.75,
        popup=folium.Popup(popup_html, max_width=380),
        weight=1,
    ).add_to(map_obj)

st_folium(map_obj, width=None, height=650, returned_objects=[])

st.subheader("Легенда")
legend_left, legend_right = st.columns(2)
with legend_left:
    st.markdown("**Цвет точки = превышение цены**")
    st.markdown(
        """
        <div style="display:flex;align-items:center;gap:12px;margin:8px 0;"><span style="display:inline-block;width:20px;height:20px;border-radius:50%;background:#2563eb;"></span><span>Сильное снижение</span></div>
        <div style="display:flex;align-items:center;gap:12px;margin:8px 0;"><span style="display:inline-block;width:20px;height:20px;border-radius:50%;background:#2ecc71;"></span><span>0% (цена покупки = старт)</span></div>
        <div style="display:flex;align-items:center;gap:12px;margin:8px 0;"><span style="display:inline-block;width:20px;height:20px;border-radius:50%;background:#f1d621;"></span><span>~50%</span></div>
        <div style="display:flex;align-items:center;gap:12px;margin:8px 0;"><span style="display:inline-block;width:20px;height:20px;border-radius:50%;background:#e74c3c;"></span><span>100%+</span></div>
        """,
        unsafe_allow_html=True,
    )
with legend_right:
    st.markdown("**Размер точки = площадь**")
    st.markdown(
        """
        <div style="display:flex;align-items:center;gap:12px;margin:8px 0;"><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#666;"></span><span>Малый лот</span></div>
        <div style="display:flex;align-items:center;gap:12px;margin:8px 0;"><span style="display:inline-block;width:16px;height:16px;border-radius:50%;background:#666;"></span><span>Средний лот</span></div>
        <div style="display:flex;align-items:center;gap:12px;margin:8px 0;"><span style="display:inline-block;width:24px;height:24px;border-radius:50%;background:#666;"></span><span>Крупный лот</span></div>
        """,
        unsafe_allow_html=True,
    )

st.subheader("Участники ↔ превышение")
corr_df = filtered[
    filtered["участники"].notna() & filtered["превышение_цены_%"].notna() & (filtered["участники"] > 0)
].copy()
if len(corr_df) > 1:
    fig, ax = plt.subplots(figsize=(12, 5))
    scatter = ax.scatter(
        corr_df["участники"],
        corr_df["превышение_цены_%"],
        c=corr_df["превышение_цены_%"],
        cmap="RdYlBu_r",
        s=np.clip(corr_df["площадь_м²"] * 0.3, 20, 300),
        alpha=0.7,
        edgecolors="gray",
        linewidth=0.3,
    )
    ax.set_xlabel("Количество участников")
    ax.set_ylabel("Превышение цены, %")
    ax.set_title(f"Зависимость превышения цены от количества участников (N={len(corr_df)})")
    cbar = plt.colorbar(scatter, ax=ax)
    cbar.set_label("Превышение, %")
    st.pyplot(fig)
    plt.close()

    corr_value = corr_df[["участники", "превышение_цены_%"]].corr().iloc[0, 1]
    st.caption(f"Корреляция (участники ↔ превышение): r = {corr_value:.3f}")
else:
    st.info("Недостаточно данных по участникам для расчёта корреляции.")

st.subheader("Данные")
st.caption(f"Показано {len(filtered)} из {len(df)} записей")

csv_data = filtered.to_csv(index=False, encoding="utf-8-sig")
st.download_button("Скачать CSV", data=csv_data, file_name="property_goals_filtered.csv", mime="text/csv")

display_df = filtered.copy()
display_df["ссылка_на_лот"] = display_df["url"].fillna("")
display_cols = [
    "match_confidence_label",
    "match_after_days",
    "likely_company",
    "likely_usage",
    "превышение_цены_%",
    "участники",
    "ссылка_на_лот",
    "номер_лота",
    "адрес",
    "площадь_м²",
    "начальная_цена_руб",
    "итоговая_цена_руб",
    "этаж_норм",
    "метро",
    "округ_код",
    "форма_проведения",
    "год_торгов",
]
st.dataframe(
    display_df[display_cols],
    use_container_width=True,
    height=420,
    hide_index=True,
    column_config={
        "match_confidence_label": "Usage match",
        "match_after_days": st.column_config.NumberColumn("Days to match", format="%d"),
        "likely_company": "Likely company",
        "likely_usage": "Likely usage",
        "превышение_цены_%": st.column_config.NumberColumn("Превышение", format="%+.1f%%"),
        "участники": "Участники",
        "ссылка_на_лот": st.column_config.LinkColumn("Лот", width="small"),
        "номер_лота": None,
    },
)
