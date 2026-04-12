# Property Goals

Исторические данные по лотам `investmoscow`, которые реально были куплены.

Критерий включения:
- есть `итоговая_цена_руб`
- нет признака `Отказ победителя`

Текущий файл:
- `investmoscow_sold_2022_2026.csv`
- `investmoscow_sold_2022_2026_clean.csv` — очищенный CSV без технических колонок
- `app.py` — Streamlit-приложение по купленным лотам

Срез по годам:
- `2022`: 737
- `2023`: 971
- `2024`: 870
- `2025`: 1065
- `2026`: 225

Запуск:

```bash
streamlit run property_goals/app.py
```

Примечание:
- приложение читает `investmoscow_sold_2022_2026.csv`
- количество участников подтягивается из `web-parsers/investmoskow_before/data/protocols/protocol_cache.json`, если файл доступен локально
