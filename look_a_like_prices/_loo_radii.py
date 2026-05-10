import re
import numpy as np
import pandas as pd

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

def haversine_vec(lat1, lon1, lats, lons):
    R = 6_371_000
    a = (np.sin(np.radians(lats-lat1)/2)**2
         + np.cos(np.radians(lat1))*np.cos(np.radians(lats))*np.sin(np.radians(lons-lon1)/2)**2)
    return R * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))

df = pd.read_excel('C:/git/realrobot/look_a_like_prices/excel2-30025-1.xlsx')
df['area'] = df.apply(_get_area, axis=1)
df['price'] = pd.to_numeric(df['Цена'], errors='coerce')
df['pm2'] = np.where(df['area'].fillna(0) > 0, df['price'] / df['area'], np.nan)
df['floor'] = df['Доп.параметры'].apply(lambda x: _parse_param(x, 'Этаж')).apply(normalize_floor)
df['lat'] = pd.to_numeric(df['lat'], errors='coerce')
df['lng'] = pd.to_numeric(df['lng'], errors='coerce')
df = df[df['floor'] != '-2']
df = df.dropna(subset=['lat','lng','price'])

valid = df.dropna(subset=['area','pm2','floor'])
valid = valid[valid['area'] > 0].reset_index(drop=True)
print(f'Valid objects: {len(valid)}')

lats = valid['lat'].values
lons = valid['lng'].values
pm2 = valid['pm2'].values
areas = valid['area'].values
prices = valid['price'].values
floors = valid['floor'].values

print(f"{'Radius':>8}  {'Cover':>6}  {'MAPE':>6}  {'Median':>7}  {'P25':>5}  {'P75':>5}  {'Nbrs(med)':>10}")
for r in [300, 500, 700, 1000, 1500, 2000]:
    errs = []
    nbrs = []
    for i in range(len(valid)):
        dists = haversine_vec(lats[i], lons[i], lats, lons)
        nb = (dists > 100) & (floors == floors[i]) & (dists <= r)
        if nb.sum() < 2:
            continue
        pred = float(np.median(pm2[nb])) * areas[i]
        errs.append((pred - prices[i]) / prices[i])
        nbrs.append(int(nb.sum()))
    if not errs:
        print(f'{r:>7}m  no data')
        continue
    e = np.array(errs)
    cov = len(e) / len(valid) * 100
    print(f'{r:>7}m  {cov:>5.0f}%  {np.abs(e).mean()*100:>5.0f}%  {np.median(e)*100:>+6.0f}%  {np.quantile(e,0.25)*100:>+4.0f}%  {np.quantile(e,0.75)*100:>+4.0f}%  {int(np.median(nbrs)):>10}')
