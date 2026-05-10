"""
Парсит тип входа с ЦИАН для всех объявлений. Сохраняет прогресс в JSON.
Запуск: python _parse_entrance_cian_full.py
"""
import json
import time
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

INPUT_TYPE_MAP = {
    "separateFromStreet": "отдельный с улицы",
    "separateFromYard":   "отдельный со двора",
    "throughEntrance":    "через подъезд",
    "throughHall":        "через холл",
}

KEY = b'"inputType":"'
PROGRESS_FILE = Path("C:/git/realrobot/look_a_like_prices/_entrance_progress.json")
OUT_FILE = Path("C:/git/realrobot/look_a_like_prices/_entrance_results.csv")


def extract_entrance(raw: bytes):
    idx = raw.find(KEY)
    if idx < 0:
        return None
    start = idx + len(KEY)
    end = raw.find(b'"', start)
    val = raw[start:end].decode("utf-8", errors="ignore")
    return INPUT_TYPE_MAP.get(val, val)


def load_progress():
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    return {}


def save_progress(data: dict):
    PROGRESS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


df = pd.read_excel("C:/git/realrobot/look_a_like_prices/excel2-30025-1.xlsx")
cian_df = df[df["URL"].str.contains("cian.ru", na=False)].copy()
urls = cian_df["URL"].tolist()
print(f"Total CIAN URLs: {len(urls)}")

progress = load_progress()
todo = [u for u in urls if u not in progress]
print(f"Already done: {len(progress)}, remaining: {len(todo)}")

if todo:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            locale="ru-RU",
        )
        page = context.new_page()

        for i, url in enumerate(todo):
            try:
                page.goto(url, wait_until="load", timeout=30000)
                raw = page.content().encode("utf-8")
                entrance = extract_entrance(raw)
                progress[url] = entrance
            except Exception as e:
                progress[url] = f"ERR: {str(e)[:60]}"

            if (i + 1) % 10 == 0:
                save_progress(progress)
                done_pct = (len(progress) / len(urls)) * 100
                print(f"  {i+1}/{len(todo)}  ({done_pct:.0f}%)  last: {entrance}")

            time.sleep(1)

        browser.close()
        save_progress(progress)

# сохранить результаты в CSV
rows = [{"URL": u, "тип_входа_циан": v} for u, v in progress.items()]
result_df = pd.DataFrame(rows)
result_df.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")
print(f"\nГотово. Сохранено в {OUT_FILE}")
print(result_df["тип_входа_циан"].value_counts().to_string())
