import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

from pep_agent import verifier_pep

print("=== VERIFICATION PEP : Alassane Ouattara ===")
print("Attendu : Président Côte d'Ivoire (actif), CI")
print()

r = verifier_pep("Alassane", "Ouattara")

print()
print("=== RAPPORT FINAL ===")
print(f"Est PEP        : {r.est_pep}")
print(f"Statut mandat  : {r.statut_mandat}")
print(f"Pays           : {r.pays} ({r.code_iso})")
print(f"Fonction       : {r.fonction}")
if r.fonctions_historiques:
    print(f"Fonctions hist : {r.fonctions_historiques}")
print(f"Date nomination: {r.date_nomination}")
print(f"Source         : {r.source_url}")
print(f"Raisonnement   : {(r.raisonnement or '')[:400]}")
