import re
import numpy as np
import pandas as pd
from itertools import product

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
    if s in ('цокольный','цоколь','подвальный','подвал','-1','0'): return 'tsokolь'
    if s == '1': return '1'
    if s == '2': return '2'
    try:
        n = int(s)
        return '3+' if n >= 3 else s
    except: pass
    return s

def normalize_type(s):
    if not isinstance(s, str): return None
    s = s.strip().lower()
    if any(x in s for x in ('торг', 'магаз', 'розниц')): return 'retail'
    if any(x in s for x in ('офис',)): return 'office'
    if any(x in s for x in ('склад', 'произв')): return 'warehouse'
    if any(x in s for x in ('свобод', 'универс', 'назначен')): return 'flex'
    return 'other'

def haversine_vec(lat1, lon1, lats, lons):
    R = 6_371_000
    a = (np.sin(np.radians(lats - lat1) / 2) ** 2
         + np.cos(np.radians(lat1)) * np.cos(np.radians(lats))
         * np.sin(np.radians(lons - lon1) / 2) ** 2)
    return R * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))

def weighted_median(values, weights):
    idx = np.argsort(values)
    v, w = values[idx], weights[idx]
    cum = np.cumsum(w)
    cutoff = cum[-1] / 2.0
    return float(v[cum >= cutoff][0])

# ── Load data ──────────────────────────────────────────────────────────────────
df = pd.read_excel('C:/git/realrobot/look_a_like_prices/excel2-30025-1.xlsx')
df['area']   = df.apply(_get_area, axis=1)
df['price']  = pd.to_numeric(df['Цена'], errors='coerce')
df['pm2']    = np.where(df['area'].fillna(0) > 0, df['price'] / df['area'], np.nan)
df['floor']  = df['Доп.параметры'].apply(lambda x: _parse_param(x, 'Этаж')).apply(normalize_floor)
df['obj_type'] = df['Доп.параметры'].apply(lambda x: _parse_param(x, 'Вид объекта')).apply(normalize_type)
df['metro_km'] = pd.to_numeric(df['Расстояние до метро, км'], errors='coerce')
df['lat']    = pd.to_numeric(df['lat'], errors='coerce')
df['lng']    = pd.to_numeric(df['lng'], errors='coerce')
df = df[df['floor'] != '-2'].dropna(subset=['lat', 'lng', 'price'])

valid = df.dropna(subset=['area', 'pm2', 'floor']).copy()
valid = valid[valid['area'] > 0].reset_index(drop=True)
print(f'Valid: {len(valid)} objects\n')

lats     = valid['lat'].values
lons     = valid['lng'].values
pm2      = valid['pm2'].values
areas    = valid['area'].values
prices   = valid['price'].values
floors   = valid['floor'].values
types    = valid['obj_type'].values
metro_km = valid['metro_km'].values

RADIUS = 700
AREA_PCT = 0.5
METRO_DELTA = 0.3  # km

def run_loo(use_area, use_type, use_metro, use_weighting):
    errs = []
    for i in range(len(valid)):
        dists = haversine_vec(lats[i], lons[i], lats, lons)
        nb = (dists > 100) & (floors == floors[i]) & (dists <= RADIUS)

        if use_area and areas[i] > 0:
            nb &= (areas >= areas[i] * (1 - AREA_PCT)) & (areas <= areas[i] * (1 + AREA_PCT))

        if use_type and types[i] is not None:
            nb &= (types == types[i])

        if use_metro and not np.isnan(metro_km[i]):
            nb &= np.abs(metro_km - metro_km[i]) <= METRO_DELTA

        if nb.sum() < 2:
            continue

        if use_weighting:
            w = 1.0 / np.maximum(dists[nb], 1.0)
            pred_pm2 = weighted_median(pm2[nb], w)
        else:
            pred_pm2 = float(np.median(pm2[nb]))

        rel_err = (pred_pm2 * areas[i] - prices[i]) / prices[i]
        errs.append(rel_err)

    if not errs:
        return None
    e = np.array(errs)
    return {
        'n':      len(e),
        'cover':  len(e) / len(valid) * 100,
        'mape':   np.abs(e).mean() * 100,
        'median': np.median(e) * 100,
        'p25':    np.quantile(e, 0.25) * 100,
        'p75':    np.quantile(e, 0.75) * 100,
    }

# ── Run all 16 combinations ────────────────────────────────────────────────────
flags = ['площадь', 'вид', 'метро', 'вес(1/d)']
print(f"{'Комбинация':<38} {'Покр':>5}  {'MAPE':>5}  {'Med':>5}  {'P25':>5}  {'P75':>5}")
print('-' * 70)

rows = []
for combo in product([False, True], repeat=4):
    use_area, use_type, use_metro, use_weight = combo
    res = run_loo(use_area, use_type, use_metro, use_weight)
    label = ' + '.join(f for f, on in zip(flags, combo) if on) or 'базовый (только этаж)'
    if res:
        rows.append((res['mape'], label, res))
        print(f"{label:<38} {res['cover']:>4.0f}%  {res['mape']:>4.0f}%  {res['median']:>+4.0f}%  {res['p25']:>+4.0f}%  {res['p75']:>+4.0f}%")
    else:
        print(f"{label:<38}  нет данных")

print()
rows.sort()
print('Топ-5 по MAPE:')
for mape, label, r in rows[:5]:
    print(f"  MAPE={mape:.0f}%  cover={r['cover']:.0f}%  P25/P75={r['p25']:+.0f}%/{r['p75']:+.0f}%  |  {label}")
