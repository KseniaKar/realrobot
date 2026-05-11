"""
Hedonic model v2: обучение на новом sale.csv (16k строк)
Территориальная медиана учитывает тип входа когда он известен.
BallTree для быстрого подсчёта квартир в радиусе.
"""
import json
import re
import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree
from xgboost import XGBRegressor

SALE_CSV   = 'C:/git/realrobot/look_a_like_prices/data/sale_dedup.csv'
ENTRANCE   = 'C:/git/realrobot/look_a_like_prices/_entrance_results.csv'
BUILDINGS  = 'C:/git/realrobot/look_a_like_prices/data/buildings_moscow.parquet'
MODEL_DIR  = 'C:/git/realrobot/look_a_like_prices/data'

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
df['этаж_норм'] = df['Доп.параметры'].apply(lambda x: _parse_param(x, 'Этаж')).apply(normalize_floor)
df['до_метро'] = pd.to_numeric(df['Расстояние до метро, км'], errors='coerce')
df['lat'] = pd.to_numeric(df['lat'], errors='coerce')
df['lng'] = pd.to_numeric(df['lng'], errors='coerce')
df['вид'] = df['Доп.параметры'].apply(lambda x: _parse_param(x, 'Вид объекта'))
df = df[df['этаж_норм'] != '-2'].copy()
df = df.dropna(subset=['lat','lng','цена','площадь','цена_за_м2']).reset_index(drop=True)
# убираем выбросы по цене/м²
df = df[(df['цена_за_м2'] >= 50_000) & (df['цена_за_м2'] <= 3_000_000)].copy()
# убираем нерелевантные типы (здания, земля, склады — другая ценовая логика)
exclude_vid = {'Здание', 'Коммерческая земля', 'Складское помещение', 'Производственное помещение', 'Гостиница'}
df = df[~df['вид'].isin(exclude_vid)].copy().reset_index(drop=True)
print(f'  После очистки: {len(df)} строк')
print(f'  Вид объекта: {df["вид"].value_counts().to_dict()}')

# тип входа — джойним старые спарсенные данные
entrance = pd.read_csv(ENTRANCE, encoding='utf-8-sig')
entrance['тип_входа'] = entrance['тип_входа_циан'].map(NORM_ENTRANCE)
df = df.merge(entrance[['URL','тип_входа']], on='URL', how='left')
n_with = df['тип_входа'].notna().sum()
print(f'  Тип входа: {n_with}/{len(df)} ({n_with/len(df)*100:.0f}%)')

# ── BallTree для квартир в радиусе ─────────────────────────────────────────────
print('\nСтроим BallTree по зданиям...')
bld = pd.read_parquet(BUILDINGS, columns=['lat','lng','apt_living','residents_est'])
b_coords = np.radians(bld[['lat','lng']].values)
b_apts = bld['apt_living'].values
b_res  = bld['residents_est'].values
tree = BallTree(b_coords, metric='haversine')

print('Считаем квартиры в 400м/800м и жителей в 500м...')
q_coords = np.radians(df[['lat','lng']].values)

R_EARTH = 6_371_000.0
idx_400 = tree.query_radius(q_coords, r=400/R_EARTH)
idx_800 = tree.query_radius(q_coords, r=800/R_EARTH)
idx_500 = tree.query_radius(q_coords, r=500/R_EARTH)

df['apt_400']      = [int(b_apts[i].sum()) for i in idx_400]
df['apt_800']      = [int(b_apts[i].sum()) for i in idx_800]
df['residents_500']= [int(b_res[i].sum())  for i in idx_500]
print(f'  Медиана apt_400: {df["apt_400"].median():.0f}, apt_800: {df["apt_800"].median():.0f}')
print(f'  Медиана residents_500: {df["residents_500"].median():.0f}')

# ── feature matrix ─────────────────────────────────────────────────────────────
print('\nСтроим матрицу признаков...')
floor_dummies = pd.get_dummies(df['этаж_норм'], prefix='этаж', drop_first=False)
entrance_dummies = pd.get_dummies(df['тип_входа'], prefix='вход', drop_first=False)

feat_cols_base = ['площадь', 'до_метро', 'apt_400', 'apt_800', 'residents_500', 'lat', 'lng']
X = pd.concat([df[feat_cols_base], floor_dummies, entrance_dummies], axis=1).astype(float)
y = df['цена_за_м2'].values

mask = np.isfinite(y) & np.isfinite(X['площадь']) & np.isfinite(X['до_метро'])
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
