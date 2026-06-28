import sys, os
sys.path.insert(0, ".")

from search_tools import rechercher_pep

print("=== TEST EXTRACTION DONNEES ===")
print("Personne : Abdelilah Benkirane (MA)")
print()

corpus = rechercher_pep("Abdelilah Benkirane", "Maroc", "MA", "permanente")

print()
print("=== CORPUS FINAL ===")
print(f"Taille totale : {len(corpus)} chars / {len(corpus.split())} mots")
print()
print("--- SECTIONS PRESENTES ---")
for section in ["TIER 1 — SCRAPLING", "TIER 2 — TAVILY", "TIER 2 — WIKIPEDIA", "TIER 2b — GOOGLE", "TIER 3 — OPENSANCTIONS"]:
    present = section in corpus
    taille  = len([l for l in corpus.split("\n") if section in l])
    print(f"  {'OK' if present else 'ABSENT'} | {section}")

print()
print("--- APERCU WIKIPEDIA ---")
idx = corpus.find("WIKIPEDIA")
if idx >= 0:
    print(corpus[idx:idx+800])
else:
    print("Wikipedia absent du corpus")

print()
print("--- APERCU SCRAPLING ---")
idx2 = corpus.find("SCRAPLING")
if idx2 >= 0:
    print(corpus[idx2:idx2+600])
else:
    print("Scrapling absent du corpus")
