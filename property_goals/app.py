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


APP_BUILD = "2026-04-27-analytics-v10"
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


def format_match_confidence(conf: object, preview: object = None) -> str:
    if not isinstance(conf, str) or not conf.strip():
        return "Нет"
    c = conf.strip().lower()
    if c == "high":
        return "Высокое"
    if c == "medium":
        n = len([x for x in str(preview or "").split("|") if x.strip()])
        if n <= 1:
            return "Вероятный"
        return f"{n} варианта" if n in (2, 3, 4) else f"{n} вариантов"
    return "Нет"


def safe_text(value: object, fallback: str = "—") -> str:
    if not isinstance(value, str):
        return fallback
    clean = value.strip()
    return clean if clean else fallback


def fmt_date(v) -> str:
    s = str(v).strip()
    if not s or s in ("nan", "None", ""):
        return "—"
    return s[:10]


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
        "multilot_building",
        "история_бизнесов",
        "сейчас_в_здании",
        "были_в_здании",
    ]:
        if col not in df.columns:
            df[col] = ""
    df["match_confidence"] = df["match_confidence"].fillna("").astype(str)
    df["match_confidence_label"] = df.apply(
        lambda r: format_match_confidence(r["match_confidence"], r.get("company_candidates_preview")),
        axis=1,
    )
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

    # Вычисляем multilot прямо из данных — не ждём перезапуска pipeline
    _addr_col = "address_norm" if "address_norm" in df.columns else "адрес"
    addr_counts = df.groupby(_addr_col)[_addr_col].transform("count")
    df["multilot_building"] = (addr_counts > 1).map({True: "1", False: ""})

    return df


df = load_data()

st.title("Property Goals")
st.caption("История реально купленных лотов investmoscow, 2022–2026")
st.caption(f"Build: {APP_BUILD}")

all_forms = sorted(df["форма_проведения"].dropna().unique())
selected_form = st.selectbox("Форма проведения", ["Все"] + all_forms, index=0)
selected_match = st.selectbox("Арендатор найден", ["Все", "Да", "Нет"], index=0)

st.sidebar.title("Фильтры")

all_years = sorted(df["год_торгов"].dropna().unique())
selected_years = st.sidebar.multiselect("Год торгов", all_years, default=all_years)

_conf_order = ["Высокое", "Вероятный", "2 варианта", "3 варианта", "4 варианта", "5 вариантов"]
all_match_conf = [c for c in _conf_order if c in set(df["match_confidence_label"].dropna().unique())]
selected_match_conf = st.sidebar.multiselect("Качество совпадения", all_match_conf, default=all_match_conf)

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
    & (df["match_confidence_label"].isin(selected_match_conf) if selected_match_conf != all_match_conf else True)
    & (
        True if selected_match == "Все"
        else (df["match_confidence"].fillna("").str.strip() != "") if selected_match == "Да"
        else (df["match_confidence"].fillna("").str.strip() == "")
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
    # Build match timing rows
    _sale_date = fmt_date(row.get("дата_подведения_итогов", ""))
    _after_days = row.get("match_after_days")
    if pd.notna(_after_days) and likely_company and likely_company != "—":
        _days_int = int(_after_days)
        _months = _days_int // 30
        if _months >= 2:
            _timing = f"{_days_int} дн. (~{_months} мес.)"
        else:
            _timing = f"{_days_int} дн."
        _match_timing_rows = f"""
            <tr><td><b>Дата торгов:</b></td><td>{_sale_date}</td></tr>
            <tr><td><b>Бизнес найден через:</b></td><td>{_timing}</td></tr>"""
    elif _sale_date != "—":
        _match_timing_rows = f"""
            <tr><td><b>Дата торгов:</b></td><td>{_sale_date}</td></tr>"""
    else:
        _match_timing_rows = ""
    def _biz_list_row(label, raw):
        if not raw or raw == "—":
            return ""
        items = "".join(f"<br>· {b.strip()}" for b in raw.split("|") if b.strip())
        return f'<tr><td valign="top"><b>{label}:</b></td><td style="font-size:11px;line-height:1.5;">{items}</td></tr>'

    _history_row = _biz_list_row("История здания", safe_text(row.get("история_бизнесов", "")))
    _now_row     = _biz_list_row("Сейчас в здании", safe_text(row.get("сейчас_в_здании", "")))
    _gone_row    = _biz_list_row("Были в здании", safe_text(row.get("были_в_здании", "")))
    _is_multilot = str(row.get("multilot_building", "")).strip() == "1"
    _multilot_row = '<tr><td colspan="2" style="color:#b45309;font-size:11px;">⚠ Здание с несколькими лотами — арендатор предположительный</td></tr>' if _is_multilot else ""
    _conf_raw = str(row.get("match_confidence", "")).strip().lower()
    if _conf_raw == "medium":
        _candidates = [c.strip() for c in str(row.get("company_candidates_preview", "")).split("|") if c.strip()]
        _usages = [u.strip() for u in str(row.get("usage_candidates_preview", "")).split("|") if u.strip()]
        _n = len(_candidates)
        _tenant_label = f"Варианты арендатора ({_n})" if _n > 1 else "Варианты арендатора"
        _tenant_value = "<br>".join(f"· {c}" for c in _candidates) if _candidates else likely_company
        _usage_label = "Варианты категории"
        _usage_value = "<br>".join(f"· {u}" for u in _usages) if _usages else likely_usage
    else:
        _tenant_label = "Арендатор"
        _tenant_value = likely_company
        _usage_label = "Категория"
        _usage_value = likely_usage
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
            <tr><td><b>Этаж:</b></td><td>{row['этаж_норм']}</td></tr>{_match_timing_rows}
            <tr><td valign="top"><b>{_tenant_label}:</b></td><td>{_tenant_value}</td></tr>
            <tr><td valign="top"><b>{_usage_label}:</b></td><td>{_usage_value}</td></tr>
            <tr><td><b>Совпадение:</b></td><td>{row['match_confidence_label']}</td></tr>
            {_multilot_row}
            {_now_row}
            {_gone_row}
            {_history_row}
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
    "match_confidence_label",
    "multilot_building",
    "match_after_days",
    "likely_company",
    "likely_usage",
    "сейчас_в_здании",
    "были_в_здании",
    "история_бизнесов",
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
display_df["multilot_building"] = display_df["multilot_building"].apply(
    lambda v: "Да" if str(v).strip() == "1" else ""
)
st.dataframe(
    display_df[display_cols],
    use_container_width=True,
    height=420,
    hide_index=True,
    column_config={
        "match_confidence_label": "Совпадение",
        "multilot_building": "Мультилот",
        "match_after_days": st.column_config.NumberColumn("Дней до матча", format="%d"),
        "likely_company": "Арендатор",
        "likely_usage": "Категория",
        "сейчас_в_здании": st.column_config.TextColumn("Сейчас в здании", width="medium"),
        "были_в_здании": st.column_config.TextColumn("Были в здании", width="medium"),
        "история_бизнесов": st.column_config.TextColumn("История здания", width="large"),
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

# ── Аналитика ───────────────────────────────────────────────────────────────────────────────
st.divider()
st.subheader("Аналитика")

_matched = df[df["match_confidence"].fillna("").str.strip() != ""]
_n_lots  = len(_matched)
_total   = len(df)

# Unique tenants: deduplicate by (company, address)
_co_df = _matched[["likely_company", "address_norm", "match_after_days",
                    "площадь_м²", "этаж", "likely_usage", "форма_проведения",
                    "итоговая_цена_руб", "начальная_цена_руб"]].copy()

_CHART_ALIASES = {
    "wildberries": "Wildberries", "вайлдберриз": "Wildberries",
    "ozon": "Ozon", "озон": "Ozon",
    "яндекс маркет": "Яндекс Маркет", "яндекс.маркет": "Яндекс Маркет",
    "сдэк": "СДЭК", "cdek": "СДЭК",
    "авито": "Авито", "магнит": "Магнит",
    "пятёрочка": "Пятёрочка", "пятерочка": "Пятёрочка",
    "вкусвилл": "ВкусВилл", "fix price": "Fix Price",
    "красное&белое": "Красное&Белое", "красное & белое": "Красное&Белое",
    "винлаб": "Винлаб", "dns": "DNS",
    "перекрёсток": "Перекрёсток", "перекресток": "Перекрёсток",
    "лента": "Лента",
    "московское долголетие": "Московское долголетие",
    "ямосковское долголетие": "Московское долголетие",
}

def _norm_chart(raw):
    name = str(raw).split(",")[0].strip()
    return _CHART_ALIASES.get(name.lower(), name)

def _norm_cat(u):
    cat = str(u).split("->")[0].split(",")[0].strip()
    return "Маркетплейсы (ПВЗ)" if cat == "Грузоперевозки / Транспортные услуги" else cat

_co_df["company"] = _co_df["likely_company"].fillna("").str.split("|").str[0].str.strip().apply(_norm_chart)
_co_df["category"] = _co_df["likely_usage"].fillna("").apply(_norm_cat)
_co_df["area"]     = pd.to_numeric(_co_df["площадь_м²"], errors="coerce")
_co_df["days"]     = pd.to_numeric(_co_df["match_after_days"], errors="coerce")
_co_df["floor_norm"]    = _co_df["этаж"].apply(normalize_floor)
_co_df["floor1"]        = _co_df["floor_norm"] == "1 этаж"
_co_df["floor_basement"]= _co_df["floor_norm"] == "Подвал"

# Deduplicated: one row per unique (company, address)
_uniq = _co_df[_co_df["company"] != ""].drop_duplicates(subset=["company", "address_norm"])
_n_unique = len(_uniq)

# ── KPI row ──────────────────────────────────────────────────────────────────
k1, k2, k3, k4 = st.columns(4)
_days_valid  = _co_df["days"].dropna()
_days_valid  = _days_valid[(_days_valid > 0) & (_days_valid <= 365)]
_floor1_pct  = int(_co_df["floor1"].mean() * 100)
_floor_bsmt_pct = int(_co_df["floor_basement"].mean() * 100)
_mp_n        = int((_uniq["category"] == "Маркетплейсы (ПВЗ)").sum())
_mp_pct      = int(_mp_n / _n_unique * 100)

k1.metric("Уникальных арендаторов", f"{_n_unique}",
          f"{_n_lots} лотов (с дублями по зданию)")
k2.metric("Маркетплейсы (ПВЗ)", f"{_mp_n} адресов", f"{_mp_pct}% от уникальных")
k3.metric("Медиана открытия", f"{int(_days_valid.median())} дней",
          f"{int((_days_valid < 180).mean()*100)}% за 6 мес.")
k4.metric("1-й этаж", f"{_floor1_pct}%", f"подвал: {_floor_bsmt_pct}%")

# ── Charts ────────────────────────────────────────────────────────────────────
ch1, ch2 = st.columns(2)

with ch1:
    st.markdown("**Топ компаний-арендаторов** (уникальных адресов)")
    _co_counts = _uniq["company"].value_counts().head(10)
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.barh(_co_counts.index[::-1], _co_counts.values[::-1])
    ax.set_xlabel("адресов")
    plt.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

with ch2:
    st.markdown("**Топ категорий** (уникальных адресов)")
    _cat_counts = _uniq["category"].value_counts().head(10)
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.barh(_cat_counts.index[::-1], _cat_counts.values[::-1])
    ax.set_xlabel("адресов")
    plt.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

# ── Insights ──────────────────────────────────────────────────────────────────
st.markdown("#### Ключевые находки")
i1, i2 = st.columns(2)

_pub   = df["форма_проведения"].fillna("").str.contains("публичн", case=False)
_start = pd.to_numeric(df["начальная_цена_руб"].astype(str).str.replace(",", "."), errors="coerce")
_final = pd.to_numeric(df["итоговая_цена_руб"].astype(str).str.replace(",", "."), errors="coerce")
_ratio = (_final / _start).replace([float("inf"), -float("inf")], pd.NA).dropna()
_ratio_pub = _ratio[_pub & (_start > 0)]
_ratio_auc = _ratio[~_pub & (_start > 0)]
_disc = int((1 - _ratio_pub.median()) * 100)
_prem = int((_ratio_auc.median() - 1) * 100)

_beauty_n  = int((_uniq["category"] == "Красота / Здоровье").sum())
_beauty_med_area = _uniq[_uniq["category"] == "Красота / Здоровье"]["area"].median()
_mp_area   = _uniq[_uniq["category"] == "Маркетплейсы (ПВЗ)"]["area"].median()

_pub_match_pct = int(df[_pub]["match_confidence"].fillna("").str.strip().ne("").mean() * 100)
_auc_match_pct = int(df[~_pub]["match_confidence"].fillna("").str.strip().ne("").mean() * 100)

_med_days = int(_days_valid.median())
_fast_pct = int((_days_valid < 90).mean() * 100)

_hist_col = "история_бизнесов"
_hist_sizes = df[_hist_col].fillna("").apply(
    lambda h: len([e for e in h.split("|") if e.strip()])
)
_has_hist = _hist_sizes > 0
_matched_mask = df["match_confidence"].fillna("").str.strip() != ""
_hist_med_matched   = int(_hist_sizes[_matched_mask & _has_hist].median())
_hist_med_unmatched = int(_hist_sizes[~_matched_mask & _has_hist].median())
_stable_n = int((_hist_sizes == 1).sum())

def _parse_hist(s):
    return [e.strip() for e in s.split("|") if e.strip()]

def _primary_cat(entry):
    if "(" in entry and entry.endswith(")"):
        return entry[entry.rfind("(")+1:-1].strip()
    return entry

_now_cats  = pd.Series([_primary_cat(e)
    for s in df["сейчас_в_здании"].fillna("") for e in _parse_hist(s)])
_gone_cats = pd.Series([_primary_cat(e)
    for s in df["были_в_здании"].fillna("") for e in _parse_hist(s)])
_now_vc  = _now_cats.value_counts()
_gone_vc = _gone_cats.value_counts()
_all_cats_idx = (_now_vc.add(_gone_vc, fill_value=0))
_survival = (_now_vc.divide(_all_cats_idx).fillna(0))
_min_total = 50
_eligible  = _all_cats_idx[_all_cats_idx >= _min_total].index
_surv_filt = _survival[_eligible].sort_values()
_stable_cats = _surv_filt.tail(5).index[::-1].tolist()
_gone_top_cats = _surv_filt.head(5).index.tolist()

with i1:
    st.info(
        f"**Треть помещений — пункты выдачи маркетплейсов.**  \n"
        f"{_mp_pct}% уникальных арендаторов — Wildberries, Ozon, Яндекс Маркет. "
        f"Типичная площадь — {int(_mp_area):.0f} м². "
        "Городские коммерческие помещения стали инфраструктурой доставки."
    )
    st.info(
        f"**Публичное предложение — дисконт для покупателя.**  \n"
        f"Нисходящий аукцион закрывается в среднем на {_disc}% ниже стартовой цены, "
        f"обычный аукцион — на {_prem}% выше. "
        f"Арендатора потом находят реже: {_pub_match_pct}% vs {_auc_match_pct}% у конкурентных торгов."
    )

with i2:
    st.info(
        f"**Красота — второй по размеру кластер.**  \n"
        f"{_beauty_n} уникальных адресов: барбершопы, ногтевые студии, косметологи. "
        f"Медиана площади — {_beauty_med_area:.0f} м². "
        "Подходят под большинство помещений 1-го этажа в жилых районах."
    )
    st.info(
        f"**{_floor1_pct}% арендаторов — 1-й этаж, {_floor_bsmt_pct}% — подвал.**  \n"
        "В подвалах — маркетплейсы, красота, медицина. "
        "2-й этаж и выше практически не сдаются. "
        f"Медиана открытия — {_med_days} дней после покупки, "
        f"{_fast_pct}% открываются в первые 3 месяца."
    )

i3, i4 = st.columns(2)
with i3:
    _stable_str = ", ".join(_stable_cats)
    st.info(
        f"**Кто остаётся в зданиях.**  \n"
        f"Самые стабильные категории в радиусе 250 м: {_stable_str}. "
        "Сетевой ретейл и маркетплейсы открылись — и не уходят."
    )
with i4:
    _gone_str = ", ".join(_gone_top_cats)
    st.info(
        f"**Кто исчезает.**  \n"
        f"Категории, которых почти не осталось: {_gone_str}. "
        "B2B-сервисы и специализированные офисы уходят из уличного ретейла."
    )

# ── Match by year ────────────────────────────────────────────────────────────
_by_year = (
    df.groupby("год_торгов")
    .apply(lambda g: pd.Series({
        "всего": len(g),
        "с матчем": (g["match_confidence"].fillna("").str.strip() != "").sum(),
    }))
    .reset_index()
)
_by_year["% матча"] = (_by_year["с матчем"] / _by_year["всего"] * 100).round(0).astype(int)

st.markdown("**Матчи по году продажи**")
st.dataframe(
    _by_year.rename(columns={"год_торгов": "Год"}).set_index("Год"),
    use_container_width=True,
)

