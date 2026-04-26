# investmoscow.ru: parser, geodata, analytics

Проект собирает и анализирует торги по нежилым помещениям с `investmoscow.ru`.

## Актуальное состояние

- Период данных: `2022-2026`
- Основной объединённый файл: `data/investmoscow_completed_2022_2026_geocoded.csv`
- Файл для карты: `data/investmoscow_completed_2022_2026_geocoded_mapped.csv`
- Всего лотов: `9595`
- С координатами: `9500`

## Основные файлы

- `parser_completed_2022_2023.py` — парсер завершённых торгов за `2022-2023`
- `parser_completed_2024.py` — парсер завершённых торгов за `2024`
- `parser_completed.py` — парсер завершённых торгов за `2025-2026`
- `geocode_2022_2024.py` — вход для backfill координат по `2022-2024`
- `backfill_geocodes_2022_2024.py` — backfill координат из API-кэшей и локальных совпадений
- `geocode_addresses.py` — геокодирование для файла `2025-2026`
- `merge_all_years.py` — объединение всех периодов в итоговый датасет
- `analyze_all_data.py` — аналитика по объединённому файлу `2022-2026`
- `app_map.py` — Streamlit-карта по всем годам

## Данные

Ключевые CSV:

- `data/investmoscow_completed_2022_2024_geocoded.csv`
- `data/investmoscow_completed_2026-04-04_geocoded.csv`
- `data/investmoscow_completed_2022_2026_geocoded.csv`
- `data/investmoscow_completed_2022_2026_geocoded_mapped.csv`

Ключевые кэши:

- `data/all_tenders_cache_2022_2023.json`
- `data/all_tenders_cache_2024.json`
- `data/geocache_dadata_2022_2024.json`
- `data/geocache_2022_2024.json`
- `data/geocache.json`

Важно:

- Для периода `2022-2024` координаты берутся в первую очередь из API-кэшей `all_tenders_cache_2022_2023.json` и `all_tenders_cache_2024.json`.
- Для периода `2025-2026` используется geocoded CSV.
- Карта по умолчанию читает `data/investmoscow_completed_2022_2026_geocoded_mapped.csv`.

## Как запускать

### 1. Собрать период `2022-2023`

```bash
py parser_completed_2022_2023.py
```

### 2. Собрать период `2024`

```bash
py parser_completed_2024.py
```

### 3. Собрать период `2025-2026`

```bash
py parser_completed.py
py geocode_addresses.py
```

### 4. Заполнить координаты для `2022-2024`

```bash
py geocode_2022_2024.py --skip-api
```

Обычно этого достаточно, потому что координаты уже есть в API-кэшах.

### 5. Объединить все годы

```bash
py merge_all_years.py
```

### 6. Построить аналитику

```bash
py analyze_all_data.py
```

### 7. Запустить карту

```bash
streamlit run app_map.py
```

## Streamlit

Приложение показывает:

- карту лотов
- фильтры по округу, году, статусу, площади, цене, этажу и превышению
- popup по каждому лоту
- таблицу и выгрузку фильтрованной выборки

## Зависимости

```bash
pip install requests beautifulsoup4 pandas matplotlib seaborn pdfplumber python-docx streamlit folium streamlit-folium
```

## Дополнительно

- Текущее краткое состояние проекта: `CURRENT_STATE_2022_2026.md`
- Итоговый график аналитики: `all_data_overview.png`
