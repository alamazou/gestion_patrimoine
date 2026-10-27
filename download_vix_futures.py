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
    """Parcourt les échéances mensuelles VX, URL CBOE confirmée par l'utilisateur."""
    from datetime import date, timedelta
    print('\\n=== Contrats VX 2014-2026 ===')
    base = 'https://cdn.cboe.com/data/us/futures/market_statistics/historical_data/VX/'
    today = date.today()
    for year in range(2014, today.year + 1):
        successes = 0
        for month in range(1, 13):
            if date(year, month, 1) > today:
                break
            # Règle standard : 30 jours avant le 3e vendredi du mois suivant.
            ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
            first = date(ny, nm, 1)
            third_friday = first + timedelta(days=(4 - first.weekday()) % 7 + 14)
            expiry = third_friday - timedelta(days=30)
            # Les jours fériés peuvent avancer l'échéance d'un jour.
            candidates = [expiry, expiry - timedelta(days=1),
                          expiry - timedelta(days=2)]
            for candidate in candidates:
                target = ROOT / f'VX_{candidate.isoformat()}.csv'
                if target.exists() and target.stat().st_size > 100:
                    successes += 1
                    break
                url = base + target.name
                if save(url):
                    successes += 1
                    break
            time.sleep(0.06)
        print(f'Année {year}: {successes} échéances mensuelles récupérées')
    print('Les contrats hebdomadaires ne sont pas inclus.')

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
