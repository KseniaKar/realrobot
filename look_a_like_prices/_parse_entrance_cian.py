"""
Парсит тип входа с ЦИАН для нескольких объявлений.
Открывает видимый браузер — если появится капча, реши её вручную.
"""
import time
import pandas as pd
from playwright.sync_api import sync_playwright

INPUT_TYPE_MAP = {
    b'separateFromStreet': 'отдельный с улицы',
    b'separateFromYard':   'отдельный со двора',
    b'throughEntrance':    'через подъезд',
    b'throughHall':        'через холл',
}

KEY = b'"inputType":"'


def extract_entrance(raw: bytes):
    idx = raw.find(KEY)
    if idx < 0:
        return None
    start = idx + len(KEY)
    end = raw.find(b'"', start)
    val = raw[start:end]
    return INPUT_TYPE_MAP.get(val, val.decode("utf-8", errors="ignore"))


df = pd.read_excel("C:/git/realrobot/look_a_like_prices/excel2-30025-1.xlsx")
cian_urls = (
    df[df["URL"].str.contains("cian.ru", na=False)]["URL"]
    .head(3)
    .tolist()
)

results = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=500)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        locale="ru-RU",
    )
    page = context.new_page()

    # первая страница — дать время решить капчу если будет
    print(f"Открываю: {cian_urls[0]}")
    page.goto(cian_urls[0], wait_until="networkidle", timeout=60000)

    # ждём пока не уйдёт капча (title не должен содержать Captcha)
    for _ in range(30):
        title = page.title()
        if "captcha" not in title.lower() and "каптча" not in title.lower():
            break
        print(f"  Капча... жду (title={title!r})")
        time.sleep(2)

    raw = page.content().encode("utf-8")
    entrance = extract_entrance(raw)
    print(f"  {cian_urls[0][-30:]}  ->  {entrance}")
    results.append({"url": cian_urls[0], "тип_входа": entrance})

    # остальные
    for url in cian_urls[1:]:
        print(f"Открываю: {url}")
        time.sleep(2)
        page.goto(url, wait_until="networkidle", timeout=60000)
        raw = page.content().encode("utf-8")
        entrance = extract_entrance(raw)
        print(f"  {url[-30:]}  ->  {entrance}")
        results.append({"url": url, "тип_входа": entrance})

    browser.close()

print("\nИтог:")
for r in results:
    print(f"  {r['url'][-35:]}  ->  {r['тип_входа']}")
