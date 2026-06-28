"""Test _est_personne_valide() sur des noms SN typiques."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv(override=True)
from pep_collector import _est_personne_valide

cas_tests = [
    # Personnes réelles — doivent passer ✅
    {"prenom": "Ousmane",     "nom": "SONKO",    "fonction": "Premier Ministre"},
    {"prenom": "Yassine",     "nom": "FALL",     "fonction": "Ministre des Affaires étrangères"},
    {"prenom": "Alioune",     "nom": "DIOP",     "fonction": "Ministre"},
    {"prenom": "Ibrahima",    "nom": "NIANG",    "fonction": "Ministre"},
    {"prenom": "Moustapha",   "nom": "GAYE",     "fonction": "Ministre"},
    {"prenom": "Cheikh",      "nom": "DIEYE",    "fonction": "Ministre"},
    {"prenom": "Mabouba",     "nom": "DIAGNE",   "fonction": "Ministre"},
    {"prenom": "Mame Mbaye",  "nom": "NIANG",    "fonction": "Ministre de la Communication"},
    {"prenom": "Seydou",      "nom": "KA",       "fonction": "Directeur"},
    # Institutions — doivent être rejetées ❌
    {"prenom": "",            "nom": "CTRF",         "fonction": "Cellule de traitement"},
    {"prenom": "",            "nom": "BCM",          "fonction": "Banque Centrale"},
    {"prenom": "",            "nom": "BCEAO",        "fonction": "Banque"},
    {"prenom": "",            "nom": "Commission",   "fonction": ""},
    {"prenom": "",            "nom": "Gouvernement du Sénégal", "fonction": ""},
    {"prenom": "",            "nom": "Ministère des Finances",  "fonction": ""},
    {"prenom": "",            "nom": "Direction Générale",      "fonction": ""},
    # Cas limites
    {"prenom": "Moustapha Mamba", "nom": "GUIRASSY", "fonction": "Ministre"},
    {"prenom": "YOUNOUSSA",   "nom": "CISSOKO",  "fonction": "Député"},
]

print(f"{'NOM':<30} {'PRÉNOM':<20} {'RÉSULTAT'}")
print("-"*70)
for c in cas_tests:
    ok = _est_personne_valide(c)
    symbole = "✅" if ok else "❌"
    print(f"{c['nom']:<30} {c['prenom']:<20} {symbole}")
