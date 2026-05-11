"""
Сравнение стратегий группировки для GroupKFold CV:
  1. Сетка 50м + этаж (текущий подход)
  2. DBSCAN (eps=50м, haversine) + этаж
  3. MeanShift (bandwidth=50м) + этаж
"""
import json, re, sys
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN, MeanShift
from sklearn.model_selection import GroupKFold
from xgboost import XGBRegressor

sys.stdout.reconfigure(encoding='utf-8')

SALE_CSV  = 'C:/git/realrobot/look_a_like_prices/data/sale_dedup.csv'
BUILDINGS = 'C:/git/realrobot/look_a_like_prices/data/buildings_moscow.parquet'

# ── загрузка ───────────────────────────────────────────────────────────────────
def _parse_param(s, key):
    if not isinstance(s, str): return None
    m = re.search(rf'{re.escape(key)}=([^|]+)', s)
    return m.group(1).strip() if m else None

def _get_area(row):
    val = _parse_param(row['Доп.параметры'], 'Общая площадь')
    if val:
        try: return float(val.replace(',', '.'))
        except: pass
    return None

def normalize_floor(s):
    if not isinstance(s, str): return None
    s = s.strip().lower()
    if s in ('цокольный','цоколь','подвальный','подвал','-1','0'): return 'цоколь'
    if s == '1': return '1'
    if s == '2': return '2'
    try:
        n = int(s)
        return '3+' if n >= 3 else s
    except: pass
    return s

def haversine_vec(lat1, lon1, lats, lons):
    R = 6_371_000
    phi1 = np.radians(lat1); phi2 = np.radians(lats)
    dphi = np.radians(lats - lat1); dlam = np.radians(lons - lon1)
    a = np.sin(dphi/2)**2 + np.cos(phi1)*np.cos(phi2)*np.sin(dlam/2)**2
    return R * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))

print('Загружаем данные...')
df = pd.read_csv(SALE_CSV, sep=';', encoding='utf-8-sig')
df['площадь']   = df.apply(_get_area, axis=1)
df['цена']       = pd.to_numeric(df['Цена'], errors='coerce')
df['цена_за_м2'] = np.where(df['площадь'].fillna(0) > 0, df['цена'] / df['площадь'], np.nan)
df['этаж_норм']  = df['Доп.параметры'].apply(lambda x: _parse_param(x, 'Этаж')).apply(normalize_floor)
df['до_метро']   = pd.to_numeric(df['Расстояние до метро, км'], errors='coerce')
df['lat']        = pd.to_numeric(df['lat'], errors='coerce')
df['lng']        = pd.to_numeric(df['lng'], errors='coerce')
df = df[df['этаж_норм'] != '-2'].copy()
df = df.dropna(subset=['lat','lng','цена','площадь','цена_за_м2']).reset_index(drop=True)
df = df[(df['цена_за_м2'] >= 50_000) & (df['цена_за_м2'] <= 3_000_000)].copy()
exclude = {'Здание','Коммерческая земля','Складское помещение','Производственное помещение','Гостиница'}
vid = df['Доп.параметры'].apply(lambda x: _parse_param(x, 'Вид объекта'))
df = df[~vid.isin(exclude)].copy().reset_index(drop=True)
print(f'  Объектов: {len(df)}')

# BallTree для квартир
from sklearn.neighbors import BallTree
bld = pd.read_parquet(BUILDINGS, columns=['lat','lng','apt_living'])
b_coords = np.radians(bld[['lat','lng']].values)
b_apts = bld['apt_living'].values
tree = BallTree(b_coords, metric='haversine')
q_coords = np.radians(df[['lat','lng']].values)
R_EARTH = 6_371_000.0
idx_400 = tree.query_radius(q_coords, r=400/R_EARTH)
idx_800 = tree.query_radius(q_coords, r=800/R_EARTH)
df['apt_400'] = [int(b_apts[i].sum()) for i in idx_400]
df['apt_800'] = [int(b_apts[i].sum()) for i in idx_800]

# матрица признаков
floor_dummies    = pd.get_dummies(df['этаж_норм'], prefix='этаж', drop_first=False)
feat_cols_base   = ['площадь','до_метро','apt_400','apt_800','lat','lng']
X = pd.concat([df[feat_cols_base], floor_dummies], axis=1).astype(float)
y = df['цена_за_м2'].values
mask = np.isfinite(y) & np.isfinite(X['площадь']) & np.isfinite(X['до_метро'])
X    = X[mask].fillna(0)
y    = y[mask]
df_v = df[mask].reset_index(drop=True)
log_y = np.log(y)
X_arr = X.values
print(f'  Для модели: {len(y)} объектов, {X.shape[1]} признаков\n')

xgb_params = dict(n_estimators=400, max_depth=5, learning_rate=0.05,
                  subsample=0.8, colsample_bytree=0.8, random_state=42,
                  verbosity=0, n_jobs=-1)

def run_gkf(groups, label):
    n_groups = len(set(groups))
    sizes = pd.Series(groups).value_counts()
    print(f'\n{"="*55}')
    print(f'Стратегия: {label}')
    print(f'  Групп: {n_groups}  |  объектов: {len(groups)}')
    print(f'  Размер группы: min={sizes.min()}  median={sizes.median():.0f}  '
          f'p90={sizes.quantile(0.9):.0f}  max={sizes.max()}')
    print(f'  Групп с >1 объектом: {(sizes>1).sum()} ({(sizes>1).sum()/n_groups*100:.0f}%)')

    preds = np.full(len(y), np.nan)
    gkf   = GroupKFold(n_splits=5)
    for fold, (tr, val) in enumerate(gkf.split(X_arr, log_y, groups)):
        m = XGBRegressor(**xgb_params)
        m.fit(X_arr[tr], log_y[tr])
        preds[val] = np.exp(m.predict(X_arr[val]))
    err  = (preds - y) / y
    mape = np.abs(err).mean() * 100
    med  = np.median(err) * 100
    print(f'  MAPE: {mape:.1f}%   Медиана ошибки: {med:+.1f}%')
    return mape

lats = df_v['lat'].values
lons = df_v['lng'].values
floors = df_v['этаж_норм'].fillna('unknown').values

# ── 1. Сетка 50м ───────────────────────────────────────────────────────────────
g_grid = ((lats * 2000).round().astype(int).astype(str) + '_' +
          (lons * 2000).round().astype(int).astype(str) + '_' + floors)
mape_grid = run_gkf(g_grid, 'Сетка 50м + этаж (текущий)')

# ── 2. DBSCAN 50м ──────────────────────────────────────────────────────────────
print('\nDBSCAN (eps=50м, haversine)...')
coords_rad = np.radians(np.column_stack([lats, lons]))
db = DBSCAN(eps=50/R_EARTH, min_samples=1, algorithm='ball_tree', metric='haversine')
db.fit(coords_rad)
# -1 (шум) не будет при min_samples=1
g_dbscan = (db.labels_.astype(str) + '_' + floors)
mape_dbscan = run_gkf(g_dbscan, 'DBSCAN 50м + этаж')

# ── 3. MeanShift ───────────────────────────────────────────────────────────────
print('\nMeanShift (bandwidth=50м)...')
coords_m = np.column_stack([lats * 111_000, lons * 111_000 * np.cos(np.radians(lats.mean()))])
ms = MeanShift(bandwidth=50, bin_seeding=True, n_jobs=-1)
ms.fit(coords_m)
g_ms = (ms.labels_.astype(str) + '_' + floors)
mape_ms = run_gkf(g_ms, 'MeanShift 50м + этаж')

# ── итог ───────────────────────────────────────────────────────────────────────
print(f'\n{"="*55}')
print(f'{"Стратегия":<30} {"MAPE":>8}')
print(f'{"-"*40}')
print(f'{"Сетка 50м + этаж":<30} {mape_grid:>7.1f}%')
print(f'{"DBSCAN 50м + этаж":<30} {mape_dbscan:>7.1f}%')
print(f'{"MeanShift 50м + этаж":<30} {mape_ms:>7.1f}%')
