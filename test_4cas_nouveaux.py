"""
test_4cas_nouveaux.py — 4 nouveaux cas variés
  - Ousmane Sonko    (SN) → Premier ministre Sénégal depuis 2024        → PEP actif attendu
  - Assimi Goïta     (ML) → Président de transition Mali (coup 2021)     → PEP actif attendu
  - Ibrahim Traoré   (BF) → Président de transition Burkina (coup 2022)  → PEP actif attendu
  - Abdourahamane Tchiani (NE) → Chef junte Niger (coup 2023)            → PEP actif attendu
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from pep_agent import verifier_pep
from search_tools import get_compteur, reset_compteur_personne

CAS = [
    ("Ousmane",       "Sonko",   "PM actif Sénégal depuis 2024"),
    ("Assimi",        "Goita",   "PEP actif Mali — coup 2021"),
    ("Ibrahim",       "Traore",  "PEP actif Burkina Faso — coup 2022"),
    ("Abdourahamane", "Tchiani", "PEP actif Niger — coup 2023"),
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
print("SYNTHÈSE — 4 CAS NOUVEAUX")
print(f"{'='*60}")
for r in resultats:
    statut = "✅ PEP" if r.get("est_pep") is True else ("❌ Non-PEP" if r.get("est_pep") is False else "⚠️ ERREUR")
    attendu = "✅ PEP"
    ok = "✅ OK" if statut == attendu else "❌ ÉCART"
    print(f"\nCas {r['cas']} — {r['nom']} ({r['description']})")
    print(f"  Statut    : {statut}  [{ok}]")
    print(f"  Pays      : {r.get('pays','')}")
    print(f"  Fonction  : {r.get('fonction','')}")
    print(f"  Raison    : {r.get('raisonnement') or r.get('erreur','')}")

cpt = get_compteur()
print(f"\nTavily total : {cpt['total']} appels pour 4 personnes (moy: {cpt['total']//4})")
