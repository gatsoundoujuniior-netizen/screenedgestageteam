"""Nettoyage ciblé de la base — supprime les faux positifs."""
import sys; sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv(override=True)
from db_utils import query_all, execute

# ── Règles de suppression ────────────────────────────────────────────────────
regles = [
    # 1. Page BKAM (Maroc) → liste des gouverneurs de banques du monde entier
    #    Ces personnes ne sont PAS marocaines, juste des invités à une réunion
    {
        "description": "Étrangers extraits de la page BKAM (gouvernance internationale)",
        "sql": """
            DELETE FROM pep
            WHERE source_url LIKE '%bkam.ma%'
            AND nom_complete NOT IN (
                'Abdelouahed Benchekroun', 'Aziz Akhannouch',
                'Abdelilah Benkirane', 'Mohammed Bennani', 'Mohammed El Othmani'
            )
        """
    },
    # 2. Entrées sans nom réel ("Premier ministre" utilisé comme nom)
    {
        "description": "Entrées sans vrai nom (titre utilisé comme nom)",
        "sql": """
            DELETE FROM pep
            WHERE nom_complete IN (
                'Premier ministre', 'Le Premier Ministre', 'Président de la République',
                'Premier ministre Premier ministre'
            )
        """
    },
    # 3. Entraîneur de handball — pas un PEP
    {
        "description": "Badreddine Haj Sassi — entraîneur handball (pas un PEP)",
        "sql": """
            DELETE FROM pep
            WHERE nom_complete ILIKE '%Haj Sassi%'
            OR fonction_actuelle ILIKE '%handball%'
            OR fonction_actuelle ILIKE '%entraîneur%'
            OR fonction_actuelle ILIKE '%entraineur%'
        """
    },
    # 4. Personnes étrangères mal attribuées à TN (gouverneurs d'autres banques centrales)
    {
        "description": "Gouverneurs étrangers mal tagués TN (BCT page gouvernance)",
        "sql": """
            DELETE FROM pep
            WHERE code_iso = 'TN'
            AND source_url LIKE '%bct.gov.tn%'
            AND (
                fonction_actuelle ILIKE '%Libye%'
                OR fonction_actuelle ILIKE '%Algérie%'
                OR fonction_actuelle ILIKE '%arabe%'
                OR fonction_actuelle ILIKE '%Fonds monétaire%'
            )
        """
    },
    # 5. Personnes d'autres pays mal attribuées à DZ (depuis bank-of-algeria)
    {
        "description": "Doublons/erreurs DZ bank-of-algeria",
        "sql": """
            DELETE FROM pep
            WHERE code_iso = 'DZ'
            AND source_url LIKE '%bank-of-algeria%'
            AND nom_complete ILIKE '%Mouatass%'
            AND id NOT IN (
                SELECT MIN(id) FROM pep
                WHERE code_iso = 'DZ' AND source_url LIKE '%bank-of-algeria%'
                AND nom_complete ILIKE '%Mouatass%'
                GROUP BY nom_complete
            )
        """
    },
    # 6. Doublons exacts (même nom_complete + code_iso — garder le plus récent)
    {
        "description": "Doublons (même nom + pays)",
        "sql": """
            DELETE FROM pep
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM pep
                GROUP BY nom_complete, code_iso
            )
        """
    },
]

total_supprime = 0

for r in regles:
    # Compter avant
    count_sql = r["sql"].replace("DELETE FROM pep", "SELECT COUNT(*) AS n FROM pep", 1)
    avant = query_all(count_sql)
    n = avant[0]["n"] if avant else 0

    if n > 0:
        execute(r["sql"])
        print(f"  ✅ [{n} supprimés] {r['description']}")
        total_supprime += n
    else:
        print(f"  ⏭️  [0] {r['description']}")

print(f"\n{'='*55}")
print(f"Total supprimé : {total_supprime} entrées")

# Vérif finale
reste = query_all("SELECT COUNT(*) AS n FROM pep WHERE DATE(date_creation) = CURRENT_DATE")
print(f"PEP restants aujourd'hui : {reste[0]['n'] if reste else '?'}")
total = query_all("SELECT COUNT(*) AS n FROM pep")
print(f"PEP total en base : {total[0]['n'] if total else '?'}")
