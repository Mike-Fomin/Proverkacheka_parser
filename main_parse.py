import concurrent.futures
import json
from tqdm import tqdm

import os
import requests
import traceback

from bs4 import BeautifulSoup

HEADERS: dict = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
}

URL: str = 'https://proverkacheka.com'

TOP_TITLES_KEYS: list = [
    'user',
    'metadata',
    'userInn',
    'dateTime',
    'requestNumber',
    'shiftNumber',
    'cashier',
    'operationType'
]

SELLED_TITLES_KEYS: list = [
    'positionNumber',
    'name',
    'price',
    'quantity',
    'sum'
]

BOTTOM_TITLES_KEYS: list = [
    'totalSum',
    'cashTotalSum',
    'ecashTotalSum'
]


def parse_check(url: str, item: dict) -> dict:
    try:
        resp: requests.Response = requests.get(url=url, headers=HEADERS)

        func_soup: BeautifulSoup = BeautifulSoup(resp.text, 'lxml')
        table: BeautifulSoup = func_soup.find('table')
        rows: list = table.find_all('tr')

        for key, value in zip(TOP_TITLES_KEYS, filter(lambda x: x.text.strip(), rows[:9])):
            value = value.text.strip()

            if key == 'userInn':
                value: str = value.replace('ИНН ', '')
            elif key == 'metadata':
                value: dict = {'address': value}
            elif key == 'requestNumber':
                value: str = value.replace('Чек №', '').strip()
            elif key == 'shiftNumber':
                value: str = value.replace('Смена №', '').strip()
            elif key == 'cashier':
                continue

            item[key] = value

        sell: list = [data.find_all('td') for data in rows[10:] if data.get('class')[0] == 'b-check_item']
        gap: int = len(sell)

        sell_elems: list = []
        for sell_item in sell:
            elem: dict = {}
            for key, value in zip(SELLED_TITLES_KEYS, sell_item):
                value = value.text.strip()

                if key == 'positionNumber':
                    value: int = int(value)
                elif key in ['price', 'quantity', 'sum']:
                    value: float = round(float(value), 2)

                elem[key] = value

            sell_elems.append(elem)

        item['items'] = sell_elems

        for key, value in zip(BOTTOM_TITLES_KEYS, rows[10 + gap:13 + gap]):
            value: str = ' '.join(map(lambda x: x.text.strip(), value.find_all('td')))
            value = value.replace('  ', ' ')

            if key == 'totalSum' and value.startswith('ИТОГО'):
                value: float = round(float(value.replace('ИТОГО:', '')), 2)
            elif key == 'cashTotalSum' and value.startswith('Наличные'):
                value: float = round(float(value.replace('Наличные', '')), 2)
            elif key == 'ecashTotalSum' and value.startswith('Карта'):
                value: float = round(float(value.replace('Карта', '')), 2)
            else:
                continue

            item[key] = value

        for data in rows[13 + gap:]:
            elem: str = data.text.strip()
            if elem.startswith('ВИД НАЛОГООБЛОЖЕНИЯ'):
                item['appliedTaxationType'] = elem.replace('ВИД НАЛОГООБЛОЖЕНИЯ: ', '')
            elif elem.startswith('РЕГ.'):
                item['kktRegId'] = elem.split('ККТ: ')[-1]
            elif elem.startswith('ЗАВОД'):
                continue
            elif elem.startswith('ФПД'):
                break
            elif elem.startswith('ФН'):
                item['fiscalDriveNumber'] = elem[4:]
            elif elem.startswith('ФД'):
                item['fiscalDocumentNumber'] = elem[4:]
            else:
                data: list = data.find_all('td')
                key, value = data[0].text.strip(), data[-1].text.strip()
                value: float = round(float(value), 2)
                if key.startswith('НДС не облагается'):
                    key: str = 'noNds'
                elif key.startswith('НДС итога чека со ставкой 0%'):
                    key: str = 'nds0'
                elif key.startswith('НДС итога чека со ставкой 10%'):
                    key: str = 'nds10'
                elif key.startswith('НДС итога чека со ставкой 20%'):
                    key: str = 'nds20'

                item[key] = value
    except:
        print(f"Чек {item['checkID']} - ошибка!")
        traceback.print_exc()
    else:
        return item


def get_all_checks_list(page: int) -> list[BeautifulSoup]:
    try:
        response: requests.Response = requests.get(url=f'https://proverkacheka.com/check&p={page}', headers=HEADERS)

        soup: BeautifulSoup = BeautifulSoup(response.text, 'lxml')
        main_block: BeautifulSoup = soup.find('div', class_='col-md-9')
        row_blocks: BeautifulSoup = main_block.find_all('div', class_='row')

        table: BeautifulSoup = row_blocks[1].find('table')
        data_rows: list = table.find_all('tr')
    except:
        print(f"Page {page} error!")
        traceback.print_exc()
    else:
        return list(filter(lambda x: not x.get('class'), data_rows))


def main() -> None:
    all_items: list = []
    existed_items: list = []

    if os.path.exists('all_items.json'):
        print('Считываются данные из файла...')
        with open('all_items.json', 'r', encoding='utf-8') as full_file:
            all_items: list = json.load(full_file)

        print('Данные успешно прочитаны...')
        existed_items: list = [ex['checkID'] for ex in all_items]

    all_checks: list = []
    print('Парсинг всех страниц с чеками...')

    with tqdm(desc='Сохранение страниц с чеками:', total=10) as pbar1:

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as page_executor:
            page_futures: list = [page_executor.submit(get_all_checks_list, page) for page in range(1, 11)]

            for page_future in concurrent.futures.as_completed(page_futures):
                result = page_future.result()
                pbar1.update(1)
                if result:
                    all_checks.extend(result)

    futures: list = []

    with tqdm(desc='Парсинг чеков:', total=len(all_checks)) as pbar2:

        with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
            for check in all_checks:
                if not check.get('class'):
                    link: str = URL + check.find('a').get('href')
                    data: list = check.find_all('td')
                    check_number: int = int(data[0].text.strip())
                    item: dict = {
                        'checkID': check_number
                    }
                    if item['checkID'] not in existed_items:
                        task = executor.submit(parse_check, link, item)
                        futures.append(task)

            for f in concurrent.futures.as_completed(futures):
                res = f.result()
                pbar2.update(1)
                if res:
                    all_items.append(res)

    print(f"Сохранение в файл...")
    with open('all_items.json', 'w', encoding='utf-8') as file:
        json.dump(all_items, file, indent=4, ensure_ascii=False)

    print(f"Парсинг успешно завершен!")


if __name__ == '__main__':
    main()
