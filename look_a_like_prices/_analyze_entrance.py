import numpy as np
import pandas as pd
import re

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

# загружаем основной датасет
df = pd.read_excel('C:/git/realrobot/look_a_like_prices/excel2-30025-1.xlsx')
df['площадь'] = df.apply(_get_area, axis=1)
df['цена'] = pd.to_numeric(df['Цена'], errors='coerce')
df['цена_за_м2'] = np.where(df['площадь'].fillna(0) > 0, df['цена'] / df['площадь'], np.nan)
df['этаж_норм'] = df['Доп.параметры'].apply(lambda x: _parse_param(x, 'Этаж')).apply(normalize_floor)

# джойним тип входа
NORM = {
    'отдельный с улицы': 'отдельный с улицы', 'separateFromTheStreet': 'отдельный с улицы',
    'separateFromStreet': 'отдельный с улицы',
    'отдельный со двора': 'отдельный со двора', 'separateFromTheYard': 'отдельный со двора',
    'separateFromYard': 'отдельный со двора',
    'commonFromStreet': 'общий с улицы', 'commonFromTheStreet': 'общий с улицы',
    'commonFromYard': 'общий со двора', 'commonFromTheYard': 'общий со двора',
    'throughEntrance': 'через подъезд', 'throughHall': 'через холл',
}
entrance = pd.read_csv('C:/git/realrobot/look_a_like_prices/_entrance_results.csv', encoding='utf-8-sig')
if 'тип_входа' not in entrance.columns:
    entrance['тип_входа'] = entrance['тип_входа_циан'].map(NORM)
df = df.merge(entrance[['URL', 'тип_входа']], on='URL', how='left')

print(f'Всего: {len(df)}, с типом входа: {df["тип_входа"].notna().sum()}')
print()

# медиана цены/м² по типу входа
valid = df.dropna(subset=['цена_за_м2', 'тип_входа'])
stats = (
    valid.groupby('тип_входа')['цена_за_м2']
    .agg(n='count', median='median', mean='mean', p25=lambda x: x.quantile(0.25), p75=lambda x: x.quantile(0.75))
    .reset_index()
    .sort_values('median', ascending=False)
)
stats['median_тр'] = (stats['median'] / 1000).round(0)
stats['p25_тр'] = (stats['p25'] / 1000).round(0)
stats['p75_тр'] = (stats['p75'] / 1000).round(0)
print('Цена/м² по типу входа (тр/м²):')
print(stats[['тип_входа','n','median_тр','p25_тр','p75_тр']].to_string(index=False))
print()

# то же самое только для 1-го этажа (чтобы убрать влияние этажа)
valid1 = valid[valid['этаж_норм'] == '1']
stats1 = (
    valid1.groupby('тип_входа')['цена_за_м2']
    .agg(n='count', median='median', p25=lambda x: x.quantile(0.25), p75=lambda x: x.quantile(0.75))
    .reset_index()
    .sort_values('median', ascending=False)
)
stats1['median_тр'] = (stats1['median'] / 1000).round(0)
stats1['p25_тр'] = (stats1['p25'] / 1000).round(0)
stats1['p75_тр'] = (stats1['p75'] / 1000).round(0)
print('Только 1-й этаж:')
print(stats1[['тип_входа','n','median_тр','p25_тр','p75_тр']].to_string(index=False))
print()

# дисконт относительно "отдельный с улицы"
base = stats1[stats1['тип_входа'] == 'отдельный с улицы']['median'].values
if len(base):
    base = base[0]
    print('Дисконт к "отдельный с улицы" (1-й этаж):')
    for _, row in stats1.iterrows():
        discount = (row['median'] - base) / base * 100
        print(f"  {row['тип_входа']:25s}  {discount:+.0f}%  (n={int(row['n'])})")
