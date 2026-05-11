"""
Hedonic model v2: обучение на новом sale.csv (16k строк)
Территориальная медиана учитывает тип входа когда он известен.
BallTree для быстрого подсчёта квартир в радиусе.
"""
import json
import re
import sys
import zipfile
import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree
from xgboost import XGBRegressor

sys.stdout.reconfigure(encoding='utf-8')

R_EARTH = 6_371_000.0

SALE_CSV       = 'C:/git/realrobot/look_a_like_prices/data/sale_dedup.csv'
ARENDA_CSV     = 'C:/git/realrobot/look_a_like_prices/data/arenda_dedup.csv'
ENTRANCE       = 'C:/git/realrobot/look_a_like_prices/_entrance_results.csv'
BUILDINGS      = 'C:/git/realrobot/look_a_like_prices/data/buildings_moscow.parquet'
VESTIBULE_ZIP  = 'C:/git/realrobot/look_a_like_prices/data/metro/624CSV.zip'
PASSENGERS_ZIP = 'C:/git/realrobot/look_a_like_prices/data/metro/62743CSV.zip'
MODEL_DIR      = 'C:/git/realrobot/look_a_like_prices/data'

NORM_ENTRANCE = {
    # Яндекс (русские значения без направления)
    'отдельный':         'отдельный',
    'общий':             'общий',
    # Яндекс и ЦИАН (с направлением)
    'отдельный с улицы': 'отдельный с улицы', 'separateFromTheStreet': 'отдельный с улицы',
    'separateFromStreet': 'отдельный с улицы',
    'отдельный со двора': 'отдельный со двора', 'separateFromTheYard': 'отдельный со двора',
    'separateFromYard':  'отдельный со двора',
    'общий с улицы':     'общий с улицы',
    'commonFromStreet':  'общий с улицы', 'commonFromTheStreet': 'общий с улицы',
    'общий со двора':    'общий со двора',
    'commonFromYard':    'общий со двора', 'commonFromTheYard': 'общий со двора',
    'через подъезд':     'через подъезд', 'throughEntrance': 'через подъезд',
    'через холл':        'через холл',    'throughHall':     'через холл',
}

def _parse_param(s, key):
    if not isinstance(s, str): return None
    m = re.search(rf'{re.escape(key)}=([^|]+)', s)
    return m.group(1).strip() if m else None

def _get_area(row):
    val = _parse_param(row['Доп.параметры'], 'Общая площадь')
    if val:
        try: return float(val.replace(',', '.'))
        except: pass
    m = re.search(r'\((\d+[\.,]?\d*)\s*м', str(row['Название']))
    if m:
        try: return float(m.group(1).replace(',', '.'))
        except: pass
    return None

def normalize_floor(s):
    if not isinstance(s, str): return None
    s = s.strip().lower()
    if s in ('цокольный','цоколь','подвальный','подвал'): return 'цоколь'
    try:
        n = int(s)
        if n <= 0: return 'цоколь'
        return '1' if n == 1 else ('2' if n == 2 else '3+')
    except: pass
    return s

def haversine_vec(lat1, lon1, lats, lons):
    R = 6_371_000
    phi1 = np.radians(lat1)
    phi2 = np.radians(lats)
    dphi = np.radians(lats - lat1)
    dlam = np.radians(lons - lon1)
    a = np.sin(dphi/2)**2 + np.cos(phi1)*np.cos(phi2)*np.sin(dlam/2)**2
    return R * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))

# ── загрузка ───────────────────────────────────────────────────────────────────
print('Загружаем sale.csv...')
df = pd.read_csv(SALE_CSV, sep=';')
df['площадь'] = df.apply(_get_area, axis=1)
df['цена'] = pd.to_numeric(df['Цена'], errors='coerce')
df['цена_за_м2'] = np.where(df['площадь'].fillna(0) > 0, df['цена'] / df['площадь'], np.nan)
df['этаж_норм']        = df['Доп.параметры'].apply(lambda x: _parse_param(x, 'Этаж')).apply(normalize_floor)
df['этажность_здания'] = pd.to_numeric(df['Доп.параметры'].apply(lambda x: _parse_param(x, 'Этажность здания')), errors='coerce')
df['lat'] = pd.to_numeric(df['lat'], errors='coerce')
df['lng'] = pd.to_numeric(df['lng'], errors='coerce')
df['вид'] = df['Доп.параметры'].apply(lambda x: _parse_param(x, 'Вид объекта'))
df = df.dropna(subset=['lat','lng','цена','площадь','цена_за_м2']).reset_index(drop=True)
# убираем выбросы по цене/м²
df = df[(df['цена_за_м2'] >= 50_000) & (df['цена_за_м2'] <= 3_000_000)].copy()
# убираем нерелевантные типы (здания, земля, склады — другая ценовая логика)
exclude_vid = {'Здание', 'Коммерческая земля', 'Складское помещение', 'Производственное помещение', 'Гостиница'}
df = df[~df['вид'].isin(exclude_vid)].copy().reset_index(drop=True)
print(f'  После очистки: {len(df)} строк')
print(f'  Вид объекта: {df["вид"].value_counts().to_dict()}')

# ── вестибюли метро + пассажиропоток ─────────────────────────────────────────
print('\nЗагружаем вестибюли и пассажиропоток...')
with zipfile.ZipFile(VESTIBULE_ZIP) as zf:
    with zf.open('data-624-15-04-2026.csv') as f:
        vest_df = pd.read_csv(f, encoding='utf-8-sig', sep=None, engine='python')
vest_df = vest_df.iloc[1:].reset_index(drop=True)
vest_df['lat_m'] = pd.to_numeric(vest_df['Latitude in WGS-84'],  errors='coerce')
vest_df['lng_m'] = pd.to_numeric(vest_df['Longitude in WGS-84'], errors='coerce')
vest_df['metro_ticket_machines'] = pd.to_numeric(vest_df['Ticket machines amount'], errors='coerce').fillna(3.0)
vest_df['metro_vest_type'] = vest_df['Vestibule type'].map({
    'подземный': 2.0, 'наземный отдельностоящий': 1.0, 'наземный, встроенный в здание': 0.0,
}).fillna(1.0)
vest_df = vest_df.dropna(subset=['lat_m', 'lng_m']).reset_index(drop=True)

with zipfile.ZipFile(PASSENGERS_ZIP) as zf:
    with zf.open('data-62743-24-04-2026.csv') as f:
        pass_df = pd.read_csv(f, encoding='utf-8-sig', sep=None, engine='python')
pass_df = pass_df.iloc[1:].copy()
pass_df.columns = ['station', 'line', 'year', 'quarter', 'incoming', 'outgoing', 'gid']
pass_df['incoming'] = pd.to_numeric(pass_df['incoming'], errors='coerce')
pass_df['outgoing'] = pd.to_numeric(pass_df['outgoing'], errors='coerce')
pass_df['total'] = pass_df['incoming'].fillna(0) + pass_df['outgoing'].fillna(0)
pass_2024 = pass_df[pass_df['year'] == '2024'].groupby('station')['total'].sum()
median_pass = float(pass_2024.median())
station_passengers = pass_2024.to_dict()

metro_tree = BallTree(np.radians(vest_df[['lat_m', 'lng_m']].values), metric='haversine')
q_metro = np.radians(df[['lat', 'lng']].values)
dist_m, idx_m = metro_tree.query(q_metro, k=1)
idx_near = idx_m.flatten()

df['до_метро'] = dist_m.flatten() * R_EARTH / 1000
df['metro_vest_type'] = vest_df['metro_vest_type'].values[idx_near]
df['metro_ticket_machines'] = vest_df['metro_ticket_machines'].values[idx_near]
nearest_stations = vest_df['Metro station name'].values[idx_near]
df['metro_passengers_annual'] = [station_passengers.get(s, median_pass) for s in nearest_stations]
print(f'  Вестибюлей: {len(vest_df)} | Медиана до_метро: {df["до_метро"].median():.3f} км')
print(f'  Пассажиропоток 2024: {len(station_passengers)} станций | Медиана: {median_pass/1e6:.1f}М')

# тип входа — джойним старые спарсенные данные
entrance = pd.read_csv(ENTRANCE, encoding='utf-8-sig')
entrance['тип_входа'] = entrance['тип_входа_циан'].map(NORM_ENTRANCE)
df = df.merge(entrance[['URL','тип_входа']], on='URL', how='left')
n_with = df['тип_входа'].notna().sum()
print(f'  Тип входа: {n_with}/{len(df)} ({n_with/len(df)*100:.0f}%)')

# ── BallTree для квартир в радиусе ─────────────────────────────────────────────
print('\nСтроим BallTree по зданиям...')
bld = pd.read_parquet(BUILDINGS, columns=['lat','lng','apt_living'])
b_coords = np.radians(bld[['lat','lng']].values)
b_apts = bld['apt_living'].values
tree = BallTree(b_coords, metric='haversine')

print('Считаем квартиры в 400м/800м...')
q_coords = np.radians(df[['lat','lng']].values)

idx_400 = tree.query_radius(q_coords, r=400/R_EARTH)
idx_800 = tree.query_radius(q_coords, r=800/R_EARTH)

df['apt_400'] = [int(b_apts[i].sum()) for i in idx_400]
df['apt_800'] = [int(b_apts[i].sum()) for i in idx_800]
print(f'  Медиана apt_400: {df["apt_400"].median():.0f}, apt_800: {df["apt_800"].median():.0f}')

# ── медиана аренды в 700м как признак ─────────────────────────────────────────
print('\nЗагружаем данные аренды для признака median_rent_700m...')
rent = pd.read_csv(ARENDA_CSV, sep=';', encoding='utf-8-sig')
rent['площадь_r'] = rent.apply(_get_area, axis=1)
rent['цена_r']    = pd.to_numeric(rent['Цена'], errors='coerce')
rent['pm2_мес']   = np.where(rent['площадь_r'].fillna(0) > 0, rent['цена_r'] / rent['площадь_r'], np.nan)
rent['lat_r']     = pd.to_numeric(rent['lat'], errors='coerce')
rent['lng_r']     = pd.to_numeric(rent['lng'], errors='coerce')
rent['вид_r']     = rent['Доп.параметры'].apply(lambda x: _parse_param(x, 'Вид объекта'))
rent = rent[~rent['вид_r'].isin(exclude_vid)].copy()
rent = rent.dropna(subset=['lat_r','lng_r','pm2_мес'])
rent = rent[(rent['pm2_мес'] >= 200) & (rent['pm2_мес'] <= 100_000) & (rent['площадь_r'] >= 15)]
rent = rent.reset_index(drop=True)
print(f'  Аренда: {len(rent)} объявлений')

r_coords  = np.radians(rent[['lat_r','lng_r']].values)
r_pm2     = rent['pm2_мес'].values
rent_tree = BallTree(r_coords, metric='haversine')

print('Считаем медиану аренды в 700м/1500м и кол-во объявлений...')
idx_rent_700  = rent_tree.query_radius(q_coords, r= 700/R_EARTH)
idx_rent_1500 = rent_tree.query_radius(q_coords, r=1500/R_EARTH)

df['median_rent_700m']  = [float(np.median(r_pm2[i])) if len(i) >= 2 else np.nan for i in idx_rent_700]
df['median_rent_1500m'] = [float(np.median(r_pm2[i])) if len(i) >= 2 else np.nan for i in idx_rent_1500]
df['rent_count_700m']   = [len(i) for i in idx_rent_700]
print(f'  Покрытие 700м: {df["median_rent_700m"].notna().sum()}/{len(df)} | '
      f'1500м: {df["median_rent_1500m"].notna().sum()}/{len(df)}')

# median_rent_700m_same_type: аренда того же вида объекта
print('Считаем median_rent_700m_same_type...')
r_vids = rent['вид_r'].values
df['median_rent_700m_same_type'] = np.nan
for vid_val in df['вид'].dropna().unique():
    sale_mask = (df['вид'] == vid_val).values
    rent_mask = r_vids == vid_val
    if sale_mask.sum() == 0 or rent_mask.sum() == 0:
        continue
    r_sub    = rent[rent_mask].reset_index(drop=True)
    pm2_sub  = r_sub['pm2_мес'].values
    tree_sub = BallTree(np.radians(r_sub[['lat_r','lng_r']].values), metric='haversine')
    idx_sub  = tree_sub.query_radius(q_coords[sale_mask], r=700/R_EARTH)
    vals = [float(np.median(pm2_sub[i])) if len(i) >= 2 else np.nan for i in idx_sub]
    df.loc[sale_mask, 'median_rent_700m_same_type'] = vals
    print(f'  {vid_val}: {sum(v==v for v in vals)}/{sale_mask.sum()} покрыто')
# фоллбэк: тип не совпал → берём общую медиану
fallback = df['median_rent_700m_same_type'].isna() & df['median_rent_700m'].notna()
df.loc[fallback, 'median_rent_700m_same_type'] = df.loc[fallback, 'median_rent_700m']
print(f'  Итого покрытие same_type: {df["median_rent_700m_same_type"].notna().sum()}/{len(df)}')

# ── кол-во продаж в 700м + расстояние до Кремля ───────────────────────────────
print('\nСчитаем sale_count_700m и dist_kremlin...')
sale_tree = BallTree(q_coords, metric='haversine')
idx_sale  = sale_tree.query_radius(q_coords, r=700/R_EARTH)
df['sale_count_700m'] = [len(i) - 1 for i in idx_sale]  # -1 чтобы не считать себя

KREMLIN_LAT, KREMLIN_LON = 55.7520, 37.6175
df['dist_kremlin'] = haversine_vec(KREMLIN_LAT, KREMLIN_LON, df['lat'].values, df['lng'].values)
print(f'  Медиана sale_count_700m: {df["sale_count_700m"].median():.0f}')
print(f'  Медиана dist_kremlin: {df["dist_kremlin"].median()/1000:.1f} км')

# ── feature matrix ─────────────────────────────────────────────────────────────
print('\nСтроим матрицу признаков...')
floor_dummies = pd.get_dummies(df['этаж_норм'], prefix='этаж', drop_first=False)
vid_dummies   = pd.get_dummies(df['вид'],        prefix='вид',  drop_first=False)

ВХОД_ОТДЕЛЬНЫЙ = {'отдельный', 'отдельный с улицы', 'отдельный со двора'}
ВХОД_ОБЩИЙ     = {'общий', 'общий с улицы', 'через подъезд', 'через холл'}
df['вход_отдельный_any'] = df['тип_входа'].isin(ВХОД_ОТДЕЛЬНЫЙ).astype(float)
df['вход_общий_any']     = df['тип_входа'].isin(ВХОД_ОБЩИЙ).astype(float)

feat_cols_base = ['площадь', 'до_метро', 'apt_400', 'apt_800',
                  'median_rent_700m', 'median_rent_700m_same_type', 'median_rent_1500m',
                  'rent_count_700m', 'sale_count_700m',
                  'dist_kremlin', 'lat', 'lng',
                  'этажность_здания',
                  'вход_отдельный_any', 'вход_общий_any',
                  'metro_passengers_annual', 'metro_vest_type']
X = pd.concat([df[feat_cols_base], floor_dummies, vid_dummies], axis=1).astype(float)
y = df['цена_за_м2'].values

mask = np.isfinite(y) & np.isfinite(X['площадь'])
X = X[mask].fillna(0)
y = y[mask]
df_valid = df[mask].reset_index(drop=True)
print(f'  Объектов для модели: {len(y)}')
print(f'  Признаков: {X.shape[1]}: {list(X.columns)}')

# ── LOO-CV территориальный baseline (с типом входа) ───────────────────────────
print('\nLOO-CV territorial (700м + этаж + площадь + тип_входа если известен)...')
lats = df_valid['lat'].values
lons = df_valid['lng'].values
areas = df_valid['площадь'].values
floors = df_valid['этаж_норм'].values
entrances = df_valid['тип_входа'].values
pm2 = y.copy()

terr_preds, terr_mask = [], []
for i in range(len(df_valid)):
    dists = haversine_vec(lats[i], lons[i], lats, lons)
    nb = (dists > 100) & (dists <= 700) & (floors == floors[i])
    nb &= (areas >= areas[i]*0.5) & (areas <= areas[i]*1.5)
    # фильтр по типу входа только если оба известны
    if entrances[i] is not None and not (isinstance(entrances[i], float) and np.isnan(float(entrances[i]))):
        has_entrance = np.array([
            e is not None and not (isinstance(e, float) and np.isnan(float(e))) and e == entrances[i]
            for e in entrances
        ])
        nb_with_entrance = nb & has_entrance
        if nb_with_entrance.sum() >= 2:
            nb = nb_with_entrance  # фильтруем если хватает аналогов

    if nb.sum() < 2:
        terr_mask.append(False); terr_preds.append(np.nan)
    else:
        terr_mask.append(True); terr_preds.append(float(np.median(pm2[nb])))

terr_mask = np.array(terr_mask)
terr_preds = np.array(terr_preds)
terr_err = (terr_preds[terr_mask] - pm2[terr_mask]) / pm2[terr_mask]
print(f'  Покрытие: {terr_mask.sum()}/{len(df_valid)} ({terr_mask.mean()*100:.0f}%)')
print(f'  MAPE territorial: {np.abs(terr_err).mean()*100:.1f}%')

# ── GroupKFold CV XGBoost (группа = coord_50м + этаж) ─────────────────────────
# объекты одного здания + одного этажа всегда в одном фолде -> нет утечки
print('\nGroupKFold CV XGBoost (coord_50m + этаж)...')
from sklearn.model_selection import GroupKFold

X_arr = X.values
log_y = np.log(y)

groups = (
    (df_valid['lat'] * 2000).round().astype(int).astype(str) + '_' +
    (df_valid['lng'] * 2000).round().astype(int).astype(str) + '_' +
    df_valid['этаж_норм'].fillna('unknown')
).values
n_groups = len(set(groups))
print(f'  Уникальных групп: {n_groups} (объектов: {len(y)})')

xgb_params = dict(
    n_estimators=400, max_depth=5, learning_rate=0.05,
    subsample=0.8, colsample_bytree=0.8, random_state=42,
    verbosity=0, n_jobs=-1,
)

feat_preds = np.full(len(y), np.nan)
gkf = GroupKFold(n_splits=5)
for fold, (tr_idx, val_idx) in enumerate(gkf.split(X_arr, log_y, groups)):
    print(f'  Fold {fold+1}/5: train={len(tr_idx)}, val={len(val_idx)}')
    model = XGBRegressor(**xgb_params)
    model.fit(X_arr[tr_idx], log_y[tr_idx])
    feat_preds[val_idx] = np.exp(model.predict(X_arr[val_idx]))

feat_err = (feat_preds - y) / y
print(f'  MAPE XGBoost (5-fold): {np.abs(feat_err).mean()*100:.1f}%')
print(f'  Медиана ошибки: {np.median(feat_err)*100:+.1f}%')

# ── combined ───────────────────────────────────────────────────────────────────
feat_mask = np.isfinite(feat_preds)
both = terr_mask & feat_mask
y_b = pm2[both]; t_b = terr_preds[both]; f_b = feat_preds[both]
best_alpha, best_mape = 0.0, 999
for alpha in np.arange(0.0, 1.01, 0.05):
    mape = np.abs((alpha*t_b + (1-alpha)*f_b - y_b) / y_b).mean() * 100
    if mape < best_mape: best_mape, best_alpha = mape, alpha

print(f'\n{"="*55}')
print(f'{"Метод":<32} {"MAPE":>8} {"Покрытие":>10}')
print(f'{"-"*55}')
print(f'{"Territorial (700м+этаж+вход+S)":<32} {np.abs(terr_err).mean()*100:>7.1f}% {terr_mask.sum():>5}/{len(df_valid)}')
print(f'{"XGBoost (5-fold CV)":<32} {np.abs(feat_err).mean()*100:>7.1f}% {feat_mask.sum():>5}/{len(df_valid)}')
print(f'{"Combined a={:.2f}":<32} {best_mape:>7.1f}% {both.sum():>5}/{len(df_valid)}'.format(best_alpha))
print(f'{"="*55}')

# ── обучаем финальную модель на всех данных ────────────────────────────────────
print('\nОбучаем финальную модель на всех данных...')
model_full = XGBRegressor(**xgb_params)
model_full.fit(X_arr, log_y)

importances = model_full.feature_importances_
print('Важность признаков:')
for col, imp in sorted(zip(X.columns, importances), key=lambda x: x[1], reverse=True):
    bar = '█' * int(imp * 200)
    print(f'  {col:<35} {imp:.3f} {bar}')

# сохраняем
model_full.save_model(f'{MODEL_DIR}/hedonic_xgb.json')
feature_cols = list(X.columns)
with open(f'{MODEL_DIR}/hedonic_features.json', 'w', encoding='utf-8') as fh:
    json.dump(feature_cols, fh, ensure_ascii=False)
print(f'\nМодель сохранена: {MODEL_DIR}/hedonic_xgb.json')
print(f'Признаки: {feature_cols}')
