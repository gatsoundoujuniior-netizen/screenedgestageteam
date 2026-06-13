"""
test_round1.py — 2 ex-PEP difficiles
  - Blaise Compaoré (BF) → renversé insurrection 2014, exil CI → ex-PEP attendu
  - Laurent Gbagbo  (CI) → arrêté 2011, acquitté 2019, retourné CI 2021 → ex-PEP attendu
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from pep_agent import verifier_pep
from search_tools import get_compteur, reset_compteur_personne

CAS = [
    ("Blaise",  "Compaore", "ex-PEP BF — renversé insurrection oct 2014, exil CI"),
    ("Laurent", "Gbagbo",   "ex-PEP CI — arrêté 2011, acquitté CPI 2019, retourné CI 2021"),
]

resultats = []
for i, (prenom, nom, description) in enumerate(CAS, 1):
    print(f"\n{'='*60}")
    print(f"CAS {i}/2 — {description}")
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
print("SYNTHÈSE — ROUND 1")
print(f"{'='*60}")
for r in resultats:
    statut  = "✅ PEP" if r.get("est_pep") is True else ("❌ Non-PEP" if r.get("est_pep") is False else "⚠️ ERREUR")
    attendu = "✅ PEP"
    ok      = "✅ OK" if statut == attendu else "❌ ÉCART"
    print(f"\nCas {r['cas']} — {r['nom']}")
    print(f"  Statut   : {statut}  [{ok}]")
    print(f"  Pays     : {r.get('pays','')}")
    print(f"  Fonction : {r.get('fonction','')}")
    print(f"  Raison   : {r.get('raisonnement') or r.get('erreur','')}")

cpt = get_compteur()
print(f"\nTavily total : {cpt['total']} appels (moy: {cpt['total']//2})")
