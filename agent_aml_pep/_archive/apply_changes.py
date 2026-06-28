"""
apply_changes.py — ScreenEdge Africa
Applique les changements GAFI en attente après validation humaine via n8n.
Appelé par n8n via Execute Command node après approbation.
"""

import os
import re
import sys
import json
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

SKILL_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aml-pep-research-agent (1).md")
PENDING_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gafi_pending.json")

LABELS = {
    "liste_noire": "🔴 **Liste noire**",
    "liste_grise": "🔴 **Liste grise**",
    "clean":       "🟢 Clean",
}

PAYS_SURVEILLES = [
    {"nom": "Maroc",         "code": "MA", "marker": "## MAROC"},
    {"nom": "Algérie",       "code": "DZ", "marker": "## ALGÉRIE"},
    {"nom": "Tunisie",       "code": "TN", "marker": "## TUNISIE"},
    {"nom": "Libye",         "code": "LY", "marker": "## LIBYE"},
    {"nom": "Sénégal",       "code": "SN", "marker": "## SÉNÉGAL"},
    {"nom": "Côte d'Ivoire", "code": "CI", "marker": "## CÔTE D'IVOIRE"},
    {"nom": "Togo",          "code": "TG", "marker": "## TOGO"},
    {"nom": "Bénin",         "code": "BJ", "marker": "## BÉNIN"},
    {"nom": "Mali",          "code": "ML", "marker": "## MALI"},
    {"nom": "Burkina Faso",  "code": "BF", "marker": "## BURKINA FASO"},
    {"nom": "Niger",         "code": "NE", "marker": "## NIGER"},
    {"nom": "Guinée-Bissau", "code": "GW", "marker": "## GUINÉE-BISSAU"},
    {"nom": "Guinée",        "code": "GN", "marker": "## GUINÉE (hors UEMOA)"},
]


def appliquer_changement(code: str, nouveau: str):
    pays = next((p for p in PAYS_SURVEILLES if p["code"] == code), None)
    if not pays:
        print(f"  Pays {code} non trouvé")
        return

    with open(SKILL_PATH, "r", encoding="utf-8") as f:
        contenu = f.read()

    marker = pays["marker"]
    if marker not in contenu:
        print(f"  Section {marker} introuvable dans le .md")
        return

    debut = contenu.index(marker)
    fin   = contenu.find("\n---", debut + len(marker))
    section = contenu[debut:fin if fin != -1 else debut + 3000]

    nouveau_label = LABELS.get(nouveau, nouveau)
    date_maj      = datetime.now().strftime("%d/%m/%Y")

    section_maj = re.sub(
        r"(\*\*Statut GAFI fév\. \d{4} :\*\* ).*",
        f"\\1{nouveau_label} (validé le {date_maj})",
        section
    )
    contenu_maj = contenu[:debut] + section_maj + contenu[fin:]

    with open(SKILL_PATH, "w", encoding="utf-8") as f:
        f.write(contenu_maj)

    print(f"  {pays['nom']} → {nouveau_label}")


def run():
    if not os.path.exists(PENDING_PATH):
        print("Aucun changement en attente.")
        return

    with open(PENDING_PATH, "r", encoding="utf-8") as f:
        pending = json.load(f)

    changements = pending.get("changements", [])
    if not changements:
        print("Fichier pending vide.")
        return

    print(f"\n{'='*50}")
    print(f"Application de {len(changements)} changement(s) validé(s)")
    print(f"{'='*50}\n")

    for c in changements:
        appliquer_changement(c["code"], c["nouveau"])

    # Archive le pending avec horodatage
    pending["applique_le"] = datetime.now().isoformat()
    archive_path = PENDING_PATH.replace(".json", f"_archive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)

    os.remove(PENDING_PATH)
    print(f"\nChangements appliqués. Archive : {archive_path}")


if __name__ == "__main__":
    run()
