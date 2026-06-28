import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

from pep_agent import verifier_pep

print("=== VERIFICATION PEP : Bassirou Diomaye Faye ===")
print("Attendu : Président du Sénégal (actif), Sénégal (SN)")
print()

rapport = verifier_pep("Bassirou Diomaye", "Faye")

print()
print("=== RAPPORT FINAL ===")
print(f"Nom complet    : {rapport.prenom} {rapport.nom}")
print(f"Est PEP        : {rapport.est_pep}")
print(f"Statut mandat  : {rapport.statut_mandat}")
print(f"Pays           : {rapport.pays} ({rapport.code_iso})")
print(f"Fonction       : {rapport.fonction}")
if rapport.fonctions_historiques:
    print(f"Fonctions hist : {rapport.fonctions_historiques}")
print(f"Date nomination: {rapport.date_nomination}")
print(f"Source         : {rapport.source_url}")
print()
print(f"Raisonnement   : {rapport.raisonnement[:500] if rapport.raisonnement else 'N/A'}")
