import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_utils import query_all

rows = query_all("""
    SELECT nom_complete, code_iso, fonction_actuelle, statut_mandat,
           date_naissance, lieu_naissance, statut_matrimonial, enfants, fonctions_interieures
    FROM pep
    WHERE nom_complete ILIKE ANY(ARRAY[
        '%faye%','%ouattara%','%gnassingbé%','%talon talon%',
        '%akhannouch%','%sonko%','%kaba%','%wadagni%','%ahmidouch%','%ouédraogo%'
    ])
    ORDER BY code_iso, nom_complete
""")
for r in rows:
    print(f"{r['nom_complete']} ({r['code_iso']})")
    print(f"  fn={r['fonction_actuelle']}")
    print(f"  statut={r['statut_mandat']} | naiss={r['date_naissance']} | lieu={r['lieu_naissance']}")
    print(f"  matrimon={r['statut_matrimonial']} | enfants={r['enfants']} | hist={r['fonctions_interieures']}")
