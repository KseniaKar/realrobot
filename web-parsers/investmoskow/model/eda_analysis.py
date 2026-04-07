"""
Полный EDA анализ признаков с графиками и корреляциями
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

plt.rcParams['font.size'] = 10
sns.set_style("whitegrid")

MODEL_DIR = Path("model")
EDA_DIR = MODEL_DIR / "eda"
EDA_DIR.mkdir(exist_ok=True)

# Загрузка данных
df = pd.read_csv(MODEL_DIR / "dataset_final_with_features.csv", encoding='utf-8-sig')
df = df[df['превышение_цены_%'].notna()].copy()

def parse_pct(val):
    if pd.isna(val): return np.nan
    try: return float(str(val).replace('%', '').replace(',', '.'))
    except: return np.nan

df['target'] = df['превышение_цены_%'].apply(parse_pct)

# Определяем признаки
exclude_cols = ['превышение_цены_%', 'url', 'номер_лота', 'id', 'участники', 'итоговая_цена_руб', 'цена_победителя', 'real_excess_raw', 'target']
features = [c for c in df.columns if c not in exclude_cols]

print("="*70)
print(f"EDA АНАЛИЗ: {len(df)} записей, {len(features)} признаков")
print("="*70)

# 1. ГЛАВНЫЙ ГРАФИК: Распределение target
fig, axes = plt.subplots(1, 3, figsize=(15, 4))

# Гистограмма
axes[0].hist(df['target'].clip(-10, 150), bins=50, edgecolor='black', alpha=0.7, color='steelblue')
axes[0].axvline(x=df['target'].median(), color='red', linestyle='--', label=f'Медиана={df["target"].median():.1f}%')
axes[0].set_title('Распределение превышения цены')
axes[0].set_xlabel('%')
axes[0].legend()

# Boxplot
axes[1].boxplot(df['target'].clip(-10, 150), vert=True, patch_artist=True,
                boxprops=dict(facecolor='lightblue', edgecolor='black'))
axes[1].set_title('Boxplot превышения')

# По категориям
cats = []
for val in df['target']:
    if val <= 0: cats.append('0%')
    elif val <= 10: cats.append('1-10%')
    elif val <= 25: cats.append('10-25%')
    elif val <= 50: cats.append('25-50%')
    elif val <= 100: cats.append('50-100%')
    else: cats.append('>100%')
df['target_cat'] = cats

cat_counts = df['target_cat'].value_counts().sort_index()
axes[2].bar(range(len(cat_counts)), cat_counts.values, edgecolor='black', color=plt.cm.Set2.colors)
axes[2].set_xticks(range(len(cat_counts)))
axes[2].set_xticklabels(cat_counts.index, rotation=45)
axes[2].set_title('Распределение по категориям')

plt.tight_layout()
plt.savefig(EDA_DIR / '00_target_distribution.png', dpi=150, bbox_inches='tight')
plt.close()
print("✅ 00_target_distribution.png")

# 2. ЧИСЛОВЫЕ ПРИЗНАКИ
numeric_features = ['площадь_м²', 'начальная_цена_руб', 'цена_за_м2_calc',
                    'расстояние_до_центра', 'расстояние_до_центра_округа', 
                    'время_до_метро', 'этажность', 'log_площадь', 'log_цена_за_м2',
                    'area_per_metro', 'price_density']

numeric_features = [f for f in numeric_features if f in df.columns]

correlations = {}

for feat in numeric_features:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    
    # Гистограмма
    data = df[feat].dropna()
    axes[0].hist(data, bins=30, edgecolor='black', alpha=0.7, color='steelblue')
    axes[0].set_title(f'Распределение: {feat}')
    axes[0].set_xlabel(feat)
    
    # Scatter с target
    axes[1].scatter(data.clip(lower=data.quantile(0.01), upper=data.quantile(0.99)),
                    df.loc[data.index, 'target'].clip(-10, 150),
                    alpha=0.3, s=10, edgecolors='none')
    axes[1].set_title(f'{feat} vs Превышение')
    axes[1].set_xlabel(feat)
    axes[1].set_ylabel('Превышение %')
    
    # Корреляция
    corr = df[[feat, 'target']].dropna().corr().iloc[0, 1]
    correlations[feat] = corr
    axes[1].text(0.05, 0.95, f'r = {corr:.3f}', transform=axes[1].transAxes,
                fontsize=12, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    
    plt.tight_layout()
    safe_name = feat.replace(' ', '_').replace('²', '2').replace('/', '_per_')
    plt.savefig(EDA_DIR / f'01_numeric_{safe_name}.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"✅ 01_numeric_{safe_name}.png (r={corr:.3f})")

# 3. КАТЕГОРИАЛЬНЫЕ ПРИЗНАКИ
categorical_features = ['округ', 'тип_входа', 'этаж_кат', 'metro_zone', 'price_category', 'наличие_метро', 'is_small_area', 'is_center']
categorical_features = [f for f in categorical_features if f in df.columns]

binary_features = ['наличие_метро', 'is_small_area', 'is_center', 'is_floor_floor_1', 'is_floor_basement', 'is_floor_floor_2', 'is_floor_floor_3_plus', 'is_floor_other']
binary_features = [f for f in binary_features if f in df.columns]

for feat in categorical_features:
    if feat in binary_features:
        # Binary - bar chart
        fig, ax = plt.subplots(figsize=(6, 4))
        counts = df[feat].value_counts()
        counts.index = ['Нет', 'Да'] if len(counts) == 2 else counts.index
        counts.plot(kind='bar', ax=ax, edgecolor='black', color=['lightcoral', 'lightgreen'][:len(counts)])
        
        corr = df[[feat, 'target']].corr().iloc[0, 1]
        correlations[feat] = corr
        ax.set_title(f'{feat} (r={corr:.3f})')
        ax.set_ylabel('Количество')
        
        plt.tight_layout()
        plt.savefig(EDA_DIR / f'02_binary_{feat}.png', dpi=150, bbox_inches='tight')
        plt.close()
        print(f"✅ 02_binary_{feat}.png (r={corr:.3f})")
    else:
        # Categorical - boxplot by category
        fig, ax = plt.subplots(figsize=(10, 5))
        df_clean = df[[feat, 'target']].dropna()
        top_cats = df_clean[feat].value_counts().head(10).index
        df_top = df_clean[df_clean[feat].isin(top_cats)]
        
        df_top.boxplot(column='target', by=feat, ax=ax, patch_artist=True)
        ax.set_title(f'{feat} vs Превышение')
        ax.set_xlabel(feat)
        ax.set_ylabel('Превышение %')
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        safe_name = feat.replace(' ', '_')
        plt.savefig(EDA_DIR / f'02_categorical_{safe_name}.png', dpi=150, bbox_inches='tight')
        plt.close()
        print(f"✅ 02_categorical_{safe_name}.png")

# 4. КОРРЕЛЯЦИОННАЯ МАТРИЦА
corr_features = numeric_features + binary_features
df_corr = df[[f for f in corr_features if f in df.columns] + ['target']].dropna()
corr_matrix = df_corr.corr()

plt.figure(figsize=(14, 12))
mask = np.triu(np.ones_like(corr_matrix, dtype=bool))
sns.heatmap(corr_matrix, mask=mask, annot=True, cmap='coolwarm', center=0,
            fmt='.2f', square=True, linewidths=0.5, cbar_kws={"shrink": 0.8})
plt.title('КОРРЕЛЯЦИОННАЯ МАТРИЦА ВСЕХ ПРИЗНАКОВ', fontsize=14, fontweight='bold', pad=20)
plt.tight_layout()
plt.savefig(EDA_DIR / '03_correlation_matrix.png', dpi=150, bbox_inches='tight')
plt.close()
print("✅ 03_correlation_matrix.png")

# 5. ТОП КОРРЕЛЯЦИЙ С TARGET
target_corr = corr_matrix['target'].drop('target').sort_values(ascending=False)

fig, ax = plt.subplots(figsize=(8, 6))
colors = ['red' if x < 0 else 'blue' for x in target_corr.values]
target_corr.plot(kind='barh', ax=ax, color=colors, edgecolor='black')
ax.set_title('Корреляция признаков с превышением цены', fontweight='bold')
ax.set_xlabel('Корреляция (r)')
ax.axvline(x=0, color='black', linestyle='-', linewidth=0.5)

plt.tight_layout()
plt.savefig(EDA_DIR / '04_feature_importance_correlation.png', dpi=150, bbox_inches='tight')
plt.close()
print("✅ 04_feature_importance_correlation.png")

# 6. ГЕОГРАФИЯ
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Карта (scatter)
valid_geo = df[df['latitude'].notna() & df['longitude'].notna()]
scatter = axes[0].scatter(valid_geo['longitude'], valid_geo['latitude'],
                          c=valid_geo['target'].clip(0, 100),
                          cmap='YlOrRd', s=10, alpha=0.5)
plt.colorbar(scatter, ax=axes[0], label='Превышение %')
axes[0].set_title('География лотов (цвет = превышение)')
axes[0].set_xlabel('Longitude')
axes[0].set_ylabel('Latitude')

# По округам
district_excess = df.groupby('округ')['target'].agg(['median', 'count']).sort_values('median', ascending=False)
district_excess = district_excess[district_excess['count'] >= 5]
axes[1].barh(range(len(district_excess)), district_excess['median'],
             edgecolor='black', color=plt.cm.RdYlGn(np.linspace(0.3, 0.9, len(district_excess))))
axes[1].set_yticks(range(len(district_excess)))
axes[1].set_yticklabels(district_excess.index)
for i, (_, row) in enumerate(district_excess.iterrows()):
    axes[1].text(row['median'] + 1, i, f'{row["median"]:.0f}% (n={int(row["count"])})', va='center', fontsize=8)
axes[1].set_title('Медианное превышение по округам')
axes[1].set_xlabel('Медиана %')

plt.tight_layout()
plt.savefig(EDA_DIR / '05_geography.png', dpi=150, bbox_inches='tight')
plt.close()
print("✅ 05_geography.png")

# 7. СВОДНАЯ ТАБЛИЦА ПРИЗНАКОВ
summary_data = []
for feat in features:
    if feat in df.columns:
        data = df[feat].dropna()
        if data.dtype in ['float64', 'int64']:
            summary_data.append({
                'Признак': feat,
                'Тип': 'Числовой',
                'Пропуски': df[feat].isna().sum(),
                'Уникальных': data.nunique(),
                'Медиана': f'{data.median():.2f}',
                'Min': f'{data.min():.2f}',
                'Max': f'{data.max():.2f}',
                'Корреляция': f'{correlations.get(feat, 0):.3f}'
            })
        else:
            summary_data.append({
                'Признак': feat,
                'Тип': 'Категориальный',
                'Пропуски': df[feat].isna().sum(),
                'Уникальных': data.nunique(),
                'Топ': data.value_counts().index[0],
                'Корреляция': 'N/A'
            })

df_summary = pd.DataFrame(summary_data)
df_summary.to_csv(EDA_DIR / '06_features_summary.csv', index=False, encoding='utf-8-sig')
print("✅ 06_features_summary.csv")

# 8. ГРАФИК ТОП-10 КОРРЕЛЯЦИЙ
top10_corr = target_corr.abs().sort_values(ascending=False).head(10)

fig, ax = plt.subplots(figsize=(8, 5))
top10_corr.plot(kind='barh', ax=ax, color='steelblue', edgecolor='black')
ax.set_title('ТОП-10 признаков по абсолютной корреляции', fontweight='bold')
ax.set_xlabel('|r|')

for i, (feat, val) in enumerate(top10_corr.items()):
    ax.text(val + 0.01, i, f'{val:.3f}', va='center', fontsize=9)

plt.tight_layout()
plt.savefig(EDA_DIR / '07_top10_features.png', dpi=150, bbox_inches='tight')
plt.close()
print("✅ 07_top10_features.png")

print("\n" + "="*70)
print("EDA ЗАВЕРШЕНА!")
print(f"Графики сохранены в: {EDA_DIR}")
print("="*70)
print("\nТОП-10 корреляций с превышением:")
for feat, corr in target_corr.head(10).items():
    print(f"  {feat:40s} r = {corr:+.3f}")
