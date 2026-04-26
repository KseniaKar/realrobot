"""
Объединённый анализ всех исторических данных 2022-2026
"""
import pandas as pd
import numpy as np
import re, os, sys
sys.stdout.reconfigure(encoding='utf-8')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
EXCLUDED_EXCEEDANCE_FORMS = {
    'Публичное предложение',
    'Без объявления цены',
}

def to_num(s):
    if pd.isna(s): return np.nan
    s = str(s).replace('\xa0','').replace(' ','').replace(',','.')
    s = re.sub(r'[^\d.]','',s).strip('.')
    return float(s) if s else np.nan

print("[1/4] Загрузка...")
merged_path = os.path.join(DATA_DIR, 'investmoscow_completed_2022_2026_geocoded.csv')
if os.path.exists(merged_path):
    df = pd.read_csv(merged_path, encoding='utf-8-sig')
    df['_period'] = df['год_торгов'].astype(str)
    print(f"  2022-2026: {len(df)} записей из объединённого файла")
else:
    files = [
        ('2022-2023', 'investmoscow_completed_2022_2023_2026-04-11.csv'),
        ('2024', 'investmoscow_completed_2024_2026-04-11.csv'),
        ('2025-2026', 'investmoscow_completed_2026-04-04_geocoded.csv'),
    ]
    frames = []
    for period, fname in files:
        path = os.path.join(DATA_DIR, fname)
        if not os.path.exists(path):
            print(f"  ПРОПУЩЕН: {fname}")
            continue
        df = pd.read_csv(path, encoding='utf-8-sig')
        df['_period'] = period
        frames.append(df)
        print(f"  {period}: {len(df)} записей")

    df = pd.concat(frames, ignore_index=True)

df['deposit'] = df['размер_задатка_руб'].apply(to_num)
df['start_price'] = pd.to_numeric(df['начальная_цена_руб'], errors='coerce')
df['final_price'] = df['итоговая_цена_руб'].apply(to_num)
df['exceedance'] = df['превышение_цены_%'].apply(lambda x: to_num(str(x).replace('%','')) if pd.notna(x) else np.nan)
df['area'] = pd.to_numeric(df['площадь_м²'], errors='coerce')
df['deposit_pct'] = (df['deposit'] / df['start_price'] * 100).round(1)
df.loc[df['форма_проведения'].isin(EXCLUDED_EXCEEDANCE_FORMS), 'exceedance'] = np.nan
auction_mask = df['форма_проведения'].eq('Открытый аукцион в электронной форме')
df.loc[auction_mask & (df['final_price'] <= 0), 'final_price'] = np.nan
df.loc[auction_mask & (df['exceedance'] < 0), 'exceedance'] = np.nan

# Извлекаем год из дат
def extract_year(row):
    year_val = row.get('год_торгов')
    if pd.notna(year_val):
        try:
            return int(year_val)
        except:
            pass
    for col in ['дата_подведения_итогов','дата_проведения_торгов']:
        val = str(row.get(col,''))
        if val and val != 'nan':
            m = re.search(r'(\d{4})', val)
            if m: return int(m.group(1))
    p = str(row['_period'])
    return int(p[:4])
df['trade_year'] = df.apply(extract_year, axis=1)
years = sorted(df['trade_year'].unique())

print(f"\n  Всего: {len(df)} лотов, годы: {years}")

# ============================================================
# Статистика
# ============================================================
print(f"\n[2/4] Статистика по годам...")
print(f"\n  {'Год':>6} {'Лотов':>7} {'Площадь м²':>11} {'Нач.цена млн':>13} {'Итог.цена млн':>14} {'Превыш.>0':>11}")
print(f"  {'-'*70}")
for y in years:
    d = df[df['trade_year']==y]
    n = len(d)
    a = d['area'].median()
    sp = d['start_price'].median()/1e6
    fp = d['final_price'].median()/1e6
    with_exc = d['exceedance'].notna().sum()
    pos_exc = (d['exceedance']>0).sum()
    print(f"  {y:>6} {n:>7} {a:>11.1f} {sp:>13.1f} {fp:>14.1f} {pos_exc:>7}/{with_exc}")

# Задаток
print(f"\n[3/4] Задаток по годам...")
print(f"\n  {'Год':>6} {'Фикс.500к':>10} {'10%':>8} {'20%+':>8} {'Нет задатка':>12}")
print(f"  {'-'*50}")
for y in years:
    d = df[df['trade_year']==y]
    n = len(d)
    f500 = ((d['deposit']-500000).abs()<1).sum()
    p10 = ((d['deposit_pct']-10).abs()<0.5).sum()
    p20 = (d['deposit_pct']>=19.5).sum()
    no = d['deposit'].isna().sum()
    print(f"  {y:>6} {f500:>10} {p10:>8} {p20:>8} {no:>12}")

# Превышение
print(f"\n  {'Год':>6} {'Ср.превыш.':>12} {'Медиана':>10} {'0%':>6} {'>0%':>6} {'<0%':>6} {'>50%':>6} {'>100%':>7}")
print(f"  {'-'*62}")
for y in years:
    d = df[df['trade_year']==y]
    exc = d['exceedance'].dropna()
    if len(exc)==0: continue
    print(f"  {y:>6} {exc.mean():>11.1f}% {exc.median():>9.1f}% {(exc==0).sum():>6} {(exc>0).sum():>6} {(exc<0).sum():>6} {(exc>50).sum():>6} {(exc>100).sum():>7}")

# ============================================================
# Графики
# ============================================================
print(f"\n[4/4] Графики...")
fig, axes = plt.subplots(2, 3, figsize=(18,12))
fig.suptitle('Обзор исторических данных 2022-2026', fontsize=16, fontweight='bold')

# 1. Лотов по годам
ax = axes[0,0]
counts = [len(df[df['trade_year']==y]) for y in years]
ax.bar(range(len(years)), counts, color='#3498db', alpha=0.8)
ax.set_xticks(range(len(years)))
ax.set_xticklabels(years)
ax.set_ylabel('Кол-во лотов')
ax.set_title('Лотов по годам')
for i,c in enumerate(counts):
    ax.text(i, c+20, str(c), ha='center', fontsize=10)

# 2. Медиана превышения
ax = axes[0,1]
medians = [df[df['trade_year']==y]['exceedance'].dropna().median() for y in years]
ax.bar(range(len(years)), medians, color='#2ecc71', alpha=0.8)
ax.set_xticks(range(len(years)))
ax.set_xticklabels(years)
ax.set_ylabel('Медиана превышения (%)')
ax.set_title('Медиана превышения по годам')
for i,m in enumerate(medians):
    ax.text(i, m+0.5, f'{m:.1f}%', ha='center', fontsize=10)

# 3. Тип задатка
ax = axes[0,2]
f500s, p10s, p20s = [], [], []
for y in years:
    d = df[df['trade_year']==y]
    f500s.append(((d['deposit']-500000).abs()<1).sum())
    p10s.append(((d['deposit_pct']-10).abs()<0.5).sum())
    p20s.append((d['deposit_pct']>=19.5).sum())
x = np.arange(len(years)); w = 0.25
ax.bar(x-w, f500s, w, label='Фикс. 500к', color='#9b59b6', alpha=0.8)
ax.bar(x, p10s, w, label='10%', color='#3498db', alpha=0.8)
ax.bar(x+w, p20s, w, label='20%+', color='#e74c3c', alpha=0.8)
ax.set_xticks(x); ax.set_xticklabels(years)
ax.set_ylabel('Кол-во лотов'); ax.set_title('Тип задатка по годам')
ax.legend(fontsize=9)

# 4. Распределение превышения
ax = axes[1,0]
exc = df['exceedance'].dropna()
exc = exc[exc.between(-60,200)]
ax.hist(exc, bins=50, color='#3498db', alpha=0.7, edgecolor='white')
ax.axvline(0, color='black', linestyle='--', linewidth=1)
ax.set_xlabel('Превышение (%)'); ax.set_ylabel('Кол-во')
ax.set_title(f'Распределение превышения (n={len(exc)})')

# 5. Цена vs площадь
ax = axes[1,1]
s = df.dropna(subset=['start_price','area']).sample(min(500, len(df)), random_state=42)
ax.scatter(s['area'], s['start_price']/1e6, alpha=0.3, s=10, color='#3498db')
ax.set_xlabel('Площадь (м²)'); ax.set_ylabel('Нач.цена (млн ₽)')
ax.set_title('Цена vs площадь (выборка 500)')
ax.set_xscale('log'); ax.set_yscale('log')

# 6. Итоговая vs начальная цена
ax = axes[1,2]
s2 = df.dropna(subset=['start_price','final_price']).sample(min(500, len(df)), random_state=42)
ax.scatter(s2['start_price']/1e6, s2['final_price']/1e6, alpha=0.3, s=10, color='#e74c3c')
mx = max(s2['start_price'].max(), s2['final_price'].max())/1e6
ax.plot([0,mx],[0,mx],'r--',alpha=0.5)
ax.set_xlabel('Нач.цена (млн ₽)'); ax.set_ylabel('Итог.цена (млн ₽)')
ax.set_title('Начальная vs итоговая цена')

plt.tight_layout()
out = os.path.join(os.path.dirname(__file__), 'all_data_overview.png')
plt.savefig(out, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Сохранено: {out}")

print(f"\n{'='*60}")
print(f"  ИТОГО: {len(df)} лотов за {min(years)}-{max(years)}")
print(f"  С задатком: {df['deposit'].notna().sum()} ({df['deposit'].notna().mean()*100:.0f}%)")
print(f"  С итоговой ценой: {df['final_price'].notna().sum()}")
print(f"  Медиана площади: {df['area'].median():.1f} м²")
print(f"  Медиана нач.цены: {df['start_price'].median()/1e6:.1f} млн ₽")
