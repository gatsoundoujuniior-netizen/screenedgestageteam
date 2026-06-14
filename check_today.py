import sys; sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv(override=True)
from db_utils import query_all

stats = query_all("""
    SELECT
        COUNT(*) AS total_aujourd_hui,
        COUNT(*) FILTER (WHERE statut_mandat = 'actif') AS actifs,
        COUNT(*) FILTER (WHERE statut_mandat = 'ex_pep') AS ex_pep
    FROM pep
    WHERE DATE(date_creation) = CURRENT_DATE
""")
if stats:
    s = stats[0]
    print(f"Total aujourd'hui : {s['total_aujourd_hui']}")
    print(f"  Actifs  : {s['actifs']}")
    print(f"  Ex-PEP  : {s['ex_pep']}")

print()
rows = query_all("""
    SELECT nom_complete, pays_nom, code_iso, fonction_actuelle, statut_mandat, source_url, date_creation
    FROM pep
    WHERE DATE(date_creation) = CURRENT_DATE
    ORDER BY date_creation DESC
""")
print(f"Détail ({len(rows)} PEP) :")
for r in rows:
    src = (r['source_url'] or 'non disponible')[:60]
    print(f"  [{r['code_iso']}] {r['nom_complete']} | {r['statut_mandat']} | {r['fonction_actuelle'] or '—'[:30]} | {src}")
