import sys, os, requests, warnings, json
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv(override=True)
from pep_collector import _nettoyer_html, _est_personne_valide, llm, _extraire_premier_json_array

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"}

url = "https://www.presidence.sn/fr/actualites/liste-complete-des-membres-du-nouveau-gouvernement/"
r = requests.get(url, headers=headers, timeout=15, verify=False)

# Fix encodage UTF-8
try:
    html_text = r.content.decode("utf-8")
except UnicodeDecodeError:
    html_text = r.text

texte = _nettoyer_html(html_text)
print(f"Texte nettoyé ({len(texte)} chars) :")
print(texte[:600])

print("\n" + "="*60)
print("Appel LLM brut...")

prompt = f"""Tu es un expert en conformité AML/PEP (Personnes Politiquement Exposées).
Voici le contenu d'une page officielle (gouvernement) du pays Sénégal (SN).
Retourne UNIQUEMENT un JSON valide :
[
  {{"prenom":"...","nom":"...","fonction":"...","statut_mandat":"actif","date_nomination":"","date_sortie":""}},
  ...
]
RÈGLES :
✅ Ministres, parlementaires, directeurs généraux, gouverneurs, ambassadeurs
✅ statut_mandat = "actif" si en poste, "ex_pep" si ancien
❌ Régions, institutions, associations, personnalités étrangères non du Sénégal

Contenu :
{texte[:3000]}

JSON :"""

try:
    resp = llm.invoke(prompt)
    raw = resp.content.strip()
    print(f"\nRéponse LLM brute ({len(raw)} chars):")
    print(raw[:800])
    personnes = _extraire_premier_json_array(raw)
    print(f"\nJSON parsé : {len(personnes)} entrées")
    for p in personnes[:10]:
        valide = _est_personne_valide(p)
        print(f"  [{'OK' if valide else 'KO'}] {p.get('prenom','')} {p.get('nom','')} | {p.get('fonction','')[:50]}")
except Exception as e:
    print(f"ERREUR LLM : {e}")
