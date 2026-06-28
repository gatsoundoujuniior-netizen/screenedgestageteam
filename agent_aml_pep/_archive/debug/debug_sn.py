import sys, os, requests, warnings
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv(override=True)
from pep_collector import _nettoyer_html, _llm_extraire_liste_pep, _est_personne_valide

r = requests.get(
    "https://primature.sn/publications/actualites/composition-du-gouvernement",
    headers={"User-Agent": "Mozilla/5.0"}, timeout=15, verify=False
)
print("Status:", r.status_code, "Len:", len(r.text))
texte = _nettoyer_html(r.text)
print("=== Extrait texte (800 chars) ===")
print(texte[:800])
print("\n=== LLM extraction ===")
personnes = _llm_extraire_liste_pep(texte, "SN", "gouvernement", "Senegal")
print(f"Extraites: {len(personnes)}")
for p in personnes[:15]:
    valide = _est_personne_valide(p)
    tag = "OK" if valide else "KO"
    print(f"  [{tag}] {p.get('prenom','')} {p.get('nom','')} | {str(p.get('fonction',''))[:50]}")
