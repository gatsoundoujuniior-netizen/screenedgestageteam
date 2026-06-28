"""
mesure_champs.py — Compte les champs remplis dans la DB pour chaque candidat de référence
"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_utils import query_all

CHAMPS_PEP = [
    "nom_complete", "pays_nom", "code_iso", "nationalite",
    "fonction_actuelle", "statut_mandat", "date_nomination",
    "date_sortie_fonction_public", "date_naissance", "lieu_naissance",
    "statut_matrimonial", "enfants", "formations",
    "fonctions_interieures", "source_url", "annee_verification",
]

rows = query_all("""
    SELECT nom_complete, pays_nom, code_iso, nationalite,
           fonction_actuelle, statut_mandat, date_nomination,
           date_sortie_fonction_public, date_naissance, lieu_naissance,
           statut_matrimonial, enfants, formations,
           fonctions_interieures, source_url, annee_verification,
           date_scraping
    FROM pep
    ORDER BY date_scraping DESC NULLS LAST
""")

print(f"\n{'='*90}")
print(f"{'NOM':35} | {'REMPLI':8} | CHAMPS MANQUANTS")
print(f"{'='*90}")

for r in rows:
    remplis = []
    manquants = []
    for c in CHAMPS_PEP:
        v = r.get(c)
        if v is not None and str(v).strip() not in ("", "non disponible"):
            remplis.append(c)
        else:
            manquants.append(c)
    pct = int(len(remplis) / len(CHAMPS_PEP) * 100)
    nom = (r.get("nom_complete") or "?")[:33]
    manquants_str = ", ".join(manquants) if manquants else "—"
    print(f"{nom:35} | {len(remplis):2}/{len(CHAMPS_PEP)} ({pct:3}%) | {manquants_str}")

print(f"{'='*90}")
print(f"Total en base : {len(rows)} PEP\n")
