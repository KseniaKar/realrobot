"""
Парсит тип входа (inputType) для объявлений из sale_dedup.csv.
CIAN: offerData.offer.inputType в HTML.
Яндекс: entranceType в HTML.

Прогресс сохраняется в _entrance_progress.jsonl.
403 не сохраняются — повторяются при следующем запуске.

Запуск:
  python _scrape_entrance.py           # парсить
  python _scrape_entrance.py --merge   # смержить прогресс -> CSV
"""
import json
import random
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

import pandas as pd

BASE          = Path('C:/git/realrobot/look_a_like_prices')
SALE_CSV      = BASE / 'data/sale_dedup.csv'
OLD_RESULTS   = BASE / '_entrance_results.csv'
PROGRESS_FILE = BASE / '_entrance_progress.jsonl'
FINAL_CSV     = BASE / '_entrance_results.csv'

WORKERS    = 1          # один поток — ЦИАН не банит
DELAY      = (2.5, 5.0) # случайная задержка между запросами
SAVE_EVERY = 30

CIAN_MAP = {
    'separateFromTheStreet': 'отдельный с улицы',
    'separateFromStreet':    'отдельный с улицы',
    'separateFromTheYard':   'отдельный со двора',
    'separateFromYard':      'отдельный со двора',
    'commonFromStreet':      'общий с улицы',
    'commonFromTheStreet':   'общий с улицы',
    'commonFromYard':        'общий со двора',
    'commonFromTheYard':     'общий со двора',
    'throughEntrance':       'через подъезд',
    'throughHall':           'через холл',
    'отдельный с улицы':  'отдельный с улицы',
    'отдельный со двора': 'отдельный со двора',
    'общий с улицы':      'общий с улицы',
    'общий со двора':     'общий со двора',
    'через подъезд':      'через подъезд',
    'через холл':         'через холл',
    'SEPARATE': 'отдельный',
    'COMMON':   'общий',
}

UA_POOL = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0',
]

def _headers():
    return {
        'User-Agent': random.choice(UA_POOL),
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
    }

def _extract_offer_json(text):
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', text, re.DOTALL)
    if not scripts:
        return None
    big = max(scripts, key=len)
    m = re.search(r'"offerData"\s*:\s*(\{)', big)
    if not m:
        return None
    start = m.start(1)
    depth, i = 0, start
    while i < len(big):
        if big[i] == '{':
            depth += 1
        elif big[i] == '}':
            depth -= 1
            if depth == 0:
                break
        i += 1
    try:
        return json.loads(big[start:i+1]).get('offer', {})
    except Exception:
        return None

_cian_cookie = ''

def _warm_up_cian():
    """Получаем session cookie через главную страницу."""
    global _cian_cookie
    try:
        req = urllib.request.Request('https://www.cian.ru/', headers=_headers())
        with urllib.request.urlopen(req, timeout=20) as r:
            _cian_cookie = r.headers.get('Set-Cookie', '')
        time.sleep(random.uniform(2, 4))
    except Exception:
        pass

def fetch_entrance_cian(url):
    h = _headers()
    if _cian_cookie:
        h['Cookie'] = _cian_cookie
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read()
    text = raw.decode('utf-8', errors='ignore')
    offer = _extract_offer_json(text)
    if not offer:
        return None
    val = offer.get('inputType')
    return CIAN_MAP.get(val, val) if val else None

def fetch_entrance_yandex(url):
    KEY = b'"entranceType":"'
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read()
    idx = raw.find(KEY)
    if idx < 0:
        return None
    start = idx + len(KEY)
    end = raw.find(b'"', start)
    val = raw[start:end].decode('utf-8', errors='ignore')
    return CIAN_MAP.get(val, val) if val else None

def fetch_entrance(url):
    """Возвращает тип входа, None если не указан, 'RETRY' при 403."""
    try:
        if 'cian.ru' in url:
            return fetch_entrance_cian(url)
        elif 'ya.ru' in url or 'yandex.ru' in url:
            return fetch_entrance_yandex(url)
        return None
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return 'RETRY'  # не сохраняем, попробуем снова
        return f'ERR:{e.code}'
    except Exception as e:
        msg = str(e)[:60].replace('\n', ' ')
        return f'ERR:{msg}'

def load_done():
    """Загружает успешно спарсенные URL (без ERR и без RETRY)."""
    done = {}
    if OLD_RESULTS.exists():
        old = pd.read_csv(OLD_RESULTS, encoding='utf-8-sig')
        for _, row in old.iterrows():
            val = str(row.get('тип_входа_циан', ''))
            if val and val != 'nan' and not val.startswith('ERR'):
                done[row['URL']] = CIAN_MAP.get(val, val)
    if PROGRESS_FILE.exists():
        with PROGRESS_FILE.open(encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    # RETRY и ERR:403 не считаем финальными — попробуем ещё раз
                    if rec['val'] and rec['val'] not in ('RETRY',) and not str(rec['val']).startswith('ERR'):
                        done[rec['url']] = rec['val']
                    elif rec['val'] is None:
                        # null = страница отдала 200 но inputType отсутствует — это финально
                        done[rec['url']] = None
                except Exception:
                    pass
    return done

def append_progress(records):
    with PROGRESS_FILE.open('a', encoding='utf-8') as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')

def merge_and_save(done):
    rows = [
        {'URL': url, 'тип_входа_циан': val}
        for url, val in done.items()
        if val and not str(val).startswith('ERR')
    ]
    result = pd.DataFrame(rows)
    result.to_csv(FINAL_CSV, index=False, encoding='utf-8-sig')
    return result

def run_scrape():
    sale = pd.read_csv(SALE_CSV, sep=';')
    all_urls = sale['URL'].dropna().unique().tolist()
    print(f'URL в sale_dedup.csv: {len(all_urls)}')
    print('Разогрев сессии ЦИАН...')
    _warm_up_cian()

    done = load_done()
    # уже обработанные = есть в done (значение любое, даже None = "проверено, нет данных")
    already_checked = set(done.keys())
    todo = [u for u in all_urls if u not in already_checked]

    already_ok = sum(1 for v in done.values() if v)
    print(f'Уже проверено: {len(already_checked)} (с типом входа: {already_ok})')
    print(f'Осталось: {len(todo)}')
    if not todo:
        print('Готово — запустите с --merge')
        return

    eta_min = len(todo) * ((DELAY[0] + DELAY[1]) / 2) / 60
    print(f'Оценка времени: ~{eta_min:.0f} мин (1 поток, {DELAY[0]}-{DELAY[1]}с)\n')

    buffer = []
    done_count = 0
    found_count = 0
    retry_count = 0
    consecutive_403 = 0

    try:
        for url in todo:
            time.sleep(random.uniform(*DELAY))
            val = fetch_entrance(url)

            if val == 'RETRY':
                retry_count += 1
                consecutive_403 += 1
                # при серии 403 — долгая пауза
                if consecutive_403 >= 5:
                    pause = random.uniform(30, 60)
                    print(f'  5 подряд 403 — пауза {pause:.0f}с...')
                    time.sleep(pause)
                    consecutive_403 = 0
                # не сохраняем в буфер — повторим при следующем запуске
                done_count += 1
                continue
            else:
                consecutive_403 = 0

            # None = проверено, нет inputType — сохраняем как финальный результат
            buffer.append({'url': url, 'val': val})
            done[url] = val
            done_count += 1

            if val and not str(val).startswith('ERR'):
                found_count += 1

            if done_count % 50 == 0:
                pct = done_count / len(todo) * 100
                print(f'  [{done_count}/{len(todo)} {pct:.0f}%] найдено={found_count} retry={retry_count}')

            if len(buffer) >= SAVE_EVERY:
                append_progress(buffer)
                buffer.clear()

    except KeyboardInterrupt:
        print('\nПрервано — сохраняем...')
    finally:
        if buffer:
            append_progress(buffer)
        result = merge_and_save(done)
        print(f'\nИтого с типом входа: {len(result)}')
        if not result.empty:
            print(result['тип_входа_циан'].value_counts().to_string())

if __name__ == '__main__':
    if '--merge' in sys.argv:
        done = load_done()
        result = merge_and_save(done)
        print(f'Смержено: {len(result)} строк -> {FINAL_CSV}')
        if not result.empty:
            print(result['тип_входа_циан'].value_counts().to_string())
    else:
        run_scrape()
