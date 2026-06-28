"""Corrections directes de champs erronés en DB."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_utils import execute, query_all

# Talon : enfants=4 mais REF=2
execute("UPDATE pep SET enfants=2 WHERE code_iso='BJ' AND nom_complete ILIKE '%talon%talon%'")
print("→ Patrice Talon : enfants = 2")

# Nialé Kaba : statut_mandat=ex_pep mais elle est active depuis Jan 2026
execute("UPDATE pep SET statut_mandat='actif' WHERE code_iso='CI' AND nom_complete ILIKE '%kaba%'")
print("→ Nialé Kaba : statut_mandat = actif")

# Vérif
rows = query_all("""
    SELECT nom_complete, code_iso, statut_mandat, enfants, lieu_naissance
    FROM pep WHERE code_iso IN ('BJ','CI','TG')
    AND nom_complete ILIKE ANY(ARRAY['%talon%','%kaba%','%gnassingbé%','%wadagni%'])
""")
print("\nVérification :")
for r in rows:
    print(f"  {r['nom_complete']} ({r['code_iso']}) — statut={r['statut_mandat']} | enfants={r['enfants']} | lieu={r['lieu_naissance']}")
