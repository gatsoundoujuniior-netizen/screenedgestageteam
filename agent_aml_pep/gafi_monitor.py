"""
GAFI Monitor — ScreenEdge Africa
Vérifie automatiquement les statuts GAFI, met à jour le référentiel.
Notifie via n8n webhook → Email + WhatsApp.
Surveillance hebdomadaire — couvre les 3 plénières GAFI (fév/mars, juin/juil, oct/nov).
"""

import os
import re
import sys
import json
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from langchain_tavily import TavilySearch

sys.stdout.reconfigure(encoding="utf-8")

load_dotenv(override=True)

# ── Configuration ──────────────────────────────────────────────────────────

SKILL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aml-pep-research-agent (1).md")

PAYS_SURVEILLES = [
    {"nom": "Maroc",          "code": "MA", "marker": "## MAROC"},
    {"nom": "Algérie",        "code": "DZ", "marker": "## ALGÉRIE"},
    {"nom": "Tunisie",        "code": "TN", "marker": "## TUNISIE"},
    {"nom": "Libye",          "code": "LY", "marker": "## LIBYE"},
    {"nom": "Sénégal",        "code": "SN", "marker": "## SÉNÉGAL"},
    {"nom": "Côte d'Ivoire",  "code": "CI", "marker": "## CÔTE D'IVOIRE"},
    {"nom": "Togo",           "code": "TG", "marker": "## TOGO"},
    {"nom": "Bénin",          "code": "BJ", "marker": "## BÉNIN"},
    {"nom": "Mali",           "code": "ML", "marker": "## MALI"},
    {"nom": "Burkina Faso",   "code": "BF", "marker": "## BURKINA FASO"},
    {"nom": "Niger",          "code": "NE", "marker": "## NIGER"},
    {"nom": "Guinée-Bissau",  "code": "GW", "marker": "## GUINÉE-BISSAU"},
    {"nom": "Guinée",         "code": "GN", "marker": "## GUINÉE (hors UEMOA)"},
]

tavily = TavilySearch(max_results=3, search_depth="advanced")


# ── Étape 1 : Lire les statuts actuels dans le .md ────────────────────────

def parse_statuts_actuels() -> dict:
    """Extrait les statuts GAFI actuels depuis le fichier .md."""
    with open(SKILL_PATH, "r", encoding="utf-8") as f:
        contenu = f.read()

    statuts = {}
    for pays in PAYS_SURVEILLES:
        marker = pays["marker"]
        if marker not in contenu:
            statuts[pays["code"]] = "inconnu"
            continue
        debut = contenu.index(marker)
        fin = contenu.find("\n---", debut + len(marker))
        section = contenu[debut:fin if fin != -1 else debut + 3000]

        # Cherche uniquement la ligne "Statut GAFI"
        # Priorité : Clean > liste_noire > liste_grise
        # "sorti liste grise 2023" sur une ligne Clean ne compte pas
        statut = "clean"
        for ligne in section.split("\n"):
            if "statut gafi" in ligne.lower():
                if "clean" in ligne.lower() or "🟢" in ligne:
                    statut = "clean"
                elif "liste noire" in ligne.lower():
                    statut = "liste_noire"
                elif "liste grise" in ligne.lower():
                    statut = "liste_grise"
                break
        statuts[pays["code"]] = statut

    return statuts


# ── Étape 2 : Vérifier les statuts en ligne via Tavily ────────────────────

def verifier_statut_en_ligne(nom_pays: str) -> str:
    """Interroge Tavily pour le statut GAFI actuel d'un pays."""
    pays_lower = nom_pays.lower()
    try:
        # Une seule requête ciblée sur la page FATF officielle
        query = f'site:fatf-gafi.org "jurisdictions under increased monitoring" OR "call for action" {nom_pays} 2026'
        result = str(tavily.invoke({"query": query})).lower()

        # Le pays doit apparaître dans le résultat
        if pays_lower not in result:
            return "clean"

        # Cherche toutes les occurrences du pays et analyse le contexte large
        idx = 0
        is_grise = False
        is_noire = False
        while True:
            idx = result.find(pays_lower, idx)
            if idx == -1:
                break
            contexte = result[max(0, idx - 300):idx + 300]
            # Vérifie que le pays n'est pas mentionné comme "sorti" de la liste
            removed = "removed" in result[max(0, idx - 60):idx + 10]
            if not removed:
                if "call for action" in contexte:
                    is_noire = True
                elif "increased monitoring" in contexte:
                    is_grise = True
            idx += len(pays_lower)

        if is_noire:
            return "liste_noire"
        elif is_grise:
            return "liste_grise"
        return "clean"
    except Exception as e:
        print(f"  Erreur Tavily pour {nom_pays} : {e}")
        return "inconnu"


# ── Étape 3 : Mettre à jour le .md si changement détecté ─────────────────

def mettre_a_jour_md(code: str, ancien: str, nouveau: str):
    """Met à jour le statut GAFI d'un pays dans le fichier .md."""
    with open(SKILL_PATH, "r", encoding="utf-8") as f:
        contenu = f.read()

    pays = next(p for p in PAYS_SURVEILLES if p["code"] == code)
    marker = pays["marker"]
    if marker not in contenu:
        return

    debut = contenu.index(marker)
    fin = contenu.find("\n---", debut + len(marker))
    section = contenu[debut:fin if fin != -1 else debut + 3000]

    # Mapping labels
    labels = {
        "liste_noire": "🔴 **Liste noire**",
        "liste_grise": "🔴 **Liste grise**",
        "clean": "🟢 Clean",
    }
    ancien_label = labels.get(ancien, ancien)
    nouveau_label = labels.get(nouveau, nouveau)

    section_maj = re.sub(
        r"(Statut GAFI fév\. \d{4}\s*:\s*).*",
        f"\\1{nouveau_label} (mis à jour {datetime.now().strftime('%d/%m/%Y')})",
        section
    )
    contenu_maj = contenu[:debut] + section_maj + contenu[fin:]

    with open(SKILL_PATH, "w", encoding="utf-8") as f:
        f.write(contenu_maj)

    print(f"  .md mis à jour : {pays['nom']} {ancien_label} → {nouveau_label}")


# ── Étape 4 : Notifier via n8n (Email + WhatsApp) ─────────────────────────

def notifier_n8n(changements: list, rapport_complet: dict):
    """Envoie les données de changement au webhook n8n.
    n8n se charge d'envoyer l'email ET le message WhatsApp."""
    webhook_url = os.getenv("N8N_WEBHOOK_URL")
    if not webhook_url:
        print("  N8N_WEBHOOK_URL manquant dans .env")
        return

    # Tableau HTML pré-construit — n8n l'injecte directement sans JS
    lignes = ""
    for c in changements:
        lignes += f"""
        <tr style="background:#fff3cd;">
          <td style="padding:10px;font-weight:bold;">{c['pays']} ({c['code']})</td>
          <td style="padding:10px;color:#856404;">{c['ancien']}</td>
          <td style="padding:10px;font-size:18px;">→</td>
          <td style="padding:10px;color:#155724;font-weight:bold;">{c['nouveau']}</td>
        </tr>"""

    tableau_html = f"""
    <table style="width:100%;border-collapse:collapse;margin-top:12px;">
      <tr style="background:#343a40;color:white;">
        <th style="padding:10px;text-align:left;">Pays</th>
        <th style="padding:10px;text-align:left;">Ancien statut</th>
        <th style="padding:10px;"></th>
        <th style="padding:10px;text-align:left;">Nouveau statut</th>
      </tr>
      {lignes}
    </table>"""

    payload = {
        "source":         "gafi_monitor",
        "date":           datetime.now().strftime("%d/%m/%Y %H:%M"),
        "nb_changements": len(changements),
        "changements":    changements,
        "rapport":        rapport_complet,
        "tableau_html":   tableau_html,
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        print(f"  n8n notifié — Email + WhatsApp en cours d'envoi")
    except Exception as e:
        print(f"  Erreur webhook n8n : {e}")


# ── Orchestrateur principal ────────────────────────────────────────────────

def run_monitor():
    """Lance le cycle complet de vérification GAFI."""
    print(f"\n{'='*60}")
    print(f"GAFI Monitor — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*60}\n")

    # Guard — évite les doublons si le script tourne plusieurs fois dans la semaine
    rapport_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gafi_rapport.json")
    if os.path.exists(rapport_path):
        with open(rapport_path, "r", encoding="utf-8") as f:
            rapport_precedent = json.load(f)
        derniere_verif = rapport_precedent.get("date_verification")
        if derniere_verif:
            delta = datetime.now() - datetime.fromisoformat(derniere_verif)
            if delta < timedelta(days=6):
                print(f"Vérification récente ({delta.days}j) — prochain check dans {6 - delta.days}j")
                return rapport_precedent

    # Étape 1 — statuts actuels dans le .md
    statuts_md = parse_statuts_actuels()
    print(f"Statuts actuels dans le référentiel :")
    for code, statut in statuts_md.items():
        print(f"  {code} : {statut}")

    # Étape 2 — vérification en ligne
    print(f"\nVérification en ligne via Tavily...")
    statuts_en_ligne = {}
    for pays in PAYS_SURVEILLES:
        print(f"  Vérification {pays['nom']}...")
        statuts_en_ligne[pays["code"]] = verifier_statut_en_ligne(pays["nom"])

    # Étape 3 — comparaison et mise à jour
    changements = []
    for pays in PAYS_SURVEILLES:
        code   = pays["code"]
        ancien = statuts_md.get(code, "inconnu")
        nouveau = statuts_en_ligne.get(code, "inconnu")

        if nouveau == "inconnu":
            print(f"  {code} : statut en ligne non déterminé, ignoré")
            continue

        if ancien != nouveau:
            print(f"  CHANGEMENT détecté : {pays['nom']} {ancien} → {nouveau}")
            changements.append({"pays": pays["nom"], "code": code, "ancien": ancien, "nouveau": nouveau})
            # Ne PAS mettre à jour le .md ici — validation humaine requise via n8n

    # Étape 4 — sauvegarde pending + notification n8n
    print(f"\n{len(changements)} changement(s) détecté(s)")
    if changements:
        # Sauvegarde dans gafi_pending.json — apply_changes.py appliquera après validation
        pending_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gafi_pending.json")
        pending = {
            "date_detection": datetime.now().isoformat(),
            "changements": changements,
            "statuts_actuels": statuts_md
        }
        with open(pending_path, "w", encoding="utf-8") as f:
            json.dump(pending, f, ensure_ascii=False, indent=2)
        print(f"Changements en attente sauvegardés : {pending_path}")

        print("Notification n8n en cours (Email + WhatsApp + approbation)...")
        notifier_n8n(changements, statuts_md)
    else:
        print("Aucun changement — pas de notification envoyée")

    # Sauvegarde du rapport JSON
    rapport = {
        "date_verification": datetime.now().isoformat(),
        "changements": changements,
        "statuts_actuels": statuts_md
    }
    rapport_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gafi_rapport.json")
    with open(rapport_path, "w", encoding="utf-8") as f:
        json.dump(rapport, f, ensure_ascii=False, indent=2)
    print(f"Rapport sauvegardé : {rapport_path}")

    print(f"\n{'='*60}")
    print("Monitoring terminé")
    print(f"{'='*60}\n")

    return rapport


if __name__ == "__main__":
    run_monitor()
