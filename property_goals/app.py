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


APP_BUILD = "2026-04-26-retailstreets-none-fix-v3"
BASE_DIR = Path(__file__).resolve().parent
ENRICHED_GEO_DATA_PATH = BASE_DIR / "investmoscow_sold_2022_2026_enriched_geo.csv"
ENRICHED_DATA_PATH = BASE_DIR / "investmoscow_sold_2022_2026_enriched.csv"
CLEAN_DATA_PATH = BASE_DIR / "investmoscow_sold_2022_2026_clean.csv"
PROTO_JSON_PATH = BASE_DIR.parent / "web-parsers" / "investmoskow_before" / "data" / "protocols" / "protocol_cache.json"
RS_SUMMARY_PATH = BASE_DIR / "matches" / "property_retailstreets_summary.csv"

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
    mapping = {"high": "Высокое", "medium": "Среднее", "low": "Низкое", "none": "Нет"}
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

    # Публичное предложение / Без объявления цены не имеют превышения на сайте — считаем сами
    mask = df["превышение_цены_%"].isna() & (df["начальная_цена_руб"] > 0)
    df.loc[mask, "превышение_цены_%"] = (
        (df.loc[mask, "итоговая_цена_руб"] - df.loc[mask, "начальная_цена_руб"])
        / df.loc[mask, "начальная_цена_руб"] * 100
    ).round(1)

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
    df["участники"] = pd.to_numeric(df["participants_count"], errors="coerce").astype("Int64")

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
    def _match_source(row) -> str:
        tw = str(row.get("match_time_window") or "")
        conf = str(row.get("match_confidence") or "").strip()
        if not conf:
            return "Без совпадения"
        if tw == "0-180d_recent_2026-04":
            return "Недавние (апрель 2026, до 180 дн.)"
        if tw.startswith("gap_snapshot_"):
            snapshot = tw.replace("gap_snapshot_", "")
            return f"Данные появления бизнеса за {snapshot}"
        if tw.startswith("first_after_snapshot_"):
            snapshot = tw.replace("first_after_snapshot_", "")
            return f"Данные появления бизнеса за {snapshot}"
        return "Базовые (180-365 дней после покупки)"

    df["match_source_label"] = df.apply(_match_source, axis=1)

    if RS_SUMMARY_PATH.exists():
        rs = pd.read_csv(RS_SUMMARY_PATH, encoding="utf-8-sig")[
            ["номер_лота", "rs_top_category", "rs_top_chains", "rs_chains_count"]
        ]
        df = df.merge(rs, on="номер_лота", how="left")
    else:
        df["rs_top_category"] = ""
        df["rs_top_chains"] = ""
        df["rs_chains_count"] = pd.NA
    df["rs_top_category"] = df["rs_top_category"].fillna("")
    df["rs_top_chains"] = df["rs_top_chains"].fillna("")

    return df


df = load_data()

st.title("Property Goals")
st.caption("История реально купленных лотов investmoscow, 2022–2026")
st.caption(f"Build: {APP_BUILD}")

all_forms = sorted(df["форма_проведения"].dropna().unique())
selected_form = st.selectbox("Форма проведения", ["Все"] + all_forms, index=0)
all_match_conf = [item for item in ["Высокое", "Среднее", "Низкое", "Нет"] if item in set(df["match_confidence_label"].dropna().unique())]
selected_match_conf = st.selectbox("Качество совпадения", ["Все"] + all_match_conf, index=0)
all_match_sources = sorted(s for s in df["match_source_label"].dropna().unique() if s != "Без совпадения")
selected_match_source = st.selectbox("Источник совпадения", ["Все совпавшие"] + all_match_sources + ["Без совпадения"], index=0)

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
    & (
        df["match_source_label"].ne("Без совпадения")
        if selected_match_source == "Все совпавшие"
        else (df["match_source_label"] == selected_match_source)
    )
    & (df["площадь_м²"].between(area_range[0], area_range[1]) | df["площадь_м²"].isna())
    & (df["итоговая_цена_млн"].between(price_range[0], price_range[1]) | df["итоговая_цена_млн"].isna())
    & (df["превышение_цены_%"].between(excess_range[0], excess_range[1]) | df["превышение_цены_%"].isna())
].copy()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Купленных лотов", len(filtered))
col2.metric("Ср. превышение", f"{filtered['превышение_цены_%'].mean():+.1f}%")
col3.metric("Ср. итоговая цена", f"{filtered['итоговая_цена_млн'].mean():.1f} млн ₽")
matched_count = int(filtered["likely_company"].fillna("").astype(str).str.strip().ne("").sum())
col4.metric("Совпало с арендатором", matched_count)

show_all_map = st.checkbox("Показать все лоты на карте (включая без совпадения)", value=False)
if show_all_map:
    map_df = filtered.copy()
    st.caption(f"На карте: {len(map_df)} лотов (все в текущем фильтре).")
else:
    map_df = filtered[filtered["match_confidence"].fillna("").astype(str).str.strip().ne("")].copy()
    st.caption(f"На карте лоты с совпадением: {len(map_df)} из {len(filtered)}. Включите галочку выше для всех лотов.")

center_lat = map_df["latitude"].mean() if len(map_df) else 55.7558
center_lon = map_df["longitude"].mean() if len(map_df) else 37.6173
map_obj = folium.Map(location=[center_lat, center_lon], zoom_start=10, tiles="CartoDB positron")

for _, row in map_df.iterrows():
    likely_company = safe_text(row["likely_company"])
    likely_usage = safe_text(row["likely_usage"])
    popup_html = f"""
    <div style="font-family: Arial, sans-serif; min-width: 340px;">
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
            {f'<tr><td><b>Подходящая категория:</b></td><td>{safe_text(row["rs_top_category"])}</td></tr><tr><td><b>Подходящие сети:</b></td><td style="font-size:11px;">{safe_text(str(row["rs_top_chains"])[:120])}</td></tr>' if not likely_company and row.get("rs_top_category") else ''}
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

st.subheader("Данные")
st.caption(f"Показано {len(filtered)} из {len(df)} записей")

csv_data = filtered.to_csv(index=False, encoding="utf-8-sig")
st.download_button("Скачать CSV", data=csv_data, file_name="property_goals_filtered.csv", mime="text/csv")

display_df = filtered.copy()
display_df["ссылка_на_лот"] = display_df["url"].fillna("")
display_cols = [
    "match_source_label",
    "match_confidence_label",
    "match_after_days",
    "likely_company",
    "likely_usage",
    "rs_top_category",
    "rs_top_chains",
    "превышение_цены_%",
    "начальная_цена_млн",
    "итоговая_цена_млн",
    "участники",
    "ссылка_на_лот",
    "номер_лота",
    "адрес",
    "площадь_м²",
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
        "match_source_label": "Источник",
        "match_confidence_label": "Совпадение",
        "match_after_days": st.column_config.NumberColumn("Дней до матча", format="%d"),
        "likely_company": "Арендатор",
        "likely_usage": "Категория",
        "rs_top_category": "Подходящая категория",
        "rs_top_chains": st.column_config.TextColumn("Подходящие сети", width="medium"),
        "превышение_цены_%": st.column_config.NumberColumn("Превышение", format="%+.1f%%"),
        "начальная_цена_млн": st.column_config.NumberColumn("Старт, млн ₽", format="%.1f"),
        "итоговая_цена_млн": st.column_config.NumberColumn("Итог, млн ₽", format="%.1f"),
        "участники": "Участники",
        "ссылка_на_лот": st.column_config.LinkColumn("Лот", width="small"),
        "номер_лота": None,
    },
)

# ── Инсайты ────────────────────────────────────────────────────────────────────────────────
st.divider()
st.subheader("Инсайты и выводы")

_matched = df[df["match_confidence"].fillna("").str.strip() != ""]
_n = len(_matched)
_total = len(df)
_revenue_bln = df["итоговая_цена_млн"].sum() / 1000
_median_price = df["итоговая_цена_млн"].median()
_excess_valid = df[df["начальная_цена_руб"] > 0]["превышение_цены_%"].dropna()
_excess_pct = (_excess_valid > 0).mean() * 100
_excess_pos = _excess_valid[_excess_valid > 0]
_excess_med = _excess_pos.median() if len(_excess_pos) > 0 else 0
_excess_max = _excess_valid.max() if len(_excess_valid) > 0 else 0
_wb_ozon = _matched["likely_company"].fillna("").str.contains("Wildberries|Ozon", case=False).sum()

_beauty_cats = ["Красота", "Медицина", "Стоматолог", "Барбер"]
_beauty_n = _matched["likely_usage"].fillna("").apply(
    lambda u: any(c.lower() in u.lower() for c in _beauty_cats)
).sum()

_public_share = (
    df["форма_проведения"].fillna("").str.contains("публичн", case=False).mean() * 100
    if "форма_проведения" in df.columns else 0
)

_by_year = (
    df.groupby("год_торгов")
    .apply(lambda g: pd.Series({
        "всего": len(g),
        "с матчем": (g["match_confidence"].fillna("").str.strip() != "").sum(),
    }))
    .reset_index()
)
_by_year["% матча"] = (_by_year["с матчем"] / _by_year["всего"] * 100).round(0).astype(int)
_by_year_indexed = _by_year.set_index("год_торгов")
_year_min_match = _by_year.loc[_by_year["% матча"].idxmin(), "год_торгов"]
_pct_min = _by_year["% матча"].min()

_best_year = df.groupby("год_торгов").size().idxmax()
_best_year_n = df.groupby("год_торгов").size().max()

# Метрики — строка 1: общая картина
mc1, mc2, mc3, mc4 = st.columns(4)
mc1.metric("Лотов продано (2022–2026)", f"{_total:,}".replace(",", " "))
mc2.metric("Выручка города", f"≈ {_revenue_bln:.0f} млрд ₽")
mc3.metric("Медиана цены продажи", f"{_median_price:.1f} млн ₽")
mc4.metric("Доля с превышением цены", f"{_excess_pct:.0f}%")

# Метрики — строка 2: матчинг и интересные факты
mc1, mc2, mc3 = st.columns(3)
mc1.metric("Лотов с установленным арендатором", f"{_n} ({_n/_total*100:.0f}%)")
mc2.metric("Маркетплейсы WB + Ozon", f"{_wb_ozon} из {_n} лотов")
mc3.metric("Пик продаж", f"{_best_year} — {_best_year_n} лотов")

# Графики
gc1, gc2 = st.columns(2)

with gc1:
    st.markdown("**Топ категорий арендаторов**")
    _usage = _matched["likely_usage"].fillna("").str.split("|").str[0].str.strip()
    def _rubric(s):
        return s.split("->")[0].strip() if "->" in s else s
    _rubric_counts = _usage.map(_rubric).value_counts().head(8)
    _rubric_counts = _rubric_counts[_rubric_counts.index != ""]
    fig, ax = plt.subplots(figsize=(5, 3))
    ax.barh(_rubric_counts.index[::-1], _rubric_counts.values[::-1])
    ax.set_xlabel("лотов")
    plt.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

with gc2:
    st.markdown("**Топ компаний-арендаторов**")
    _companies = _matched["likely_company"].fillna("").str.split("|").str[0].str.strip()
    _companies = _companies[_companies != ""]
    _companies = (
        _companies
        .str.replace(r"Wildberries,.*", "Wildberries (ПВЗ)", regex=True)
        .str.replace(r"Магнит,.*", "Магнит", regex=True)
        .str.replace(r"Красное&Белое,.*", "Красное&Белое", regex=True)
        .str.replace(r"Яндекс Маркет,.*", "Яндекс Маркет (ПВЗ)", regex=True)
        .str.replace(r"Барберхаус,.*", "Барберхаус", regex=True)
        .str.replace(r"Винлаб,.*", "Винлаб", regex=True)
    )
    _co_counts = _companies.value_counts().head(10)
    fig, ax = plt.subplots(figsize=(5, 3))
    ax.barh(_co_counts.index[::-1], _co_counts.values[::-1])
    ax.set_xlabel("лотов")
    plt.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

# Текстовые выводы
st.markdown("#### Ключевые выводы")
ki1, ki2 = st.columns(2)
with ki1:
    _wb_ratio = round(_n / _wb_ozon) if _wb_ozon > 0 else 0
    st.info(
        "**Маркетплейсы — главный тренд.**  \n"
        f"Каждый {_wb_ratio}-й установленный арендатор — "
        "пункт выдачи Wildberries или Ozon. "
        "Городские помещения массово перепрофилируются под логистику последней мили."
    )
    st.info(
        "**Красота и сервис — второй кластер.**  \n"
        f"Барбершопы, ногтевые студии, стоматологии — суммарно {_beauty_n} лотов. "
        "Типичный профиль: 50–100 м², 1 этаж, жилой район."
    )
    st.info(
        "**Аукцион реально конкурентный.**  \n"
        f"{_excess_pct:.0f}% лотов уходят дороже старта, медиана +{_excess_med:.1f}%. "
        f"Рекорд — превышение +{_excess_max:.0f}%."
    )
with ki2:
    st.info(
        "**Публичное предложение — индикатор неликвида.**  \n"
        f"{_public_share:.0f}% лотов уходят на нисходящем аукционе — подвалы, "
        "нестандартные площади, плохая локация. Берут только с дисконтом."
    )
    st.info(
        f"**Пик продаж — {_best_year} год ({_best_year_n} лотов).**  \n"
        f"Процент совпадений минимален в {_year_min_match} году ({_pct_min}%) — "
        "многие арендаторы ещё не появились в 2GIS или не накопилось данных."
    )
    st.info(
        f"**{_n/_total*100:.0f}% матча — нижняя оценка.**  \n"
        "Ограничения: пробел в снимках 2GIS (2021–2022), нет кадастрового номера, "
        "матч по адресу. Компании без онлайн-присутствия (ИП, склады) не видны в справочнике."
    )

# Дополнительная аналитика
st.markdown("#### Детали матчинга")
da1, da2 = st.columns(2)

with da1:
    st.markdown("**Матчи по году продажи**")
    fig, ax = plt.subplots(figsize=(5, 3))
    x = range(len(_by_year_indexed))
    ax.bar([i - 0.2 for i in x], _by_year_indexed["всего"], width=0.4, label="всего")
    ax.bar([i + 0.2 for i in x], _by_year_indexed["с матчем"], width=0.4, label="с матчем")
    ax.set_xticks(list(x))
    ax.set_xticklabels(_by_year_indexed.index, rotation=45)
    ax.legend()
    plt.tight_layout()
    st.pyplot(fig)
    plt.close(fig)
    st.dataframe(
        _by_year.rename(columns={"год_торгов": "Год"}).set_index("Год"),
        use_container_width=True,
    )

with da2:
    st.markdown("**Источник данных о матче (2022–2026)**")
    def _source_label(tw: str) -> str:
        if not tw:
            return ""
        if tw.startswith("gap_snapshot_"):
            return "Промежуточные снэпшоты\n(2022–2026)"
        if tw.startswith("first_after_snapshot_"):
            return "Снэпшот 2025-09\n(4-летнее окно)"
        if tw == "180-365d":
            return "Baseline\n(180–365 дней)"
        if "recent" in tw:
            return "Недавние\n(0–180 дней)"
        return tw
    _tw_counts = (
        _matched["match_time_window"].fillna("").map(_source_label)
        .value_counts()
    )
    fig, ax = plt.subplots(figsize=(5, 3))
    ax.barh(_tw_counts.index[::-1], _tw_counts.values[::-1])
    ax.set_xlabel("лотов")
    plt.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

