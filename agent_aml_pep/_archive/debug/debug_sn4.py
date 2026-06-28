import sys, json, requests, warnings, re
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv(override=True)
from pep_collector import _nettoyer_html, llm, _extraire_premier_json_array

r = requests.get(
    "https://www.presidence.sn/fr/actualites/liste-complete-des-membres-du-nouveau-gouvernement/",
    headers={"User-Agent": "Mozilla/5.0"}, timeout=15, verify=False
)
texte = _nettoyer_html(r.content.decode("utf-8"))

prompt = (
    "Extrait les PEP du texte suivant. Retourne UNIQUEMENT un tableau JSON valide, "
    "sans backticks markdown, sans texte avant ou après :\n"
    '[{"prenom":"...","nom":"...","fonction":"...","statut_mandat":"actif",'
    '"date_nomination":"","date_sortie":""}]\n\n'
    + texte[:2500]
    + "\n\nJSON :"
)

resp = llm.invoke(prompt)
raw = resp.content.strip()
raw_clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

print(f"Longueur totale réponse : {len(raw_clean)} chars")
print(f"Début : {raw_clean[:200]}")
print(f"Fin   : {raw_clean[-200:]}")

# Tester json.loads directement
try:
    data = json.loads(raw_clean)
    print(f"\njson.loads OK : {len(data)} entrées")
    for p in data[:5]:
        print(f"  {p.get('prenom','')} {p.get('nom','')} | {p.get('fonction','')[:50]}")
except json.JSONDecodeError as e:
    print(f"\njson.loads ERREUR : {e}")
    # Trouver l'endroit du problème
    pos = e.pos
    print(f"Position erreur : {pos}")
    print(f"Contexte : ...{raw_clean[max(0,pos-50):pos+50]}...")

print(f"\n_extraire_premier_json_array : {len(_extraire_premier_json_array(raw_clean))} entrées")
