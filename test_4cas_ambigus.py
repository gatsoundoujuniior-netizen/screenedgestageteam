"""
test_4cas_ambigus.py — 4 cas ambigus pour valider les garde-codes
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from pep_agent import verifier_pep
from search_tools import get_compteur, reset_compteur_personne

CAS = [
    ("Macky",    "Sall",    "Ex-PEP Sénégal — quitté la présidence avril 2024 (récent)"),
    ("Roch",     "Kabore",  "Ex-PEP Burkina Faso — renversé coup d'état jan 2022"),
    ("Mohamed",  "Bazoum",  "Ex-PEP Niger — renversé et emprisonné juil 2023"),
    ("Mamadi",   "Doumbouya","PEP actif Guinée — président de transition depuis oct 2021"),
]

resultats = []

for i, (prenom, nom, description) in enumerate(CAS, 1):
    print(f"\n{'='*60}")
    print(f"CAS {i}/4 — {description}")
    print(f"{'='*60}")
    reset_compteur_personne()
    try:
        r = verifier_pep(prenom, nom)
        resultats.append({
            "cas": i, "nom": f"{prenom} {nom}", "description": description,
            "est_pep": r.est_pep, "pays": f"{r.pays} ({r.code_iso})",
            "fonction": r.fonction, "raisonnement": r.raisonnement,
        })
    except Exception as e:
        print(f"  ERREUR : {e}")
        resultats.append({"cas": i, "nom": f"{prenom} {nom}", "description": description,
                          "est_pep": "ERREUR", "erreur": str(e)})

print(f"\n\n{'='*60}")
print("SYNTHÈSE — 4 CAS AMBIGUS")
print(f"{'='*60}")
for r in resultats:
    statut = "✅ PEP" if r.get("est_pep") is True else ("❌ Non-PEP" if r.get("est_pep") is False else "⚠️ ERREUR")
    print(f"\nCas {r['cas']} — {r['nom']} ({r['description']})")
    print(f"  Statut    : {statut}")
    print(f"  Pays      : {r.get('pays','')}")
    print(f"  Fonction  : {r.get('fonction','')}")
    print(f"  Raison    : {r.get('raisonnement') or r.get('erreur','')}")

cpt = get_compteur()
print(f"\nTavily total : {cpt['total']} appels pour 4 personnes (moy: {cpt['total']//4})")
