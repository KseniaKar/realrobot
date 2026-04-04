# Парсер investmoscow.ru

Парсер для сбора данных о торгах по нежилым помещениям на [Инвестиционном портале Москвы](https://investmoscow.ru/tenders/).

## Что реализовано

### ✅ Парсер завершенных торгов 2025–2026

```bash
python parser_completed.py
```

**Результат:** `data/investmoscow_completed_2026-04-04.csv` — **2 839 записей**

Поля: url, номер_лота, площадь, начальная/итоговая цена, задаток, шаг аукциона, превышение, адрес, кадастр, метро, этаж, этажность, форма торгов, даты, ссылка на roseltorg.

### ✅ Аналитика

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
├── parser_completed.py          # Парсер завершенных торгов 2025-2026
├── run_analytics.py             # Скрипт аналитики
├── analytics_completed.ipynb    # Jupyter-ноутбук
├── data/
│   ├── investmoscow_completed_2026-04-04.csv  # 2 839 записей
│   ├── analytics_summary.md      # Отчёт с ключевыми цифрами
│   └── charts/                   # Графики (PNG)
├── AGENT_TASK.md                 # ТЗ и план работ
└── README.md                     # Этот файл
```

## Ключевые цифры

| Показатель | Значение |
|-----------|----------|
| Всего завершенных торгов | 2 839 |
| С известной итоговой ценой | 1 393 (49.1%) |
| Не состоялись | 1 446 (50.9%) |
| Среднее превышение цены | +30.5% |
| Максимальное превышение | +285% |
| Общая начальная стоимость | 72.2 млрд руб |

Подробности — в `data/analytics_summary.md`

## Требования

- Python 3.9+
- requests, beautifulsoup4, pandas, matplotlib, seaborn
