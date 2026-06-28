import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_utils import execute, query_all

# Supprimer les doublons SN : faye bassirou, Faye Diomaye (entrées erronées)
rows = query_all("SELECT id, nom_complete, fonction_actuelle FROM pep WHERE code_iso='SN' ORDER BY id")
for r in rows:
    print(r['id'], '|', r['nom_complete'], '|', r['fonction_actuelle'])

execute("""
    DELETE FROM pep WHERE code_iso='SN'
    AND nom_complete IN ('faye bassirou','Faye Diomaye','Macky Sall')
""")
print("\n→ Doublons SN supprimés")

rows2 = query_all("SELECT id, nom_complete, fonction_actuelle FROM pep WHERE code_iso='SN'")
print("Restant SN:")
for r in rows2:
    print(" ", r['id'], '|', r['nom_complete'], '|', r['fonction_actuelle'])
