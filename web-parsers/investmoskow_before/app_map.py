"""
Streamlit-приложение для визуализации торгов investmoscow.ru на карте
"""
import streamlit as st
import pandas as pd
import folium
from folium import plugins
import numpy as np
from streamlit_folium import st_folium
import io
import base64
import os

# Определяем базовую директорию (где лежит app_map.py)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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
@st.cache_data
def load_data():
    csv_path = os.path.join(BASE_DIR, "data", "investmoscow_completed_2026-04-04_geocoded.csv")
    if not os.path.exists(csv_path):
        st.error(f"Файл не найден: {csv_path}")
        st.error(f"BASE_DIR: {BASE_DIR}")
        st.error(f"Содержимое директории: {os.listdir(BASE_DIR)}")
        if os.path.exists(os.path.join(BASE_DIR, "data")):
            st.error(f"Содержимое data/: {os.listdir(os.path.join(BASE_DIR, 'data'))}")
        st.stop()
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    # Убираем строки без координат
    df = df.dropna(subset=["latitude", "longitude"])

    # Превышение: "95.0%" → 95.0, NaN → -1
    if "превышение_цены_%" in df.columns:
        df["превышение_цены_%"] = (
            df["превышение_цены_%"]
            .astype(str)
            .str.replace("%", "", regex=False)
            .str.strip()
        )
        df["превышение_цены_%"] = pd.to_numeric(df["превышение_цены_%"], errors="coerce").fillna(-1)

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

    return df

df = load_data()

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

# ── Определение статуса ──
def get_status(row):
    if row["превышение_цены_%"] < 0:
        return "Не состоялся"
    return "Состоялся"

df["статус_торга"] = df.apply(get_status, axis=1)

# ── Цветовая функция ──
def get_color(row):
    """Серый для несостоявшихся, 0% = зелёный, >0% = жёлтый→красный"""
    if row["статус_торга"] == "Не состоялся":
        return "#4a4a4a"  # тёмно-серый

    pct = row["превышение_цены_%"]
    # 0% = зелёный
    if pct <= 0:
        return "#2ecc71"

    # Любое превышение > 0: жёлтый (малое) → красный (большое)
    # Нормализация: 0-200% → 0-1
    norm = min(pct / 200.0, 1.0)
    # Жёлтый (241,214,33) → Красный (231,76,60)
    r = int(241 + (231 - 241) * norm)
    g = int(214 + (76 - 214) * norm)
    b = int(33 + (60 - 33) * norm)
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
status_options = ["Все", "Состоялся", "Не состоялся"]
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
max_exc = max(float(df["превышение_цены_%"].max()), 0.0)  # минимум 0 чтобы избежать -1 == -1
excess_range = st.sidebar.slider(
    "Превышение цены, %",
    min_value=-1.0,
    max_value=max_exc,
    value=(-1.0, max_exc),
    step=1.0
)

# Этаж
all_floors = sorted(df["этаж"].dropna().unique())
floor_labels = {
    "1": "1 этаж",
    "2": "2 этаж",
    "Подвал": "Подвал",
    "Цоколь": "Цоколь",
}
selected_floors = st.sidebar.multiselect(
    "Этаж",
    options=all_floors,
    default=all_floors,
    format_func=lambda x: floor_labels.get(str(x), str(x))
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
    (filtered["превышение_цены_%"] >= excess_range[0]) &
    (filtered["превышение_цены_%"] <= excess_range[1])
]

if selected_floors != all_floors:
    filtered = filtered[filtered["этаж"].isin(selected_floors)]

# ═══════════════════════════════════════════════
#  ОСНОВНОЙ ЭКРАН
# ═══════════════════════════════════════════════
st.title("Карта торгов investmoscow.ru")
st.caption("Нежилые помещения, торги 2025–2026")

# Статистика
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Всего лотов", len(filtered))
with col2:
    n_successful = len(filtered[filtered["статус_торга"] == "Состоялся"])
    st.metric("Состоялись", n_successful)
with col3:
    n_failed = len(filtered[filtered["статус_торга"] == "Не состоялся"])
    st.metric("Не состоялись", n_failed)
with col4:
    if n_successful > 0:
        avg_excess = filtered[filtered["превышение_цены_%"] >= 0]["превышение_цены_%"].mean()
        st.metric("Ср. превышение", f"+{avg_excess:.1f}%")
    else:
        st.metric("Ср. превышение", "—")
with col5:
    if n_successful > 0:
        avg_price_m2 = filtered[filtered["итоговая_цена_руб"].notna()]["цена_за_м²"].mean()
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

    # Popup
    excess_text = f"+{row['превышение_цены_%']:.1f}%" if row["превышение_цены_%"] >= 0 else "Не состоялся"
    final_price = f"{row['итоговая_цена_руб']/1e6:.1f} млн ₽" if pd.notna(row["итоговая_цена_руб"]) else "—"
    start_price = f"{row['начальная_цена_руб']/1e6:.1f} млн ₽"

    popup_html = f"""
    <div style="font-family: Arial, sans-serif; min-width: 220px;">
        <h4 style="margin: 0 0 8px; color: #333;">Лот #{row['номер_лота']}</h4>
        <table style="font-size: 13px; line-height: 1.6;">
            <tr><td><b>Адрес:</b></td><td> {row['адрес'][:80]}...</td></tr>
            <tr><td><b>Площадь:</b></td><td> {row['площадь_м²']:.1f} м²</td></tr>
            <tr><td><b>Начальная цена:</b></td><td> {start_price}</td></tr>
            <tr><td><b>Итоговая цена:</b></td><td> {final_price}</td></tr>
            <tr><td><b>Превышение:</b></td><td style="color: {'green' if row['превышение_цены_%'] >= 0 else 'gray'}; font-weight: bold;"> {excess_text}</td></tr>
            <tr><td><b>Этаж:</b></td><td> {row['этаж']}</td></tr>
            <tr><td><b>Метро:</b></td><td> {row['метро']}</td></tr>
            <tr><td><b>Округ:</b></td><td> {row['округ_код']}</td></tr>
        </table>
        {'<br><a href="' + str(row['platformLink']) + '" target="_blank" style="color: #1a73e8;">→ Подробнее на roseltorg.ru</a>' if pd.notna(row['platformLink']) else ''}
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
    st.markdown("**Цвет точки = превышение цены**")
    st.markdown(
        """
        <div style="display: flex; align-items: center; gap: 12px; margin: 8px 0;">
            <span style="display: inline-block; width: 20px; height: 20px; border-radius: 50%; background: #4a4a4a;"></span>
            <span>Торг не состоялся</span>
        </div>
        <div style="display: flex; align-items: center; gap: 12px; margin: 8px 0;">
            <span style="display: inline-block; width: 20px; height: 20px; border-radius: 50%; background: #2ecc71;"></span>
            <span>0% (без превышения)</span>
        </div>
        <div style="display: flex; align-items: center; gap: 12px; margin: 8px 0;">
            <span style="display: inline-block; width: 20px; height: 20px; border-radius: 50%; background: #f1d621;"></span>
            <span>~50% (небольшое превышение)</span>
        </div>
        <div style="display: flex; align-items: center; gap: 12px; margin: 8px 0;">
            <span style="display: inline-block; width: 20px; height: 20px; border-radius: 50%; background: #e74c3c;"></span>
            <span>200%+ (высокое превышение)</span>
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
#  ТАБЛИЦА ДАННЫХ
# ═══════════════════════════════════════════════
st.subheader("Данные")
st.caption(f"Показано {len(filtered)} из {len(df)} записей")

# Кнопка скачивания
csv_data = filtered[["номер_лота", "адрес", "площадь_м²", "начальная_цена_руб",
                      "итоговая_цена_руб", "превышение_цены_%", "этаж", "метро",
                      "округ_код", "статус_торга", "latitude", "longitude"]].to_csv(index=False, encoding="utf-8-sig")
st.download_button(
    label="Скачать CSV",
    data=csv_data,
    file_name="investmoscow_filtered.csv",
    mime="text/csv"
)

# Создаём колонку со ссылкой на investmoscow.ru и форматируем превышение
filtered = filtered.copy()

# Сортируем ПОКА превышение ещё числовое
filtered = filtered.sort_values("превышение_цены_%", ascending=False)

# Форматируем превышение для отображения (после сортировки!)
def fmt_excess(val):
    if val < 0:
        return "Не состоялся"
    return f"+{val:.1f}%"

filtered["превышение_display"] = filtered["превышение_цены_%"].apply(fmt_excess)

# Для LinkColumn нужен URL
filtered["ссылка_на_лот"] = filtered["url"].fillna("")

display_cols = [
    "превышение_display", "ссылка_на_лот", "номер_лота", "адрес", "площадь_м²",
    "начальная_цена_руб", "итоговая_цена_руб", "этаж", "метро", "округ_код",
    "статус_торга"
]
st.dataframe(
    filtered[display_cols],
    use_container_width=True,
    height=400,
    hide_index=True,
    column_config={
        "превышение_display": "Превышение",
        "ссылка_на_лот": st.column_config.LinkColumn("Лот", width="small"),
        "номер_лота": None,
    }
)
