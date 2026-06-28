import sys, json, requests, warnings, re
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv(override=True)
from pep_collector import _nettoyer_html, llm, _extraire_premier_json_array, _normaliser_guillemets, _PROMPT_EXTRACTION

r = requests.get(
    "https://www.presidence.sn/fr/actualites/liste-complete-des-membres-du-nouveau-gouvernement/",
    headers={"User-Agent": "Mozilla/5.0"}, timeout=15, verify=False
)
contenu = _nettoyer_html(r.content.decode("utf-8"))
print(f"Contenu nettoyé : {len(contenu)} chars\n")

prompt = _PROMPT_EXTRACTION.format(
    categorie="gouvernement", pays_nom="Sénégal",
    code_iso="SN", contenu=contenu[:6000]
)
resp = llm.invoke(prompt)
raw = resp.content.strip()
print(f"=== RÉPONSE LLM BRUTE ({len(raw)} chars) ===")
print(raw[:300])
print("...")
print(raw[-300:])

# Appliquer le fix
texte = raw.replace("```json", "").replace("```", "").strip()
texte = _normaliser_guillemets(texte)
print(f"\n=== APRÈS NETTOYAGE ({len(texte)} chars) ===")
print(texte[:200])
print("...")
print(texte[-200:])

# Parser
data = _extraire_premier_json_array(texte)
print(f"\n=== RÉSULTAT : {len(data)} entrées ===")
for p in data[:5]:
    print(f"  {p.get('prenom','')} {p.get('nom','')} | {p.get('fonction','')[:50]}")

# Si 0, tenter json.loads direct
if len(data) == 0:
    print("\n=== json.loads direct ===")
    try:
        d2 = json.loads(texte)
        print(f"OK : {len(d2)} entrées")
    except json.JSONDecodeError as e:
        print(f"ERREUR : {e}")
        pos = e.pos
        print(f"Contexte erreur : ...{texte[max(0,pos-60):pos+60]}...")
