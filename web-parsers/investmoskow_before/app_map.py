"""
Streamlit-приложение для визуализации торгов investmoscow.ru на карте
"""
import streamlit as st
import pandas as pd
import folium
from folium import plugins
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from streamlit_folium import st_folium
import io
import base64
import os
import json
import re

APP_BUILD = "2026-04-12-refusal-participants-v2"

# Определяем базовую директорию
# Если запущено из поддиректории (web-parsers/investmoskow_before/), ищем данные там
# Иначе — ищем на уровень выше (в корне репозитория)
FILE_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(FILE_DIR, "data")):
    BASE_DIR = FILE_DIR
elif os.path.exists(os.path.join(os.path.dirname(FILE_DIR), "data")):
    BASE_DIR = os.path.dirname(FILE_DIR)
else:
    BASE_DIR = FILE_DIR

# ── Настройки страницы ──
st.set_page_config(
    page_title="Карта торгов investmoscow.ru",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Принудительная синяя тема через CSS-переменные Streamlit
st.markdown("""
<style>
:root {
    --primary-color: #60a5fa !important;
    --text-color: #262730;
    --background-color: #ffffff;
    --secondary-background-color: #f0f2f6;
}
.stApp {
    --primary-color: #60a5fa !important;
}
.st-emotion-cache-1kyxreq {
    background-color: #60a5fa !important;
    border-color: #60a5fa !important;
    color: #60a5fa !important;
}
.st-emotion-cache-13lic5j {
    background-color: #60a5fa !important;
}
.st-emotion-cache-77el07 {
    background-color: #60a5fa !important;
}
[data-testid="stSidebar"] .st-emotion-cache-1kyxreq {
    background-color: #60a5fa !important;
    border-color: #60a5fa !important;
}
[data-testid="stSidebar"] input[type="range"] {
    accent-color: #60a5fa !important;
}
[data-testid="stSidebar"] .st-cg {
    background-color: #60a5fa !important;
}
/* Слайдеры */
.stSlider > div > div > div > div {
    background-color: #60a5fa !important;
}
.stSlider [role="slider"] {
    background-color: #60a5fa !important;
}
/* Selectbox */
.stSelectbox > div > div > div {
    border-color: #d1d5db !important;
}
/* Multiselect */
.stMultiSelect > div > div > div {
    border-color: #d1d5db !important;
}
/* Active элементы */
:focus {
    outline-color: #60a5fa !important;
    box-shadow: 0 0 0 2px rgba(96, 165, 250, 0.3) !important;
}
</style>
""", unsafe_allow_html=True)

# ── Загрузка данных ──
@st.cache_data(ttl=3600)
def load_data():
    mapped_csv_path = os.path.join(BASE_DIR, "data", "investmoscow_completed_2022_2026_geocoded_mapped.csv")
    merged_csv_path = os.path.join(BASE_DIR, "data", "investmoscow_completed_2022_2026_geocoded.csv")
    legacy_csv_path = os.path.join(BASE_DIR, "data", "investmoscow_completed_2026-04-04_geocoded.csv")
    if os.path.exists(mapped_csv_path):
        csv_path = mapped_csv_path
    elif os.path.exists(merged_csv_path):
        csv_path = merged_csv_path
    else:
        csv_path = legacy_csv_path
    if not os.path.exists(csv_path):
        st.error(f"Файл не найден: {csv_path}")
        st.error(f"BASE_DIR: {BASE_DIR}")
        st.error(f"Содержимое директории: {os.listdir(BASE_DIR)}")
        if os.path.exists(os.path.join(BASE_DIR, "data")):
            st.error(f"Содержимое data/: {os.listdir(os.path.join(BASE_DIR, 'data'))}")
        st.stop()
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    # Убираем строки без координат
    # Для fallback-файлов дополнительно отбрасываем строки без координат.
    df = df.dropna(subset=["latitude", "longitude"])

    # Превышение: "95.0%" → 95.0
    if "превышение_цены_%" in df.columns:
        df["превышение_цены_%"] = (
            df["превышение_цены_%"]
            .astype(str)
            .str.replace("%", "", regex=False)
            .str.strip()
        )
        df["превышение_цены_%"] = pd.to_numeric(df["превышение_цены_%"], errors="coerce")

    # Ценовые колонки: "117613372,50" → 117613372.50
    money_cols = ["итоговая_цена_руб", "начальная_цена_руб", "цена_за_м²"]
    for col in money_cols:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(",", ".", regex=False)
                .str.strip()
            )
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Если превышение не пришло из источника, рассчитываем его из стартовой и итоговой цены.
    can_compute_excess = (
        df["превышение_цены_%"].isna()
        & df["начальная_цена_руб"].gt(0)
        & df["итоговая_цена_руб"].notna()
    )
    df.loc[can_compute_excess, "превышение_цены_%"] = (
        (df.loc[can_compute_excess, "итоговая_цена_руб"] - df.loc[can_compute_excess, "начальная_цена_руб"])
        / df.loc[can_compute_excess, "начальная_цена_руб"]
        * 100
    )

    return df

df = load_data()


def normalize_floor(value):
    if pd.isna(value):
        return "Не указано"

    raw = str(value).replace("\xa0", " ").strip()
    if not raw:
        return "Не указано"

    lower = raw.lower()

    if "," in lower:
        return "Многоуровневый"

    if " и выше" in lower:
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
        num = int(match.group())
        if num == 0:
            return "0 этаж"
        if num >= 5:
            return "5+ этаж"
        return f"{num} этаж"

    return raw


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

df["этаж_норм"] = df["этаж"].apply(normalize_floor)

# ── Пути к данным об участниках ──
PROTO_CSV_PATH = os.path.join(BASE_DIR, "data", "protocols", "participants_data.csv")
PROTO_JSON_PATH = os.path.join(BASE_DIR, "data", "protocols", "protocol_cache.json")
REFUSAL_LOTS_PATH = os.path.join(BASE_DIR, "data", "protocols", "refusal_protocols", "refusal_lots.txt")

# ── Извлечение округа из адреса ──
def extract_okrug(addr):
    if not isinstance(addr, str):
        return "Неизвестно"
    parts = addr.split(",")
    if parts:
        first = parts[0].strip()
        if "административный округ" in first:
            return first
        # Для Зеленограда
        if "Зеленоградский" in first:
            return first
    return "Неизвестно"

df["округ"] = df["адрес"].apply(extract_okrug)

# Словарь коротких названий округов
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

df["округ_код"] = df["округ"].map(OKRUG_SHORT).fillna("Другое")

df = df.merge(
    pd.DataFrame(
        [
            {
                "lot_id": int(k),
                "participants_count": v.get("participants_count"),
                "winner": v.get("winner"),
                "winner_price": v.get("winner_price"),
            }
            for k, v in json.load(open(PROTO_JSON_PATH, encoding="utf-8")).items()
        ]
    ),
    left_on="номер_лота",
    right_on="lot_id",
    how="left",
) if os.path.exists(PROTO_JSON_PATH) else df

# ── Протокол отказа ──
refusal_lots = set()
if os.path.exists(REFUSAL_LOTS_PATH):
    with open(REFUSAL_LOTS_PATH, "r", encoding="utf-8") as f:
        refusal_lots = set(line.strip() for line in f if line.strip())

df["есть_протокол_отказа"] = df["номер_лота"].astype(str).apply(lambda x: x in refusal_lots)

# Лоты с участниками, но без финальной цены, тоже считаем отказом победителя.
df["есть_скрытый_срыв_после_торгов"] = (
    df["participants_count"].fillna(-1).gt(0)
    & df["итоговая_цена_руб"].isna()
)
df["исключить_из_ценовой_статистики"] = (
    df["есть_протокол_отказа"] | df["есть_скрытый_срыв_после_торгов"]
)

# У лотов с отказом победителя превышение не должно участвовать в ценовой статистике.
df.loc[df["исключить_из_ценовой_статистики"], "превышение_цены_%"] = np.nan

# ── Определение статуса ──
def get_status(row):
    # Явный протокол отказа или отсутствие финальной цены после торгов = отказ победителя.
    if row.get("исключить_из_ценовой_статистики", False):
        return "Отказ победителя"
    # Нет итоговой цены = не состоялся
    if pd.isna(row.get("итоговая_цена_руб")):
        return "Не состоялся"
    return "Состоялся"

df["статус_торга"] = df.apply(get_status, axis=1)

# ── Цветовая функция ──
def get_color(row):
    """Цвет точки по статусу и превышению цены."""
    pc = row.get("participants_count")
    pct = row["превышение_цены_%"]

    # Отказ победителя = тёмно-серый.
    if row.get("статус_торга") == "Отказ победителя":
        return "#4a4a4a"

    # Не состоялся = светло-серый.
    if row.get("статус_торга") == "Не состоялся":
        return "#8f8f8f"

    if pd.isna(pct):
        return "#8f8f8f"

    # 0% = зелёный, 50% = жёлтый, 100%+ = красный
    if pct <= 0:
        return "#2ecc71"  # зелёный
    elif pct <= 50:
        # Зелёный → Жёлтый
        t = pct / 50.0
        r = int(46 + (241 - 46) * t)
        g = int(204 + (214 - 204) * t)
        b = int(113 + (33 - 113) * t)
    else:
        # Жёлтый → Красный
        t = min((pct - 50) / 50.0, 1.0)
        r = int(241 + (231 - 241) * t)
        g = int(214 + (76 - 214) * t)
        b = int(33 + (60 - 33) * t)
    return f"#{r:02x}{g:02x}{b:02x}"

df["color"] = df.apply(get_color, axis=1)

# Размер точки: площадь, масштабируем
def get_radius(area):
    """Радиус точки на основе площади, от 4 до 25"""
    if pd.isna(area) or area <= 0:
        return 5
    # Логарифмическое масштабирование
    r = 4 + 6 * np.log1p(area) / np.log1p(df["площадь_м²"].max())
    return max(4, min(r, 25))

df["radius"] = df["площадь_м²"].apply(get_radius)

# ═══════════════════════════════════════════════
#  SIDEBAR — ФИЛЬТРЫ
# ═══════════════════════════════════════════════
st.sidebar.title("Фильтры")

# Округ
all_okrugs = sorted(df["округ_код"].unique())
selected_okrugs = st.sidebar.multiselect("Округ", options=all_okrugs, default=all_okrugs)

# Год
years = sorted(df["год_торгов"].dropna().unique())
selected_year = st.sidebar.selectbox("Год торгов", options=["Все"] + list(years), index=0)

# Статус
status_options = ["Все", "Состоялся", "Не состоялся", "Отказ победителя"]
selected_status = st.sidebar.selectbox("Статус", options=status_options, index=0)

# Диапазон площади
min_area = float(df["площадь_м²"].min())
max_area = float(df["площадь_м²"].max())
area_range = st.sidebar.slider(
    "Площадь, м²",
    min_value=min_area,
    max_value=max_area,
    value=(min_area, max_area),
    step=1.0
)

# Диапазон начальной цены (млн руб)
df["начальная_цена_млн"] = df["начальная_цена_руб"] / 1e6
min_price = float(df["начальная_цена_млн"].min())
max_price = float(df["начальная_цена_млн"].max())
price_range = st.sidebar.slider(
    "Начальная цена, млн ₽",
    min_value=min_price,
    max_value=max_price,
    value=(min_price, max_price),
    step=0.5
)

# Превышение цены
valid_excess = df["превышение_цены_%"].dropna()
min_exc = float(valid_excess.min()) if len(valid_excess) > 0 else 0.0
max_exc = float(valid_excess.max()) if len(valid_excess) > 0 else 0.0
excess_range = st.sidebar.slider(
    "Превышение цены, %",
    min_value=min_exc,
    max_value=max_exc,
    value=(min_exc, max_exc),
    step=1.0
)

# Этаж
all_floors = [floor for floor in FLOOR_ORDER if floor in set(df["этаж_норм"].dropna().unique())]
selected_floors = st.sidebar.multiselect(
    "Этаж",
    options=all_floors,
    default=all_floors,
)

# Исключить лоты с отказом
exclude_refusal = st.sidebar.checkbox(
    "❌ Исключить лоты с отказом",
    value=False,
    help="Исключить лоты, где победитель уклонился от заключения договора"
)

# ═══════════════════════════════════════════════
#  ФИЛЬТРАЦИЯ
# ═══════════════════════════════════════════════
filtered = df.copy()

if selected_okrugs != all_okrugs:
    filtered = filtered[filtered["округ_код"].isin(selected_okrugs)]

if selected_year != "Все":
    filtered = filtered[filtered["год_торгов"] == selected_year]

if selected_status != "Все":
    filtered = filtered[filtered["статус_торга"] == selected_status]

filtered = filtered[
    (filtered["площадь_м²"] >= area_range[0]) &
    (filtered["площадь_м²"] <= area_range[1])
]

filtered = filtered[
    (filtered["начальная_цена_млн"] >= price_range[0]) &
    (filtered["начальная_цена_млн"] <= price_range[1])
]

filtered = filtered[
    filtered["превышение_цены_%"].isna() |
    (
        (filtered["превышение_цены_%"] >= excess_range[0]) &
        (filtered["превышение_цены_%"] <= excess_range[1])
    )
]

if selected_floors != all_floors:
    filtered = filtered[filtered["этаж_норм"].isin(selected_floors)]

# Исключить лоты с отказом
if exclude_refusal:
    filtered = filtered[~filtered["есть_протокол_отказа"]]

# ═══════════════════════════════════════════════
#  ОСНОВНОЙ ЭКРАН
# ═══════════════════════════════════════════════
st.title("Карта торгов investmoscow.ru")
st.caption("Нежилые помещения, торги 2022–2026")
st.caption(f"Build: {APP_BUILD}")

# ── Разделение по форме проведения ──
form_options = ["Все"] + sorted(df["форма_проведения"].dropna().unique())

# Считаем количество лотов по формам
form_counts = {}
for form in form_options:
    if form == "Все":
        form_counts[form] = len(filtered)
    else:
        form_counts[form] = len(filtered[filtered["форма_проведения"] == form])

form_labels = [f"{form} ({form_counts[form]})" for form in form_options]
selected_idx = st.selectbox("Форма проведения", options=form_labels, index=0, label_visibility="collapsed")
selected_form = form_options[form_labels.index(selected_idx)]

# Фильтруем по форме
if selected_form != "Все":
    filtered = filtered[filtered["форма_проведения"] == selected_form]

# Показываем текущую форму
if selected_form != "Все":
    st.subheader(f"📋 {selected_form}")

# Статистика без лотов со статусом "Отказ победителя".
stats_df = filtered[~filtered["исключить_из_ценовой_статистики"]]
n_successful = len(stats_df[stats_df["статус_торга"] == "Состоялся"])
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Всего лотов", len(filtered))
with col2:
    avg_excess = stats_df["превышение_цены_%"].dropna().mean()
    if pd.notna(avg_excess):
        st.metric("Ср. превышение", f"{avg_excess:+.1f}%")
    else:
        st.metric("Ср. превышение", "н/д")
with col3:
    if n_successful > 0:
        avg_price_m2 = stats_df[stats_df["итоговая_цена_руб"].notna()]["цена_за_м²"].mean()
        st.metric("Ср. цена за м²", f"{avg_price_m2/1e3:.0f}K ₽")
    else:
        st.metric("Ср. цена за м²", "—")

# ═══════════════════════════════════════════════
#  КАРТА
# ═══════════════════════════════════════════════

# Центр карты
center_lat = filtered["latitude"].mean() if len(filtered) > 0 else 55.7558
center_lon = filtered["longitude"].mean() if len(filtered) > 0 else 37.6173

m = folium.Map(location=[center_lat, center_lon], zoom_start=10, tiles="CartoDB positron")

# Добавляем точки
for _, row in filtered.iterrows():
    if pd.isna(row["latitude"]) or pd.isna(row["longitude"]):
        continue

    # Получаем участников
    participants = None
    if "participants_count" in row.index and pd.notna(row["participants_count"]):
        participants = int(row["participants_count"])

    # Popup
    if pd.notna(row["превышение_цены_%"]):
        excess_text = f"{row['превышение_цены_%']:+.1f}%"
    else:
        excess_text = row["статус_торга"]
    final_price = f"{row['итоговая_цена_руб']/1e6:.1f} млн ₽" if pd.notna(row["итоговая_цена_руб"]) else "—"
    start_price = f"{row['начальная_цена_руб']/1e6:.1f} млн ₽"

    participants_text = f"<tr><td><b>Участников:</b></td><td> {participants}</td></tr>" if participants is not None else ""
    winner_text = ""
    if "winner" in row.index and pd.notna(row.get("winner")):
        winner_name = str(row["winner"])[:60]
        winner_text = f"<tr><td><b>Победитель:</b></td><td> {winner_name}</td></tr>"
        if "winner_price" in row.index and pd.notna(row.get("winner_price")):
            winner_text = f"<tr><td><b>Победитель:</b></td><td> {winner_name} ({row['winner_price']} ₽)</td></tr>"

    popup_html = f"""
    <div style="font-family: Arial, sans-serif; min-width: 280px;">
        <h4 style="margin: 0 0 8px; color: #333;">Лот #{row['номер_лота']}</h4>
        <table style="font-size: 13px; line-height: 1.6;">
            <tr><td><b>Адрес:</b></td><td> {row['адрес'][:60]}...</td></tr>
            <tr><td><b>Площадь:</b></td><td> {row['площадь_м²']:.1f} м²</td></tr>
            <tr><td><b>Начальная цена:</b></td><td> {start_price}</td></tr>
            <tr><td><b>Итоговая цена:</b></td><td> {final_price}</td></tr>
            <tr><td><b>Статус:</b></td><td> {row['статус_торга']}</td></tr>
            {participants_text}
            {winner_text}
            <tr><td><b>Превышение:</b></td><td style="color: {'green' if pd.notna(row['превышение_цены_%']) and row['превышение_цены_%'] <= 0 else ('#d97706' if pd.notna(row['превышение_цены_%']) else 'gray')}; font-weight: bold;"> {excess_text}</td></tr>
            <tr><td><b>Этаж:</b></td><td> {row['этаж_норм']}</td></tr>
            <tr><td><b>Как в источнике:</b></td><td> {row['этаж']}</td></tr>
            <tr><td><b>Метро:</b></td><td> {row['метро']}</td></tr>
            <tr><td><b>Округ:</b></td><td> {row['округ_код']}</td></tr>
        </table>
        <hr style="border: 0; border-top: 1px solid #ccc; margin: 6px 0;">
        <table style="font-size: 12px; line-height: 1.5; color: #555;">
            <tr><td><b>Приём заявок:</b></td><td> {row.get('дата_начала_приёма', '—')} — {row.get('дата_окончания_приёма', '—')}</td></tr>
            <tr><td><b>Отбор:</b></td><td> {row.get('дата_отбора_участников', '—')}</td></tr>
            <tr><td><b>Торги:</b></td><td> {row.get('дата_проведения_торгов', '—')}</td></tr>
            <tr><td><b>Итоги:</b></td><td> {row.get('дата_подведения_итогов', '—')}</td></tr>
        </table>
        {'<br><a href="' + str(row['platformLink']) + '" target="_blank" style="color: #1a73e8;">→ Подробнее на roseltorg.ru</a>' if pd.notna(row['platformLink']) else ''}
        {'<br><a href="https://investmoscow.ru/tenders/tender/' + str(row['номер_лота']) + '" target="_blank" style="color: #1a73e8;">→ Подробнее на investmoscow.ru</a>' if pd.notna(row['номер_лота']) else ''}
    </div>
    """

    folium.CircleMarker(
        location=[row["latitude"], row["longitude"]],
        radius=row["radius"],
        color=row["color"],
        fill=True,
        fill_color=row["color"],
        fill_opacity=0.7,
        popup=folium.Popup(popup_html, max_width=350),
        weight=1,
        opacity=0.8,
    ).add_to(m)

# Добавляем маркерный кластер для удобства зума
# (опционально — можно включить если точек слишком много)
# plugins.MarkerCluster().add_to(m)

# Отображаем карту
st_folium(m, width=None, height=650, returned_objects=[])

# ═══════════════════════════════════════════════
#  ЛЕГЕНДА
# ═══════════════════════════════════════════════
st.subheader("Легенда")

col_l1, col_l2 = st.columns(2)

with col_l1:
    st.markdown("**Цвет точки = статус торгов**")
    st.markdown(
        """
        <div style="display: flex; align-items: center; gap: 12px; margin: 8px 0;">
            <span style="display: inline-block; width: 20px; height: 20px; border-radius: 50%; background: #4a4a4a;"></span>
            <span>Отказ победителя</span>
        </div>
        <div style="display: flex; align-items: center; gap: 12px; margin: 8px 0;">
            <span style="display: inline-block; width: 20px; height: 20px; border-radius: 50%; background: #8f8f8f;"></span>
            <span>Не состоялся</span>
        </div>
        <div style="display: flex; align-items: center; gap: 12px; margin: 8px 0;">
            <span style="display: inline-block; width: 20px; height: 20px; border-radius: 50%; background: #2ecc71;"></span>
            <span>0% (стартовая цена)</span>
        </div>
        <div style="display: flex; align-items: center; gap: 12px; margin: 8px 0;">
            <span style="display: inline-block; width: 20px; height: 20px; border-radius: 50%; background: #f1d621;"></span>
            <span>~50% (среднее превышение)</span>
        </div>
        <div style="display: flex; align-items: center; gap: 12px; margin: 8px 0;">
            <span style="display: inline-block; width: 20px; height: 20px; border-radius: 50%; background: #e74c3c;"></span>
            <span>100%+ (высокое превышение)</span>
        </div>
        """,
        unsafe_allow_html=True
    )

with col_l2:
    st.markdown("**Размер точки = площадь помещения**")
    st.markdown(
        """
        <div style="display: flex; align-items: center; gap: 12px; margin: 8px 0;">
            <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: #666;"></span>
            <span>Малая площадь (&lt; 50 м²)</span>
        </div>
        <div style="display: flex; align-items: center; gap: 12px; margin: 8px 0;">
            <span style="display: inline-block; width: 16px; height: 16px; border-radius: 50%; background: #666;"></span>
            <span>Средняя (50–200 м²)</span>
        </div>
        <div style="display: flex; align-items: center; gap: 12px; margin: 8px 0;">
            <span style="display: inline-block; width: 24px; height: 24px; border-radius: 50%; background: #666;"></span>
            <span>Крупная (&gt; 200 м²)</span>
        </div>
        """,
        unsafe_allow_html=True
    )

# ═══════════════════════════════════════════════
#  АНАЛИЗ: превышение vs участники
# ═══════════════════════════════════════════════
st.subheader("Превышение цены от количества участников")

# Загружаем данные об участниках — используем полный кэш, а не ограниченный CSV
if os.path.exists(PROTO_JSON_PATH):
    import json
    with open(PROTO_JSON_PATH, "r", encoding="utf-8") as f:
        cache_data = json.load(f)
    
    # Создаём DataFrame из кэша — там все 2839 записей
    rows = []
    for lot_id, data in cache_data.items():
        row = {"lot_id": int(lot_id)}
        row.update(data)
        rows.append(row)
    df_proto = pd.DataFrame(rows)
elif os.path.exists(PROTO_CSV_PATH):
    df_proto = pd.read_csv(PROTO_CSV_PATH, encoding="utf-8-sig")
    df_proto["lot_id"] = df_proto["lot_id"].astype(int)
else:
    df_proto = None

if df_proto is not None and "participants_count" in df_proto.columns:
    df_proto["lot_id"] = df_proto["lot_id"].astype(int)
    df_proto = df_proto[["lot_id", "participants_count", "winner", "winner_price"]].copy()

    # Используем filtered (там уже есть participants_count из раннего merge)
    # Исключаем лоты с отказом из статистики
    df_merged = filtered[~filtered["исключить_из_ценовой_статистики"]].copy()

    # НЕ меняем participants_count — считаем как есть
    # 0 = реально 0 участников, NaN = нет данных (Нет протокола)
    df_has = df_merged[df_merged["participants_count"].notna()].copy()
    df_has["участники"] = df_has["participants_count"].astype(int)

    # Превышение уже числовое (load_data обработал).
    df_has = df_has[df_has["превышение_цены_%"].notna()].copy()

    if len(df_has) > 0:
        # Преобразуем превышение в числовое для корректной статистики
        def clean_excess(x):
            if pd.isna(x):
                return np.nan
            try:
                return float(str(x).replace('%', ''))
            except:
                return np.nan
        
        df_has['exc_num'] = df_has['превышение_цены_%'].apply(clean_excess)
        
        # Scatter plot — только лоты с участниками > 0
        df_plot = df_has[df_has["участники"] > 0].copy()
        if len(df_plot) > 0:
            fig, ax = plt.subplots(figsize=(12, 5))
            scatter = ax.scatter(
                df_plot["участники"],
                df_plot["exc_num"],
                c=df_plot["exc_num"],
                cmap="RdYlBu_r",
                s=np.clip(df_plot["площадь_м²"] * 0.3, 20, 300),
                alpha=0.7,
                edgecolors="gray",
                linewidth=0.3
            )
            ax.set_xlabel("Количество участников")
            ax.set_ylabel("Превышение цены, %")
            ax.set_title(f"Зависимость превышения цены от количества участников (N={len(df_plot)})")
            cbar = plt.colorbar(scatter, ax=ax)
            cbar.set_label("Превышение, %")
            st.pyplot(fig)
            plt.close()

        # Статистика по диапазонам
        def range_participants(n):
            if n == 0: return "0 участников"
            elif n == 1: return "1 участник"
            elif n == 2: return "2 участника"
            elif n == 3: return "3 участника"
            elif n <= 5: return "4-5 участников"
            elif n <= 10: return "6-10 участников"
            elif n <= 15: return "11-15 участников"
            elif n <= 20: return "16-20 участников"
            else: return "20+ участников"

        df_has["диапазон"] = df_has["участники"].apply(range_participants)
        range_stats = df_has.groupby("диапазон").agg(
            lot_count=("номер_лота", "count"),
            avg_excess=("exc_num", "mean"),
            median_excess=("exc_num", "median"),
            max_excess=("exc_num", "max"),
            success_rate=("exc_num", lambda x: (x >= 0).sum() / len(x) * 100)
        ).reset_index()

        order = ["0 участников", "1 участник", "2 участника", "3 участника", "4-5 участников",
                 "6-10 участников", "11-15 участников", "16-20 участников", "20+ участников", "Нет протокола"]
        range_stats["sort_key"] = range_stats["диапазон"].map({v: i for i, v in enumerate(order)})
        range_stats = range_stats.dropna(subset=["sort_key"]).sort_values("sort_key")

        # Добавляем строку "Нет протокола" для лотов без данных об участниках
        total_lots_in_filter = len(df_merged)
        lots_with_data = len(df_has)
        no_protocol_count = total_lots_in_filter - lots_with_data
        
        if no_protocol_count > 0:
            new_row = pd.DataFrame([{
                "диапазон": "Нет протокола",
                "lot_count": no_protocol_count,
                "avg_excess": None,
                "median_excess": None,
                "max_excess": None,
                "success_rate": None,
                "sort_key": len(order) - 1
            }])
            range_stats = pd.concat([range_stats, new_row], ignore_index=True)

        # Форматирование: прочерки для "0 участников" и "1 участник"
        no_excess_ranges = ["0 участников", "1 участник", "Нет протокола"]
        def fmt_excess(val, range_name):
            if range_name in no_excess_ranges:
                return "—"
            if pd.isna(val):
                return "—"
            if val == 0.0:
                return "0.0%"
            return f"+{val:.1f}%" if val > 0 else "—"

        range_stats["avg_excess"] = range_stats.apply(lambda r: fmt_excess(r["avg_excess"], r["диапазон"]), axis=1)
        range_stats["median_excess"] = range_stats.apply(lambda r: fmt_excess(r["median_excess"], r["диапазон"]), axis=1)
        range_stats["max_excess"] = range_stats.apply(lambda r: fmt_excess(r["max_excess"], r["диапазон"]), axis=1)
        range_stats["success_rate"] = range_stats.apply(
            lambda r: "—" if r["диапазон"] in ["0 участников", "Нет протокола"] else f"{r['success_rate']:.0f}%", axis=1
        )
        range_stats = range_stats.rename(columns={
            "диапазон": "Диапазон",
            "lot_count": "Лотов",
            "avg_excess": "Ср.превыш",
            "median_excess": "Мед.превыш",
            "max_excess": "Макс.превыш",
            "success_rate": "Успешность"
        })

        st.dataframe(
            range_stats[["Диапазон", "Лотов", "Ср.превыш", "Мед.превыш", "Макс.превыш", "Успешность"]],
            use_container_width=True,
            hide_index=True
        )

        # Корреляция
        valid = df_has[(df_has["участники"] > 0) & (df_has["превышение_цены_%"] >= 0)]
        if len(valid) > 1:
            corr = valid[["участники", "превышение_цены_%"]].corr().iloc[0, 1]
            st.caption(f"Корреляция (участники ↔ превышение): r = {corr:.3f}")

    else:
        st.info("Нет данных об участниках для отфильтрованных лотов")
else:
    st.info("Данные об участниках не найдены")

# ═══════════════════════════════════════════════
#  ТАБЛИЦА ДАННЫХ
# ═══════════════════════════════════════════════
st.subheader("Данные")
st.caption(f"Показано {len(filtered)} из {len(df)} записей")

# Кнопка скачивания
csv_data = filtered[["номер_лота", "адрес", "площадь_м²", "начальная_цена_руб",
                      "итоговая_цена_руб", "превышение_цены_%", "этаж_норм", "метро",
                      "округ_код", "статус_торга", "latitude", "longitude"]].to_csv(index=False, encoding="utf-8-sig")
st.download_button(
    label="Скачать CSV",
    data=csv_data,
    file_name="investmoscow_filtered_2022_2026.csv",
    mime="text/csv"
)

# Создаём колонку со ссылкой на investmoscow.ru и форматируем превышение
filtered = filtered.copy()

# Сортируем ПОКА превышение ещё числовое
filtered = filtered.sort_values("превышение_цены_%", ascending=False)

# Форматируем превышение для отображения (после сортировки!)
def fmt_excess(val):
    if pd.isna(val):
        return "Отказ победителя / не состоялся"
    return f"{val:+.1f}%"

filtered["превышение_display"] = filtered["превышение_цены_%"].apply(fmt_excess)

# Для LinkColumn нужен URL
filtered["ссылка_на_лот"] = filtered["url"].fillna("")

# Добавляем колонку с количеством участников
if os.path.exists(PROTO_JSON_PATH):
    import json
    with open(PROTO_JSON_PATH, "r", encoding="utf-8") as f:
        cache_data = json.load(f)
    rows = []
    for lot_id, data in cache_data.items():
        row = {"lot_id": int(lot_id)}
        row.update(data)
        rows.append(row)
    df_proto_full = pd.DataFrame(rows)
elif os.path.exists(PROTO_CSV_PATH):
    df_proto_full = pd.read_csv(PROTO_CSV_PATH, encoding="utf-8-sig")
else:
    df_proto_full = None

if df_proto_full is not None and "participants_count" not in filtered.columns:
    df_proto_full["lot_id"] = df_proto_full["lot_id"].astype(int)
    filtered = filtered.merge(
        df_proto_full[["lot_id", "participants_count"]],
        left_on="номер_лота",
        right_on="lot_id",
        how="left"
    )

if "participants_count" in filtered.columns:
    filtered["участники"] = filtered["participants_count"].apply(
        lambda x: int(x) if pd.notna(x) else None
    )
else:
    filtered["участники"] = None

display_cols = [
    "превышение_display", "участники", "ссылка_на_лот", "номер_лота", "адрес", "площадь_м²",
    "начальная_цена_руб", "итоговая_цена_руб", "этаж_норм", "метро", "округ_код",
    "статус_торга"
]
st.dataframe(
    filtered[display_cols],
    use_container_width=True,
    height=400,
    hide_index=True,
    column_config={
        "превышение_display": "Превышение",
        "участники": "Участники",
        "ссылка_на_лот": st.column_config.LinkColumn("Лот", width="small"),
        "номер_лота": None,
        "lot_id": None,
        "participants_count": None,
    }
)
