import csv
import math
import re
from pathlib import Path

INPUT_PATH = Path('data/investmoscow_2026-03-04.csv')
OUTPUT_PATH = INPUT_PATH.with_name(INPUT_PATH.stem + '_usage-descriptions.md')


def to_float(value: str) -> float:
    cleaned = value.strip().replace(' ', '').replace('\u00a0', '').replace(',', '.')
    try:
        return float(cleaned)
    except ValueError:
        return float('nan')


def format_area(value: float) -> str:
    if math.isnan(value):
        return ''
    rounded = round(value, 1)
    if abs(rounded - round(rounded)) < 0.05:
        return str(int(round(rounded)))
    return f"{rounded:.1f}".replace('.', ',')


def format_price(value: float, decimals: int = 0) -> str:
    if math.isnan(value):
        return ''
    formatted = f"{value:,.{decimals}f}"
    return formatted.replace(',', ' ').replace('.', ',')


def extract_district(address: str) -> str:
    parts = [p.strip() for p in address.split(',') if p.strip()]
    for part in parts:
        if 'АО' in part or 'р-н' in part or 'округ' in part.lower():
            return part
    return parts[0] if parts else ''


def floor_profile(floor_value: str) -> dict:
    floor = (floor_value or '').strip().lower()
    is_basement = 'подвал' in floor or '-1' in floor
    is_cokol = 'цокол' in floor
    numbers = re.findall(r'-?\d+', floor)
    numeric = numbers[0] if numbers else ''
    is_ground = numeric == '1'
    if floor in {'подвал', 'подполье'}:
        label = 'подвальный уровень'
        prep = 'подвальном уровне'
        gen = 'подвального уровня'
    elif is_cokol:
        label = 'цокольный этаж'
        prep = 'цокольном этаже'
        gen = 'цокольного этажа'
    elif numeric:
        label = f"{numeric}-й этаж"
        prep = f"{numeric}-м этаже"
        gen = f"{numeric}-го этажа"
    elif floor:
        label = floor_value
        prep = floor_value
        gen = floor_value
    else:
        label = 'неуточнённый уровень'
        prep = 'неуточнённом уровне'
        gen = 'неуточнённого уровня'
    return {
        'label': label,
        'is_basement': is_basement,
        'is_cokol': is_cokol,
        'is_ground': is_ground,
        'prep': prep,
        'genitive': gen,
    }


def entry_profile(entry_value: str) -> dict:
    entry = (entry_value or '').strip().lower()
    if 'отдель' in entry:
        label = 'отдельный вход с улицы'
        typ = 'street'
    elif 'подъезд' in entry:
        label = 'вход через подъезд дома'
        typ = 'hallway'
    elif 'места общего пользования' in entry:
        label = 'вход через места общего пользования'
        typ = 'common'
    elif 'иную собственность' in entry:
        label = 'вход через соседнюю собственность'
        typ = 'shared'
    else:
        label = entry_value or 'тип входа не указан'
        typ = 'other'
    return {'label': label, 'type': typ}


def describe_location(floor_info: dict, storeys: str) -> str:
    storeys_part = f"в здании из {storeys} этажей" if storeys else "в здании"
    if floor_info['is_basement']:
        return f"Помещение занимает {floor_info['label']} {storeys_part}"
    return f"Помещение расположено на {floor_info['prep']} {storeys_part}"


def describe_entry(entry_info: dict) -> str:
    return f"{entry_info['label'].capitalize()} обеспечивает доступ посетителям и персоналу"


def build_suggestions(area: float, district: str, metro: str, floor_info: dict, entry_info: dict) -> list:
    suggestions = []
    metro_phrase = f" (метро {metro})" if metro else ''
    metro_text = metro if metro else 'ближайшего метро'
    district_phrase = f"в {district}" if district else 'в районе'

    def add(text: str):
        if text and text not in suggestions:
            suggestions.append(text)

    if area <= 60:
        add(f"Пункт выдачи заказов и микро-ритейл: компактная площадь {format_area(area)} м² и {entry_info['label']} дают возможность быстро запустить магазин у дома{metro_phrase}.")
    if 40 <= area <= 140 and entry_info['type'] == 'street':
        add(f"Кафе, кофейня to-go или пекарня: фиксируйте посадку {district_phrase}, а поток с улицы поддерживает {entry_info['label']}.")
    if area >= 80:
        add(f"Клиентский офис или сервисный центр: пространства {format_area(area)} м² хватит для ресепшена и рабочих мест, а близость {metro_text} удобна персоналу.")
    if area >= 120 and not floor_info['is_basement']:
        add(f"Образовательная площадка или детский клуб: можно выделить аудитории и подсобные зоны, главное — продумать акустику на {floor_info['prep']}.")
    if area >= 200:
        add(f"Фитнес, йога или танцевальная студия: метраж позволяет разделить зал, раздевалки и техчасть, потребуется усилить вентиляцию и шумоизоляцию.")
    if floor_info['is_basement'] or floor_info['is_cokol']:
        add(f"Мастерские, студии или бэк-офис: формат {floor_info['genitive']} снижает ставку, зато подойдёт для тихого производства и хранения.")
    if area <= 120 and entry_info['type'] in {'hallway', 'common', 'shared'}:
        add(f"Кабинеты услуг по записи (косметология, репетиторы, микроковоркинг): спокойный {entry_info['label']} регулирует поток посетителей.")
    if area >= 60 and area <= 200:
        add(f"Шоурум маркетплейса или демонстрационный зал: зонирование на склад и клиентскую часть легко реализовать на {format_area(area)} м².")
    if area >= 90:
        add(f"Мультимедийные/креативные студии: можно поставить павильоны для съёмок контента или подкастов, используя {floor_info['label']} и {entry_info['label']}.")
    if area > 250:
        add(f"Фуд-маркет локального масштаба или гастропарк с корнерами: позволяет собрать несколько концепций и общий food-тех блок.")

    base_pool = [
        f"Гибкий склад-офис для e-commerce: совместите хранение и обработку заказов, загрузку организуйте через {entry_info['label']}.",
        f"Социальные сервисы (МФЦ, центр поддержки резидентов): площадь позволяет планировать залы ожидания и переговорные.",
        f"Частная клиника или стоматология: зонирование на кабинеты и стерилизационные отвечает требованиям формата при условии усиленной инженерии.",
        f"IT- или цифровой кампус: можно выделить openspace, комнаты фокуса и серверную, а пешая доступность {metro_text} облегчает набор команды.",
    ]
    for idea in base_pool:
        add(idea)
        if len(suggestions) >= 5:
            break

    while len(suggestions) < 5:
        add("Многофункциональная площадка с гибким графиком: пространство можно адаптировать под pop-up форматы, сезонные шоурумы и совместные мероприятия.")

    return suggestions[:5]


def build_special_notes(tender_id: str, url: str, price_per_sqm: float, entry_info: dict, floor_info: dict, metro: str, functional: str) -> list:
    notes = []
    if not math.isnan(price_per_sqm):
        notes.append(f"Ориентировочная цена квадратного метра — {format_price(price_per_sqm)} руб.; используйте показатель в финансовой модели.")
        notes.append(f"Назначение по документации: {functional or 'не указано'}.")
        notes.append(f"Тип входа: {entry_info['label']}.")
        metro_note = metro if metro else 'не указано'
        notes.append(f"Расположение: {floor_info['label']}, пешая доступность метро {metro_note}.")
    notes.append(f"Полный пакет документов и регламент участия опубликованы на портале (тендер {tender_id}, {url}).")
    if floor_info['is_basement']:
        notes.append("Для форматов с массовым посещением понадобится согласовать требования по эвакуации, вентиляции и гидроизоляции подвального уровня.")
    if entry_info['type'] in {'hallway', 'common', 'shared'}:
        notes.append("Рекламные конструкции и режим доступа нужно синхронизировать с управляющей организацией дома.")
    return notes


def main() -> None:
    if not INPUT_PATH.exists():
        raise SystemExit(f'Не найден файл {INPUT_PATH}')

    with INPUT_PATH.open('r', encoding='utf-8-sig', newline='') as src:
        reader = csv.DictReader(src)
        rows = list(reader)

    lines = []
    lines.append('# Варианты использования объектов (данные от 2026-03-04)')
    lines.append('')
    for idx, row in enumerate(rows, 1):
        url = row['url']
        tender_id = url.rstrip('/').split('/')[-1]
        area_value = to_float(row['площадь м²'])
        price_value = to_float(row['цена руб.'])
        price_per_sqm = price_value / area_value if area_value and not math.isnan(price_value) else math.nan
        area_text = format_area(area_value)
        price_text = row['цена руб.']
        address = row['адрес']
        functional = row['функциональное_назначение']
        entry_raw = row['тип_входа']
        floor_raw = row['этаж']
        storeys = row['этажность']
        metro = row['метро']

        district = extract_district(address)
        floor_info = floor_profile(floor_raw)
        entry_info = entry_profile(entry_raw)
        suggestions = build_suggestions(area_value, district, metro, floor_info, entry_info)
        notes = build_special_notes(tender_id, url, price_per_sqm, entry_info, floor_info, metro, functional)
        price_per_text = format_price(price_per_sqm) if not math.isnan(price_per_sqm) else ''
        price_fragment = f"(≈ {price_per_text} руб./м²)" if price_per_text else ''
        location_sentence = describe_location(floor_info, storeys)
        entry_sentence = describe_entry(entry_info)
        metro_sentence = f"Ближайшее метро — {metro}." if metro else "Ближайшее метро не указано в выгрузке."
        summary = (
            f"## Тендер {tender_id} — {area_text} м²\n"
            f"Площадь {area_text} м² по адресу {address}. Цена из лота — {price_text} {price_fragment}. "
            f"Назначение: {functional or 'не указано'}. {location_sentence}. {entry_sentence}. {metro_sentence}"
        )
        lines.append(summary)
        lines.append('')
        lines.append('Варианты использования:')
        for i, idea in enumerate(suggestions, 1):
            lines.append(f"{i}. {idea}")
        lines.append('')
        lines.append('Особые условия:')
        for note in notes:
            lines.append(f"- {note}")
        lines.append('')

    OUTPUT_PATH.write_text('\n'.join(lines).strip() + '\n', encoding='utf-8-sig')
    print(f'Готово: {OUTPUT_PATH} ({len(rows)} объектов)')


if __name__ == '__main__':
    main()
