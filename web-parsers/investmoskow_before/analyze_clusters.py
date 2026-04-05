import pandas as pd
import re

df = pd.read_csv('data/investmoscow_completed_2026-04-04_geocoded.csv', encoding='utf-8-sig')

# Чистим цены
df['цена_за_м2'] = df['цена_за_м²'].astype(str).str.replace(',', '.').astype(float)
df['превышение'] = df['превышение_цены_%'].astype(str).str.replace('%', '').astype(float).fillna(-1)

# Определяем категорию этажа
def classify_floor(этаж_str):
    if not isinstance(этаж_str, str):
        return 'unknown'
    s = этаж_str.lower().strip()
    if 'подвал' in s:
        return 'подвал'
    if 'цоколь' in s or 'цокольный' in s:
        return 'цоколь'
    # Ищем номер этажа
    m = re.search(r'(\d+)', s)
    if m:
        floor = int(m.group(1))
        if floor == 1:
            return '1 этаж'
        elif floor == 2:
            return '2 этаж'
        elif floor == 3:
            return '3 этаж'
        elif floor <= 5:
            return '4-5 этажи'
        else:
            return '6+ этажи'
    return 'unknown'

df['этаж_кат'] = df['этаж'].apply(classify_floor)

# Анализируем по этажам
print('=== АНАЛИЗ ПО ЭТАЖАМ ===')
print(f'{"Этаж":<20} {"Кол-во":>6} {"% от всех":>9} {"Ср.цена/м2":>10} {"Ср.площадь":>11} {"Ср.превыш":>10} {"Сост.":>6}')
print('-' * 80)

for cat in ['подвал', 'цоколь', '1 этаж', '2 этаж', '3 этаж', '4-5 этажи', '6+ этажи', 'unknown']:
    sub = df[df['этаж_кат'] == cat]
    if len(sub) == 0:
        continue
    ok = sub[sub['превышение'] >= 0]
    avg_price = sub['цена_за_м2'].mean()
    avg_area = sub['площадь_м²'].mean()
    avg_exc = ok['превышение'].mean() if len(ok) > 0 else 0
    success_pct = len(ok) / len(sub) * 100 if len(sub) > 0 else 0
    print(f'{cat:<20} {len(sub):>6} {len(sub)/len(df)*100:>8.1f}% {avg_price/1e3:>8.0f}K {avg_area:>8.0f}м2 {avg_exc:>8.1f}% {success_pct:>5.0f}%')

# А теперь: ЦЕНА за м2 vs ЭТАЖ - медианы по кластерам
print('\n\n=== РАСПРЕДЕЛЕНИЕ ЦЕНЫ ЗА м2 ПО ЭТАЖАМ (медиана) ===')
for cat in ['подвал', 'цоколь', '1 этаж', '2 этаж', '3 этаж', '4-5 этажи', '6+ этажи', 'unknown']:
    sub = df[df['этаж_кат'] == cat]
    if len(sub) == 0:
        continue
    median = sub['цена_за_м2'].median()
    q25 = sub['цена_за_м2'].quantile(0.25)
    q75 = sub['цена_за_м2'].quantile(0.75)
    print(f'{cat:<20} медиана: {median/1e3:>6.0f}K (Q25: {q25/1e3:.0f}K, Q75: {q75/1e3:.0f}K)')

# Кластеры: дешёвые (<=100К) и дорогие (>100К) внутри каждого этажа
print('\n\n=== ДОЛЯ ДОРОГИХ ЛОТОВ (>100К/м2) ПО ЭТАЖАМ ===')
for cat in ['подвал', 'цоколь', '1 этаж', '2 этаж', '3 этаж', '4-5 этажи', '6+ этажи']:
    sub = df[df['этаж_кат'] == cat]
    if len(sub) == 0:
        continue
    expensive = sub[sub['цена_за_м2'] >= 100000]
    cheap = sub[sub['цена_за_м2'] < 100000]
    print(f'{cat:<20} дорогие(>=100К): {len(expensive):>4} ({len(expensive)/len(sub)*100:.0f}%), дешёвые: {len(cheap):>4} ({len(cheap)/len(sub)*100:.0f}%)')
