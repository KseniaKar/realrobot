import pandas as pd
import json
import numpy as np
import re

# Загружаем данные
c = json.load(open('data/protocols/protocol_cache.json', encoding='utf-8'))
df = pd.read_csv('data/investmoscow_completed_2026-04-04_geocoded.csv', encoding='utf-8-sig')

# Чистим цены
df['начальная_цена_млн'] = df['начальная_цена_руб'].astype(str).str.replace(',', '.').astype(float) / 1e6
df['итоговая_цена_млн'] = df['итоговая_цена_руб'].astype(str).str.replace(',', '.').astype(float) / 1e6
df['цена_за_м2'] = df['цена_за_м²'].astype(str).str.replace(',', '.').astype(float)

# Превышение: строка → число, NaN = не состоялись
df['превышение_str'] = df['превышение_цены_%'].fillna('Не состоялся')
df['превышение'] = df['превышение_str'].apply(lambda x: float(x.replace('%', '')) if x != 'Не состоялся' else None)

# Добавляем участников
df = df.merge(
    pd.DataFrame([{'lot_id': int(k), 'участники': v.get('participants_count', 0)} for k, v in c.items()]),
    left_on='номер_лота', right_on='lot_id', how='left'
)
df['участники'] = df['участники'].fillna(0).astype(int)

# Статус
df['состоялись'] = df['итоговая_цена_руб'].notna().astype(int)
df['отриц_превыш'] = (df['превышение'].notna()) & (df['превышение'] < 0)

# Этаж категория
def classify_floor(s):
    if not isinstance(s, str): return 'unknown'
    s = s.lower().strip()
    if 'подвал' in s: return 'подвал'
    if 'цоколь' in s: return 'цоколь'
    m = re.search(r'(\d+)', s)
    if m:
        f = int(m.group(1))
        if f == 1: return '1 этаж'
        elif f == 2: return '2 этаж'
        elif f == 3: return '3 этаж'
        elif f <= 5: return '4-5 этажи'
        else: return '6+ этажи'
    return 'unknown'

df['этаж_кат'] = df['этаж'].apply(classify_floor)

# Округ
def extract_okrug(addr):
    if not isinstance(addr, str): return 'Неизвестно'
    parts = addr.split(',')
    if parts:
        first = parts[0].strip()
        if 'административный округ' in first:
            return first
    return 'Неизвестно'

OKRUG_SHORT = {
    "Центральный административный округ": "ЦАО",
    "Западный административный округ": "ЗАО",
    "Северо-Западный административный округ": "СЗАО",
    "Северный административный округ": "САО",
    "Северо-Восточный административный округ": "СВАО",
    "Восточный административный округ": "ВАО",
    "Юго-Восточный административный округ": "ЮВАО",
    "Южный административный округ": "ЮАО",
    "Юго-Западный административный округ": "ЮЗАО",
    "Зеленоградский административный округ": "ЗелАО",
    "Новомосковский административный округ": "НАО",
    "Троицкий административный округ": "ТАО",
}
df['округ'] = df['адрес'].apply(extract_okrug).map(OKRUG_SHORT).fillna('Другое')

# Форма торгов
df['форма'] = df['форма_проведения'].fillna('Неизвестно')

print('=' * 80)
print('КОМПЛЕКСНЫЙ АНАЛИЗ ТОРГОВ INVESTMOSCOW.RU')
print(f'Всего лотов: {len(df)}')
print(f'Состоялись: {df["состоялись"].sum()} ({df["состоялись"].mean()*100:.0f}%)')
print(f'Отриц. превышение: {df["отриц_превыш"].sum()} ({df["отриц_превыш"].mean()*100:.0f}%)')
print('=' * 80)

# ═══════════════════════════════════════════════
#  1. КОРРЕЛЯЦИЯ: от чего зависит количество участников
# ═══════════════════════════════════════════════
print('\n\n1. КОРРЕЛЯЦИЯ: от чего зависит количество участников')
print('-' * 80)

# Только лоты с участниками > 0 и превышением >= 0
df_with_participants = df[(df['участники'] > 0) & (df['превышение'].notna())].copy()

if len(df_with_participants) > 0:
    corr_cols = ['участники', 'превышение', 'площадь_м²', 'начальная_цена_млн', 'цена_за_м2']
    corr_labels_map = {
        'участники': 'Участники',
        'превышение': 'Превышение',
        'площадь_м²': 'Площадь (м²)',
        'начальная_цена_млн': 'Нач.цена (млн)',
        'цена_за_м2': 'Цена/м²'
    }
    
    corr_matrix = df_with_participants[corr_cols].corr()
    for col in corr_cols[1:]:
        r = corr_matrix.loc['участники', col]
        print(f'{corr_labels_map[col]:<20} r = {r:+.3f}')

# По форме торгов
print(f'\nСр.участники по форме торгов:')
for form in df['форма'].unique():
    sub = df[df['форма'] == form]
    if len(sub) > 10:
        avg = sub['участники'].mean()
        print(f'  {form:<50} {avg:.2f} (лотов: {len(sub)})')

# По округу
print(f'\nСр.участники по округу:')
for okrug in sorted(df['округ'].unique()):
    sub = df[df['округ'] == okrug]
    if len(sub) > 10:
        avg = sub['участники'].mean()
        print(f'  {okrug:<6} {avg:.2f} (лотов: {len(sub)})')

# ═══════════════════════════════════════════════
#  2. УСПЕШНОСТЬ: от чего зависит состоялись торги
# ═══════════════════════════════════════════════
print('\n\n2. УСПЕШНОСТЬ: от чего зависят успешные торги')
print('-' * 80)

# По этажам
print(f'\nУспешность по этажам:')
for cat in ['подвал', 'цоколь', '1 этаж', '2 этаж', '3 этаж', '4-5 этажи', '6+ этажи']:
    sub = df[df['этаж_кат'] == cat]
    if len(sub) > 0:
        success = sub['состоялись'].mean() * 100
        avg_part = sub['участники'].mean()
        print(f'  {cat:<20} успех: {success:.0f}%, ср.уч.: {avg_part:.1f}, лотов: {len(sub)}')

# По цене
print(f'\nУспешность по начальной цене:')
price_ranges = [(0, 10), (10, 30), (30, 50), (50, 100), (100, 9999)]
for low, high in price_ranges:
    sub = df[(df['начальная_цена_млн'] >= low) & (df['начальная_цена_млн'] < high)]
    if len(sub) > 0:
        success = sub['состоялись'].mean() * 100
        print(f'  {low}-{high:>3} млн руб   успех: {success:.0f}%, лотов: {len(sub)}')

# По площади
print(f'\nУспешность по площади:')
area_ranges = [(0, 50), (50, 100), (100, 200), (200, 500), (500, 9999)]
for low, high in area_ranges:
    sub = df[(df['площадь_м²'] >= low) & (df['площадь_м²'] < high)]
    if len(sub) > 0:
        success = sub['состоялись'].mean() * 100
        print(f'  {low:>3}-{high:>3} м²        успех: {success:.0f}%, лотов: {len(sub)}')

# По форме торгов
print(f'\nУспешность по форме торгов:')
for form in df['форма'].unique():
    sub = df[df['форма'] == form]
    if len(sub) > 10:
        success = sub['состоялись'].mean() * 100
        print(f'  {form:<50} {success:.0f}% (лотов: {len(sub)})')

# ═══════════════════════════════════════════════
#  3. ОТРИЦАТЕЛЬНОЕ ПРЕВЫШЕНИЕ: когда цена падает
# ═══════════════════════════════════════════════
print('\n\n3. ОТРИЦАТЕЛЬНОЕ ПРЕВЫШЕНИЕ: когда цена падает')
print('-' * 80)

neg = df[df['отриц_превыш']].copy()
print(f'Всего лотов с отрицательным превышением: {len(neg)} ({len(neg)/len(df)*100:.1f}% от всех, {len(neg)/df["состоялись"].sum()*100:.1f}% от состоявшихся)')

if len(neg) > 0:
    print(f'\nСреднее снижение: {neg["превышение"].mean():.1f}%')
    print(f'Медианное снижение: {neg["превышение"].median():.1f}%')
    print(f'Максимальное снижение: {neg["превышение"].min():.1f}%')
    
    print(f'\nПо форме торгов:')
    for form in neg['форма'].unique():
        sub = neg[neg['форма'] == form]
        if len(sub) > 5:
            print(f'  {form:<50} {len(sub)} лотов, ср.снижение: {sub["превышение"].mean():.1f}%')
    
    print(f'\nПо этажам:')
    for cat in ['подвал', 'цоколь', '1 этаж', '2 этаж', '3 этаж', '4-5 этажи']:
        sub = neg[neg['этаж_кат'] == cat]
        if len(sub) > 0:
            print(f'  {cat:<20} {len(sub)} лотов ({len(sub)/len(df[df["этаж_кат"]==cat])*100:.0f}% от этажа), ср.снижение: {sub["превышение"].mean():.1f}%')

# ═══════════════════════════════════════════════
#  4. КОРРЕЛЯЦИЯ: от чего зависит превышение цены
# ═══════════════════════════════════════════════
print('\n\n4. КОРРЕЛЯЦИЯ: от чего зависит превышение цены')
print('-' * 80)

df_valid = df[df['превышение'].notna()].copy()
if len(df_valid) > 0:
    corr_cols = ['превышение', 'участники', 'площадь_м²', 'начальная_цена_млн', 'цена_за_м2']
    corr_labels_map = {
        'участники': 'Участники',
        'превышение': 'Превышение',
        'площадь_м²': 'Площадь (м²)',
        'начальная_цена_млн': 'Нач.цена (млн)',
        'цена_за_м2': 'Цена/м²'
    }
    
    corr_matrix = df_valid[corr_cols].corr()
    for col in corr_cols[1:]:
        r = corr_matrix.loc['превышение', col]
        print(f'{corr_labels_map[col]:<20} r = {r:+.3f}')

# ═══════════════════════════════════════════════
#  5. КЛЮЧЕВЫЕ ИНСАЙТЫ
# ═══════════════════════════════════════════════
print('\n\n5. КЛЮЧЕВЫЕ ИНСАЙТЫ')
print('=' * 80)

# Инсайт 1: Цена → успех
print(f'\n💰 ЦЕНА:')
for low, high in [(0, 10), (10, 30), (30, 50), (50, 100), (100, 9999)]:
    sub = df[(df['начальная_цена_млн'] >= low) & (df['начальная_цена_млн'] < high)]
    if len(sub) > 0:
        success = sub['состоялись'].mean() * 100
        print(f'   {low}-{high:>3} млн: успех {success:.0f}%')

# Инсайт 2: Площадь → успех
print(f'\n📏 ПЛОЩАДЬ:')
for low, high in [(0, 50), (50, 100), (100, 200), (200, 500), (500, 9999)]:
    sub = df[(df['площадь_м²'] >= low) & (df['площадь_м²'] < high)]
    if len(sub) > 0:
        success = sub['состоялись'].mean() * 100
        print(f'   {low:>3}-{high:>3} м²: успех {success:.0f}%')

# Инсайт 3: Этаж
print(f'\n📍 ЭТАЖ:')
for cat in ['подвал', 'цоколь', '1 этаж', '2 этаж', '3 этаж', '4-5 этажи']:
    sub = df[df['этаж_кат'] == cat]
    if len(sub) > 0:
        success = sub['состоялись'].mean() * 100
        print(f'   {cat:<20} успех {success:.0f}%, ср.уч.: {sub["участники"].mean():.1f}')

# Инсайт 4: Формат
print(f'\n📋 ФОРМАТ ТОРГОВ:')
for form in df['форма'].unique():
    sub = df[df['форма'] == form]
    if len(sub) > 10:
        success = sub['состоялись'].mean() * 100
        pos_excess = sub[sub['превышение'].notna()]['превышение'].mean() if sub['превышение'].notna().any() else 0
        print(f'   {form:<50} успех {success:.0f}%, превыш. {pos_excess:+.1f}%')

# Инсайт 5: Корреляции
print(f'\n🔗 КОРРЕЛЯЦИИ:')
if len(df_with_participants) > 0:
    corr_matrix = df_with_participants[corr_cols].corr()
    for col in corr_cols[1:]:
        r = corr_matrix.loc['участники', col]
        print(f'   Участники ↔ {corr_labels_map[col]:<20} r = {r:+.3f}')

print(f'\n🔗 Превышение:')
if len(df_valid) > 0:
    corr_matrix = df_valid[corr_cols].corr()
    for col in corr_cols[1:]:
        r = corr_matrix.loc['превышение', col]
        print(f'   Превышение ↔ {corr_labels_map[col]:<15} r = {r:+.3f}')
