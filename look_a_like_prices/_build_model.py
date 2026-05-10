"""
Hedonic model: цена/м² ~ площадь + этаж + тип_входа + до_метро + apt_400m + apt_800m
LOO-CV сравнение: territorial vs feature model vs combined (alpha-blend)
"""
import json
import re
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from xgboost import XGBRegressor

ANALOGUES = 'C:/git/realrobot/look_a_like_prices/excel2-30025-1.xlsx'
ENTRANCE  = 'C:/git/realrobot/look_a_like_prices/_entrance_results.csv'
BUILDINGS = 'C:/git/realrobot/look_a_like_prices/data/buildings_moscow.parquet'

NORM_ENTRANCE = {
    'отдельный с улицы': 'отдельный с улицы', 'separateFromTheStreet': 'отдельный с улицы',
    'separateFromStreet': 'отдельный с улицы',
    'отдельный со двора': 'отдельный со двора', 'separateFromTheYard': 'отдельный со двора',
    'separateFromYard': 'отдельный со двора',
    'commonFromStreet': 'общий с улицы', 'commonFromTheStreet': 'общий с улицы',
    'commonFromYard': 'общий со двора', 'commonFromTheYard': 'общий со двора',
    'throughEntrance': 'через подъезд', 'throughHall': 'через холл',
}

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

print('Загружаем аналоги...')
df = pd.read_excel(ANALOGUES)
df['площадь'] = df.apply(_get_area, axis=1)
df['цена'] = pd.to_numeric(df['Цена'], errors='coerce')
df['цена_за_м2'] = np.where(df['площадь'].fillna(0) > 0, df['цена'] / df['площадь'], np.nan)
df['этаж_норм'] = df['Доп.параметры'].apply(lambda x: _parse_param(x, 'Этаж')).apply(normalize_floor)
df['до_метро'] = pd.to_numeric(df['Расстояние до метро, км'], errors='coerce')
df['lat'] = pd.to_numeric(df['lat'], errors='coerce')
df['lng'] = pd.to_numeric(df['lng'], errors='coerce')
df = df[df['этаж_норм'] != '-2'].copy()
df = df.dropna(subset=['lat','lng','цена','площадь','цена_за_м2']).reset_index(drop=True)
print(f'  Аналогов: {len(df)}')

# тип входа
entrance = pd.read_csv(ENTRANCE, encoding='utf-8-sig')
entrance['тип_входа'] = entrance['тип_входа_циан'].map(NORM_ENTRANCE)
df = df.merge(entrance[['URL','тип_входа']], on='URL', how='left')
print(f'  С типом входа: {df["тип_входа"].notna().sum()}')

# ── квартиры в радиусе ─────────────────────────────────────────────────────────
print('Считаем квартиры в радиусе (1164 × 36k зданий)...')
bld = pd.read_parquet(BUILDINGS, columns=['lat','lng','apt_living'])
b_lats = bld['lat'].values
b_lons = bld['lng'].values
b_apts = bld['apt_living'].values

apt_400, apt_800 = [], []
for i, row in df.iterrows():
    if i % 200 == 0: print(f'  {i}/{len(df)}')
    dists = haversine_vec(row['lat'], row['lng'], b_lats, b_lons)
    apt_400.append(int(b_apts[dists <= 400].sum()))
    apt_800.append(int(b_apts[dists <= 800].sum()))

df['apt_400'] = apt_400
df['apt_800'] = apt_800
print(f'  Медиана apt_400: {np.median(apt_400):.0f}, apt_800: {np.median(apt_800):.0f}')

# ── feature matrix ─────────────────────────────────────────────────────────────
print('\nСтроим матрицу признаков...')

floor_dummies = pd.get_dummies(df['этаж_норм'], prefix='этаж', drop_first=False)
entrance_dummies = pd.get_dummies(df['тип_входа'], prefix='вход', drop_first=False)

feat_cols = ['площадь', 'до_метро', 'apt_400', 'apt_800', 'lat', 'lng']
X_base = df[feat_cols].copy()
X = pd.concat([X_base, floor_dummies, entrance_dummies], axis=1).astype(float)
y = df['цена_за_м2'].values

# убираем строки где нет цены или ключевых фич
mask = np.isfinite(y) & np.isfinite(X['площадь']) & np.isfinite(X['до_метро'])
X = X[mask].fillna(0)
y = y[mask]
df_valid = df[mask].reset_index(drop=True)
print(f'  Объектов для модели: {len(y)}')
print(f'  Признаков: {X.shape[1]} ({list(X.columns)})')

# ── LOO-CV: территориальный baseline (700м, тот же этаж, площадь ±50%) ─────────
print('\nLOO-CV territorial baseline...')
lats = df_valid['lat'].values
lons = df_valid['lng'].values
areas = df_valid['площадь'].values
floors = df_valid['этаж_норм'].values
pm2 = y.copy()

terr_preds, terr_mask = [], []
for i in range(len(df_valid)):
    dists = haversine_vec(lats[i], lons[i], lats, lons)
    nb = (dists > 100) & (dists <= 700) & (floors == floors[i])
    nb &= (areas >= areas[i]*0.5) & (areas <= areas[i]*1.5)
    if nb.sum() < 2:
        terr_mask.append(False)
        terr_preds.append(np.nan)
    else:
        terr_mask.append(True)
        terr_preds.append(float(np.median(pm2[nb])))

terr_mask = np.array(terr_mask)
terr_preds = np.array(terr_preds)
terr_err = (terr_preds[terr_mask] - pm2[terr_mask]) / pm2[terr_mask]
print(f'  Покрытие: {terr_mask.sum()}/{len(df_valid)} ({terr_mask.mean()*100:.0f}%)')
print(f'  MAPE territorial: {np.abs(terr_err).mean()*100:.1f}%')

# ── LOO-CV: feature model (XGBoost, log target) ───────────────────────────────
print('\nLOO-CV feature model (XGBoost, log цена/м²)...')
X_arr = X.values
log_y = np.log(y)
feat_preds = np.full(len(y), np.nan)

xgb_params = dict(
    n_estimators=300, max_depth=4, learning_rate=0.05,
    subsample=0.8, colsample_bytree=0.8, random_state=42,
    verbosity=0, n_jobs=-1,
)

for i in range(len(y)):
    if i % 200 == 0: print(f'  {i}/{len(y)}')
    X_train = np.delete(X_arr, i, axis=0)
    y_train = np.delete(log_y, i)
    X_test = X_arr[i:i+1]
    model = XGBRegressor(**xgb_params)
    model.fit(X_train, y_train)
    feat_preds[i] = np.exp(model.predict(X_test)[0])

feat_err = (feat_preds - y) / y
print(f'  MAPE feature model (XGB): {np.abs(feat_err).mean()*100:.1f}%')
print(f'  Медиана ошибки: {np.median(feat_err)*100:+.1f}%')

# ── combined: alpha-blend по объектам где есть оба предсказания ────────────────
print('\nПодбор оптимального alpha...')
both = terr_mask & np.isfinite(feat_preds)
y_b = pm2[both]
t_b = terr_preds[both]
f_b = feat_preds[both]

best_alpha, best_mape = 0.0, 999
for alpha in np.arange(0.0, 1.01, 0.05):
    combined = alpha * t_b + (1 - alpha) * f_b
    mape = np.abs((combined - y_b) / y_b).mean() * 100
    if mape < best_mape:
        best_mape, best_alpha = mape, alpha

print(f'  Лучший alpha (territorial): {best_alpha:.2f}')
print(f'  MAPE combined: {best_mape:.1f}%')
print(f'  (на {both.sum()} объектах где есть оба предсказания)')

# ── итог ───────────────────────────────────────────────────────────────────────
print('\n' + '='*55)
print(f'{"Метод":<30} {"MAPE":>8} {"Покрытие":>10}')
print('-'*55)
print(f'{"Territorial (700м + этаж + S)":<30} {np.abs(terr_err).mean()*100:>7.1f}% {terr_mask.sum():>6}/{len(df_valid)}')
print(f'{"Feature model (Ridge)":<30} {np.abs(feat_err).mean()*100:>7.1f}% {len(y):>6}/{len(df_valid)}')
print(f'{"Combined (alpha={:.2f})":<30} {best_mape:>7.1f}% {both.sum():>6}/{len(df_valid)}'.format(best_alpha))
print('='*55)

# важность признаков финальной модели
model_full = XGBRegressor(**xgb_params)
model_full.fit(X_arr, log_y)
importances = model_full.feature_importances_
print('\nВажность признаков (XGBoost):')
for col, imp in sorted(zip(X.columns, importances), key=lambda x: x[1], reverse=True):
    bar = '█' * int(imp * 200)
    print(f'  {col:<35} {imp:.3f} {bar}')

# ── сохраняем модель ───────────────────────────────────────────────────────────
MODEL_DIR = 'C:/git/realrobot/look_a_like_prices/data'
model_full.save_model(f'{MODEL_DIR}/hedonic_xgb.json')
feature_cols = list(X.columns)
with open(f'{MODEL_DIR}/hedonic_features.json', 'w', encoding='utf-8') as fh:
    json.dump(feature_cols, fh, ensure_ascii=False)
print(f'\nМодель сохранена → data/hedonic_xgb.json')
print(f'Признаки сохранены → data/hedonic_features.json ({len(feature_cols)} шт)')
