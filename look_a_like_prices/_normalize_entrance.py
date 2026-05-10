import pandas as pd

NORM = {
    'отдельный с улицы':     'отдельный с улицы',
    'separateFromTheStreet': 'отдельный с улицы',
    'отдельный со двора':    'отдельный со двора',
    'separateFromTheYard':   'отдельный со двора',
    'commonFromStreet':      'общий с улицы',
    'commonFromTheStreet':   'общий с улицы',
    'commonFromYard':        'общий со двора',
    'commonFromTheYard':     'общий со двора',
}

df = pd.read_csv('C:/git/realrobot/look_a_like_prices/_entrance_results.csv')
df['тип_входа'] = df['тип_входа_циан'].map(NORM)
df.to_csv('C:/git/realrobot/look_a_like_prices/_entrance_results.csv', index=False, encoding='utf-8-sig')

print(df['тип_входа'].value_counts().to_string())
print('Нет данных:', df['тип_входа'].isna().sum())
