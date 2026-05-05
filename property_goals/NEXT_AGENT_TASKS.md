# Задание для следующего агента — property_goals

## Контекст

Проект: матчинг лотов Investmoscow (продажа нежилых помещений Москвы 2022–2026) с данными 2GIS.
Цель: определить, какой бизнес появился в помещении после покупки.

**Текущий статус: 2313 матчей из 3868 лотов (59.8%)**

| Тип | Лотов |
|-----|-------|
| Новый бизнес (high/medium/low) | 1522 |
| Действующий арендатор (existing_tenant) | 791 |
| **Итого** | **2313** |

Основные файлы:
- `investmoscow_sold_2022_2026_enriched_geo.csv` — главный выходной файл
- `moscow/*.with_norm.csv` — срезы 2GIS (21 срез, не в git — гигабайты)
- `CLAUDE.md` — полная архитектура и pipeline
- `FINDINGS.md` — накопленные аналитические выводы

Pipeline (запускать в этом порядке):
```
"/c/Program Files/Python39/python.exe" property_goals/match_gap_snapshots.py
"/c/Program Files/Python39/python.exe" property_goals/merge_gap_matches.py
"/c/Program Files/Python39/python.exe" property_goals/revalidate_matches.py
"/c/Program Files/Python39/python.exe" property_goals/detect_tenant_buyout.py
"/c/Program Files/Python39/python.exe" property_goals/merge_tenant_buyout.py
"/c/Program Files/Python39/python.exe" property_goals/build_business_history.py
"/c/Program Files/Python39/python.exe" property_goals/match_retailstreets.py
```

---

## ✅ Выполнено (не переделывать)

- [x] Нормализация `стр N` vs `стN` (+109 матчей)
- [x] Нормализация `к3` vs `корп 3` (+627 матчей)
- [x] Фильтр этажей в `revalidate_matches.py` (46 цепочек, чистый подвал)
- [x] `detect_tenant_buyout.py` — детектор выкупа арендатора (1124 лота под паттерн)
- [x] `merge_tenant_buyout.py` — слияние в enriched CSV (+1101 лот, existing_tenant)
- [x] `app.py` — фильтр «Новый бизнес» / «Действующий арендатор», отдельный лист Excel
- [x] К&Б и Ароматный Мир добавлены в "первый этаж" в retailstreets_requirements.csv
- [x] `match_retailstreets.py` перезапущен — подвальные лоты больше не получают К&Б/Ароматный Мир

---

## Задача 1 — Добавить новый срез 2GIS (когда появится)

Следующий срез — вероятно `2026-07`.

1. Положить срез в `property_goals/moscow/2026-07.with_norm.csv`
2. В `match_gap_snapshots.py`: добавить пару `("2026-04", "2026-07")` в `SNAPSHOT_PAIRS`
3. В `build_business_history.py`: обновить `LATEST_LABEL = "2026-07"`
4. Перезапустить полный pipeline (все 7 шагов выше)

---

## Задача 2 — Улучшить качество existing_tenant кандидатов

Текущий детектор (`detect_tenant_buyout.py`) работает с радиусом 50м — захватывает соседей по кварталу, не только арендаторов конкретного помещения.

Возможные улучшения:
- Уменьшить радиус до 20–30м для `existing_tenant` с высоким confidence (→ `existing_tenant_high`)
- Добавить сигнал: если бизнес совпадает по адресу (address_norm) с лотом — это более сильный кандидат
- Проверить: сколько existing_tenant кандидатов имеют address_norm = адресу лота?

---

## Задача 3 — Мелкие нормализации адресов (низкий приоритет)

- `вл N` (4 лота) — владение; в срезах может быть просто N
- Зеленоград: 51+ лот с `фестивальная` — проверить, есть ли их адреса в срезах вообще

---

## Порядок работы

1. Прочитай `CLAUDE.md` и `property_goals/CLAUDE.md` — там вся архитектура
2. Прочитай `property_goals/FINDINGS.md` — предыдущие выводы
3. Начни с Задачи 1 (новый срез) если он есть, иначе — Задача 2
