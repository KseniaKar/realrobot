import pandas as pd
import glob

files = glob.glob('C:/git/realrobot/look_a_like_prices/data/zhk/*.csv')
dfs = []
for f in files:
    dfs.append(pd.read_csv(f, sep='|', encoding='utf-8-sig', dtype=str))
df = pd.concat(dfs, ignore_index=True)
print(f'Всего строк: {len(df)}')
print('Колонки:', df.columns.tolist())
print()

fias_col = 'Глобальный уникальный идентификатор дома по ФИАС'
area_col = 'Общая площадь дома'
living_col = 'Жилая площадь в доме'
tip_col = 'Тип помещения (блока)'
nom_col = 'Номер помещения (блока)'

print('Тип помещения (распределение):')
print(df[tip_col].value_counts().head(10).to_string())
print()

# только жилые квартиры — строки где Номер помещения заполнен
apts = df[df[nom_col].notna()]
print(f'Строк с квартирами: {len(apts)}')
print(f'Уникальных домов (ФИАС): {apts[fias_col].nunique()}')
print()

# координаты
coords = pd.read_csv('C:/git/realrobot/look_a_like_prices/data/moscow_addresses.csv')
print(f'Строк в coords (адреса→коорд): {len(coords)}')
print(f'Пример coords: {coords.head(2).to_string()}')
print()

# сколько домов из ЖКХ есть в координатах
unique_fias = apts[fias_col].dropna().unique()
coords_ids = set(coords['_id'].values)
matched = sum(1 for f in unique_fias if f in coords_ids)
print(f'Совпадений ФИАС → координаты: {matched} из {len(unique_fias)}')
