"""
compare_candidats.py — Compare les données extraites (DB) vs référence (fichier candidats)
"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_utils import query_all

# ─── Vérité terrain (fichier candidats) ───────────────────────────────────────
REFERENCE = [
    {
        "nom_complet": "Bassirou Diomaye Faye",
        "code_iso": "SN",
        "date_naissance": "25/03/1980",
        "lieu_naissance": "Ndiaganiao",
        "statut_matrimonial": "polygame",
        "nb_enfants": None,
        "fonction": "Président de la République du Sénégal",
        "date_nomination": "02/04/2024",
        "statut_mandat": "actif",
        "fonctions_hist": [],
    },
    {
        "nom_complet": "Alassane Ouattara",
        "code_iso": "CI",
        "date_naissance": "01/01/1942",
        "lieu_naissance": "Dimbokro",
        "statut_matrimonial": "marié",
        "nb_enfants": 2,
        "fonction": "Président de la République de Côte d'Ivoire",
        "date_nomination": "06/05/2011",
        "statut_mandat": "actif",
        "fonctions_hist": ["Premier ministre (1990-1993)"],
    },
    {
        "nom_complet": "Faure Gnassingbé",
        "code_iso": "TG",
        "date_naissance": "06/06/1966",
        "lieu_naissance": "Afagnan",
        "statut_matrimonial": None,
        "nb_enfants": None,
        "fonction": "Président du Conseil du Togo",
        "date_nomination": "03/05/2025",
        "statut_mandat": "actif",
        "fonctions_hist": ["Président de la République du Togo (2005-2025)"],
    },
    {
        "nom_complet": "Patrice Talon",
        "code_iso": "BJ",
        "date_naissance": "01/05/1958",
        "lieu_naissance": "Ouidah",
        "statut_matrimonial": "marié",
        "nb_enfants": 2,
        "fonction": "ex-Président de la République du Bénin",
        "date_nomination": "06/04/2016",
        "statut_mandat": "ex_pep",
        "fonctions_hist": [],
    },
    {
        "nom_complet": "Aziz Akhannouch",
        "code_iso": "MA",
        "date_naissance": "16/08/1961",
        "lieu_naissance": "Tafraout",
        "statut_matrimonial": "marié",
        "nb_enfants": 3,
        "fonction": "Chef du gouvernement du Maroc",
        "date_nomination": "07/10/2021",
        "statut_mandat": "actif",
        "fonctions_hist": ["Ministre de l'Agriculture et de la Pêche (2007-2021)"],
    },
    {
        "nom_complet": "Ousmane Sonko",
        "code_iso": "SN",
        "date_naissance": "15/07/1974",
        "lieu_naissance": "Thiès",
        "statut_matrimonial": "polygame",
        "nb_enfants": None,
        "fonction": "Président de l'Assemblée nationale du Sénégal",
        "date_nomination": "26/05/2026",
        "statut_mandat": "actif",
        "fonctions_hist": ["Premier ministre (02/04/2024 - 22/05/2026)"],
    },
    {
        "nom_complet": "Nialé Kaba",
        "code_iso": "CI",
        "date_naissance": "1962",
        "lieu_naissance": "Bouko",
        "statut_matrimonial": None,
        "nb_enfants": None,
        "fonction": "Ministre d'État, Affaires étrangères et Coopération internationale",
        "date_nomination": "23/01/2026",
        "statut_mandat": "actif",
        "fonctions_hist": ["Ministre déléguée Économie et Finances (2012-2016)", "Ministre du Plan et du Développement (2016-2026)"],
    },
    {
        "nom_complet": "Romuald Wadagni",
        "code_iso": "BJ",
        "date_naissance": "20/06/1976",
        "lieu_naissance": "Lokossa",
        "statut_matrimonial": None,
        "nb_enfants": None,
        "fonction": "Président de la République du Bénin",
        "date_nomination": "24/05/2026",
        "statut_mandat": "actif",
        "fonctions_hist": ["Ministre de l'Économie et des Finances (2016-2026)"],
    },
    {
        "nom_complet": "Saïd Ahmidouch",
        "code_iso": "MA",
        "date_naissance": "1959",
        "lieu_naissance": None,
        "statut_matrimonial": None,
        "nb_enfants": None,
        "fonction": "Wali de la région Casablanca-Settat",
        "date_nomination": "18/02/2019",
        "statut_mandat": "actif",
        "fonctions_hist": ["Directeur général de la CNSS (2004-2019)"],
    },
    {
        "nom_complet": "Kadré Désiré Ouédraogo",
        "code_iso": "BF",
        "date_naissance": "31/12/1953",
        "lieu_naissance": "Boussouma",
        "statut_matrimonial": None,
        "nb_enfants": None,
        "fonction": "ex-Premier ministre du Burkina Faso",
        "date_nomination": "06/02/1996",
        "statut_mandat": "ex_pep",
        "fonctions_hist": ["Président de la Commission CEDEAO (2012-2016)", "Ambassadeur à Bruxelles (2001-2011)"],
    },
]

# ─── Données DB ───────────────────────────────────────────────────────────────
rows_db = query_all("""
    SELECT nom_complete, code_iso, pays_nom,
           fonction_actuelle, statut_mandat,
           date_nomination, date_sortie_fonction_public,
           date_naissance, lieu_naissance,
           statut_matrimonial, enfants,
           fonctions_interieures, source_url, date_scraping
    FROM pep
    ORDER BY nom_complete
""")

def find_in_db(nom_complet, code_iso):
    nom_lower = nom_complet.lower()
    parts = [p.lower() for p in nom_complet.split() if len(p) > 2]
    # Chercher par nom + pays
    for r in rows_db:
        if r.get("code_iso") != code_iso:
            continue
        db_nom = (r.get("nom_complete") or "").lower()
        commun = sum(1 for p in parts if p in db_nom)
        if commun >= 2 or db_nom == nom_lower:
            return r
    return None

def fmt(v):
    if v is None:
        return "—"
    if hasattr(v, 'strftime'):
        return v.strftime("%d/%m/%Y")
    return str(v).strip() or "—"

def cmp(ref_val, db_val):
    if ref_val is None:
        return "N/A"
    ref_s = str(ref_val).lower().strip()
    db_s  = str(db_val or "").lower().strip()
    if not db_s or db_s in ("none", "non disponible", "—"):
        return "MANQUANT"
    if ref_s in db_s or db_s in ref_s:
        return "OK"
    # date partielle (année seule)
    if len(ref_s) == 4 and ref_s in db_s:
        return "OK"
    if ref_s[:4] == db_s[:4] and len(ref_s) >= 4:
        return "APPROX"
    return f"DIFF (ref={ref_val} | db={db_val})"

SEP = "═" * 110
SEP2 = "─" * 110

total_champs = 0
champs_ok = 0
champs_manquants = 0
champs_diff = 0

print(f"\n{SEP}")
print(f"COMPARAISON EXTRACTION DB ↔ RÉFÉRENCE CANDIDATS")
print(SEP)

for ref in REFERENCE:
    nom   = ref["nom_complet"]
    ciso  = ref["code_iso"]
    db    = find_in_db(nom, ciso)

    print(f"\n{'▶':2} {nom:30} ({ciso})")
    print(SEP2)

    if db is None:
        print(f"  ⚠  ABSENT en base (code_iso={ciso})")
        continue

    print(f"  Source DB : {db.get('source_url', '—')}")
    print(f"  Scraping  : {fmt(db.get('date_scraping'))}")
    print()

    champs = [
        ("Fonction",         ref["fonction"],           db.get("fonction_actuelle")),
        ("Statut mandat",    ref["statut_mandat"],      db.get("statut_mandat")),
        ("Date nomination",  ref["date_nomination"],    fmt(db.get("date_nomination"))),
        ("Date naissance",   ref["date_naissance"],     fmt(db.get("date_naissance"))),
        ("Lieu naissance",   ref["lieu_naissance"],     db.get("lieu_naissance")),
        ("Statut matrimon.", ref["statut_matrimonial"], db.get("statut_matrimonial")),
        ("Nb enfants",       ref["nb_enfants"],         db.get("enfants")),
        ("Fonctions hist.",  " / ".join(ref["fonctions_hist"]) if ref["fonctions_hist"] else None,
                             db.get("fonctions_interieures")),
    ]

    for label, ref_v, db_v in champs:
        total_champs += 1
        status = cmp(ref_v, db_v)
        if status == "OK" or status == "APPROX":
            champs_ok += 1
            icon = "✅" if status == "OK" else "🟡"
        elif status == "MANQUANT":
            champs_manquants += 1
            icon = "❌"
        elif status == "N/A":
            total_champs -= 1
            icon = "·"
        else:
            champs_diff += 1
            icon = "⚠"

        ref_disp = str(ref_v) if ref_v is not None else "—"
        db_disp  = fmt(db_v) if db_v is not None else "—"
        print(f"  {icon} {label:20} REF: {ref_disp:40} DB: {db_disp}")

print(f"\n{SEP}")
total_evalue = champs_ok + champs_manquants + champs_diff
pct_ok  = int(champs_ok  / total_evalue * 100) if total_evalue else 0
pct_man = int(champs_manquants / total_evalue * 100) if total_evalue else 0
pct_dif = int(champs_diff / total_evalue * 100) if total_evalue else 0
print(f"RÉSULTAT GLOBAL : {total_evalue} champs évalués")
print(f"  ✅ Corrects   : {champs_ok:3} ({pct_ok}%)")
print(f"  ❌ Manquants  : {champs_manquants:3} ({pct_man}%)")
print(f"  ⚠  Différents : {champs_diff:3} ({pct_dif}%)")
print(SEP)
