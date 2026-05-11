"""
Дедупликация sale.csv:
- Группа = (coord ~50м, этаж, area_bucket)
- Для маленьких площадей (<15м²) бакет 1м², иначе 5м²
- В каждой группе оставляем строку с самой поздней датой
- Сохраняет data/sale_dedup.csv
"""
import re
import numpy as np
import pandas as pd

SRC  = 'C:/git/realrobot/look_a_like_prices/data/sale.csv/sale.csv'
DST  = 'C:/git/realrobot/look_a_like_prices/data/sale_dedup.csv'

def get_param(s, key):
    if not isinstance(s, str): return None
    m = re.search(rf'{re.escape(key)}=([^|]+)', s)
    return m.group(1).strip() if m else None

df = pd.read_csv(SRC, sep=';')
print(f'Исходных строк: {len(df)}')

df['площадь'] = df['Доп.параметры'].apply(lambda x: get_param(x, 'Общая площадь'))
df['площадь'] = pd.to_numeric(df['площадь'].str.replace(',', '.'), errors='coerce')
df['этаж']    = df['Доп.параметры'].apply(lambda x: get_param(x, 'Этаж'))
df['lat']     = pd.to_numeric(df['lat'], errors='coerce')
df['lng']     = pd.to_numeric(df['lng'], errors='coerce')
df['дата_dt'] = pd.to_datetime(df['Дата'], errors='coerce')

# строки без координат/площади/этажа — не дедуплицируем, просто оставляем
has_geo = df['lat'].notna() & df['lng'].notna() & df['площадь'].notna() & df['этаж'].notna()
df_geo  = df[has_geo].copy()
df_nogeo = df[~has_geo].copy()
print(f'  С координатами + площадь + этаж: {len(df_geo)}')
print(f'  Без (оставляем как есть):        {len(df_nogeo)}')

# area_bucket: мелкие объекты — шаг 1м², крупные — шаг 5м²
df_geo['area_g'] = np.where(
    df_geo['площадь'] < 15,
    df_geo['площадь'].round().astype('Int64'),
    (df_geo['площадь'] / 5).round().astype(int)
)

df_geo['lat_g'] = (df_geo['lat'] * 2000).round().astype(int)
df_geo['lng_g'] = (df_geo['lng'] * 2000).round().astype(int)
df_geo['group'] = (df_geo['lat_g'].astype(str) + '_' +
                   df_geo['lng_g'].astype(str) + '_' +
                   df_geo['этаж'].astype(str)  + '_' +
                   df_geo['area_g'].astype(str))

before = len(df_geo)
df_geo = df_geo.sort_values('дата_dt', ascending=False).drop_duplicates(subset='group', keep='first')
after  = len(df_geo)
print(f'\nДедупликация: {before} -> {after} (убрано {before - after} строк, {(before-after)/before*100:.1f}%)')

# статистика по группам
grp_sizes = df[has_geo].groupby(
    (df[has_geo]['lat'].pipe(lambda s: (s * 2000).round().astype(int)).astype(str) + '_' +
     df[has_geo]['lng'].pipe(lambda s: (s * 2000).round().astype(int)).astype(str) + '_' +
     df[has_geo]['этаж'].astype(str))
).size()
print(f'Уникальных зданий (coord+этаж): {len(grp_sizes)}')
print(f'Зданий с >1 объявлением: {(grp_sizes > 1).sum()}')

# итоговый датасет
result = pd.concat([df_geo.drop(columns=['площадь','этаж','дата_dt','lat_g','lng_g','area_g','group']),
                    df_nogeo], ignore_index=True)
print(f'\nФинальных строк: {len(result)}')
print(f'Источники: {result["Источник"].value_counts().to_dict()}')

result.to_csv(DST, index=False, sep=';', encoding='utf-8-sig')
print(f'\nСохранено: {DST}')
