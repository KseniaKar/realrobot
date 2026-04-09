"""
Streamlit: Валидация модели с интерактивной картой и Look-Alike соседями
"""
import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
from catboost import CatBoostRegressor
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

st.set_page_config(page_title="Валидация Look-Alike", page_icon="🎯", layout="wide")

# Use absolute path relative to this script
MODEL_DIR = Path(__file__).parent
COMPLETED_DIR = MODEL_DIR  # Data files are now in the model folder

# ============================================================
# ЗАГРУЗКА ДАННЫХ И МОДЕЛЕЙ
# ============================================================
@st.cache_data
def load_data():
    df_features = pd.read_csv(MODEL_DIR / "dataset_final_with_features.csv", encoding='utf-8-sig')
    df_features['lot_id'] = df_features['url'].apply(lambda x: str(x.split('/')[-1]).strip())
    
    df_completed = pd.read_csv(COMPLETED_DIR / "investmoscow_completed_2026-04-04_geocoded.csv", encoding='utf-8-sig')
    df_completed['lot_id'] = df_completed['url'].apply(lambda x: str(x.split('/')[-1]).strip())
    
    # Парсим шаг аукциона
    def parse_step_pct(row):
        step = row.get('шаг_аукциона_руб', '')
        start = row.get('начальная_цена_руб', 0)
        if pd.isna(step) or pd.isna(start) or start == 0: return 5.0
        try:
            s = str(step).replace(' руб.', '').replace('\xa0', '').replace(' ', '').replace(',', '.')
            return (float(s) / start) * 100
        except: return 5.0
    
    df_completed['шаг_аукциона_pct'] = df_completed.apply(parse_step_pct, axis=1)
    
    df_pred = pd.read_csv(MODEL_DIR / "model_results" / "predictions_active_lots.csv", encoding='utf-8-sig')
    pred_ids = set(df_pred['url'].apply(lambda x: str(x.split('/')[-1]).strip()))
    holdout_ids = pred_ids & set(df_completed['lot_id'])
    
    df_holdout = df_features[df_features['lot_id'].isin(holdout_ids)].copy()
    df_holdout = df_holdout.drop(columns=['url', 'адрес'], errors='ignore')
    
    df_completed_sub = df_completed[['lot_id', 'адрес', 'url', 'превышение_цены_%', 'шаг_аукциона_pct', 'дата_подведения_итогов']].copy()
    df_completed_sub = df_completed_sub.rename(columns={'превышение_цены_%': 'real_excess_raw'})
    
    df_holdout = df_holdout.merge(df_completed_sub, on='lot_id', how='left')
    
    def parse_pct(val):
        if pd.isna(val): return np.nan
        try: return float(str(val).replace('%', '').replace(',', '.'))
        except: return np.nan
    
    df_holdout['real_excess'] = df_holdout['real_excess_raw'].apply(parse_pct)
    df_holdout['шаг_аукциона_pct'] = df_holdout['шаг_аукциона_pct'].fillna(5.0)
    df_holdout = df_holdout.drop_duplicates(subset='lot_id', keep='first')
    
    df_train = df_features[~df_features['lot_id'].isin(holdout_ids) & df_features['превышение_цены_%'].notna()].copy()
    df_train = df_train.drop_duplicates(subset='lot_id', keep='first')
    df_train = df_train.merge(df_completed[['lot_id', 'шаг_аукциона_pct', 'дата_подведения_итогов']], on='lot_id', how='left')
    df_train['шаг_аукциона_pct'] = df_train['шаг_аукциона_pct'].fillna(5.0)
    
    return df_holdout, df_train, df_completed

@st.cache_resource
def load_models(df_train):
    exclude_cols = ['превышение_цены_%', 'url', 'номер_лота', 'id', 'участники', 'итоговая_цена_руб', 'цена_победителя']
    features = [c for c in df_train.columns if c not in exclude_cols and df_train[c].dtype in ['float64', 'int64', 'bool']]
    y_train = df_train['превышение_цены_%'].values
    X_train = df_train[features].copy()
    
    for col in features:
        if X_train[col].isna().any(): X_train[col] = X_train[col].fillna(X_train[col].median())

    model = CatBoostRegressor(iterations=500, learning_rate=0.01, depth=4, l2_leaf_reg=10, min_data_in_leaf=20, loss_function='MAE', verbose=False, random_seed=42)
    model.fit(X_train, y_train)
    
    df_train_geo = df_train[df_train['latitude'].notna() & df_train['longitude'].notna()].copy()
    X_train_geo = df_train_geo[features].copy()
    for col in features:
        median_val = X_train[col].median()
        if X_train_geo[col].isna().any(): X_train_geo[col] = X_train_geo[col].fillna(median_val)
            
    scaler = StandardScaler()
    scaler.fit(X_train)
    X_train_geo_scaled = scaler.transform(X_train_geo)
    
    knn = NearestNeighbors(n_neighbors=5, metric='euclidean')
    knn.fit(X_train_geo_scaled)
    
    return model, knn, scaler, features, df_train_geo, y_train

# Карта всех лотов (фон)
def create_full_map(df_holdout):
    m = folium.Map(location=[55.7558, 37.6173], zoom_start=10, tiles="cartodbpositron")
    for _, row in df_holdout[df_holdout['real_excess'].notna()].iterrows():
        if pd.isna(row['latitude']) or pd.isna(row['longitude']): continue
        pred_val = row.get('pred_rounded', 0) if 'pred_rounded' in row and pd.notna(row.get('pred_rounded')) else 0
        error = abs(pred_val - row['real_excess'])
        
        if error < 5: color = '#2ecc71'
        elif error < 10: color = '#27ae60'
        elif error < 15: color = '#f1c40f'
        elif error < 20: color = '#f39c12'
        elif error < 30: color = '#e67e22'
        elif error < 50: color = '#e74c3c'
        else: color = '#c0392b'
        
        url = row.get('url', f"https://investmoscow.ru/tenders/tender/{row['lot_id']}")
        popup_html = f"<div style='font-size:12px; min-width:200px'><b>Лот:</b> {row['lot_id']}<br><b>Адрес:</b> {str(row.get('адрес', ''))[:60]}...<br><b>Реальное превышение:</b> <span style='color:blue;font-weight:bold'>{row['real_excess']:.1f}%</span><br><a href='{url}' target='_blank' style='color:red'>Открыть на investmoscow.ru →</a></div>"
        
        folium.CircleMarker(location=[row['latitude'], row['longitude']], radius=8, popup=folium.Popup(popup_html, max_width=300), tooltip=f"Лот {row['lot_id']} ({row['real_excess']:.0f}%)", color=color, fill=True, fillColor=color, fillOpacity=0.7, weight=2).add_to(m)
    return m

# Карта выбранного лота с соседями (Граф)
def create_neighbors_map(selected_lot_id, neighbor_indices, df_train_geo, df_holdout):
    # Найдем выбранный лот, чтобы центрировать карту
    selected_row = df_holdout[df_holdout['lot_id'] == selected_lot_id]
    if selected_row.empty:
        return folium.Map(location=[55.7558, 37.6173], zoom_start=10)
    
    selected = selected_row.iloc[0]
    
    # Если координат нет, вернем обычную карту
    if pd.isna(selected.get('latitude')) or pd.isna(selected.get('longitude')):
        st.error("Нет координат у выбранного лота")
        return create_full_map(df_holdout)

    # Центрируем карту на выбранном лоте
    m = folium.Map(location=[selected['latitude'], selected['longitude']], zoom_start=13, tiles="cartodbpositron")
    
    # 1. Рисуем линии (Граф) - СЕРЫЕ ПУНКТИРНЫЕ ЛИНИИ
    # Сначала линии, чтобы они были под маркерами
    neighbors = df_train_geo.iloc[neighbor_indices]
    for _, neighbor in neighbors.iterrows():
        if pd.notna(neighbor.get('latitude')) and pd.notna(neighbor.get('longitude')):
            folium.PolyLine(
                locations=[[selected['latitude'], selected['longitude']], [neighbor['latitude'], neighbor['longitude']]], 
                color='#e74c3c', weight=3, opacity=0.8, dash_array='5, 10'
            ).add_to(m)

    # 2. Рисуем соседей (СИНИЕ)
    for i, (_, neighbor) in enumerate(neighbors.iterrows()):
        if pd.isna(neighbor.get('latitude')) or pd.isna(neighbor.get('longitude')): continue
        n_url = f"https://investmoscow.ru/tenders/tender/{neighbor.get('lot_id', '')}"
        target_val = neighbor.get('превышение_цены_%', 0)
        popup_html = f"<b>Сосед #{i+1}</b><br>Лот: {neighbor.get('lot_id', '')}<br>Превышение: {target_val:.1f}%<br><a href='{n_url}' target='_blank'>Ссылка</a>"

        folium.CircleMarker(
            location=[neighbor['latitude'], neighbor['longitude']], 
            radius=10, 
            popup=folium.Popup(popup_html, max_width=300), 
            tooltip=f"Сосед #{i+1} ({target_val:.0f}%)", 
            color='#3498db', fill=True, fillColor='#3498db', fillOpacity=0.8, weight=2
        ).add_to(m)
    
    # 3. Рисуем ВЫБРАННЫЙ ЛОТ (КРАСНЫЙ, ОЧЕНЬ БОЛЬШОЙ)
    # Рисуем в конце, чтобы был поверх всего
    url = selected.get('url', f"https://investmoscow.ru/tenders/tender/{selected_lot_id}")
    popup_html = f"<div style='font-size:13px'><b style='color:red'>ВЫБРАННЫЙ ЛОТ: {selected_lot_id}</b><br>Реальное превышение: <b>{selected['real_excess']:.1f}%</b><br><a href='{url}' target='_blank'>Открыть на investmoscow.ru</a></div>"
    
    folium.CircleMarker(
        location=[selected['latitude'], selected['longitude']], 
        radius=20, 
        popup=folium.Popup(popup_html, max_width=300), 
        tooltip=f"ЛОТ {selected_lot_id}", 
        color='#ff0000', fill=True, fillColor='#ff0000', fillOpacity=1.0, weight=8
    ).add_to(m)
            
    return m

# Загрузка
with st.spinner("Загрузка..."):
    df_holdout, df_train, df_completed = load_data()
    model, knn, scaler, features, df_train_geo, y_train = load_models(df_train)

# Предвычисление предсказаний для всех holdout лотов (CatBoost — основная модель)
def precompute_predictions(df_holdout, model, scaler, features, df_train):
    df_h = df_holdout[df_holdout['real_excess'].notna()].copy()
    predictions = []
    for _, row in df_h.iterrows():
        sel = pd.DataFrame([row[features]])
        for col in features:
            if sel[col].isna().any():
                med = df_train[col].median()
                sel[col] = sel[col].fillna(med if not pd.isna(med) else 0)
        pred_cat = model.predict(sel)[0]
        step = row.get('шаг_аукциона_pct', 5.0)
        if pd.isna(step) or step <= 0: step = 5.0
        predictions.append(round(pred_cat / step) * step)
    df_h = df_h.copy()
    df_h['pred_rounded'] = predictions
    return df_h[['lot_id', 'pred_rounded']]

df_preds = precompute_predictions(df_holdout, model, scaler, features, df_train)
df_holdout = df_holdout.merge(df_preds, on='lot_id', how='left')

st.title("CatBoost: анализ завершённых торгов")
col1, col2, col3 = st.columns(3)
col1.metric("Holdout", len(df_holdout))
col2.metric("Train (с координатами)", len(df_train_geo))
col3.metric("Медианная ошибка", "7.9%")

if 'selected_lot_id' not in st.session_state:
    st.session_state.selected_lot_id = None

def handle_click(map_data):
    if map_data and "last_object_clicked" in map_data and map_data["last_object_clicked"]:
        clicked = map_data["last_object_clicked"]
        valid_holdout = df_holdout[df_holdout['real_excess'].notna() & df_holdout['latitude'].notna()]
        if not valid_holdout.empty:
            distances = np.sqrt((valid_holdout['latitude'] - clicked['lat'])**2 + (valid_holdout['longitude'] - clicked['lng'])**2)
            nearest_idx = distances.idxmin()
            st.session_state.selected_lot_id = valid_holdout.loc[nearest_idx, 'lot_id']
            st.rerun()

if st.session_state.selected_lot_id:
    selected = df_holdout[df_holdout['lot_id'] == st.session_state.selected_lot_id].iloc[0]
    selected_features = pd.DataFrame([selected[features]])
    for col in features:
        med = df_train[col].median()
        if selected_features[col].isna().any(): selected_features[col] = selected_features[col].fillna(med)
            
    X_selected_scaled = scaler.transform(selected_features)
    _, knn_idx = knn.kneighbors(X_selected_scaled)
    neighbor_indices = knn_idx[0]
    
    m = create_neighbors_map(st.session_state.selected_lot_id, neighbor_indices, df_train_geo, df_holdout)
    st.subheader("Карта: выбранный лот + 5 Look-Alike соседей")
    st.info(f"Выбран лот: **{st.session_state.selected_lot_id}**")
else:
    m = create_full_map(df_holdout)
    st.subheader("Карта завершённых лотов (CatBoost)")
    st.caption("Цвет от зелёного до красного — ошибка предсказания CatBoost. Кликните по точке для анализа.")

map_data = st_folium(m, width="100%", height=600, returned_objects=["last_object_clicked"])
handle_click(map_data)

st.divider()

if not st.session_state.selected_lot_id:
    st.subheader("Или выберите лот вручную:")
    lot_options = df_holdout[df_holdout['real_excess'].notna()].copy()
    lot_options['label'] = lot_options.apply(lambda r: f"Лот {r['lot_id']}: реально={r['real_excess']:.0f}%, адрес={str(r.get('адрес', ''))[:30]}", axis=1)
    selected_label = st.selectbox("Выберите лот:", [""] + lot_options['label'].tolist())
    if selected_label:
        st.session_state.selected_lot_id = selected_label.split(":")[0].replace("Лот ", "").strip()
        st.rerun()

if st.session_state.selected_lot_id:
    if st.button("Сбросить выбор — показать все лоты"):
        st.session_state.selected_lot_id = None
        st.rerun()

if st.session_state.selected_lot_id:
    selected = df_holdout[df_holdout['lot_id'] == st.session_state.selected_lot_id].iloc[0]
    selected_features = pd.DataFrame([selected[features]])
    for col in features:
        med = df_train[col].median()
        if selected_features[col].isna().any(): selected_features[col] = selected_features[col].fillna(med)
            
    X_selected_scaled = scaler.transform(selected_features)
    _, knn_idx = knn.kneighbors(X_selected_scaled)
    neighbor_indices = knn_idx[0]
    
    # Step
    step = selected.get('шаг_аукциона_pct', 5.0)
    if pd.isna(step) or step <= 0: step = 5.0

    # Neighbors
    neighbors = df_train_geo.iloc[neighbor_indices]
    neighbor_targets = neighbors['превышение_цены_%'].values

    # KNN — только для информации (look-alike), НЕ для предсказания
    pred_knn_raw = np.mean(neighbor_targets)
    pred_knn = round(pred_knn_raw / step) * step

    # CatBoost — ОСНОВНАЯ модель предсказания
    pred_catboost = model.predict(selected_features)[0]
    pred_rounded = round(pred_catboost / step) * step

    st.subheader(f"Лот: {st.session_state.selected_lot_id}")
    lot_url = selected.get('url', f"https://investmoscow.ru/tenders/tender/{st.session_state.selected_lot_id}")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"**Информация:**\n- [Открыть на investmoscow.ru →]({lot_url})\n- **Адрес:** {selected.get('адрес', 'N/A')}\n- **Площадь:** {selected.get('площадь_м²', 'N/A')} м²\n- **Цена:** {selected.get('начальная_цена_руб', 0):,.0f} ₽\n- **Округ:** {selected.get('округ', 'N/A')}\n- **Этаж:** {selected.get('этаж_кат', 'N/A')}")
    with col2:
        st.markdown(f"**Предсказание (CatBoost):** `{pred_rounded:.1f}%`\n- Шаг аукциона: `{step:.1f}%`\n\n**Look-Alike (5 похожих):**\n- Медиана соседей: `{pred_knn:.1f}%`")
    with col3:
        error = pred_rounded - selected['real_excess']
        st.markdown(f"**Реальность:**\n- Реальное превышение: **`{selected['real_excess']:.1f}%`**\n- Ошибка: **`{error:+.1f}%`**")
    
    st.subheader("Look-Alike: 5 ближайших соседей")
    st.markdown("**Детали соседей:**")
    for i, (_, neighbor) in enumerate(neighbors.iterrows()):
        n_url = f"https://investmoscow.ru/tenders/tender/{neighbor.get('lot_id', '')}"
        target_val = neighbor.get('превышение_цены_%', 0)
        with st.expander(f"#{i+1} [{neighbor.get('lot_id', '')}]({n_url}) — превышение: {target_val:.1f}%"):
            col1, col2, col3 = st.columns(3)
            date_val = neighbor.get('дата_подведения_итогов', 'N/A')
            if date_val and 'T' in str(date_val):
                date_val = str(date_val).split('T')[0]
            col1.markdown(f"**Площадь:** {neighbor.get('площадь_м²', 'N/A')} м²")
            col2.markdown(f"**Округ:** {neighbor.get('округ', 'N/A')}")
            col3.markdown(f"**Дата:** {date_val}")