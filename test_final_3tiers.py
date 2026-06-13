"""
test_final_3tiers.py — Validation architecture 3 tiers (Scrapling + Tavily + OpenSanctions)

Série 1 — 2 cas ambigus (ex-PEP difficiles)
  - Macky Sall    (SN) → quitté avril 2024 → ex-PEP attendu
  - Roch Kaboré   (BF) → renversé jan 2022 → ex-PEP attendu

Série 2 — 2 cas normaux (présidents actifs)
  - Alassane Ouattara  (CI) → en poste depuis 2011 → PEP actif attendu
  - Faure Gnassingbé   (TG) → en poste depuis 2005 → PEP actif attendu
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from pep_agent import verifier_pep
from search_tools import get_compteur, reset_compteur_personne

SERIES = [
    {
        "label": "SÉRIE 1 — CAS AMBIGUS (ex-PEP difficiles)",
        "cas": [
            ("Macky",  "Sall",   "SN", "ex-PEP — quitté avril 2024",        True),
            ("Roch",   "Kabore", "BF", "ex-PEP — renversé coup jan 2022",   True),
        ]
    },
    {
        "label": "SÉRIE 2 — CAS NORMAUX (présidents actifs)",
        "cas": [
            ("Alassane", "Ouattara",  "CI", "PEP actif — Président depuis 2011", True),
            ("Faure",    "Gnassingbe","TG", "PEP actif — Président depuis 2005", True),
        ]
    },
]

tous_resultats = []

for serie in SERIES:
    print(f"\n\n{'#'*65}")
    print(f"  {serie['label']}")
    print(f"{'#'*65}")

    for prenom, nom, iso, description, attendu_pep in serie["cas"]:
        print(f"\n{'='*65}")
        print(f"  {prenom} {nom} ({iso}) — {description}")
        print(f"{'='*65}")
        reset_compteur_personne()
        try:
            r = verifier_pep(prenom, nom)
            tous_resultats.append({
                "prenom": prenom, "nom": nom, "iso": iso,
                "description": description, "attendu_pep": attendu_pep,
                "rapport": r, "erreur": None
            })
        except Exception as e:
            print(f"  ERREUR : {e}")
            tous_resultats.append({
                "prenom": prenom, "nom": nom, "iso": iso,
                "description": description, "attendu_pep": attendu_pep,
                "rapport": None, "erreur": str(e)
            })

# ── SYNTHÈSE COMPLÈTE ────────────────────────────────────────────────────────────
print(f"\n\n{'#'*65}")
print(f"  SYNTHÈSE FINALE — RAPPORT COMPLET")
print(f"{'#'*65}")

ok_count = 0
for res in tous_resultats:
    r = res["rapport"]
    if res["erreur"]:
        print(f"\n❌ {res['prenom']} {res['nom']} — ERREUR : {res['erreur']}")
        continue

    est_ok = r.est_pep == res["attendu_pep"]
    ok_count += est_ok
    statut_str = "✅ PEP" if r.est_pep else "❌ Non-PEP"
    ok_str     = "✅ OK" if est_ok else "❌ ÉCART"

    print(f"\n{'─'*65}")
    print(f"  {res['prenom']} {res['nom']} ({res['iso']}) — {res['description']}")
    print(f"{'─'*65}")
    print(f"  Statut PEP     : {statut_str}  [{ok_str}]")
    print(f"  Statut mandat  : {r.statut_mandat}")
    print(f"  Pays           : {r.pays} ({r.code_iso})")
    print(f"  Fonction       : {r.fonction or '—'}")
    print(f"  Date nomination: {r.date_nomination or '—'}")
    print(f"  Source URL     : {r.source_url or '—'}")
    print(f"  Source type    : {r.source_type or '—'}")
    print(f"  Raisonnement   : {r.raisonnement}")
    print(f"  Date vérif     : {r.date_verification}")

cpt = get_compteur()
print(f"\n{'#'*65}")
print(f"  SCORE : {ok_count}/{len(tous_resultats)}")
print(f"  Tavily total : {cpt['total']} appels")
print(f"{'#'*65}\n")
