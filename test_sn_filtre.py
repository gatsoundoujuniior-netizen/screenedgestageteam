"""Test Track B extraction SN avec filtre corrigé — sans Track A."""
import sys, warnings
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv(override=True)
from pep_collector import (
    _llm_extraire_liste_pep, _est_personne_valide,
    _scraper_avec_fallback, SOURCES_TRACK_B
)

code_iso = "SN"
pays_nom = "Sénégal"
sources = SOURCES_TRACK_B.get(code_iso, {})
total_extraites = 0
total_valides = 0

for categorie, url in sources.items():
    print(f"\n--- [{categorie}] {url[:70]} ---")
    contenu, url_reelle = _scraper_avec_fallback(url, code_iso, categorie, pays_nom)
    if not contenu:
        print("  Aucun contenu")
        continue
    personnes = _llm_extraire_liste_pep(contenu, code_iso, categorie, pays_nom)
    valides = [p for p in personnes if _est_personne_valide(p)]
    total_extraites += len(personnes)
    total_valides += len(valides)
    print(f"  {len(personnes)} extraites → {len(valides)} valides")
    for p in valides[:10]:
        print(f"  ✅ {p['prenom']} {p['nom']} | {(p.get('fonction') or '')[:55]}")

print(f"\n{'='*60}")
print(f"TOTAL SN: {total_extraites} extraites → {total_valides} valides")
