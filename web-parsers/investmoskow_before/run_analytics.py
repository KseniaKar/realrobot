"""
Запуск аналитики из ноутбука как обычного скрипта
"""
import pandas as pd
import numpy as np
import re
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import seaborn as sns
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

plt.style.use('seaborn-v0_8-whitegrid')
plt.rcParams['font.size'] = 11
plt.rcParams['figure.figsize'] = (12, 6)

CSV_PATH = Path('data/investmoscow_completed_2026-04-04.csv')
CHARTS_DIR = Path('data/charts')
CHARTS_DIR.mkdir(exist_ok=True)

df = pd.read_csv(CSV_PATH, encoding='utf-8-sig')
print(f'Загружено: {len(df)} записей')

# === Преобразование типов ===
def clean_num(s):
    if pd.isna(s) or s == '':
        return np.nan
    s = str(s).replace('\xa0', '').replace(' ', '')
    # Убираем 'руб.' в любых вариантах
    s = s.replace('руб.', '').replace('руб', '').replace('₽', '')
    s = s.replace(',', '.').strip()
    try:
        return float(s)
    except:
        return np.nan

df['start_price'] = pd.to_numeric(df['начальная_цена_руб'], errors='coerce')
df['final_price'] = df['итоговая_цена_руб'].apply(clean_num)
df['deposit'] = df['размер_задатка_руб'].apply(clean_num)
df['bid_step'] = df['шаг_аукциона_руб'].apply(clean_num)
df['price_per_m2'] = pd.to_numeric(df['цена_за_м²'], errors='coerce')
df['area'] = pd.to_numeric(df['площадь_м²'], errors='coerce')
df['floors'] = pd.to_numeric(df['этажность'], errors='coerce')
df['exceedance'] = df['превышение_цены_%'].apply(lambda x: clean_num(str(x).replace('%', '')) if pd.notna(x) and x != '' else np.nan)
df['year'] = pd.to_numeric(df['год_торгов'], errors='coerce').astype('Int64')
df['request_end'] = pd.to_datetime(df['дата_окончания_приёма'], format='%d.%m.%Y %H:%M:%S', errors='coerce')
df['month'] = df['request_end'].dt.to_period('M')

# Округ
district_map = {
    'Центральный административный округ': 'ЦАО',
    'Северный административный округ': 'САО',
    'Северо-Восточный административный округ': 'СВАО',
    'Восточный административный округ': 'ВАО',
    'Юго-Восточный административный округ': 'ЮВАО',
    'Южный административный округ': 'ЮАО',
    'Юго-Западный административный округ': 'ЮЗАО',
    'Западный административный округ': 'ЗАО',
    'Северо-Западный административный округ': 'СЗАО',
    'Зеленоградский административный округ': 'ЗелАО',
    'Новомосковский административный округ': 'НАО',
    'Троицкий административный округ': 'ТАО',
}

def extract_district(addr):
    if pd.isna(addr):
        return 'Неизвестно'
    # Сначала пробуем найти АО
    ao_match = re.search(r'([А-Я]{2,3}АО)', addr)
    if ao_match:
        return ao_match.group(1)
    # Потом полный вариант
    full_match = re.search(r'([А-Яа-яё\s]+административный округ)', addr)
    if full_match:
        return full_match.group(1).strip()
    return 'Неизвестно'

df['district_short'] = df['адрес'].apply(extract_district)
df['district_short'] = df['district_short'].replace(district_map)

def floor_category(floor):
    if pd.isna(floor):
        return 'Не указан'
    f = str(floor).lower().strip()
    if 'подвал' in f:
        return 'Подвал'
    if 'цокол' in f:
        return 'Цоколь'
    if f == '1':
        return '1 этаж'
    if f == '2':
        return '2 этаж'
    return '3+ этаж'

df['floor_cat'] = df['этаж'].apply(floor_category)

with_final = df[df['final_price'].notna()]
with_exceed = df[df['exceedance'].notna()]

print(f'С итоговыми ценами: {len(with_final)}')
print(f'С превышением: {len(with_exceed)}')

# === 1. Общая статистика ===
print('\n' + '='*60)
print('ОБЩАЯ СТАТИСТИКА')
print('='*60)
print(f"Всего завершенных торгов: {len(df):,}")
print(f"  2025 год: {(df['year'] == 2025).sum():,}")
print(f"  2026 год: {(df['year'] == 2026).sum():,}")
print(f"С известной итоговой ценой: {len(with_final):,} ({len(with_final)/len(df)*100:.1f}%)")
print(f"Без итоговой цены: {len(df) - len(with_final):,}")

if len(with_exceed) > 0:
    print(f"\nПревышение цены:")
    print(f"  Среднее: {with_exceed['exceedance'].mean():.1f}%")
    print(f"  Выше старта: {(with_exceed['exceedance'] > 0).sum()} ({(with_exceed['exceedance'] > 0).mean()*100:.1f}%)")
    print(f"  Ниже старта: {(with_exceed['exceedance'] < 0).sum()} ({(with_exceed['exceedance'] < 0).mean()*100:.1f}%)")
    print(f"  Без изменений: {(with_exceed['exceedance'] == 0).sum()}")

# === 2. Динамика по месяцам ===
print('\n[CHART] Monthly dynamics...')
monthly = df.groupby('month').agg(
    total=('номер_лота', 'count'),
    with_final=('final_price', lambda x: x.notna().sum()),
    avg_start=('start_price', 'mean'),
    avg_final=('final_price', 'mean'),
    avg_exceedance=('exceedance', 'mean'),
).reset_index()
monthly['month_str'] = monthly['month'].astype(str)

fig, axes = plt.subplots(2, 2, figsize=(16, 10))
fig.suptitle('Динамика торгов по месяцам', fontsize=14, fontweight='bold')

ax = axes[0, 0]
ax.bar(monthly['month_str'], monthly['total'], alpha=0.7, label='Всего', color='#2196F3')
ax.bar(monthly['month_str'], monthly['with_final'], alpha=0.9, label='С итоговой ценой', color='#4CAF50')
ax.set_ylabel('Количество торгов')
ax.set_title('Количество торгов по месяцам')
ax.legend()
ax.tick_params(axis='x', rotation=45)

ax = axes[0, 1]
ax.plot(monthly['month_str'], monthly['avg_start'] / 1e6, 'o-', label='Средняя стартовая', color='#FF5722')
ax.plot(monthly['month_str'], monthly['avg_final'] / 1e6, 's-', label='Средняя итоговая', color='#4CAF50')
ax.set_ylabel('Средняя цена, млн руб')
ax.set_title('Средние цены по месяцам')
ax.legend()
ax.tick_params(axis='x', rotation=45)

ax = axes[1, 0]
ax.bar(monthly['month_str'], monthly['avg_exceedance'], alpha=0.7, color='#FF9800')
ax.axhline(y=0, color='black', linewidth=0.5)
ax.set_ylabel('Среднее превышение, %')
ax.set_title('Среднее превышение цены по месяцам')
ax.tick_params(axis='x', rotation=45)

ax = axes[1, 1]
ax.plot(monthly['month_str'], monthly['with_final'] / monthly['total'] * 100, 'o-', color='#9C27B0', linewidth=2)
ax.set_ylabel('% с итоговой ценой')
ax.set_title('Доля успешных торгов по месяцам')
ax.tick_params(axis='x', rotation=45)

plt.tight_layout()
plt.savefig(CHARTS_DIR / 'monthly_dynamics.png', dpi=150, bbox_inches='tight')
plt.close()
print(f'  -> {CHARTS_DIR / "monthly_dynamics.png"}')

# === 3. Анализ по округам ===
print('\n[CHART] District analysis...')
district_stats = df.groupby('district_short').agg(
    count=('номер_лота', 'count'),
    avg_area=('area', 'mean'),
    avg_start=('start_price', 'mean'),
    avg_price_per_m2=('price_per_m2', 'mean'),
    success_rate=('final_price', lambda x: x.notna().sum() / len(x) * 100),
    avg_exceedance=('exceedance', 'mean'),
).sort_values('count', ascending=False)

fig, axes = plt.subplots(2, 2, figsize=(16, 10))
fig.suptitle('Анализ по округам Москвы', fontsize=14, fontweight='bold')

ax = axes[0, 0]
district_stats['count'].sort_values(ascending=True).plot(kind='barh', ax=ax, color='#2196F3')
ax.set_xlabel('Количество торгов')
ax.set_title('Количество торгов по округам')

ax = axes[0, 1]
avg_ppm = district_stats['avg_price_per_m2'].dropna().sort_values(ascending=True)
avg_ppm.plot(kind='barh', ax=ax, color='#FF9800')
ax.set_xlabel('Средняя цена за м², руб')
ax.set_title('Средняя цена за м² по округам')
ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f'{x:,.0f}'))

ax = axes[1, 0]
sr = district_stats['success_rate'].sort_values(ascending=True)
sr.plot(kind='barh', ax=ax, color='#4CAF50')
ax.set_xlabel('% успешных торгов')
ax.set_title('Доля успешных торгов по округам')

ax = axes[1, 1]
exc = district_stats['avg_exceedance'].dropna().sort_values(ascending=True)
colors = ['#F44336' if v < 0 else '#4CAF50' for v in exc]
exc.plot(kind='barh', ax=ax, color=colors)
ax.set_xlabel('Среднее превышение, %')
ax.set_title('Среднее превышение цены по округам')
ax.axvline(x=0, color='black', linewidth=0.5)

plt.tight_layout()
plt.savefig(CHARTS_DIR / 'district_analysis.png', dpi=150, bbox_inches='tight')
plt.close()
print(f'  -> {CHARTS_DIR / "district_analysis.png"}')

# === 4. Распределение цен ===
print('\n[CHART] Price distribution...')
fig, axes = plt.subplots(2, 2, figsize=(16, 10))
fig.suptitle('Распределение цен', fontsize=14, fontweight='bold')

ax = axes[0, 0]
valid_start = df['start_price'].dropna()
valid_start = valid_start[valid_start > 0]
ax.hist(np.log10(valid_start), bins=50, alpha=0.7, color='#2196F3', edgecolor='white')
ax.set_xlabel('log10(Начальная цена, руб)')
ax.set_ylabel('Частота')
ax.set_title('Распределение начальных цен (лог)')

ax = axes[0, 1]
valid_final = df['final_price'].dropna()
valid_final = valid_final[valid_final > 0]
ax.hist(np.log10(valid_final), bins=50, alpha=0.7, color='#4CAF50', edgecolor='white')
ax.set_xlabel('log10(Итоговая цена, руб)')
ax.set_ylabel('Частота')
ax.set_title('Распределение итоговых цен (лог)')

ax = axes[1, 0]
valid_ppm = df['price_per_m2'].dropna()
valid_ppm = valid_ppm[valid_ppm > 0]
q99 = valid_ppm.quantile(0.99)
valid_ppm = valid_ppm[valid_ppm <= q99]
ax.hist(valid_ppm / 1000, bins=50, alpha=0.7, color='#FF9800', edgecolor='white')
ax.set_xlabel('Цена за м², тыс руб')
ax.set_ylabel('Частота')
ax.set_title('Распределение цены за м² (без выбросов >99 перцентиля)')

ax = axes[1, 1]
valid_exc = df['exceedance'].dropna()
ax.hist(valid_exc, bins=50, alpha=0.7, color='#9C27B0', edgecolor='white')
ax.axvline(x=0, color='red', linestyle='--', linewidth=1, label='Без превышения')
ax.set_xlabel('Превышение, %')
ax.set_ylabel('Частота')
ax.set_title('Распределение превышения цены')
ax.legend()

plt.tight_layout()
plt.savefig(CHARTS_DIR / 'price_distribution.png', dpi=150, bbox_inches='tight')
plt.close()
print(f'  -> {CHARTS_DIR / "price_distribution.png"}')

# === 5. Этажи и площади ===
print('\n[CHART] Floor analysis...')
fig, axes = plt.subplots(1, 3, figsize=(18, 5))
fig.suptitle('Анализ по этажам и площадям', fontsize=14, fontweight='bold')

ax = axes[0]
floor_counts = df['floor_cat'].value_counts()
floor_counts.plot(kind='bar', ax=ax, color='#2196F3')
ax.set_ylabel('Количество')
ax.set_title('Распределение по этажам')
ax.tick_params(axis='x', rotation=45)

ax = axes[1]
floor_price = df.groupby('floor_cat')['price_per_m2'].mean().dropna().sort_values(ascending=True)
floor_price.plot(kind='barh', ax=ax, color='#FF9800')
ax.set_xlabel('Средняя цена за м², руб')
ax.set_title('Средняя цена за м² по типу этажа')

ax = axes[2]
floor_exc = df.groupby('floor_cat')['exceedance'].mean().dropna().sort_values(ascending=True)
floor_exc.plot(kind='barh', ax=ax, color='#4CAF50')
ax.set_xlabel('Среднее превышение, %')
ax.set_title('Среднее превышение по типу этажа')
ax.axvline(x=0, color='black', linewidth=0.5)

plt.tight_layout()
plt.savefig(CHARTS_DIR / 'floor_analysis.png', dpi=150, bbox_inches='tight')
plt.close()
print(f'  -> {CHARTS_DIR / "floor_analysis.png"}')

# === Площадь vs Цена ===
print('\n[CHART] Area vs Price...')
fig, axes = plt.subplots(1, 2, figsize=(16, 5))
fig.suptitle('Площадь vs Цена за м²', fontsize=14, fontweight='bold')

ax = axes[0]
valid = df[(df['area'].notna()) & (df['price_per_m2'].notna())]
valid = valid[(valid['area'] > 0) & (valid['price_per_m2'] > 0)]
valid = valid[(valid['area'] <= 500) & (valid['price_per_m2'] <= 500000)]
ax.scatter(valid['area'], valid['price_per_m2'], alpha=0.3, s=20, c='#2196F3')
ax.set_xlabel('Площадь, м²')
ax.set_ylabel('Цена за м², руб')
ax.set_title('Зависимость цены за м² от площади')
corr = valid['area'].corr(valid['price_per_m2'])
ax.text(0.05, 0.95, f'Корреляция: {corr:.3f}', transform=ax.transAxes,
        fontsize=12, verticalalignment='top',
        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

ax = axes[1]
valid2 = df[(df['area'].notna()) & (df['exceedance'].notna())]
valid2 = valid2[(valid2['area'] > 0) & (valid2['area'] <= 500)]
ax.scatter(valid2['area'], valid2['exceedance'], alpha=0.3, s=20, c='#FF9800')
ax.axhline(y=0, color='red', linestyle='--', linewidth=0.5)
ax.set_xlabel('Площадь, м²')
ax.set_ylabel('Превышение, %')
ax.set_title('Превышение цены от площади')
corr2 = valid2['area'].corr(valid2['exceedance'])
ax.text(0.05, 0.95, f'Корреляция: {corr2:.3f}', transform=ax.transAxes,
        fontsize=12, verticalalignment='top',
        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

plt.tight_layout()
plt.savefig(CHARTS_DIR / 'area_vs_price.png', dpi=150, bbox_inches='tight')
plt.close()
print(f'  -> {CHARTS_DIR / "area_vs_price.png"}')

# === Несостоявшиеся торги ===
print('\n[CHART] No final distribution...')
no_final = df[df['final_price'].isna()]
fig, ax = plt.subplots(figsize=(10, 5))
ax.hist(no_final['start_price'].dropna() / 1e6, bins=50, alpha=0.7, color='#F44336', edgecolor='white')
ax.set_xlabel('Начальная цена, млн руб')
ax.set_ylabel('Частота')
ax.set_title('Распределение начальных цен несостоявшихся торгов')
plt.tight_layout()
plt.savefig(CHARTS_DIR / 'no_final_distribution.png', dpi=150, bbox_inches='tight')
plt.close()
print(f'  -> {CHARTS_DIR / "no_final_distribution.png"}')

# === Топ конкурентных ===
print('\n' + '='*60)
print('ТОП-15 САМЫХ КОНКУРЕНТНЫХ ТОРГОВ')
print('='*60)
top_competitive = df[df['exceedance'].notna()].nlargest(15, 'exceedance')[[
    'номер_лота', 'адрес', 'area', 'start_price', 'final_price', 'exceedance', 'floor_cat', 'district_short'
]]
for _, row in top_competitive.iterrows():
    addr = str(row['адрес'])[:50] + '...' if len(str(row['адрес'])) > 50 else row['адрес']
    print(f"Лот {row['номер_лота']:>12} | {addr:<55} | {row['area']:>7.1f} м² | "
          f"{row['start_price']:>12,.0f} → {row['final_price']:>12,.0f} | {row['exceedance']:>+7.1f}%")

# === Выводы ===
print('\n' + '='*60)
print('КЛЮЧЕВЫЕ ВЫВОДЫ')
print('='*60)

total_start_value = df['start_price'].sum()
total_final_value = with_final['final_price'].sum() if len(with_final) > 0 else 0
print(f"\n1. ОБЪЁМ РЫНКА")
print(f"   Общая начальная стоимость: {total_start_value/1e9:.1f} млрд руб")
print(f"   Общая итоговая стоимость: {total_final_value/1e9:.1f} млрд руб")
print(f"   Допродано сверх старта: {(total_final_value - total_start_value)/1e9:+.1f} млрд руб")

if len(with_exceed) > 0:
    hot = (with_exceed['exceedance'] >= 50).sum()
    very_hot = (with_exceed['exceedance'] >= 100).sum()
    print(f"\n2. КОНКУРЕНТНОСТЬ")
    print(f"   {hot} лотов ушли с превышением >=50% от стартовой цены")
    print(f"   {very_hot} лотов ушли с превышением >=100% (удвоение и более)")

best_district = district_stats['avg_exceedance'].dropna().idxmax()
worst_district = district_stats['avg_exceedance'].dropna().idxmin()
print(f"\n3. ОКРУГА")
print(f"   Самое высокое превышение: {best_district} ({district_stats.loc[best_district, 'avg_exceedance']:.1f}%)")
print(f"   Самое низкое превышение: {worst_district} ({district_stats.loc[worst_district, 'avg_exceedance']:.1f}%)")

if len(floor_exc) > 0:
    print(f"\n4. ЭТАЖИ")
    print(f"   Наибольшее среднее превышение: {floor_exc.idxmax()} ({floor_exc.max():.1f}%)")
    print(f"   Наименьшее: {floor_exc.idxmin()} ({floor_exc.min():.1f}%)")

print(f"\n5. НЕСОСТОЯВШИЕСЯ ТОРГИ")
print(f"   {len(df) - len(with_final):,} лотов ({(len(df)-len(with_final))/len(df)*100:.1f}%) не имели итоговой цены")

print(f"\n{'='*60}")
print(f"Все графики сохранены в: {CHARTS_DIR}")
print(f"Готово!")
