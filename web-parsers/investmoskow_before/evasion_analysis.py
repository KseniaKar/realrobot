"""
Статистика уклонения от договора по размеру задатка.
Уклонение = 2+ участников, но нет итоговой цены (победитель отказался подписывать).
"""
import pandas as pd
import numpy as np
import re
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'investmoskow_before', 'data')

def to_num(s):
    if pd.isna(s):
        return np.nan
    s = str(s).replace('\xa0', '').replace(' ', '').replace(',', '.')
    s = re.sub(r'[^\d.]', '', s).strip('.')
    return float(s) if s else np.nan

# ============================================================
# 1. Загрузка данных
# ============================================================
print("[1/4] Загрузка данных...")

# Completed с задатком
df = pd.read_csv(os.path.join(DATA_DIR, 'protocols', 'merged_data.csv'), encoding='utf-8-sig')
df['deposit'] = df['размер_задатка_руб'].apply(to_num)
df['start_price'] = pd.to_numeric(df['начальная_цена_руб'], errors='coerce')
df['final_price'] = df['итоговая_цена_руб'].apply(to_num)
# participants_count из протоколов
df['participants'] = pd.to_numeric(df['participants_count'], errors='coerce')
# fallback: если нет participants_count, пробуем 'участники'
if 'участники' in df.columns:
    df['participants'] = df['participants'].fillna(pd.to_numeric(df['участники'], errors='coerce'))

print(f"  Всего лотов: {len(df)}")
print(f"  С задатком: {df['deposit'].notna().sum()}")
print(f"  С участниками: {df['participants'].notna().sum()}")
print(f"  С итоговой ценой: {df['final_price'].notna().sum()}")

# ============================================================
# 2. Определяем уклонение
# ============================================================
print("\n[2/4] Определение уклонения...")

# Базовая логика: 2+ участников, но нет итоговой цены → победитель уклонился
# 1 участник, нет итоговой цены → могли просто не явиться (не уклонение)
df['has_final'] = df['final_price'].notna()
df['evasion'] = (df['participants'] >= 2) & (~df['has_final'])
df['no_bids'] = (df['participants'].isna()) | (df['participants'] == 0)
df['one_bidder_no_final'] = (df['participants'] == 1) & (~df['has_final'])

print(f"  Есть итоговая цена: {df['has_final'].sum()} ({df['has_final'].mean()*100:.1f}%)")
print(f"  Уклонение (2+ участников, нет цены): {df['evasion'].sum()} ({df['evasion'].mean()*100:.1f}%)")
print(f"  1 участник, нет цены: {df['one_bidder_no_final'].sum()}")
print(f"  Нет заявок: {df['no_bids'].sum()}")

# ============================================================
# 3. Группировка по типу задатка
# ============================================================
print("\n[3/4] Группировка по типу задатка...")

# deposit_pct
df['deposit_pct'] = (df['deposit'] / df['start_price'] * 100).round(1)

def deposit_type(row):
    if pd.isna(row['deposit']):
        return 'Нет задатка'
    if abs(row['deposit'] - 500000) < 1:
        return 'Фикс. 500к\n(повторные)'
    pct = row['deposit_pct']
    if pct < 5:
        return '1-5%\n(дешёвые)'
    if pct < 10:
        return '5-10%'
    if abs(pct - 10) < 0.5:
        return '10%\n(стандарт)'
    if pct < 20:
        return '10-20%'
    return '20%+\n(повышенный)'

df['deposit_type'] = df.apply(deposit_type, axis=1)

# Статистика по группам
types_order = ['Фикс. 500к\n(повторные)', '1-5%\n(дешёвые)', '5-10%', '10%\n(стандарт)', '10-20%', '20%+\n(повышенный)', 'Нет задатка']
stats = []
for t in types_order:
    subset = df[df['deposit_type'] == t]
    if len(subset) == 0:
        continue
    n = len(subset)
    evasion_count = subset['evasion'].sum()
    evasion_pct = evasion_count / n * 100 if n > 0 else 0
    with_final = subset['has_final'].sum()
    final_pct = with_final / n * 100 if n > 0 else 0
    avg_participants = subset['participants'].mean()
    stats.append({
        'Тип задатка': t,
        'Всего': n,
        'С итоговой ценой': with_final,
        '% с итоговой': f'{final_pct:.1f}%',
        'Уклонений': int(evasion_count),
        '% уклонения': f'{evasion_pct:.1f}%',
        'Ср. участников': f'{avg_participants:.1f}' if not pd.isna(avg_participants) else 'N/A'
    })

stats_df = pd.DataFrame(stats)
print(f"\n{'='*80}")
print(f"  УКЛОНЕНИЕ ПО ТИПУ ЗАДАТКА")
print(f"{'='*80}")
for _, row in stats_df.iterrows():
    print(f"  {row['Тип задатка']:<20s}  n={row['Всего']:>5d}  итог={row['С итоговой ценой']:>5d} ({row['% с итоговой']:>7s})  уклон={row['Уклонений']:>5d} ({row['% уклонения']:>7s})  участники={row['Ср. участников']}")

# ============================================================
# 4. Дополнительно: уклонение по абсолютному размеру задатка
# ============================================================
print(f"\n{'='*80}")
print(f"  УКЛОНЕНИЕ ПО АБСОЛЮТНОМУ РАЗМЕРУ ЗАДАТКА")
print(f"{'='*80}")

deposit_ranges = [
    ('< 100 тыс', 0, 100_000),
    ('100-300 тыс', 100_000, 300_000),
    ('300-500 тыс', 300_000, 500_000),
    ('500 тыс (фикс)', 499_999, 500_001),
    ('500к - 1 млн', 500_001, 1_000_000),
    ('1-3 млн', 1_000_000, 3_000_000),
    ('3-5 млн', 3_000_000, 5_000_000),
    ('> 5 млн', 5_000_000, float('inf')),
]

for label, lo, hi in deposit_ranges:
    subset = df[(df['deposit'] >= lo) & (df['deposit'] < hi)]
    if len(subset) == 0:
        continue
    n = len(subset)
    evasion_count = subset['evasion'].sum()
    evasion_pct = evasion_count / n * 100
    print(f"  {label:<18s}: n={n:>5d}, уклонений={evasion_count:>5d} ({evasion_pct:.1f}%)")

# ============================================================
# 5. Графики
# ============================================================
print(f"\n[4/4] Графики...")

fig, axes = plt.subplots(2, 2, figsize=(16, 12))
fig.suptitle('Уклонение от договора vs размер задатка', fontsize=16, fontweight='bold')

# 1. % уклонения по типу задатка (bar)
ax = axes[0, 0]
plot_stats = stats_df[stats_df['Тип задатка'] != 'Нет задатка'].copy()
x = np.arange(len(plot_stats))
evasion_vals = [float(r['% уклонения'].replace('%', '')) for _, r in plot_stats.iterrows()]
colors = ['#e74c3c' if '500к' in str(r['Тип задатка']) else '#3498db' for _, r in plot_stats.iterrows()]
bars = ax.bar(x, evasion_vals, 0.6, color=colors, alpha=0.8)
ax.set_xticks(x)
ax.set_xticklabels([t.split('\n')[0] for t in plot_stats['Тип задатка']], rotation=0, fontsize=9)
ax.set_ylabel('% уклонения')
ax.set_title('Уклонение по типу задатка')
for i, v in enumerate(evasion_vals):
    ax.text(i, v + 0.5, f'{v:.1f}%', ha='center', fontsize=9, fontweight='bold')

# 2. % уклонения по % задатка (scatter + trend)
ax = axes[0, 1]
# Группируем по deposit_pct с шагом 1%
pct_groups = df[df['deposit_pct'].notna() & (df['deposit_pct'] <= 30)].copy()
pct_groups['deposit_pct_bin'] = pct_groups['deposit_pct'].round(0)
pct_stats = pct_groups.groupby('deposit_pct_bin').agg(
    n=('deposit_pct', 'count'),
    evasion=('evasion', 'sum')
).reset_index()
pct_stats['evasion_pct'] = (pct_stats['evasion'] / pct_stats['n'] * 100).round(1)
pct_stats = pct_stats[pct_stats['n'] >= 5]  # фильтр малых групп

ax.scatter(pct_stats['deposit_pct_bin'], pct_stats['evasion_pct'],
           s=pct_stats['n'] * 2, alpha=0.6, color='#3498db')
ax.set_xlabel('% задатка от цены')
ax.set_ylabel('% уклонения')
ax.set_title('Уклонение vs % задатка (размер = кол-во лотов)')
ax.axvline(x=10, color='green', linestyle='--', alpha=0.5, label='Стандарт 10%')
ax.legend()

# 3. Кол-во лотов по типу задатка + доля уклонения (stacked bar)
ax = axes[1, 0]
plot_stats2 = stats_df[stats_df['Тип задатка'] != 'Нет задатка'].copy()
labels = plot_stats2['Тип задатка'].str.split('\n').str[0].tolist()
with_final_vals = [int(r['С итоговой ценой']) for _, r in plot_stats2.iterrows()]
evasion_vals2 = [int(r['Уклонений']) for _, r in plot_stats2.iterrows()]
# Остальные = 1 участник без цены или no_bids
other_vals = [r['Всего'] - r['С итоговой ценой'] - r['Уклонений'] for _, r in plot_stats2.iterrows()]

x = np.arange(len(labels))
width = 0.6
ax.bar(x, with_final_vals, width, label='С итоговой ценой', color='#2ecc71', alpha=0.8)
ax.bar(x, evasion_vals2, width, bottom=with_final_vals, label='Уклонение', color='#e74c3c', alpha=0.8)
ax.bar(x, other_vals, width, bottom=[w+e for w, e in zip(with_final_vals, evasion_vals2)],
       label='Прочее (1 участник/нет заявок)', color='#95a5a6', alpha=0.8)
ax.set_xticks(x)
ax.set_xticklabels(labels, rotation=0, fontsize=9)
ax.set_ylabel('Кол-во лотов')
ax.set_title('Структура лотов по типу задатка')
ax.legend(fontsize=8)

# 4. Уклонение vs кол-во участников (heatmap)
ax = axes[1, 1]
# Группируем по кол-ву участников и типу задатка
heatmap_data = []
for t in ['Фикс. 500к\n(повторные)', '10%\n(стандарт)', '20%+\n(повышенный)']:
    for n_part in [1, 2, 3, 4, 5]:
        subset = df[(df['deposit_type'] == t) & (df['participants'] == n_part)]
        if len(subset) >= 3:
            ev_pct = subset['evasion'].mean() * 100
            heatmap_data.append({'Тип': t.split('\n')[0], 'Участники': n_part, '% уклонения': ev_pct, 'n': len(subset)})

if heatmap_data:
    hm_df = pd.DataFrame(heatmap_data)
    pivot = hm_df.pivot(index='Тип', columns='Участники', values='% уклонения')
    im = ax.imshow(pivot.values, cmap='Reds', aspect='auto', vmin=0, vmax=100)
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    ax.set_xlabel('Кол-во участников')
    ax.set_ylabel('Тип задатка')
    ax.set_title('% уклонения (участники × тип задатка)')
    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            val = pivot.values[i, j]
            if not np.isnan(val):
                ax.text(j, i, f'{val:.0f}%', ha='center', va='center', fontsize=9,
                       color='white' if val > 60 else 'black')
    plt.colorbar(im, ax=ax, label='% уклонения')

plt.tight_layout()
out_path = os.path.join(os.path.dirname(__file__), 'evasion_vs_deposit.png')
plt.savefig(out_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Сохранено: {out_path}")

# ============================================================
# Итоговый вывод
# ============================================================
print(f"\n{'='*80}")
print(f"  ИТОГОВЫЙ ВЫВОД")
print(f"{'='*80}")

# Найдём тип с самым высоким и низким уклонением
if len(stats_df) > 1:
    no_deposit_stats = stats_df[stats_df['Тип задатка'] != 'Нет задатка'].copy()
    no_deposit_stats['ev_pct_num'] = no_deposit_stats['Уклонений'] / no_deposit_stats['Всего'] * 100
    max_ev = no_deposit_stats.loc[no_deposit_stats['ev_pct_num'].idxmax()]
    min_ev = no_deposit_stats.loc[no_deposit_stats['ev_pct_num'].idxmin()]
    print(f"\n  Самое высокое уклонение: {max_ev['Тип задатка']} — {max_ev['% уклонения']} ({max_ev['Уклонений']} из {max_ev['Всего']})")
    print(f"  Самое низкое уклонение: {min_ev['Тип задатка']} — {min_ev['% уклонения']} ({min_ev['Уклонений']} из {min_ev['Всего']})")

total_evasion = df['evasion'].sum()
print(f"\n  Всего уклонений: {total_evasion} ({df['evasion'].mean()*100:.1f}%)")
print(f"  Всего с итоговой ценой: {df['has_final'].sum()} ({df['has_final'].mean()*100:.1f}%)")
