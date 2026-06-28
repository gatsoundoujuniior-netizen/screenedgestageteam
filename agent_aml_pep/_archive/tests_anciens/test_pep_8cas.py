"""
test_pep_8cas.py — Test du pipeline PEP sur 8 cas représentatifs
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from pep_agent import verifier_pep
from search_tools import get_compteur

CAS_TEST = [
    ("Aziz",             "Akhannouch",        "PEP — PM Maroc (Clean)"),
    ("Aïmene",           "Benabderrahmane",   "PEP — PM Algérie (liste grise)"),
    ("Alassane",         "Ouattara",          "PEP — Président CI (liste grise)"),
    ("Bassirou Diomaye", "Faye",              "PEP — Président Sénégal"),
    ("Patrice",          "Talon",             "PEP — Président Bénin"),
    ("Faure",            "Gnassingbé",        "PEP — Président Togo"),
    ("Alpha",            "Condé",             "Ex-PEP — ancien président Guinée"),
    ("Stevy",            "Gatsoundou",        "Non-PEP — test faux positif"),
]

resultats = []

for i, (prenom, nom, description) in enumerate(CAS_TEST, 1):
    print(f"\n{'='*60}")
    print(f"CAS {i}/8 — {description}")
    print(f"{'='*60}")
    try:
        rapport = verifier_pep(prenom, nom)
        resultats.append({
            "cas": i,
            "nom": f"{prenom} {nom}",
            "description": description,
            "est_pep": rapport.est_pep,
            "pays": f"{rapport.pays} ({rapport.code_iso})",
            "fonction": rapport.fonction,
            "source_type": rapport.source_type,
            "raisonnement": rapport.raisonnement,
        })
    except Exception as e:
        print(f"  ERREUR : {e}")
        resultats.append({
            "cas": i,
            "nom": f"{prenom} {nom}",
            "description": description,
            "est_pep": "ERREUR",
            "erreur": str(e),
        })

print(f"\n\n{'='*60}")
print("SYNTHÈSE DES 8 CAS")
print(f"{'='*60}")
for r in resultats:
    statut = "✅ PEP" if r.get("est_pep") is True else ("❌ Non-PEP" if r.get("est_pep") is False else "⚠️ ERREUR")
    print(f"\nCas {r['cas']} — {r['nom']}")
    print(f"  Statut    : {statut}")
    if r.get("est_pep") is True:
        print(f"  Pays      : {r.get('pays')}")
        print(f"  Fonction  : {r.get('fonction')}")
        print(f"  Source    : {r.get('source_type')}")
    print(f"  Raison    : {r.get('raisonnement') or r.get('erreur', '')}")

cpt = get_compteur()
print(f"\n{'='*60}")
print(f"CONSOMMATION TAVILY — 8 cas")
print(f"{'='*60}")
print(f"Total appels Tavily : {cpt['total']}")
print(f"Moyenne par personne : {cpt['total'] // 8} appels")
print(f"Estimation mensuelle (100 vérifications) : ~{(cpt['total'] // 8) * 100} appels")
