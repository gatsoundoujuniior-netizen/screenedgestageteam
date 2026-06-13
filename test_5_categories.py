"""
test_5_categories.py — Validation sur les 5 types de profils problématiques

Catégorie 1 — Ex-PEP récents (départ < 2 ans, sources outdatées)
  - Macky Sall (SN) → ex_pep depuis mars 2024

Catégorie 2 — Ex-PEP par coup d'état (sites officiels tombés)
  - Roch Kabore (BF) → renversé jan 2022
  - Mohamed Bazoum (NE) → renversé juil 2023

Catégorie 3 — PEP non-présidents (ministres, assemblée, banque centrale)
  - Robert Dussey (TG) → Ministre AE depuis 2013
  - Adama Bictogo (CI) → Président Assemblée Nationale depuis 2022

Catégorie 4 — Noms avec accents / graphies manquantes
  - Blaise Compaore (BF) → Compaoré sans accent (ex-PEP 1987–2014)

Catégorie 5 — Homonymes / noms très communs
  - Abdoulaye Wade (SN) → ex-Président (2000–2012), "Abdoulaye" très courant
  - Ibrahim Traore (BF) → Président junta (oct 2022), "Traoré" ultra-courant
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

# Usage : python test_5_categories.py [lot]
# lot=1 → profils 1-4  |  lot=2 → profils 5-8  |  (vide) → tous
LOT = int(sys.argv[1]) if len(sys.argv) > 1 else 0

from pep_agent import verifier_pep
from search_tools import get_compteur, reset_compteur_personne

SERIES = [
    {
        "label": "CAT 1 — EX-PEP RÉCENTS (sources web outdatées)",
        "cas": [
            ("Macky",     "Sall",    "SN", "Ex-Président Sénégal, quitté mars 2024",  True),
        ]
    },
    {
        "label": "CAT 2 — EX-PEP PAR COUP D'ÉTAT (sites officiels tombés)",
        "cas": [
            ("Roch",      "Kabore",  "BF", "Ex-Président BF, renversé jan 2022",       True),
            ("Mohamed",   "Bazoum",  "NE", "Ex-Président Niger, renversé juil 2023",   True),
        ]
    },
    {
        "label": "CAT 3 — PEP NON-PRÉSIDENTS (ministres / assemblée)",
        "cas": [
            ("Robert",    "Dussey",  "TG", "Ministre Affaires Étrangères Togo depuis 2013", True),
            ("Adama",     "Bictogo", "CI", "Président Assemblée Nationale CI depuis 2022",  True),
        ]
    },
    {
        "label": "CAT 4 — NOMS AVEC ACCENTS MANQUANTS",
        "cas": [
            ("Blaise",    "Compaore","BF", "Ex-Président BF (1987–2014), accent manquant",  True),
        ]
    },
    {
        "label": "CAT 5 — HOMONYMES / NOMS TRÈS COMMUNS",
        "cas": [
            ("Abdoulaye", "Wade",    "SN", "Ex-Président Sénégal (2000–2012)",              True),
            ("Ibrahim",   "Traore",  "BF", "Président junta BF depuis oct 2022",            True),
        ]
    },
]

# Aplatir tous les cas avec leur catégorie
tous_cas = []
for serie in SERIES:
    for cas in serie["cas"]:
        tous_cas.append((serie["label"], cas))

# Sélection du lot
if LOT == 1:
    tous_cas = tous_cas[:4]
    print(f"  >>> LOT 1 — profils 1 à 4")
elif LOT == 2:
    tous_cas = tous_cas[4:]
    print(f"  >>> LOT 2 — profils 5 à 8")

tous_resultats = []
cat_courante = ""
for label_cat, (prenom, nom, iso, description, attendu_pep) in tous_cas:
    if label_cat != cat_courante:
        cat_courante = label_cat
        print(f"\n\n{'#'*65}")
        print(f"  {label_cat}")
        print(f"{'#'*65}")

    print(f"\n{'='*65}")
    print(f"  {prenom} {nom} ({iso}) — {description}")
    print(f"{'='*65}")
    reset_compteur_personne()
    try:
        r = verifier_pep(prenom, nom)
        tous_resultats.append({
            "prenom": prenom, "nom": nom, "iso": iso,
            "description": description, "attendu_pep": attendu_pep,
            "rapport": r, "erreur": None, "categorie": label_cat
        })
    except Exception as e:
        print(f"  ERREUR : {e}")
        tous_resultats.append({
            "prenom": prenom, "nom": nom, "iso": iso,
            "description": description, "attendu_pep": attendu_pep,
            "rapport": None, "erreur": str(e), "categorie": label_cat
        })

# ── SYNTHÈSE ─────────────────────────────────────────────────────────────────────
print(f"\n\n{'#'*65}")
print(f"  SYNTHÈSE FINALE — 5 CATÉGORIES")
print(f"{'#'*65}")

ok_count = 0
cat_actuelle = ""
for res in tous_resultats:
    if res["categorie"] != cat_actuelle:
        cat_actuelle = res["categorie"]
        print(f"\n  ── {cat_actuelle} ──")

    r = res["rapport"]
    if res["erreur"]:
        print(f"  ❌ {res['prenom']} {res['nom']} — ERREUR : {res['erreur']}")
        continue

    est_ok = r.est_pep == res["attendu_pep"]
    ok_count += est_ok
    statut_str = "✅ PEP" if r.est_pep else "❌ Non-PEP"
    ok_str     = "✅ OK" if est_ok else "❌ ÉCART"

    print(f"\n  {'─'*61}")
    print(f"  {res['prenom']} {res['nom']} ({res['iso']}) — {res['description']}")
    print(f"  {'─'*61}")
    print(f"  Statut PEP     : {statut_str}  [{ok_str}]")
    print(f"  Statut mandat  : {r.statut_mandat}")
    print(f"  Pays           : {r.pays} ({r.code_iso})")
    print(f"  Fonction       : {r.fonction or '—'}")
    print(f"  Date nomination: {r.date_nomination or '—'}")
    print(f"  Source URL     : {r.source_url or '—'}")
    print(f"  Raisonnement   : {r.raisonnement}")

cpt = get_compteur()
print(f"\n{'#'*65}")
print(f"  SCORE GLOBAL : {ok_count}/{len(tous_resultats)}")
print(f"  Tavily total : {cpt['total']} appels")
print(f"{'#'*65}\n")
