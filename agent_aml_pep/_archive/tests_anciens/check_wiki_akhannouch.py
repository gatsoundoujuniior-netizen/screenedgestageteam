import sys, os, requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

name = "Aziz Akhannouch"

# Wikipedia API — recherche fr
url = "https://fr.wikipedia.org/w/api.php"
params = {
    "action": "query", "list": "search",
    "srsearch": name, "srlimit": 3,
    "format": "json"
}
r = requests.get(url, params=params, timeout=10)
results = r.json().get("query", {}).get("search", [])
print(f"=== Résultats recherche Wikipedia '{name}' ===")
for res in results:
    print(f"  - {res['title']} (pageid={res['pageid']})")

# Récupérer le contenu de la page principale
if results:
    pageid = results[0]["pageid"]
    params2 = {
        "action": "query", "pageids": pageid,
        "prop": "extracts", "explaintext": True,
        "exsectionformat": "plain",
        "format": "json"
    }
    r2 = requests.get(url, params=params2, timeout=10)
    pages = r2.json().get("query", {}).get("pages", {})
    for pid, page in pages.items():
        extract = page.get("extract", "")
        print(f"\n=== Contenu Wikipedia — {page['title']} ({len(extract)} chars) ===\n")
        print(extract[:6000])
        print("\n...\n[SUITE]\n")
        # Chercher spécifiquement les sections bio
        for keyword in ["né", "naissance", "épouse", "marié", "mariage", "enfant", "Tafraout", "Agadir", "1961", "Agriculture"]:
            idx = extract.lower().find(keyword.lower())
            if idx != -1:
                print(f"['{keyword}' trouvé à pos {idx}]: ...{extract[max(0,idx-100):idx+200]}...")
