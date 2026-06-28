"""Corrections depuis le fichier candidats (source de vérité)."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_utils import execute, query_all

corrections = [
    # Akhannouch — toutes les données bio du fichier candidats
    dict(
        nom="akhannouch", iso="MA",
        date_naissance="1961-08-16",
        lieu_naissance="Tafraout",
        statut_matrimonial="marié",
        enfants=3,
        fonctions_interieures="Ministre de l'Agriculture et de la Pêche (2007-2021)",
        fonction_actuelle="Chef du gouvernement",
    ),
    # Faye — polygame (ligne 3 du fichier)
    dict(nom="faye", iso="SN", statut_matrimonial="polygame"),
    # Sonko — polygame (ligne 350 du fichier)
    dict(nom="sonko", iso="SN", statut_matrimonial="polygame"),
]

for c in corrections:
    sets, vals = [], []
    for col in ["date_naissance","lieu_naissance","statut_matrimonial","enfants",
                "fonctions_interieures","fonction_actuelle"]:
        if col in c:
            sets.append(f"{col}=%s")
            vals.append(c[col])
    vals += [c["iso"], f"%{c['nom']}%"]
    sql = f"UPDATE pep SET {', '.join(sets)} WHERE code_iso=%s AND nom_complete ILIKE %s"
    execute(sql, vals)
    print(f"→ {c['nom'].capitalize()} ({c['iso']}) mis à jour")

# Vérification finale
rows = query_all("""
    SELECT nom_complete, code_iso, fonction_actuelle, date_naissance, lieu_naissance,
           statut_matrimonial, enfants, fonctions_interieures
    FROM pep
    WHERE nom_complete ILIKE ANY(ARRAY['%akhannouch%','%faye%','%sonko%'])
    ORDER BY code_iso, nom_complete
""")
print("\n── Vérification ──")
for r in rows:
    print(f"\n{r['nom_complete']} ({r['code_iso']})")
    print(f"  fn      = {r['fonction_actuelle']}")
    print(f"  naiss   = {r['date_naissance']} | lieu = {r['lieu_naissance']}")
    print(f"  matrimon= {r['statut_matrimonial']} | enfants = {r['enfants']}")
    print(f"  hist    = {r['fonctions_interieures']}")
