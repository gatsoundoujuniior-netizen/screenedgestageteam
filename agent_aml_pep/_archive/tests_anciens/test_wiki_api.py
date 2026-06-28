import requests

nom = "Abdelilah Benkirane"
titre = "_".join(p.capitalize() for p in nom.strip().split())

url = "https://fr.wikipedia.org/w/api.php"
params = {
    "action": "query",
    "titles": titre,
    "prop": "extracts",
    "explaintext": True,   # texte brut sans HTML
    "exsectionformat": "plain",
    "format": "json",
    "redirects": 1,
}

r = requests.get(url, params=params, timeout=10, headers={"User-Agent": "PEPAgent/1.0"})
data = r.json()

pages = data.get("query", {}).get("pages", {})
page  = next(iter(pages.values()))

texte = page.get("extract", "")
print(f"Titre    : {page.get('title')}")
print(f"Taille   : {len(texte)} chars / {len(texte.split())} mots")
print()
print("--- Aperçu (800 chars) ---")
print(texte[:800])
print()
print("--- Recherche date ---")
for ligne in texte.split("\n"):
    if "29 novembre" in ligne or "2011" in ligne or "chef du gouvernement" in ligne.lower():
        print(ligne[:200])
