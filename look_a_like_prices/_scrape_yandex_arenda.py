"""Парсит тип входа для Яндекс URL из arenda.csv (дедуплицированных)."""
import json, random, re, time, urllib.request, urllib.error
from pathlib import Path
import numpy as np
import pandas as pd

BASE            = Path('C:/git/realrobot/look_a_like_prices')
ARENDA_CSV      = BASE / 'data/arenda.csv/arenda.csv'
PROGRESS_FILE   = BASE / '_entrance_progress_arenda.jsonl'
FINAL_CSV       = BASE / '_entrance_results_arenda.csv'
DELAY           = (2.5, 5.0)
SAVE_EVERY      = 30

CIAN_MAP = {
    'SEPARATE': 'отдельный', 'COMMON': 'общий',
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
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'ru-RU,ru;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}
KEY = b'"entranceType":"'

def get_param(s, key):
    if not isinstance(s, str): return None
    m = re.search(rf'{re.escape(key)}=([^|]+)', s)
    return m.group(1).strip() if m else None

def dedup_urls(df):
    """Возвращает дедуплицированный список Яндекс URL (последняя дата в группе)."""
    df = df.copy()
    df['площадь'] = pd.to_numeric(
        df['Доп.параметры'].apply(lambda x: get_param(x, 'Общая площадь')).str.replace(',', '.'),
        errors='coerce')
    df['этаж']    = df['Доп.параметры'].apply(lambda x: get_param(x, 'Этаж'))
    df['lat']     = pd.to_numeric(df['lat'], errors='coerce')
    df['lng']     = pd.to_numeric(df['lng'], errors='coerce')
    df['дата_dt'] = pd.to_datetime(df['Дата'], errors='coerce')

    has_geo = df['lat'].notna() & df['lng'].notna() & df['площадь'].notna() & df['этаж'].notna()
    df_geo  = df[has_geo].copy()
    df_nogeo = df[~has_geo].copy()

    df_geo['area_g'] = np.where(
        df_geo['площадь'] < 15,
        df_geo['площадь'].round().astype('Int64'),
        (df_geo['площадь'] / 5).round().astype(int))
    df_geo['lat_g'] = (df_geo['lat'] * 2000).round().astype(int)
    df_geo['lng_g'] = (df_geo['lng'] * 2000).round().astype(int)
    df_geo['group'] = (df_geo['lat_g'].astype(str) + '_' + df_geo['lng_g'].astype(str) + '_' +
                       df_geo['этаж'].astype(str) + '_' + df_geo['area_g'].astype(str))

    df_dedup = df_geo.sort_values('дата_dt', ascending=False).drop_duplicates('group', keep='first')
    all_dedup = pd.concat([df_dedup, df_nogeo], ignore_index=True)
    ya = all_dedup[all_dedup['URL'].str.contains('ya.ru|yandex.ru', na=False)]
    return ya['URL'].dropna().unique().tolist()

def fetch_yandex(url):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read()
        idx = raw.find(KEY)
        if idx < 0:
            return None
        start = idx + len(KEY)
        end = raw.find(b'"', start)
        val = raw[start:end].decode('utf-8', errors='ignore')
        return CIAN_MAP.get(val, val) if val else None
    except urllib.error.HTTPError as e:
        return f'ERR:{e.code}'
    except Exception as e:
        return f'ERR:{str(e)[:50]}'

# загружаем уже готовые
done = {}
if PROGRESS_FILE.exists():
    for line in PROGRESS_FILE.open(encoding='utf-8'):
        try:
            r = json.loads(line.strip())
            if r['val'] is not None:
                done[r['url']] = r['val']
        except Exception:
            pass

# дедуплицированные Яндекс URL аренды
print('Загружаем и дедуплицируем arenda.csv...')
ar = pd.read_csv(ARENDA_CSV, sep=';')
ya_urls = dedup_urls(ar)
todo = [u for u in ya_urls if u not in done]

print(f'Яндекс аренда: {len(ya_urls)} уникальных URL после дедупа')
print(f'Уже готово: {len(ya_urls) - len(todo)}, осталось: {len(todo)}')
eta = len(todo) * (DELAY[0] + DELAY[1]) / 2 / 60
print(f'Оценка: ~{eta:.0f} мин (~{eta/60:.1f} ч)\n')

buffer = []
found = 0

try:
    for i, url in enumerate(todo, 1):
        time.sleep(random.uniform(*DELAY))
        val = fetch_yandex(url)
        buffer.append({'url': url, 'val': val})
        if val and not str(val).startswith('ERR'):
            found += 1
        if i % 50 == 0 or i <= 3:
            print(f'[{i}/{len(todo)}] найдено={found} ({found/i*100:.0f}%)  {str(val):<20} {url[-45:]}')
        if len(buffer) >= SAVE_EVERY:
            with PROGRESS_FILE.open('a', encoding='utf-8') as f:
                for rec in buffer:
                    f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            buffer.clear()
except KeyboardInterrupt:
    print('\nПрервано')
finally:
    if buffer:
        with PROGRESS_FILE.open('a', encoding='utf-8') as f:
            for rec in buffer:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    all_done = {}
    if PROGRESS_FILE.exists():
        for line in PROGRESS_FILE.open(encoding='utf-8'):
            try:
                r = json.loads(line.strip())
                if r['val'] and not str(r['val']).startswith('ERR'):
                    all_done[r['url']] = r['val']
            except Exception:
                pass
    rows = [{'URL': u, 'тип_входа': v} for u, v in all_done.items()]
    pd.DataFrame(rows).to_csv(FINAL_CSV, index=False, encoding='utf-8-sig')
    print(f'\nГотово: {found} новых, итого в CSV: {len(rows)} -> {FINAL_CSV}')
