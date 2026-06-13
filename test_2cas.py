import sys
sys.stdout.reconfigure(encoding="utf-8")

from pep_agent import verifier_pep
from search_tools import get_compteur

print("="*60)
print("CAS 1 — Stevy Gatsoundou (attendu : Non-PEP, hors perimetre)")
print("="*60)
r1 = verifier_pep("Stevy", "Gatsoundou")
print(f"est_pep      : {r1.est_pep}")
print(f"pays         : {r1.pays} ({r1.code_iso})")
print(f"raisonnement : {r1.raisonnement}")

print()
print("="*60)
print("CAS 2 — Alpha Conde (attendu : ex-PEP Guinee)")
print("="*60)
r2 = verifier_pep("Alpha", "Conde")
print(f"est_pep      : {r2.est_pep}")
print(f"pays         : {r2.pays} ({r2.code_iso})")
print(f"fonction     : {r2.fonction}")
print(f"raisonnement : {r2.raisonnement}")

cpt = get_compteur()
print()
print(f"Tavily total : {cpt['total']} appels pour 2 personnes")
