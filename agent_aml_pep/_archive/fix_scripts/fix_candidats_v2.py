import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_utils import execute, query_all

# 1. Ouattara : 2 enfants biologiques (pas 4 — les 2 autres sont les enfants de Dominique)
execute("UPDATE pep SET enfants=2 WHERE code_iso='CI' AND nom_complete ILIKE '%ouattara%'")
print("-> Ouattara : enfants=2")

# 2. Kaba : renommée ministre d'Etat le 23 janvier 2026 (gouvernement Beugre Mambe II)
execute("""
    UPDATE pep
    SET statut_mandat='actif',
        fonction_actuelle='Ministre d''Etat, ministre des Affaires etrangeres et de la Cooperation internationale',
        date_nomination='2026-01-23'
    WHERE code_iso='CI' AND nom_complete ILIKE '%kaba%'
""")
print("-> Kaba : statut_mandat=actif, fonction=Ministre d'Etat")

rows = query_all("""
    SELECT nom_complete, code_iso, fonction_actuelle, statut_mandat, enfants, date_nomination
    FROM pep
    WHERE code_iso='CI' AND nom_complete ILIKE ANY(ARRAY['%ouattara%','%kaba%'])
""")
for r in rows:
    print(f"  {r['nom_complete']} -> fn={r['fonction_actuelle']} | statut={r['statut_mandat']} | enfants={r['enfants']} | nomination={r['date_nomination']}")
