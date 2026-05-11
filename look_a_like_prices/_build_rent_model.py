"""
Hedonic rent model: XGBoost на arenda_dedup.csv
Цель: log(цена_за_м²_мес). GroupKFold CV (coord_50m + этаж).
Кросс-признак: median_sale_700m из sale_dedup.csv.
"""
import json
import re
import sys
import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree
from sklearn.model_selection import GroupKFold
from xgboost import XGBRegressor

sys.stdout.reconfigure(encoding='utf-8')

ARENDA_CSV    = 'C:/git/realrobot/look_a_like_prices/data/arenda_dedup.csv'
SALE_CSV      = 'C:/git/realrobot/look_a_like_prices/data/sale_dedup.csv'
ENTRANCE_FILE = 'C:/git/realrobot/look_a_like_prices/_entrance_results_arenda.csv'
BUILDINGS     = 'C:/git/realrobot/look_a_like_prices/data/buildings_moscow.parquet'
MODEL_DIR     = 'C:/git/realrobot/look_a_like_prices/data'

NORM_ENTRANCE = {
    'отдельный':         'отдельный',
    'общий':             'общий',
    'отдельный с улицы': 'отдельный с улицы', 'separateFromTheStreet': 'отдельный с улицы',
    'separateFromStreet': 'отдельный с улицы',
    'отдельный со двора': 'отдельный со двора', 'separateFromTheYard': 'отдельный со двора',
    'separateFromYard':  'отдельный со двора',
    'общий с улицы':     'общий с улицы',
    'commonFromStreet':  'общий с улицы', 'commonFromTheStreet': 'общий с улицы',
    'через подъезд':     'через подъезд', 'throughEntrance': 'через подъезд',
    'через холл':        'через холл',    'throughHall':     'через холл',
}
ВХОД_ОТДЕЛЬНЫЙ = {'отдельный', 'отдельный с улицы', 'отдельный со двора'}
ВХОД_ОБЩИЙ     = {'общий', 'общий с улицы', 'через подъезд', 'через холл'}

EXCLUDE_VID = {'Здание', 'Коммерческая земля', 'Складское помещение',
               'Производственное помещение', 'Гостиница'}

KREMLIN_LAT, KREMLIN_LON = 55.7520, 37.6175
R_EARTH = 6_371_000.0

def _parse_param(s, key):
    if not isinstance(s, str): return None
    m = re.search(rf'{re.escape(key)}=([^|]+)', s)
    return m.group(1).strip() if m else None

def _get_area(row):
    val = _parse_param(row['Доп.параметры'], 'Общая площадь')
    if val:
        try: return float(val.replace(',', '.'))
        except: pass
    m = re.search(r'\((\d+[\.,]?\d*)\s*м', str(row.get('Название', '')))
    if m:
        try: return float(m.group(1).replace(',', '.'))
        except: pass
    return None

def normalize_floor(s):
    if not isinstance(s, str): return None
    s = s.strip().lower()
    if s in ('цокольный', 'цоколь', 'подвальный', 'подвал'): return 'цоколь'
    try:
        n = int(s)
        if n <= 0: return 'цоколь'
        return '1' if n == 1 else ('2' if n == 2 else '3+')
    except: pass
    return s

def haversine_vec(lat1, lon1, lats, lons):
    R = 6_371_000
    phi1 = np.radians(lat1); phi2 = np.radians(lats)
    dphi = np.radians(lats - lat1); dlam = np.radians(lons - lon1)
    a = np.sin(dphi/2)**2 + np.cos(phi1)*np.cos(phi2)*np.sin(dlam/2)**2
    return R * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))

# ── загрузка аренды ────────────────────────────────────────────────────────────
print('Загружаем arenda_dedup.csv...')
df = pd.read_csv(ARENDA_CSV, sep=';', encoding='utf-8-sig')
df['площадь']    = df.apply(_get_area, axis=1)
df['цена']       = pd.to_numeric(df['Цена'], errors='coerce')
df['цена_за_м2'] = np.where(df['площадь'].fillna(0) > 0, df['цена'] / df['площадь'], np.nan)
df['этаж_норм']  = df['Доп.параметры'].apply(lambda x: _parse_param(x, 'Этаж')).apply(normalize_floor)
df['до_метро']   = pd.to_numeric(df['Расстояние до метро, км'], errors='coerce')
df['lat']        = pd.to_numeric(df['lat'], errors='coerce')
df['lng']        = pd.to_numeric(df['lng'], errors='coerce')
df['вид']        = df['Доп.параметры'].apply(lambda x: _parse_param(x, 'Вид объекта'))
df = df.dropna(subset=['lat', 'lng', 'цена', 'площадь', 'цена_за_м2']).reset_index(drop=True)
df = df[(df['цена_за_м2'] >= 200) & (df['цена_за_м2'] <= 100_000) & (df['площадь'] >= 15)].copy()
df = df[~df['вид'].isin(EXCLUDE_VID)].copy().reset_index(drop=True)
print(f'  После очистки: {len(df)} строк')
print(f'  Вид объекта: {df["вид"].value_counts().to_dict()}')

# тип входа
entrance = pd.read_csv(ENTRANCE_FILE, encoding='utf-8-sig')
entrance['тип_входа_норм'] = entrance['тип_входа'].map(NORM_ENTRANCE)
df = df.merge(entrance[['URL', 'тип_входа_норм']].rename(columns={'тип_входа_норм': 'тип_входа'}),
              on='URL', how='left')
n_with = df['тип_входа'].notna().sum()
print(f'  Тип входа: {n_with}/{len(df)} ({n_with/len(df)*100:.0f}%)')

# ── BallTree квартиры ─────────────────────────────────────────────────────────
print('\nСтроим BallTree по зданиям...')
bld = pd.read_parquet(BUILDINGS, columns=['lat', 'lng', 'apt_living'])
b_coords = np.radians(bld[['lat', 'lng']].values)
b_apts   = bld['apt_living'].values
bld_tree = BallTree(b_coords, metric='haversine')

q_coords = np.radians(df[['lat', 'lng']].values)
idx_400  = bld_tree.query_radius(q_coords, r=400/R_EARTH)
idx_800  = bld_tree.query_radius(q_coords, r=800/R_EARTH)
df['apt_400'] = [int(b_apts[i].sum()) for i in idx_400]
df['apt_800'] = [int(b_apts[i].sum()) for i in idx_800]
print(f'  Медиана apt_400: {df["apt_400"].median():.0f}, apt_800: {df["apt_800"].median():.0f}')

# ── dist_kremlin ──────────────────────────────────────────────────────────────
df['dist_kremlin'] = haversine_vec(KREMLIN_LAT, KREMLIN_LON, df['lat'].values, df['lng'].values)
print(f'  Медиана dist_kremlin: {df["dist_kremlin"].median()/1000:.1f} км')

# ── конкурирующие объявления аренды в 700м (self-excluded) ───────────────────
print('\nСчитаем rent_count_700m (самоисключение)...')
rent_tree = BallTree(q_coords, metric='haversine')
idx_rent  = rent_tree.query_radius(q_coords, r=700/R_EARTH)
df['rent_count_700m'] = [len(i) - 1 for i in idx_rent]

# ── кросс-признак: медиана продажи в 700м ─────────────────────────────────────
print('\nЗагружаем sale_dedup.csv для кросс-признака median_sale_700m...')
sale = pd.read_csv(SALE_CSV, sep=';', encoding='utf-8-sig')
sale['площадь_s'] = sale.apply(_get_area, axis=1)
sale['цена_s']    = pd.to_numeric(sale['Цена'], errors='coerce')
sale['pm2_s']     = np.where(sale['площадь_s'].fillna(0) > 0, sale['цена_s'] / sale['площадь_s'], np.nan)
sale['lat_s']     = pd.to_numeric(sale['lat'], errors='coerce')
sale['lng_s']     = pd.to_numeric(sale['lng'], errors='coerce')
sale['вид_s']     = sale['Доп.параметры'].apply(lambda x: _parse_param(x, 'Вид объекта'))
sale = sale[~sale['вид_s'].isin(EXCLUDE_VID)].copy()
sale = sale.dropna(subset=['lat_s', 'lng_s', 'pm2_s'])
sale = sale[(sale['pm2_s'] >= 50_000) & (sale['pm2_s'] <= 3_000_000) & (sale['площадь_s'] >= 15)]
sale = sale.reset_index(drop=True)
print(f'  Продажа: {len(sale)} объявлений')

s_coords  = np.radians(sale[['lat_s', 'lng_s']].values)
s_pm2     = sale['pm2_s'].values
sale_tree = BallTree(s_coords, metric='haversine')

idx_sale_700  = sale_tree.query_radius(q_coords, r= 700/R_EARTH)
idx_sale_1500 = sale_tree.query_radius(q_coords, r=1500/R_EARTH)
df['median_sale_700m']  = [float(np.median(s_pm2[i])) if len(i) >= 2 else np.nan for i in idx_sale_700]
df['median_sale_1500m'] = [float(np.median(s_pm2[i])) if len(i) >= 2 else np.nan for i in idx_sale_1500]
df['sale_count_700m']   = [len(i) for i in idx_sale_700]
print(f'  Покрытие 700м: {df["median_sale_700m"].notna().sum()}/{len(df)} | '
      f'1500м: {df["median_sale_1500m"].notna().sum()}/{len(df)}')

# ── feature matrix ─────────────────────────────────────────────────────────────
print('\nСтроим матрицу признаков...')
floor_dummies = pd.get_dummies(df['этаж_норм'], prefix='этаж', drop_first=False)
vid_dummies   = pd.get_dummies(df['вид'],        prefix='вид',  drop_first=False)

df['вход_отдельный_any'] = df['тип_входа'].isin(ВХОД_ОТДЕЛЬНЫЙ).astype(float)
df['вход_общий_any']     = df['тип_входа'].isin(ВХОД_ОБЩИЙ).astype(float)

feat_cols_base = [
    'площадь', 'до_метро', 'apt_400', 'apt_800',
    'median_sale_700m', 'median_sale_1500m', 'sale_count_700m', 'rent_count_700m',
    'dist_kremlin', 'lat', 'lng',
    'вход_отдельный_any', 'вход_общий_any',
]
X = pd.concat([df[feat_cols_base], floor_dummies, vid_dummies], axis=1).astype(float)
y = df['цена_за_м2'].values

mask = np.isfinite(y) & np.isfinite(X['площадь']) & np.isfinite(X['до_метро'])
X = X[mask].fillna(0)
y = y[mask]
df_valid = df[mask].reset_index(drop=True)
print(f'  Объектов для модели: {len(y)}')
print(f'  Признаков: {X.shape[1]}: {list(X.columns)}')

# ── LOO-CV территориальный baseline ───────────────────────────────────────────
print('\nLOO-CV territorial (700м + этаж + площадь ±50%)...')
lats     = df_valid['lat'].values
lons     = df_valid['lng'].values
areas    = df_valid['площадь'].values
floors   = df_valid['этаж_норм'].values
pm2      = y.copy()

terr_preds, terr_mask = [], []
for i in range(len(df_valid)):
    dists = haversine_vec(lats[i], lons[i], lats, lons)
    nb = (dists > 100) & (dists <= 700) & (floors == floors[i])
    nb &= (areas >= areas[i] * 0.5) & (areas <= areas[i] * 1.5)
    if nb.sum() < 2:
        terr_mask.append(False); terr_preds.append(np.nan)
    else:
        terr_mask.append(True); terr_preds.append(float(np.median(pm2[nb])))

terr_mask  = np.array(terr_mask)
terr_preds = np.array(terr_preds)
terr_err   = (terr_preds[terr_mask] - pm2[terr_mask]) / pm2[terr_mask]
print(f'  Покрытие: {terr_mask.sum()}/{len(df_valid)} ({terr_mask.mean()*100:.0f}%)')
print(f'  MAPE territorial: {np.abs(terr_err).mean()*100:.1f}%')
print(f'  Медиана ошибки: {np.median(terr_err)*100:+.1f}%')

# ── GroupKFold CV XGBoost ─────────────────────────────────────────────────────
print('\nGroupKFold CV XGBoost (coord_50m + этаж)...')
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

# ── combined alpha ─────────────────────────────────────────────────────────────
feat_mask = np.isfinite(feat_preds)
both = terr_mask & feat_mask
y_b = pm2[both]; t_b = terr_preds[both]; f_b = feat_preds[both]
best_alpha, best_mape = 0.0, 999
for alpha in np.arange(0.0, 1.01, 0.05):
    mape = np.abs((alpha * t_b + (1 - alpha) * f_b - y_b) / y_b).mean() * 100
    if mape < best_mape:
        best_mape, best_alpha = mape, alpha

print(f'\n{"="*55}')
print(f'{"Метод":<32} {"MAPE":>8} {"Покрытие":>10}')
print(f'{"-"*55}')
print(f'{"Territorial (700м+этаж+S)":<32} {np.abs(terr_err).mean()*100:>7.1f}%  {terr_mask.sum():>5}/{len(df_valid)}')
print(f'{"XGBoost (5-fold CV)":<32} {np.abs(feat_err).mean()*100:>7.1f}%  {feat_mask.sum():>5}/{len(df_valid)}')
print(f'{"Combined a=%.2f" % best_alpha:<32} {best_mape:>7.1f}%  {both.sum():>5}/{len(df_valid)}')
print(f'{"="*55}')

# ── обучаем финальную модель ──────────────────────────────────────────────────
print('\nОбучаем финальную модель на всех данных...')
model_full = XGBRegressor(**xgb_params)
model_full.fit(X_arr, log_y)

importances = model_full.feature_importances_
print('Важность признаков:')
for col, imp in sorted(zip(X.columns, importances), key=lambda x: x[1], reverse=True):
    bar = '█' * int(imp * 200)
    print(f'  {col:<35} {imp:.3f} {bar}')

model_full.save_model(f'{MODEL_DIR}/rent_xgb.json')
feature_cols = list(X.columns)
with open(f'{MODEL_DIR}/rent_features.json', 'w', encoding='utf-8') as fh:
    json.dump(feature_cols, fh, ensure_ascii=False)
print(f'\nМодель сохранена: {MODEL_DIR}/rent_xgb.json')
print(f'Признаки ({len(feature_cols)}): {feature_cols}')
