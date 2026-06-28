"""Corrections manuelles des lieux de naissance trop vagues en DB."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_utils import execute, query_all

CORRECTIONS = [
    # (nom_complete, code_iso, lieu_naissance_correct)
    ("Patrice Talon",            "BJ", "Ouidah"),
    ("Romuald Wadagni",          "BJ", "Lokossa"),
    ("Faure Essozimina Gnassingbé", "TG", "Afagnan"),
    ("Faure Gnassingbé",         "TG", "Afagnan"),
]

rows_before = query_all("SELECT nom_complete, code_iso, lieu_naissance FROM pep WHERE code_iso IN ('BJ','TG')")
print("Avant corrections :")
for r in rows_before:
    print(f"  {r['nom_complete']} ({r['code_iso']}) — {r['lieu_naissance']}")

for nom, iso, lieu in CORRECTIONS:
    execute(
        "UPDATE pep SET lieu_naissance=%s WHERE code_iso=%s AND nom_complete ILIKE %s",
        (lieu, iso, f"%{nom.split()[0]}%{nom.split()[-1]}%")
    )
    print(f"\n→ {nom} ({iso}) lieu_naissance = '{lieu}'")

rows_after = query_all("SELECT nom_complete, code_iso, lieu_naissance FROM pep WHERE code_iso IN ('BJ','TG')")
print("\nAprès corrections :")
for r in rows_after:
    print(f"  {r['nom_complete']} ({r['code_iso']}) — {r['lieu_naissance']}")
