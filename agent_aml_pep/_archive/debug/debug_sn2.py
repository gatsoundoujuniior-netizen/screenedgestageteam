import sys, os, requests, warnings
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv(override=True)
from pep_collector import _nettoyer_html

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
           "Accept-Language": "fr-FR,fr;q=0.9"}

urls = [
    "https://www.presidence.sn/fr/institutions/le-gouvernement/",
    "https://www.presidence.sn/fr/actualites/liste-complete-des-membres-du-nouveau-gouvernement/",
]

for url in urls:
    print(f"\n{'='*60}")
    print(f"URL : {url}")
    r = requests.get(url, headers=headers, timeout=15, verify=False)
    print(f"Status : {r.status_code} | Raw HTML : {len(r.text)} chars")
    texte = _nettoyer_html(r.text)
    print(f"Texte nettoyé : {len(texte)} chars")
    print(f"--- Extrait (500 premiers chars) ---")
    print(texte[:500])
    print(f"--- Mots-clés ministres présents ? ---")
    mots = ["ministre", "premier", "president", "Faye", "Sonko", "gouvernement"]
    for m in mots:
        print(f"  '{m}' : {'OUI' if m.lower() in texte.lower() else 'NON'}")
