import pandas as pd
import glob

FIAS = 'Глобальный уникальный идентификатор дома по ФИАС'
AREA_TOTAL = 'Общая площадь дома'
AREA_LIVING = 'Жилая площадь в доме'
TIP = 'Тип помещения (блока)'
NOM = 'Номер помещения (блока)'
ADDR = 'Адрес ОЖФ'

print('Читаем ЖКХ...')
files = glob.glob('C:/git/realrobot/look_a_like_prices/data/zhk/*.csv')
dfs = []
for f in files:
    dfs.append(pd.read_csv(f, sep='|', encoding='utf-8-sig', usecols=[FIAS, AREA_TOTAL, AREA_LIVING, TIP, NOM, ADDR], dtype=str))
df = pd.concat(dfs, ignore_index=True)
print(f'  Строк: {len(df):,}')

# агрегируем по дому
print('Агрегируем по домам...')
apts = df[df[NOM].notna() & df[FIAS].notna()].copy()
apts['is_living'] = apts[TIP].str.strip() == 'Жилое'

agg = apts.groupby(FIAS).agg(
    apt_total=('is_living', 'count'),
    apt_living=(('is_living'), 'sum'),
).reset_index()
agg.columns = ['fias', 'apt_total', 'apt_living']

# берём площадь и адрес из первой строки каждого дома
meta = df[df[FIAS].notna()].drop_duplicates(subset=[FIAS])[[FIAS, AREA_TOTAL, AREA_LIVING, ADDR]].copy()
meta.columns = ['fias', 'area_total_m2', 'area_living_m2', 'address']
meta['area_total_m2'] = pd.to_numeric(meta['area_total_m2'].str.replace(',', '.'), errors='coerce')
meta['area_living_m2'] = pd.to_numeric(meta['area_living_m2'].str.replace(',', '.'), errors='coerce')

buildings = agg.merge(meta, on='fias', how='left')
print(f'  Уникальных домов: {len(buildings):,}')

# джойним координаты
print('Джойним координаты...')
coords = pd.read_csv('C:/git/realrobot/look_a_like_prices/data/moscow_addresses.csv')
coords.columns = ['fias', 'address_geo', 'lat', 'lng']

buildings = buildings.merge(coords[['fias', 'lat', 'lng']], on='fias', how='left')
has_coords = buildings['lat'].notna().sum()
print(f'  С координатами: {has_coords:,} из {len(buildings):,} ({has_coords/len(buildings)*100:.1f}%)')

# оставляем только с координатами
buildings = buildings[buildings['lat'].notna()].copy()
buildings['residents_est'] = (buildings['apt_living'] * 2.4).round(0).astype(int)

print()
print('Итог:')
print(f'  Домов с координатами: {len(buildings):,}')
print(f'  Квартир всего: {buildings["apt_living"].sum():,.0f}')
print(f'  Жителей (оценка): {buildings["residents_est"].sum():,.0f}')
print()
print(buildings[['fias','address','lat','lng','apt_living','area_living_m2','residents_est']].head(3).to_string())

out = 'C:/git/realrobot/look_a_like_prices/data/buildings_moscow.parquet'
buildings.to_parquet(out, index=False)
print(f'\nСохранено: {out}')
