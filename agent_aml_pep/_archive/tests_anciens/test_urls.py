"""Test de tous les liens SOURCES_TRACK_B — vérifie accessibilité + contenu."""
import sys, requests, warnings
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv(override=True)
from pep_collector import SOURCES_TRACK_B, _nettoyer_html

def _est_page_maintenance(texte: str) -> bool:
    mots = ["maintenance", "reviendrons bientôt", "we'll be back", "coming soon",
            "temporarily unavailable", "under construction", "indisponible",
            "503 service", "502 bad gateway", "be back soon"]
    t = texte.lower()
    return any(m in t for m in mots) and len(texte) < 5000

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"}
PAYS_NOMS = {
    "MA":"Maroc","DZ":"Algérie","TN":"Tunisie","LY":"Libye",
    "SN":"Sénégal","CI":"Côte d'Ivoire","ML":"Mali","BF":"Burkina Faso",
    "NE":"Niger","TG":"Togo","BJ":"Bénin","GW":"Guinée-Bissau","GN":"Guinée",
}

resultats = {"ok": [], "maintenance": [], "vide": [], "erreur": []}

for code, sources in SOURCES_TRACK_B.items():
    pays = PAYS_NOMS.get(code, code)
    print(f"\n[{code}] {pays}")
    for categorie, url in sources.items():
        try:
            r = requests.get(url, headers=HEADERS, timeout=12, verify=False)
            if r.status_code == 200:
                try:
                    html = r.content.decode("utf-8")
                except UnicodeDecodeError:
                    html = r.text
                texte = _nettoyer_html(html)
                if _est_page_maintenance(html):
                    print(f"  ⚠️  [{categorie}] MAINTENANCE — {url[:65]}")
                    resultats["maintenance"].append((code, categorie, url))
                elif len(texte) < 300:
                    print(f"  ⬜ [{categorie}] VIDE ({len(texte)} chars) — {url[:65]}")
                    resultats["vide"].append((code, categorie, url))
                else:
                    print(f"  ✅ [{categorie}] OK {r.status_code} — {len(texte)} chars — {url[:65]}")
                    resultats["ok"].append((code, categorie, url))
            else:
                print(f"  ❌ [{categorie}] HTTP {r.status_code} — {url[:65]}")
                resultats["erreur"].append((code, categorie, url, f"HTTP {r.status_code}"))
        except Exception as e:
            msg = str(e)[:60]
            print(f"  ❌ [{categorie}] ERREUR — {msg}")
            resultats["erreur"].append((code, categorie, url, msg))

print(f"\n{'='*65}")
print(f"✅ OK          : {len(resultats['ok'])}")
print(f"⚠️  Maintenance : {len(resultats['maintenance'])}")
print(f"⬜ Vide         : {len(resultats['vide'])}")
print(f"❌ Erreur       : {len(resultats['erreur'])}")
print(f"{'='*65}")

if resultats["erreur"]:
    print("\nLiens à corriger :")
    for code, cat, url, err in resultats["erreur"]:
        print(f"  [{code}] {cat} → {url[:60]} ({err})")
if resultats["maintenance"]:
    print("\nLiens en maintenance :")
    for code, cat, url in resultats["maintenance"]:
        print(f"  [{code}] {cat} → {url[:60]}")
