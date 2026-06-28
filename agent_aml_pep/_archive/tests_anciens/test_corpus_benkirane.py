import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
from search_tools import rechercher_pep

print("=== TEST CORPUS : Abdelilah Benkirane ===")
corpus = rechercher_pep("Abdelilah Benkirane", "Maroc", "MA", "permanente")

print()
print(f"Taille totale : {len(corpus)} chars / {len(corpus.split())} mots")

print()
print("--- SECTIONS ---")
sections = ["TIER 1 — SCRAPLING", "TIER 2 — WIKIPEDIA", "TIER 2 — TAVILY", "TIER 2b — GOOGLE", "TIER 3 — OPENSANCTIONS"]
for s in sections:
    ok = "OK" if s in corpus else "ABSENT"
    print(f"  {ok} | {s}")

print()
print("--- APERCU WIKIPEDIA ---")
idx = corpus.find("WIKIPEDIA")
if idx >= 0:
    print(corpus[idx:idx+800])
else:
    print("Wikipedia absent du corpus")

print()
print("--- APERCU OPENSANCTIONS ---")
idx2 = corpus.find("OPENSANCTIONS")
if idx2 >= 0:
    print(corpus[idx2:idx2+600])
else:
    print("OpenSanctions absent")

print()
print("--- MOTS-CLES CRITIQUES ---")
mots = ["Premier ministre", "chef du gouvernement", "2011", "2017", "Benkirane", "Rabat"]
for m in mots:
    n = corpus.count(m)
    print(f"  '{m}' : {n} occurrence(s)")
