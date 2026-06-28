import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_utils import execute, query_all

# Supprimer Macky Sall stocké par erreur (normalisé depuis Ousmane Sonko)
rows = query_all("SELECT id, nom_complete, code_iso, fonction_actuelle, date_naissance FROM pep WHERE code_iso='SN' ORDER BY date_scraping DESC")
for r in rows:
    print(r['id'], '|', r['nom_complete'], '|', r['fonction_actuelle'], '|', r['date_naissance'])

# Supprimer l'entrée Macky Sall (né 11/12/1950)
execute("DELETE FROM pep WHERE code_iso='SN' AND nom_complete ILIKE '%macky%'")
print("\n→ Entrée Macky Sall supprimée")

# Vérif finale
rows2 = query_all("SELECT nom_complete, fonction_actuelle FROM pep WHERE code_iso='SN'")
print("Restant SN:", [(r['nom_complete'], r['fonction_actuelle']) for r in rows2])
