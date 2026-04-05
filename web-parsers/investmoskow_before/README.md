# Парсер investmoscow.ru

Парсер для сбора данных о торгах по нежилым помещениям на [Инвестиционном портале Москвы](https://investmoscow.ru/tenders/).

## Что реализовано

###  Парсер завершенных торгов 2025–2026

```bash
python parser_completed.py
```

**Результат:** `data/investmoscow_completed_2026-04-04.csv` — **2 839 записей**

Поля: url, номер_лота, площадь, начальная/итоговая цена, задаток, шаг аукциона, превышение, адрес, кадастр, метро, этаж, этажность, форма торгов, даты, ссылка на roseltorg.

###  Геокодирование адресов

```bash
py geocode_addresses.py
```

**Результат:** `data/investmoscow_completed_2026-04-04_geocoded.csv` — **2 839 записей, 2 744 с координатами (96.7%)**

Добавлены поля: `latitude`, `longitude`. Используется Nominatim (OpenStreetMap) с кэшированием и валидацией по границам Москвы.

###  Аналитика

```bash
python run_analytics.py
```

Или открыть `analytics_completed.ipynb` в Jupyter.

**Результат:** 6 графиков в `data/charts/` + отчёт `data/analytics_summary.md`

## Установка зависимостей

```bash
pip install requests beautifulsoup4 pandas matplotlib seaborn
```

Playwright **не нужен** — данные извлекаются из SSR HTML.

## Структура проекта

```
investmoskow_before/
├── parser_completed.py            # Парсер завершенных торгов 2025-2026
├── geocode_addresses.py           # Геокодирование адресов (Nominatim)
├── run_analytics.py               # Скрипт аналитики
├── analytics_completed.ipynb      # Jupyter-ноутбук
├── data/
│   ├── investmoscow_completed_2026-04-04.csv          # 2 839 записей
│   ├── investmoscow_completed_2026-04-04_geocoded.csv # + latitude, longitude
│   ├── geocache.json               # Кэш геокодирования
│   ├── analytics_summary.md        # Отчёт с ключевыми цифрами
│   └── charts/                     # Графики (PNG)
├── AGENT_TASK.md                   # ТЗ и план работ
└── README.md                       # Этот файл
```

## Ключевые цифры

```
┌─────────────────────────────────┬─────────────────────┐
│ Всего завершенных торгов        │ 2 839               │
│ 2025 год / 2026 год             │ 2 226 / 613         │
│ С известной итоговой ценой      │ 1 393 (49.1%)       │
│ Не состоялись                   │ 1 446 (50.9%)       │
│ Средняя начальная цена          │ ~25.4 млн руб       │
│ Средняя цена за м²              │ ~169 тыс руб        │
│ Среднее превышение (у успешных) │ +30.5%              │
│ Лотов с превышением ≥50%        │ 350                 │
│ Лотов с удвоением цены          │ 113                 │
│ Топ-1 превышение                │ +285% (ЦАО, 45.1 м²)│
│ Самый конкурентный округ        │ ЦАО (+40.1%)        │
│ Самый конкурентный этаж         │ 1 этаж (+32.7%)     │
└─────────────────────────────────┴─────────────────────┘
```

Подробности — в `data/analytics_summary.md`

## Требования

- Python 3.9+
- requests, beautifulsoup4, pandas, matplotlib, seaborn
