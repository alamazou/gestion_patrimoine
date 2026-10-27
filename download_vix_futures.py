#!/usr/bin/env python3
"""Télécharge les fichiers officiels CBOE VX, sans inventer de données manquantes.

pip install requests beautifulsoup4 pandas playwright
python -m playwright install chromium
python download_vix_futures.py
"""
from pathlib import Path
from urllib.parse import urljoin
import re
import time
import requests
from bs4 import BeautifulSoup

ROOT = Path('vix_futures_cboe')
ROOT.mkdir(exist_ok=True)
ARCHIVE = 'https://www.cboe.com/markets/us/futures/market-statistics/historical-data/settlement-archive/'
RECENT = 'https://www.cboe.com/markets/us/futures/market-statistics/historical-data/futures/'
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; VIXResearch/1.0)'}
session = requests.Session()
session.headers.update(HEADERS)

def save(url):
    name = url.split('?')[0].rsplit('/', 1)[-1]
    if not name.lower().endswith('.csv'):
        return False
    target = ROOT / name
    if target.exists() and target.stat().st_size > 100:
        return True
    try:
        r = session.get(url, timeout=45)
        r.raise_for_status()
        if len(r.content) < 100 or b',' not in r.content[:500]:
            print('  Format inattendu :', url)
            return False
        target.write_bytes(r.content)
        print('  OK', name, len(r.content), 'octets')
        return True
    except requests.RequestException as e:
        print('  ECHEC', url, str(e)[:130])
        return False

def archive_2004_2013():
    print('\n=== Archive CBOE 2004-2013 ===')
    # Schéma vérifié sur le site officiel : CFE_F13_VX.csv
    codes = 'FGHJKMNQUVXZ'
    for year in range(2004, 2014):
        for code in codes:
            url = (f'https://cdn.cboe.com/resources/futures/archive/volume-and-price/'
                   f'CFE_{code}{year % 100:02d}_VX.csv')
            save(url)
            time.sleep(0.07)

def recent_2013_present():
    print('\n=== Archive récente CBOE : recherche des liens CSV ===')
    # Les listes 2013+ sont souvent chargées dynamiquement : on utilise un navigateur.
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('Installer playwright : pip install playwright ; python -m playwright install chromium')
        return
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(RECENT, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(2000)
        # Détecter les sélecteurs de produit et d'année sans supposer leurs identifiants.
        selects = page.locator('select')
        print('Sélecteurs trouvés :', selects.count())
        for i in range(selects.count()):
            opts = selects.nth(i).locator('option').all_text_contents()
            print('  Sélecteur', i, ':', [x.strip() for x in opts[:8]])
        urls = set()
        def harvest():
            for a in page.locator('a[href]').all():
                href = a.get_attribute('href') or ''
                if '.csv' in href.lower() and ('vx' in href.lower() or 'vxt' in href.lower()):
                    urls.add(urljoin(RECENT, href))
        harvest()
        # Parcourir les sélecteurs d'année contenant des années 2013+.
        for i in range(selects.count()):
            options = selects.nth(i).locator('option')
            values = []
            for j in range(options.count()):
                opt = options.nth(j)
                label = (opt.text_content() or '').strip()
                value = opt.get_attribute('value') or ''
                if re.search(r'20(1[3-9]|2[0-9])', label + ' ' + value):
                    values.append(value)
            for value in dict.fromkeys(values):
                try:
                    selects.nth(i).select_option(value=value)
                    page.wait_for_timeout(450)
                    harvest()
                except Exception as exc:
                    print('  Sélection ignorée :', value, str(exc)[:70])
        browser.close()
    print('Fichiers CSV récents détectés :', len(urls))
    for url in sorted(urls):
        save(url)
        time.sleep(0.1)
    if not urls:
        print('ATTENTION : liens récents non détectés automatiquement. ')
        print('Téléchargement manuel possible :', RECENT)

def inventory():
    files = sorted(ROOT.glob('*.csv'))
    print(f'\nTOTAL : {len(files)} fichiers CSV dans {ROOT.resolve()}')
    if not files:
        raise RuntimeError('Aucun fichier téléchargé. Vérifier réseau et accès CBOE.')
    # Ne pas fusionner aveuglément : formats CBOE anciens/récents potentiellement différents.
    import pandas as pd
    info = []
    for f in files:
        try:
            df = pd.read_csv(f, nrows=2)
            info.append({'file': f.name, 'size_bytes': f.stat().st_size,
                         'columns': ' | '.join(map(str, df.columns))})
        except Exception as e:
            info.append({'file': f.name, 'size_bytes': f.stat().st_size, 'columns': f'ERROR {e}'})
    pd.DataFrame(info).to_csv(ROOT / 'inventory.csv', index=False)
    print('Inventaire des formats :', ROOT / 'inventory.csv')
    print('IMPORTANT : vérifier la couverture et les colonnes avant de construire VX1-VX4.')

if __name__ == '__main__':
    archive_2004_2013()
    recent_2013_present()
    inventory()
