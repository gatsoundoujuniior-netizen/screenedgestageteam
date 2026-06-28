"""
batch_loop.py — Batch + comparaison automatique jusqu'à convergence
Lance verifier_pep() pour les 10 candidats, compare avec référence candidats,
relance les candidats insuffisants, boucle jusqu'à score OK ou max 3 passes.
"""
import sys, os, time, re
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pep_agent import verifier_pep
from db_utils import query_all

# ─── 10 candidats à vérifier ──────────────────────────────────────────────────
CANDIDATS = [
    ("Bassirou Diomaye", "Faye",        "SN"),
    ("Alassane",         "Ouattara",    "CI"),
    ("Faure",            "Gnassingbé",  "TG"),
    ("Patrice",          "Talon",       "BJ"),
    ("Aziz",             "Akhannouch",  "MA"),
    ("Ousmane",          "Sonko",       "SN"),
    ("Nialé",            "Kaba",        "CI"),
    ("Romuald",          "Wadagni",     "BJ"),
    ("Saïd",             "Ahmidouch",   "MA"),
    ("Kadré Désiré",     "Ouédraogo",   "BF"),
]

# ─── Vérité terrain ───────────────────────────────────────────────────────────
REFERENCE = [
    {
        "prenom": "Bassirou Diomaye", "nom": "Faye", "code_iso": "SN",
        "nom_complet": "Bassirou Diomaye Faye",
        "date_naissance": "1980-03-25", "lieu_naissance": "Ndiaganiao",
        "statut_matrimonial": "polygame", "nb_enfants": None,
        "fonction": "Président de la République du Sénégal",
        "date_nomination": "2024-04-02", "statut_mandat": "actif",
        "fonctions_hist": None,
    },
    {
        "prenom": "Alassane", "nom": "Ouattara", "code_iso": "CI",
        "nom_complet": "Alassane Ouattara",
        "date_naissance": "1942-01-01", "lieu_naissance": "Dimbokro",
        "statut_matrimonial": "marié", "nb_enfants": 2,
        "fonction": "Président de la République de Côte d'Ivoire",
        "date_nomination": "2011-05-06", "statut_mandat": "actif",
        "fonctions_hist": "Premier ministre",
    },
    {
        "prenom": "Faure", "nom": "Gnassingbé", "code_iso": "TG",
        "nom_complet": "Faure Gnassingbé",
        "date_naissance": "1966-06-06", "lieu_naissance": "Afagnan",
        "statut_matrimonial": None, "nb_enfants": None,
        "fonction": "Président du Conseil des ministres",
        "date_nomination": "2025-05-03", "statut_mandat": "actif",
        "fonctions_hist": "Président de la République du Togo",
    },
    {
        "prenom": "Patrice", "nom": "Talon", "code_iso": "BJ",
        "nom_complet": "Patrice Talon",
        "date_naissance": "1958-05-01", "lieu_naissance": "Ouidah",
        "statut_matrimonial": "marié", "nb_enfants": 2,
        "fonction": "Président de la République du Bénin",
        "date_nomination": "2016-04-06", "statut_mandat": "ex_pep",
        "fonctions_hist": None,
    },
    {
        "prenom": "Aziz", "nom": "Akhannouch", "code_iso": "MA",
        "nom_complet": "Aziz Akhannouch",
        "date_naissance": "1961-08-16", "lieu_naissance": "Tafraout",
        "statut_matrimonial": "marié", "nb_enfants": 3,
        "fonction": "Chef du gouvernement",
        "date_nomination": "2021-10-07", "statut_mandat": "actif",
        "fonctions_hist": "Ministre de l'Agriculture",
    },
    {
        "prenom": "Ousmane", "nom": "Sonko", "code_iso": "SN",
        "nom_complet": "Ousmane Sonko",
        "date_naissance": "1974-07-15", "lieu_naissance": "Thiès",
        "statut_matrimonial": "polygame", "nb_enfants": None,
        "fonction": "Président de l'Assemblée nationale",
        "date_nomination": "2026-05-26", "statut_mandat": "actif",
        "fonctions_hist": "Premier ministre",
    },
    {
        "prenom": "Nialé", "nom": "Kaba", "code_iso": "CI",
        "nom_complet": "Nialé Kaba",
        "date_naissance": "1962", "lieu_naissance": "Bouko",
        "statut_matrimonial": None, "nb_enfants": None,
        "fonction": "Ministre d'Etat",
        "date_nomination": "2026-01-23", "statut_mandat": "actif",
        "fonctions_hist": "Ministre du Plan",
    },
    {
        "prenom": "Romuald", "nom": "Wadagni", "code_iso": "BJ",
        "nom_complet": "Romuald Wadagni",
        "date_naissance": "1976-06-20", "lieu_naissance": "Lokossa",
        "statut_matrimonial": None, "nb_enfants": None,
        "fonction": "Président de la République du Bénin",
        "date_nomination": "2026-05-24", "statut_mandat": "actif",
        "fonctions_hist": "Ministre de l'Économie",
    },
    {
        "prenom": "Saïd", "nom": "Ahmidouch", "code_iso": "MA",
        "nom_complet": "Saïd Ahmidouch",
        "date_naissance": "1959", "lieu_naissance": None,
        "statut_matrimonial": None, "nb_enfants": None,
        "fonction": "Wali",
        "date_nomination": "2019-02-18", "statut_mandat": "actif",
        "fonctions_hist": "Directeur général de la CNSS",
    },
    {
        "prenom": "Kadré Désiré", "nom": "Ouédraogo", "code_iso": "BF",
        "nom_complet": "Kadré Désiré Ouédraogo",
        "date_naissance": "1953-12-31", "lieu_naissance": "Boussouma",
        "statut_matrimonial": None, "nb_enfants": None,
        "fonction": "Premier ministre",
        "date_nomination": "1996-02-06", "statut_mandat": "ex_pep",
        "fonctions_hist": "Président de la Commission CEDEAO",
    },
]

SEP  = "═" * 100
SEP2 = "─" * 100

def get_db_record(nom_complet, code_iso, rows_db):
    parts = [p.lower() for p in nom_complet.split() if len(p) > 2]
    for r in rows_db:
        if r.get("code_iso") != code_iso:
            continue
        db_nom = (r.get("nom_complete") or "").lower()
        commun = sum(1 for p in parts if p in db_nom)
        if commun >= 2 or db_nom == nom_complet.lower():
            return r
    return None

def fmt_date(v):
    if v is None:
        return ""
    if hasattr(v, 'strftime'):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()

def score_candidat(ref, db):
    """Retourne (champs_ok, champs_total, details)"""
    if db is None:
        return 0, 1, ["ABSENT en base"]

    champs = [
        ("fonction",         ref["fonction"],          db.get("fonction_actuelle")),
        ("statut_mandat",    ref["statut_mandat"],     db.get("statut_mandat")),
        ("date_naissance",   ref["date_naissance"],    fmt_date(db.get("date_naissance"))),
        ("lieu_naissance",   ref["lieu_naissance"],    db.get("lieu_naissance")),
        ("statut_matrimon",  ref["statut_matrimonial"],db.get("statut_matrimonial")),
        ("fonctions_hist",   ref["fonctions_hist"],    db.get("fonctions_interieures")),
        ("nb_enfants",       ref["nb_enfants"],        db.get("enfants")),
    ]
    ok = 0
    total = 0
    details = []
    for label, ref_v, db_v in champs:
        if ref_v is None:
            continue
        total += 1
        ref_s = str(ref_v).lower().strip()
        db_s  = str(db_v or "").lower().strip()
        if db_s and db_s not in ("none", "non disponible", "0"):
            if ref_s[:4] in db_s or ref_s in db_s or db_s in ref_s:
                ok += 1
                details.append(f"  ✅ {label}")
            else:
                details.append(f"  ⚠  {label}: REF={ref_v} | DB={db_v}")
        else:
            details.append(f"  ❌ {label}: MANQUANT (REF={ref_v})")
    return ok, total, details

def run_comparison(iteration):
    rows_db = query_all("""
        SELECT nom_complete, code_iso, fonction_actuelle, statut_mandat,
               date_nomination, date_naissance, lieu_naissance,
               statut_matrimonial, enfants, fonctions_interieures, source_url
        FROM pep ORDER BY nom_complete
    """)

    total_ok = 0
    total_champs = 0
    a_relancer = []

    print(f"\n{SEP}")
    print(f"COMPARAISON — ITÉRATION {iteration}")
    print(SEP)

    for ref in REFERENCE:
        db = get_db_record(ref["nom_complet"], ref["code_iso"], rows_db)
        ok, total, details = score_candidat(ref, db)
        total_ok     += ok
        total_champs += total
        pct = int(ok / total * 100) if total else 0
        flag = "✅" if pct >= 70 else ("🟡" if pct >= 40 else "❌")
        print(f"\n{flag} {ref['nom_complet']:30} ({ref['code_iso']}) — {ok}/{total} ({pct}%)")
        for d in details:
            print(d)
        if pct < 80:
            a_relancer.append((ref["prenom"], ref["nom"], ref["code_iso"]))

    score_global = int(total_ok / total_champs * 100) if total_champs else 0
    print(f"\n{SEP}")
    print(f"SCORE GLOBAL : {total_ok}/{total_champs} champs corrects → {score_global}%")
    print(SEP)
    return score_global, a_relancer

# ─── BOUCLE PRINCIPALE ────────────────────────────────────────────────────────
MAX_ITERATIONS = 3
SEUIL_OK       = 80   # % de champs corrects pour arrêter

print(f"\n{'#'*100}")
print(f"  BATCH LOOP — 10 candidats | stocker=True | seuil={SEUIL_OK}%")
print(f"{'#'*100}")

# Première itération : lancer tout le monde
a_traiter = [(p, n, c) for p, n, c in CANDIDATS]

for iteration in range(1, MAX_ITERATIONS + 1):
    print(f"\n{'#'*100}")
    print(f"  PASSE {iteration}/{MAX_ITERATIONS} — {len(a_traiter)} candidats à traiter")
    print(f"{'#'*100}")

    for i, (prenom, nom, ciso) in enumerate(a_traiter, 1):
        print(f"\n[{i}/{len(a_traiter)}] ▶ {prenom} {nom} ({ciso})")
        tentatives = 0
        while tentatives < 3:
            try:
                r = verifier_pep(prenom, nom, stocker=True)
                print(f"  → PEP={r.est_pep} | {r.fonction} | {r.pays} ({r.code_iso})")
                print(f"  → Naissance={r.date_naissance} | Lieu={r.lieu_naissance} | Matrimonial={r.statut_matrimonial}")
                break
            except Exception as e:
                msg = str(e)
                # Détecter rate limit Groq et extraire le délai
                m = re.search(r'try again in (\d+)m(\d+)', msg)
                if m:
                    attente = int(m.group(1)) * 60 + int(m.group(2)) + 30
                    print(f"  ⏳ Groq rate limit — attente {attente}s ({int(attente/60)}min)...")
                    time.sleep(attente)
                    tentatives += 1
                    continue
                print(f"  ERREUR : {e}")
                break
        # Pause anti-rate-limit entre candidats
        if i < len(a_traiter):
            time.sleep(5)

    # Comparaison post-batch
    score, a_relancer = run_comparison(iteration)

    if score >= SEUIL_OK:
        print(f"\n✅ Score {score}% ≥ seuil {SEUIL_OK}% — ARRÊT de la boucle")
        break

    if iteration < MAX_ITERATIONS:
        print(f"\n🔄 Score {score}% < {SEUIL_OK}% — Relance des candidats insuffisants ({len(a_relancer)}) dans 10s...")
        # Filtrer pour ne relancer que ceux encore insuffisants
        a_traiter = [(p, n, c) for p, n, c in a_relancer]
        time.sleep(10)
    else:
        print(f"\n⚠  Max itérations ({MAX_ITERATIONS}) atteint. Score final : {score}%")

print(f"\n{'#'*100}")
print("  FIN DU BATCH LOOP")
print(f"{'#'*100}\n")
