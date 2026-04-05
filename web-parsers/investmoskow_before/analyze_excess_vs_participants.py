"""
Анализ: превышение цены от количества участников аукциона
"""
import pandas as pd
import numpy as np

# Загружаем данные
df_geo = pd.read_csv("data/investmoscow_completed_2026-04-04_geocoded.csv", encoding="utf-8-sig")
df_proto = pd.read_csv("data/protocols/participants_data.csv", encoding="utf-8-sig")

# Чистим цены
df_geo["цена_за_м2"] = df_geo["цена_за_м²"].astype(str).str.replace(",", ".").astype(float)
df_geo["превышение"] = df_geo["превышение_цены_%"].astype(str).str.replace("%", "").astype(float)
df_geo["нач_цена_млн"] = df_geo["начальная_цена_руб"].astype(str).str.replace(",", ".").astype(float) / 1e6
df_geo["итог_цена_млн"] = df_geo["итоговая_цена_руб"].astype(str).str.replace(",", ".").astype(float) / 1e6

# Объединяем по номеру лота
df_proto["lot_id"] = df_proto["lot_id"].astype(int)
df = df_geo.merge(df_proto, left_on="номер_лота", right_on="lot_id", how="left")

# Фильтр: только лоты с известным количеством участников
df_has = df[df["participants_count"].notna()].copy()
df_has["участники"] = df_has["participants_count"].astype(int)

# Группируем по количеству участников
print("=" * 70)
print("ПРЕВЫШЕНИЕ ЦЕНЫ ОТ КОЛИЧЕСТВА УЧАСТНИКОВ")
print("=" * 70)

# Группировка
groups = df_has.groupby("участники").agg(
    lot_count=("номер_лота", "count"),
    avg_excess=("превышение", "mean"),
    median_excess=("превышение", "median"),
    max_excess=("превышение", "max"),
    avg_price_m2=("цена_за_м2", "mean"),
    success_rate=("превышение", lambda x: (x >= 0).sum() / len(x) * 100)
).reset_index()

print(f"\n{'Участники':>10} {'Лотов':>6} {'Ср.превыш':>10} {'Мед.превыш':>11} {'Макс.превыш':>12} {'Ср.цена/м2':>10} {'Успешность':>11}")
print("-" * 80)

for _, row in groups.iterrows():
    n = int(row["участники"])
    if n == 0:
        label = "0 (без борьбы)"
    elif n == 1:
        label = "1"
    else:
        label = str(n)
    print(f"{label:>12} {int(row['lot_count']):>6} {row['avg_excess']:>9.1f}% {row['median_excess']:>10.1f}% {row['max_excess']:>11.1f}% {row['avg_price_m2']/1e3:>8.0f}K {row['success_rate']:>9.1f}%")

# Корреляция
corr = df_has[df_has["участники"] > 0][["участники", "превышение"]].corr().iloc[0, 1]
print(f"\nКорреляция (участники ↔ превышение): {corr:.3f}")

# Группировка по диапазонам
print("\n" + "=" * 70)
print("ПО ДИАПАЗОНАМ УЧАСТНИКОВ")
print("=" * 70)

def range_participants(n):
    if n == 0: return "0 (без борьбы)"
    elif n == 1: return "1 участник"
    elif n == 2: return "2 участника"
    elif n == 3: return "3 участника"
    elif n <= 5: return "4-5 участников"
    elif n <= 10: return "6-10 участников"
    elif n <= 15: return "11-15 участников"
    elif n <= 20: return "16-20 участников"
    else: return "20+ участников"

df_has["диапазон"] = df_has["участники"].apply(range_participants)

range_groups = df_has.groupby("диапазон").agg(
    lot_count=("номер_лота", "count"),
    avg_excess=("превышение", "mean"),
    median_excess=("превышение", "median"),
    max_excess=("превышение", "max"),
    avg_price_m2=("цена_за_м2", "mean"),
    success_rate=("превышение", lambda x: (x >= 0).sum() / len(x) * 100)
).reset_index()

# Порядок сортировки
order = ["0 (без борьбы)", "1 участник", "2 участника", "3 участника", "4-5 участников",
         "6-10 участников", "11-15 участников", "16-20 участников", "20+ участников"]
range_groups["sort_key"] = range_groups["диапазон"].map({v: i for i, v in enumerate(order)})
range_groups = range_groups.sort_values("sort_key")

print(f"\n{'Диапазон':>18} {'Лотов':>6} {'Ср.превыш':>10} {'Мед.превыш':>11} {'Макс.превыш':>12} {'Ср.цена/м2':>10} {'Успешность':>11}")
print("-" * 90)

for _, row in range_groups.iterrows():
    print(f"{row['диапазон']:>18} {int(row['lot_count']):>6} {row['avg_excess']:>9.1f}% {row['median_excess']:>10.1f}% {row['max_excess']:>11.1f}% {row['avg_price_m2']/1e3:>8.0f}K {row['success_rate']:>9.1f}%")

# Топ-10 лотов по количеству участников
print("\n" + "=" * 70)
print("ТОП-10 ЛОТОВ ПО КОЛИЧЕСТВУ УЧАСТНИКОВ")
print("=" * 70)

top = df_has.nlargest(10, "участники")[["номер_лота", "адрес", "участники", "превышение", "нач_цена_млн", "итог_цена_млн"]]
for _, row in top.iterrows():
    addr = str(row["адрес"])[:60]
    exc = f"+{row['превышение']:.0f}%" if row["превышение"] >= 0 else "Не состоялся"
    start = f"{row['нач_цена_млн']:.1f} млн" if pd.notna(row["нач_цена_млн"]) else "?"
    final = f"{row['итог_цена_млн']:.1f} млн" if pd.notna(row["итог_цена_млн"]) else "?"
    print(f"  #{int(row['номер_лота']):>10} | {int(row['участники']):>2} уч. | {exc:>8} | {start} → {final} | {addr}")

# Сохраняем объединённые данные
df_has.to_csv("data/protocols/merged_data.csv", index=False, encoding="utf-8-sig")
print(f"\n[FILE] data/protocols/merged_data.csv")
