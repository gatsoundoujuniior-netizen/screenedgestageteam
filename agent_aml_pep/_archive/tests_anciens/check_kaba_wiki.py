import sys, requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Recherche Wikipedia Kaba
for query in ["Nialé Kaba", "Niale Kaba politique ivoirienne"]:
    r = requests.get("https://fr.wikipedia.org/w/api.php", params={
        "action":"query","list":"search","srsearch":query,
        "srlimit":5,"format":"json"
    }, timeout=10, headers={"User-Agent":"PEPAgent/1.0"})
    hits = r.json().get("query",{}).get("search",[])
    print(f"=== Recherche: {query} ===")
    for h in hits:
        print(f"  - {h['title']} (pageid={h['pageid']})")

# Slug avec accent (encodé)
for slug in ["Nial%C3%A9_Kaba", "Nialé_Kaba"]:
    r = requests.get("https://fr.wikipedia.org/w/api.php", params={
        "action":"query","titles":slug,"prop":"extracts",
        "explaintext":True,"exsectionformat":"plain","format":"json","redirects":1
    }, timeout=10, headers={"User-Agent":"PEPAgent/1.0"})
    pages = r.json().get("query",{}).get("pages",{})
    page = next(iter(pages.values()))
    if page.get("missing") is not None:
        print(f"\n[{slug}] -> PAGE ABSENTE")
    else:
        texte = page.get("extract","")
        print(f"\n[{slug}] -> {len(texte)} chars / {len(texte.split())} mots")
        # Chercher 2026
        idx = texte.lower().find("2026")
        if idx != -1:
            print(f"  '2026' trouve pos {idx}:")
            print(f"  ...{texte[max(0,idx-200):idx+300]}...")
        else:
            print("  '2026' ABSENT du texte Wikipedia")
        print("\n--- TEXTE COMPLET ---")
        print(texte)
