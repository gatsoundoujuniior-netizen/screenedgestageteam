"""Audit qualité des PEP en base — vérifie la cohérence des données."""
import sys; sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv(override=True)
from db_utils import query_all

rows = query_all("""
    SELECT id, nom_complete, code_iso, pays_nom, fonction_actuelle,
           statut_mandat, source_url, date_creation
    FROM pep
    ORDER BY code_iso, nom_complete
""")

# Regrouper par pays
par_pays = {}
for r in rows:
    c = r["code_iso"]
    par_pays.setdefault(c, []).append(r)

PAYS_NOMS = {
    "MA":"Maroc","DZ":"Algérie","TN":"Tunisie","LY":"Libye",
    "SN":"Sénégal","CI":"Côte d'Ivoire","ML":"Mali","BF":"Burkina Faso",
    "NE":"Niger","TG":"Togo","BJ":"Bénin","GW":"Guinée-Bissau","GN":"Guinée",
}

# Mots suspects dans les noms → probablement pas une personne
MOTS_SUSPECTS_NOM = [
    "ministre", "président", "premier", "gouvernement", "assemblée",
    "direction", "bureau", "commission", "conseil", "comité",
    "banque", "fonds", "programme", "agence", "organisation",
]
# Fonctions qui indiquent un étranger (pour vérif croisée pays)
MOTS_PAYS_ETRANGERS = {
    "MA": ["algérie","tunisie","libye","nigeria","sénégal","mali","ghana","côte d'ivoire",
           "kazakhstan","guyana","iran","irak","indonésie","azerbaïdjan","albanie","bahreïn"],
    "TN": ["algérie","libye","maroc","mali","ghana"],
    "DZ": ["tunisie","libye","maroc"],
}

print(f"{'='*65}")
print(f"AUDIT BASE PEP — {len(rows)} entrées")
print(f"{'='*65}\n")

total_suspects = 0

for code, peps in sorted(par_pays.items()):
    pays = PAYS_NOMS.get(code, code)
    suspects = []

    for p in peps:
        nom = (p["nom_complete"] or "").lower()
        fn  = (p["fonction_actuelle"] or "").lower()
        src = (p["source_url"] or "")
        problemes = []

        # Nom contient un mot institutionnel
        for m in MOTS_SUSPECTS_NOM:
            if m in nom:
                problemes.append(f"nom suspect ('{m}')")
                break

        # Fonction mentionne un pays étranger pour ce code_iso
        pays_etrangers = MOTS_PAYS_ETRANGERS.get(code, [])
        for pe in pays_etrangers:
            if pe in fn:
                problemes.append(f"étranger dans fonction ('{pe}')")
                break

        # Nom trop court (< 5 chars) → probablement mal extrait
        if len((p["nom_complete"] or "").strip()) < 5:
            problemes.append("nom trop court")

        # Fonction vide
        if not p["fonction_actuelle"] or p["fonction_actuelle"].strip() in ("—", "-", ""):
            problemes.append("fonction vide")

        if problemes:
            suspects.append((p, problemes))
            total_suspects += 1

    print(f"[{code}] {pays} — {len(peps)} PEP | {len(suspects)} suspects")
    for p in peps:
        fn_court = (p["fonction_actuelle"] or "—")[:50]
        print(f"   {'⚠️ ' if any(p['id'] == s[0]['id'] for s in suspects) else '  ✅'} {p['nom_complete'][:35]:<35} | {fn_court}")

    for p, probs in suspects:
        print(f"      └─ [{p['nom_complete']}] → {', '.join(probs)}")
    print()

print(f"{'='*65}")
print(f"TOTAL : {len(rows)} PEP | {total_suspects} suspects à vérifier")
