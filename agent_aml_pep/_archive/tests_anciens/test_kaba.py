import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pep_agent import verifier_pep

r = verifier_pep("Nialé", "Kaba", stocker=True)
print(f"\nFonction   : {r.fonction}")
print(f"Statut     : {r.statut_mandat}")
print(f"Naissance  : {r.date_naissance} | Lieu : {r.lieu_naissance}")
print(f"Matrimonial: {r.statut_matrimonial}")
