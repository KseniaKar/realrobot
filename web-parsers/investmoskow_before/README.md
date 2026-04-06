# Парсер и дашборд investmoscow.ru

Интерактивная карта и аналитика торгов по нежилым помещениям на [Инвестиционном портале Москвы](https://investmoscow.ru/tenders/).

**Деплой:** https://realrobothistory.streamlit.app/

---

## Ключевые выводы

### Торги и конкуренция

- **2 839 завершённых торгов** за 2025–2026 гг.
- **49%** состоялись, **51%** — без итоговой цены
- Среднее превышение цены среди успешных: **+30.5%**
- Рекорд: **+285%** (ЦАО, Пресненский, 45.1 м²)
- Корреляция участников и превышения: **r = 0.709** (сильная связь)

### Участники торгов

- **1 722 лота** с распарсенными протоколами
- **449 лотов** без заявок
- **668 лотов** — протокол не найден на сайте
- **1 участник** = цена не растёт (86% успешность по стартовой цене)
- **6+ участников** = среднее превышение >40%

### Этажи и цены

- **1 этаж** — 67% всех лотов, самый конкурентный (223К ₽/м², 52% успешность)
- **Подвал** — 22% лотов, самый дешёвый (87К ₽/м², 37% успешность)
- **1 и 2 этажи** стоят одинаково (214К vs 217К ₽/м²), но спрос на 2-й ниже (32% vs 52%)
- **99%** лотов на 1 этаже — дороже 100К ₽/м²

---

## Что реализовано

### 1. Парсер завершенных торгов

```bash
python parser_completed.py
```

Скачивание через API → фильтрация по дате → парсинг страниц → **2 839 лотов** с ценами, датами, адресами.

### 2. Геокодирование адресов

```bash
py geocode_addresses.py
```

Nominatim (OpenStreetMap) с кэшированием → **96.7%** лотов получили координаты.

### 3. Парсинг протоколов

```bash
py parse_all_protocols.py
```

PDF (pdfplumber) + DOCX (python-docx) → количество участников, победители, цены.

### 4. Streamlit дашборд

```bash
streamlit run app_map.py
```

Интерактивная карта, фильтры, scatter plot, таблица статистики по диапазонам участников.

---

## Установка зависимостей

```bash
pip install requests beautifulsoup4 pandas matplotlib seaborn pdfplumber python-docx streamlit folium streamlit-folium
```

Playwright **не нужен** — данные извлекаются из SSR HTML.

---

## Структура проекта

```
investmoskow_before/
├── parser_completed.py            # Парсер завершенных торгов 2025-2026
├── geocode_addresses.py           # Геокодирование адресов (Nominatim)
├── parse_all_protocols.py         # Парсинг протоколов PDF + DOCX
├── app_map.py                     # Streamlit дашборд
├── run_analytics.py               # Скрипт аналитики
├── analyze_clusters.py            # Анализ ценовых кластеров по этажам
├── analytics_completed.ipynb      # Jupyter-ноутбук
├── data/
│   ├── investmoscow_completed_2026-04-04.csv          # 2 839 записей
│   ├── investmoscow_completed_2026-04-04_geocoded.csv # + координаты
│   ├── geocache.json               # Кэш геокодирования
│   ├── analytics_summary.md        # Отчёт с ключевыми цифрами
│   ├── protocols/
│   │   ├── protocol_cache.json     # Кэш парсинга протоколов
│   │   └── participants_data.csv   # Участники по лотам
│   └── charts/                     # Графики (PNG)
├── EXCESS_VS_PARTICIPANTS.md       # Анализ: превышение vs участники
├── CLUSTER_ANALYSIS.md             # Анализ ценовых кластеров по этажам
├── COMPREHENSIVE_ANALYSIS.md       # Комплексный анализ всех факторов
├── AGENT_TASK.md                   # ТЗ и план работ
└── README.md                       # Этот файл
```

---

## Требования

- Python 3.9+
- requests, beautifulsoup4, pandas, matplotlib, seaborn
- pdfplumber, python-docx (парсинг протоколов)
- streamlit, folium, streamlit-folium (дашборд)

---

**Заказчик:** Ксения Карюкина, Telegram @kseniakeera
**Репозиторий:** https://github.com/KseniaKar/realrobot
