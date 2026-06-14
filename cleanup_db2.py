"""Nettoyage phase 2 — faux positifs + doublons identifiés à l'audit."""
import sys; sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv(override=True)
from db_utils import execute, query_all

suppressions = [
    # ── Faux positifs clairs ─────────────────────────────────────────────────
    ("CI — Daniel Kouadjo (faux Président, Ouattara est président)",
     "DELETE FROM pep WHERE nom_complete ILIKE '%Daniel Kouadjo%' AND code_iso='CI'"),

    ("BJ — Corinne Brunet (Ministre française, pas béninoise)",
     "DELETE FROM pep WHERE nom_complete ILIKE '%Corinne Brunet%' AND code_iso='BJ'"),

    ("BJ — Daris Gildas Gbaguidi (supporter politique, pas fonction PEP)",
     "DELETE FROM pep WHERE nom_complete ILIKE '%Gbaguidi%' AND code_iso='BJ'"),

    ("LY — Abdoulaye Bathily (représentant ONU sénégalais, pas PEP libyen)",
     "DELETE FROM pep WHERE nom_complete ILIKE '%Bathily%' AND code_iso='LY'"),

    ("LY — Hannah Tetteh (représentante ONU ghanéenne, pas PEP libyenne)",
     "DELETE FROM pep WHERE nom_complete ILIKE '%Tetteh%' AND code_iso='LY'"),

    ("BF — Dr. Aminta (nom incomplet)",
     "DELETE FROM pep WHERE nom_complete ILIKE 'Dr. Aminta' AND code_iso='BF'"),

    # ── Doublons CI (préfixe M. / Me) — garder la version sans préfixe ─────
    ("CI — doublon 'M. Adama Kone'",
     "DELETE FROM pep WHERE nom_complete = 'M. Adama Kone' AND code_iso='CI'"),

    ("CI — doublon 'M. Gbatou Tonga Guillaume'",
     "DELETE FROM pep WHERE nom_complete = 'M. Gbatou Tonga Guillaume' AND code_iso='CI'"),

    ("CI — doublon 'M. Houra Kouassi Marc'",
     "DELETE FROM pep WHERE nom_complete = 'M. Houra Kouassi Marc' AND code_iso='CI'"),

    ("CI — doublon 'Me Blessy Chrysostome'",
     "DELETE FROM pep WHERE nom_complete = 'Me Blessy Chrysostome' AND code_iso='CI'"),

    # ── Doublons DZ (orthographe différente) — garder la version la plus récente ─
    ("DZ — doublon 'Mouatassem Boudiaf' (garder Mouatassim)",
     "DELETE FROM pep WHERE nom_complete = 'Mouatassem Boudiaf' AND code_iso='DZ'"),

    ("DZ — doublon 'Salah Eddine Taleb' (garder Salah-Eddine avec tiret)",
     "DELETE FROM pep WHERE nom_complete = 'Salah Eddine Taleb' AND code_iso='DZ'"),

    # ── Doublon TG Gnassingbé — garder le nom complet ───────────────────────
    ("TG — doublon 'Faure E. Gnassingbé' (garder Faure Essozimna Gnassingbé)",
     "DELETE FROM pep WHERE nom_complete = 'Faure E. Gnassingbé' AND code_iso='TG'"),

    # ── TG ex-PEP sans aucune fonction (non identifiables) ──────────────────
    ("TG — ex-PEP sans fonction : Edem Kodjo",
     "DELETE FROM pep WHERE nom_complete='Edem Kodjo' AND code_iso='TG' AND (fonction_actuelle IS NULL OR fonction_actuelle='')"),

    ("TG — ex-PEP sans fonction : Gilchrist Olympio",
     "DELETE FROM pep WHERE nom_complete='Gilchrist Olympio' AND code_iso='TG' AND (fonction_actuelle IS NULL OR fonction_actuelle='')"),

    ("TG — ex-PEP sans fonction : Joseph Kokou Koffigoh",
     "DELETE FROM pep WHERE nom_complete='Joseph Kokou Koffigoh' AND code_iso='TG' AND (fonction_actuelle IS NULL OR fonction_actuelle='')"),

    ("TG — ex-PEP sans fonction : Paul Amégankpo",
     "DELETE FROM pep WHERE nom_complete='Paul Amégankpo' AND code_iso='TG' AND (fonction_actuelle IS NULL OR fonction_actuelle='')"),

    ("TG — ex-PEP sans fonction : Yawovi Agboyibo",
     "DELETE FROM pep WHERE nom_complete='Yawovi Agboyibo' AND code_iso='TG' AND (fonction_actuelle IS NULL OR fonction_actuelle='')"),
]

total = 0
for label, sql in suppressions:
    execute(sql)
    print(f"  ✅ {label}")
    total += 1

print(f"\n{'='*55}")
print(f"Total : {total} opérations exécutées")
reste = query_all("SELECT COUNT(*) AS n FROM pep")
print(f"PEP restants en base : {reste[0]['n']}")
