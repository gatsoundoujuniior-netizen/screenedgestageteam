import sys
sys.path.insert(0, ".")

from search_tools import scraper_json_officiel

nom = "Abdelilah Benkirane"
wiki_url = "https://fr.wikipedia.org/wiki/Abdelilah_Benkirane"

print(f"Test scraping direct Wikipedia : {wiki_url}")
print()

result = scraper_json_officiel(nom, [wiki_url])

print()
print("=== RÉSULTAT ===")
if result.get("texte_brut"):
    print(f"texte_brut : {len(result['texte_brut'])} chars")
    print(result["texte_brut"][:1000])
elif result.get("nominations"):
    print(f"nominations : {len(result['nominations'])} entrées")
    print(result["nominations"][:3])
else:
    print("VIDE — Scrapling n'a rien extrait")
    print(f"result brut : {result}")
