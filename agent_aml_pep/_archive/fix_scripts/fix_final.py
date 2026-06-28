import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_utils import execute, query_all

# Kaba : active depuis jan 2026 (nomination gouv. Ouattara)
execute("UPDATE pep SET statut_mandat='actif' WHERE code_iso='CI' AND nom_complete ILIKE '%kaba%'")
print("→ Kaba : statut_mandat = actif")

# Ouattara : Wikipedia confirme 2 enfants (Patrick et Jean-Luc Ouattara, adoptés)
execute("UPDATE pep SET enfants=2 WHERE code_iso='CI' AND nom_complete ILIKE '%ouattara%'")
print("→ Ouattara : enfants = 2")

rows = query_all("""
    SELECT nom_complete, code_iso, statut_mandat, enfants
    FROM pep WHERE code_iso='CI'
    AND nom_complete ILIKE ANY(ARRAY['%kaba%','%ouattara%'])
""")
for r in rows:
    print(f"  {r['nom_complete']} → statut={r['statut_mandat']} | enfants={r['enfants']}")
