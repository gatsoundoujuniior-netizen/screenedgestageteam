"""Restaure les fonctions écrasées par régression en passe 3."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_utils import execute, query_all

# Ahmidouch : pipeline a retourné son ancien poste CNSS comme fonction courante
execute("""
    UPDATE pep SET
        fonction_actuelle = 'Wali de la région de Casablanca-Settat',
        statut_mandat     = 'actif'
    WHERE code_iso='MA' AND nom_complete ILIKE '%ahmidouch%'
""")
print("→ Ahmidouch : fonction restaurée → Wali de la région de Casablanca-Settat")

# Sonko : pipeline garde "Premier ministre" au lieu de "Président de l'Assemblée nationale"
execute("""
    UPDATE pep SET
        fonction_actuelle = 'Président de l''Assemblée nationale',
        date_nomination   = '2026-05-26',
        statut_mandat     = 'actif'
    WHERE code_iso='SN' AND nom_complete ILIKE '%sonko%'
""")
print("→ Sonko : fonction restaurée → Président de l'Assemblée nationale")

# Vérif
rows = query_all("""
    SELECT nom_complete, code_iso, fonction_actuelle, statut_mandat, lieu_naissance, date_naissance
    FROM pep
    WHERE code_iso IN ('MA','SN')
    AND nom_complete ILIKE ANY(ARRAY['%ahmidouch%','%sonko%'])
""")
print("\nVérification :")
for r in rows:
    print(f"  {r['nom_complete']} ({r['code_iso']}) — {r['fonction_actuelle']} | {r['statut_mandat']}")
    print(f"    naissance={r['date_naissance']} | lieu={r['lieu_naissance']}")
