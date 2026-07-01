"""
pep_collector.py — ScreenEdge Africa
Collecteur autonome de PEP : Track B (sites officiels) + Track A (OpenSanctions + Tavily + Serper)

Track B : site officiel → HTML → LLM JSON → INSERT direct (fast, ~30 min)
Track A : OpenSanctions + Tavily + Serper → découverte noms → verifier_pep (continu)

Lancer :
  python pep_collector.py                    # les deux tracks, 13 pays
  python pep_collector.py --pays MA,SN,CI    # pays sélectionnés
"""

import sys, os, json, re, time
import requests
import argparse
from datetime import datetime
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8")

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from db_utils import query_one, query_all, execute
from search_tools import rechercher_opensanctions, URLS_GOUVERNEMENTALES

load_dotenv(override=True)

llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0.1)

PAYS_PERIMETRE = ["MA", "DZ", "TN", "LY", "SN", "CI", "ML", "BF", "NE", "TG", "BJ", "GW", "GN"]

STATUS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "collector_status.json")
REF_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "referentiel_pep.json")

# ── État global de la collecte (écrit dans collector_status.json) ────────────────

_status: dict = {
    "running":         False,
    "track":           "",
    "country":         "",
    "category":        "",
    "inserted_total":  0,
    "inserted_last":   0,
    "verif_total":     0,
    "max_verif":       0,
    "countries_done":  0,
    "countries_total": len(PAYS_PERIMETRE),
    "errors":          [],
    "last_update":     "",
    "llm_actif":       "",
}


def _update_status(**kwargs) -> None:
    _status.update(kwargs)
    _status["last_update"] = datetime.now().isoformat()
    try:
        with open(STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(_status, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ── Sources officielles Track B — URLs hardcodées par pays/catégorie ─────────────

SOURCES_TRACK_B: dict[str, dict[str, str]] = {
    "MA": {
        "parlement":       "https://www.chambredesrepresentants.ma/fr",
        "gouvernement":    "https://www.cg.gov.ma/fr",
        "banque_centrale": "https://www.bkam.ma/fr",
    },
    "DZ": {
        # premier-ministre.gov.dz + apn.dz inaccessibles → Serper fallback
        "banque_centrale": "https://www.bank-of-algeria.dz/fr",
    },
    "TN": {
        "parlement":       "https://www.arp.tn",
        "presidence":      "https://www.carthage.tn",
        # gouvernement.tn + bct.gov.tn inaccessibles → Serper fallback
    },
    "LY": {
        # gov.ly inaccessible → Serper fallback
        "banque_centrale": "https://www.cbl.gov.ly",
    },
    "SN": {
        "gouvernement":       "https://www.presidence.sn/fr/institutions/le-gouvernement/",
        "gouvernement_liste": "https://www.presidence.sn/fr/actualites/liste-complete-des-membres-du-nouveau-gouvernement/",
        # assemblee-nationale.sn inaccessible → Serper fallback
    },
    "CI": {
        "gouvernement":    "https://www.gouv.ci/gouvernement",
        # assemblee-nationale.ci vide → Serper fallback
    },
    "ML": {
        "presidence":      "https://www.koulouba.ml",
        # primature.gov.ml inaccessible → Serper fallback
    },
    "BF": {
        "gouvernement":    "https://www.gouvernement.gov.bf/gouvernement",
        "presidence":      "https://www.sig.gov.bf/gouvernement",
    },
    "NE": {
        "gouvernement":    "https://www.gouv.ne",
        # presidence.ne inaccessible → Serper fallback
    },
    "TG": {
        # presidence.gouv.tg retourne HTML vide (JS-rendu) → Scrapling + Serper fallback
    },
    "BJ": {
        "gouvernement":    "https://gouv.bj",
        "parlement":       "https://assemblee-nationale.bj",
        "presidence":      "https://presidence.bj",
    },
    "GW": {
        # Tous les domaines inaccessibles → Serper fallback uniquement
    },
    "GN": {
        "gouvernement":    "https://www.gouvernement.gov.gn/gouvernement/composition",
        "banque_centrale": "https://www.bcrg-guinee.org",
        # presidence.gov.gn → HTTP 403, bcrg.org → chemin 404 → remplacés
    },
}


# ── Configuration par pays : catégories actives + requêtes spécifiques ───────────
# contexte : "democratie" | "monarchie" | "junte" | "crise"
# categories_inactives : catégories à exclure (sénat inexistant, partis suspendus…)
# requetes_specifiques : surcharge des requêtes génériques pour ce pays

_CONFIG_PAYS: dict[str, dict] = {
    "MA": {
        "contexte": "monarchie",
        "categories_inactives": [],
        "requetes_specifiques": {
            "senat": [
                '"Maroc" "Chambre des Conseillers" membres liste {annee}',
                '"Maroc" chambre haute parlement conseillers composition',
            ],
            "presidence": [
                '"Maroc" "Chef du Gouvernement" membres cabinet royal',
                '"Maroc" "Palais Royal" conseillers royaux liste',
                '"Maroc" premier ministre chef gouvernement {annee}',
            ],
            "conseil_constitutionnel": [
                '"Maroc" "Cour Constitutionnelle" membres composition {annee}',
                '"Maroc" "Conseil Constitutionnel" membres liste officielle',
            ],
            "entreprises_etat": [
                '"Maroc" "OCP" OR "ONEE" OR "ONCF" OR "RAM" directeur général',
                '"Maroc" établissements publics directeurs généraux liste',
                '"Maroc" société nationale directeur PDG conseil administration',
            ],
            "collectivites_locales": [
                '"Maroc" présidents régions conseils régionaux liste {annee}',
                '"Maroc" "wali" gouverneur région liste officielle',
                '"Maroc" maires grandes villes Casablanca Rabat Fès Marrakech',
            ],
        },
    },
    "DZ": {
        "contexte": "democratie",
        "categories_inactives": [],
        "requetes_specifiques": {
            "parlement": [
                '"Algérie" "Assemblée Populaire Nationale" APN membres députés {annee}',
                '"Algérie" APN composition membres liste officielle',
            ],
            "senat": [
                '"Algérie" "Conseil de la Nation" membres sénateurs composition {annee}',
                '"Algérie" chambre haute parlement Conseil Nation liste',
            ],
            "presidence": [
                '"Algérie" "Présidence de la République" conseillers cabinet {annee}',
                '"Algérie" premier ministre chef gouvernement Tebboune',
            ],
            "conseil_constitutionnel": [
                '"Algérie" "Cour Constitutionnelle" membres composition {annee}',
                '"Algérie" conseil constitutionnel membres liste',
            ],
            "entreprises_etat": [
                '"Algérie" "Sonatrach" OR "Sonelgaz" OR "Air Algérie" directeur général PDG',
                '"Algérie" entreprises publiques directeurs généraux liste {annee}',
            ],
            "collectivites_locales": [
                '"Algérie" walis gouverneurs wilayas liste {annee}',
                '"Algérie" "assemblée populaire communale" APC maires grandes villes',
            ],
        },
    },
    "TN": {
        "contexte": "democratie",
        "categories_inactives": ["senat"],  # Chambre des Conseillers supprimée en 2021
        "requetes_specifiques": {
            "parlement": [
                '"Tunisie" "Assemblée des Représentants du Peuple" membres {annee}',
                '"Tunisie" "Conseil National des Régions et Districts" membres',
                '"Tunisie" ARP parlement membres composition liste',
            ],
            "presidence": [
                '"Tunisie" "Kaïs Saïed" OR "Saied" présidence cabinet',
                '"Tunisie" présidence de la République conseillers {annee}',
            ],
            "conseil_constitutionnel": [
                '"Tunisie" "Cour Constitutionnelle" membres {annee}',
                '"Tunisie" conseil constitutionnel membres liste',
            ],
            "entreprises_etat": [
                '"Tunisie" "STEG" OR "SONEDE" OR "Tunisair" OR "ONCTT" directeur général',
                '"Tunisie" entreprises publiques directeurs généraux liste',
            ],
        },
    },
    "LY": {
        "contexte": "crise",
        "categories_inactives": ["senat", "collectivites_locales", "partis_politiques", "conseil_economique"],
        "requetes_specifiques": {
            "gouvernement": [
                '"Libye" "Gouvernement d\'Unité Nationale" GNU membres Tripoli {annee}',
                '"Libye" "Gouvernement de Stabilité Nationale" GNS membres Tobrouk',
                '"Libye" premier ministre gouvernement membres composition',
            ],
            "parlement": [
                '"Libye" "Chambre des Représentants" HoR membres Tobrouk {annee}',
                '"Libye" "Haut Conseil d\'État" membres Tripoli composition',
            ],
            "forces_armees": [
                '"Libye" "Armée Nationale Libyenne" ANL LNA Haftar commandement',
                '"Libye" "Forces armées" direction commandement généraux {annee}',
            ],
            "securite_police": [
                '"Libye" milices armées direction responsables Tripoli Misrata',
                '"Libye" forces sécurité intérieure direction nationale',
            ],
        },
    },
    "SN": {
        "contexte": "democratie",
        "categories_inactives": ["senat"],  # Sénat supprimé par référendum 2012
        "requetes_specifiques": {
            "gouvernement": [
                '"Sénégal" "composition du gouvernement" Sonko Faye ministres {annee}',
                '"Sénégal" liste membres gouvernement premier ministre {annee}',
                'presidence.sn composition gouvernement membres liste',
            ],
            "parlement": [
                '"Sénégal" "Assemblée Nationale" membres députés liste {annee}',
                '"Sénégal" parlement Pastef APR AGRESSIF députés composition',
            ],
            "entreprises_etat": [
                '"Sénégal" "SENELEC" OR "SONES" OR "Air Sénégal" OR "DDD" directeur général',
                '"Sénégal" sociétés nationales paraétatiques directeurs généraux {annee}',
            ],
            "institutions_regionales": [
                '"Sénégal" commissaire UEMOA représentant Dakar {annee}',
                '"Sénégal" délégué CEDEAO Nations Unies représentant permanent',
            ],
            "collectivites_locales": [
                '"Sénégal" "maires" Dakar Thiès Ziguinchor Saint-Louis liste {annee}',
                '"Sénégal" présidents conseils régionaux départements liste',
            ],
        },
    },
    "CI": {
        "contexte": "democratie",
        "categories_inactives": [],
        "requetes_specifiques": {
            "senat": [
                '"Côte d\'Ivoire" "Sénat" membres sénateurs composition liste {annee}',
                '"Côte d\'Ivoire" chambre haute parlement sénateurs',
            ],
            "gouvernement": [
                '"Côte d\'Ivoire" "composition du gouvernement" ministres liste {annee}',
                'gouv.ci gouvernement membres composition liste officielle',
            ],
            "entreprises_etat": [
                '"Côte d\'Ivoire" "CIE" OR "SODECI" OR "Air Côte d\'Ivoire" OR "Port Abidjan" directeur général',
                '"Côte d\'Ivoire" sociétés d\'État directeurs généraux liste {annee}',
            ],
            "collectivites_locales": [
                '"Côte d\'Ivoire" maires Abidjan Bouaké Yamoussoukro liste {annee}',
                '"Côte d\'Ivoire" présidents conseils régionaux composition',
            ],
        },
    },
    "ML": {
        "contexte": "junte",
        # Junte CNSP/CNT depuis août 2020 — partis et parlement suspendus
        "categories_inactives": ["senat", "partis_politiques", "conseil_economique"],
        "requetes_specifiques": {
            "gouvernement": [
                '"Mali" "gouvernement de transition" membres ministres {annee}',
                '"Mali" "CNSP" OR "CNT" membres junte composition {annee}',
                '"Mali" Assimi Goïta gouvernement transition liste',
            ],
            "parlement": [
                '"Mali" "Conseil National de Transition" CNT membres composition',
                '"Mali" organe législatif transition membres liste {annee}',
            ],
            "forces_armees": [
                '"Mali" "FAMa" "Forces Armées du Mali" commandement généraux {annee}',
                '"Mali" état-major armée direction militaire Goïta',
                '"Mali" chef état-major forces armées direction {annee}',
            ],
            "entreprises_etat": [
                '"Mali" "SOMAGEP" OR "EDM" OR "Air Mali" directeur général {annee}',
                '"Mali" sociétés d\'État entreprises publiques directeurs transition',
            ],
        },
    },
    "BF": {
        "contexte": "junte",
        # Junte MPSR depuis janvier 2022, capitaine Ibrahim Traoré depuis oct 2022
        "categories_inactives": ["senat", "partis_politiques", "conseil_economique"],
        "requetes_specifiques": {
            "gouvernement": [
                '"Burkina Faso" "gouvernement de transition" membres ministres {annee}',
                '"Burkina Faso" Ibrahim Traoré gouvernement transition liste',
                '"Burkina Faso" "MPSR" membres junte composition {annee}',
            ],
            "parlement": [
                '"Burkina Faso" "Assemblée Législative de Transition" ALT membres',
                '"Burkina Faso" organe législatif transition membres composition',
            ],
            "forces_armees": [
                '"Burkina Faso" "Forces Armées" FABS commandement généraux {annee}',
                '"Burkina Faso" état-major armée direction Ibrahim Traoré',
                '"Burkina Faso" VDP "Volontaires pour la Défense de la Patrie" direction',
            ],
            "entreprises_etat": [
                '"Burkina Faso" "SONABEL" OR "ONEA" OR "Air Burkina" directeur général {annee}',
                '"Burkina Faso" entreprises publiques direction transition {annee}',
            ],
        },
    },
    "NE": {
        "contexte": "junte",
        # Junte CNSP depuis juillet 2023, Général Tiani
        "categories_inactives": ["senat", "partis_politiques", "conseil_economique"],
        "requetes_specifiques": {
            "gouvernement": [
                '"Niger" "gouvernement de transition" membres ministres {annee}',
                '"Niger" "CNSP" Tiani gouvernement transition liste',
                '"Niger" Ali Mahamane Lamine Zeine premier ministre transition',
            ],
            "parlement": [
                '"Niger" "Conseil National pour la Sauvegarde de la Patrie" CNSP membres',
                '"Niger" organe législatif transition membres composition {annee}',
            ],
            "forces_armees": [
                '"Niger" "Forces Armées du Niger" FAN commandement généraux {annee}',
                '"Niger" Tiani état-major armée direction militaire',
                '"Niger" chef état-major forces armées {annee}',
            ],
            "entreprises_etat": [
                '"Niger" "NIGELEC" OR "SEEN" OR "SONIDEP" directeur général {annee}',
                '"Niger" entreprises publiques état direction transition',
            ],
        },
    },
    "TG": {
        "contexte": "democratie",
        "categories_inactives": [],
        "requetes_specifiques": {
            "senat": [
                '"Togo" "Sénat" membres sénateurs composition liste {annee}',
                '"Togo" chambre haute sénat Gnassingbé membres {annee}',
            ],
            "gouvernement": [
                '"Togo" "composition du gouvernement" ministres liste {annee}',
                '"Togo" "Conseil des Ministres" membres premier ministre {annee}',
                'republicoftogo.com gouvernement composition membres',
            ],
            "entreprises_etat": [
                '"Togo" "CEET" OR "TDE" OR "Air Togo" OR "Port Lomé" directeur général {annee}',
                '"Togo" entreprises publiques parapubliques directeurs généraux liste',
            ],
            "collectivites_locales": [
                '"Togo" maires Lomé Kpalimé Sokodé Kara liste {annee}',
                '"Togo" présidents conseils régionaux collectivités liste',
            ],
        },
    },
    "BJ": {
        "contexte": "democratie",
        "categories_inactives": ["senat"],  # Parlement unicaméral
        "requetes_specifiques": {
            "gouvernement": [
                '"Bénin" "composition du gouvernement" ministres liste {annee}',
                '"Bénin" "Conseil des Ministres" membres premier ministre {annee}',
                'gouv.bj gouvernement composition membres liste',
            ],
            "entreprises_etat": [
                '"Bénin" "SBEE" OR "SONEB" OR "Port Autonome Cotonou" OR "Bénin Télécoms" directeur général',
                '"Bénin" sociétés d\'État entreprises publiques directeurs généraux liste {annee}',
                '"Bénin" SONACOP OR SONAPRA OR BENIN-CONTROL directeur PDG',
            ],
            "collectivites_locales": [
                '"Bénin" maires Cotonou Porto-Novo Parakou Abomey liste {annee}',
                '"Bénin" "départements" préfets liste officielle {annee}',
            ],
            "securite_police": [
                '"Bénin" "directeur général police républicaine" direction nationale',
                '"Bénin" "Forces Armées du Bénin" FAB état-major direction {annee}',
            ],
        },
    },
    "GW": {
        "contexte": "crise",
        "categories_inactives": ["senat", "conseil_economique"],
        "requetes_specifiques": {
            "gouvernement": [
                '"Guinée-Bissau" gouvernement membres ministres liste {annee}',
                '"Guinée-Bissau" "premier ministre" gouvernement composition',
            ],
            "parlement": [
                '"Guinée-Bissau" "Assemblée Nationale Populaire" ANP membres {annee}',
                '"Guinée-Bissau" parlement membres composition liste',
            ],
            "forces_armees": [
                '"Guinée-Bissau" forces armées FARP commandement direction {annee}',
                '"Guinée-Bissau" état-major armée généraux direction',
            ],
            "entreprises_etat": [
                '"Guinée-Bissau" entreprises publiques direction directeurs {annee}',
                '"Guinée-Bissau" EAGB OR "électricité eau" directeur général',
            ],
        },
    },
    "GN": {
        "contexte": "junte",
        # Junte CNRD depuis septembre 2021, Colonel Mamadi Doumbouya
        "categories_inactives": ["senat", "partis_politiques", "conseil_economique"],
        "requetes_specifiques": {
            "gouvernement": [
                '"Guinée" "gouvernement de transition" membres ministres {annee}',
                '"Guinée" Doumbouya "CNRD" gouvernement transition liste',
                '"Guinée" Conakry gouvernement transition composition {annee}',
            ],
            "parlement": [
                '"Guinée" "Conseil National de Transition" CNT membres composition {annee}',
                '"Guinée" organe législatif transition Doumbouya membres',
            ],
            "forces_armees": [
                '"Guinée" "Forces Armées de Guinée" FAG commandement Doumbouya {annee}',
                '"Guinée" CNRD état-major armée direction militaire',
                '"Guinée" Mamadi Doumbouya forces armées commandement',
            ],
            "entreprises_etat": [
                '"Guinée" "CBG" OR "SMB" OR "EDG" OR "Air Guinée" directeur général {annee}',
                '"Guinée" mines bauxite entreprises nationales direction Conakry',
            ],
            "securite_police": [
                '"Guinée" "direction générale police" OR "gendarmerie nationale" direction {annee}',
                '"Guinée" forces sécurité intérieure commandement CNRD',
            ],
        },
    },
}


# ── Référentiel ──────────────────────────────────────────────────────────────────

def _charger_referentiel() -> dict:
    try:
        with open(REF_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {e["code_iso"]: e for e in data}
    except Exception:
        return {}


# ── Nettoyage HTML ───────────────────────────────────────────────────────────────

def _nettoyer_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "meta", "link", "noscript", "iframe"]):
        tag.decompose()
    texte = soup.get_text(separator="\n", strip=True)
    # Supprimer les lignes vides consécutives
    lignes = [l for l in texte.splitlines() if l.strip()]
    return "\n".join(lignes)[:8000]


# ── Scraping avec fallback ───────────────────────────────────────────────────────

def _scraper_avec_fallback(url: str, code_iso: str, categorie: str,
                           pays_nom: str = "") -> tuple[Optional[str], str]:
    """
    Retourne (contenu_texte, url_reelle_utilisee).
    Si échec total → (None, url_originale).
    """
    domaine = url.split("/")[2] if url.startswith("http") else url
    annee   = datetime.now().year

    _MOTS_MAINTENANCE = [
        "maintenance", "reviendrons bientôt", "we'll be back", "coming soon",
        "site en cours de maintenance", "temporarily unavailable", "under construction",
        "en cours de mise à jour", "indisponible", "503 service", "502 bad gateway",
        "be back soon", "down for maintenance", "site temporairement",
    ]

    def _est_page_maintenance(texte: str) -> bool:
        t = texte.lower()
        return any(m in t for m in _MOTS_MAINTENANCE) and len(texte) < 5000

    _headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    # ── Tentative 1 : requests direct sur l'URL hardcodée ──
    try:
        r = requests.get(url, headers=_headers, timeout=15, verify=False)
        if r.status_code == 200 and len(r.content) > 500:
            # Forcer UTF-8 — les sites africains servent souvent UTF-8
            # mais requests détecte Latin-1 par défaut → mojibake
            try:
                html_text = r.content.decode("utf-8")
            except UnicodeDecodeError:
                html_text = r.text
            if _est_page_maintenance(html_text):
                print(f"  ⚠️  Page maintenance détectée : {url[:60]}")
            else:
                print(f"  ✅ requests OK : {url[:60]}")
                return _nettoyer_html(html_text), url
        else:
            print(f"  ⚠️  requests HTTP {r.status_code} pour {url[:50]}")
    except Exception as e:
        print(f"  ⚠️  requests {url[:50]} : {str(e)[:70]}")

    # ── Tentative 2 : Serper (Google Search) — remplace Tavily ──
    _CATEG_FR = {
        "parlement":         "liste parlementaires deputés",
        "gouvernement":      "composition gouvernement ministres",
        "banque_centrale":   "direction gouverneur banque centrale",
        "ambassadeurs":      "ambassadeurs représentants diplomatiques",
        "presidence":        "président premier ministre chef état",
        "conseil_superieur": "composition gouvernement conseil ministres",
    }
    termes = _CATEG_FR.get(categorie, categorie.replace("_", " "))
    serper_key = os.getenv("serper_dev_aoi_key", "")
    if serper_key:
        print(f"  🔄 Serper → {termes} {pays_nom} {annee}...")
        time.sleep(1)
        try:
            q = f'{pays_nom} {termes} {annee}'
            r_s = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                json={"q": q, "hl": "fr", "num": 5},
                timeout=10,
            )
            if r_s.status_code == 200:
                items = r_s.json().get("organic", [])
                if items:
                    for item in items[:5]:
                        u_found = item.get("link", "")
                        if not u_found:
                            continue
                        if any(d in u_found for d in _DOMAINES_BLOQUES):
                            continue
                        try:
                            r2 = requests.get(u_found, headers=_headers, timeout=12, verify=False)
                            if r2.status_code == 200 and len(r2.content) > 500:
                                try:
                                    html2 = r2.content.decode("utf-8")
                                except UnicodeDecodeError:
                                    html2 = r2.text
                                if _est_page_maintenance(html2):
                                    continue
                                texte_page = _nettoyer_html(html2)
                                if len(texte_page) > 800:
                                    print(f"  ✅ Serper → {u_found[:60]}")
                                    return texte_page, u_found
                        except Exception:
                            pass
                    # Fallback : snippets (URL source = premier résultat Serper)
                    snippets = "\n\n".join(
                        f"{it.get('title','')}\n{it.get('snippet','')}"
                        for it in items
                    )
                    if len(snippets) > 200:
                        url_serper = items[0].get("link", url)
                        print(f"  ✅ Serper snippets ({len(snippets)} chars)")
                        return snippets[:6000], url_serper  # ← URL réelle
                else:
                    print(f"  ⚠️  Serper 0 résultat pour {q[:50]}")
            else:
                print(f"  ⚠️  Serper HTTP {r_s.status_code}")
        except Exception as e:
            print(f"  ⚠️  Serper {pays_nom}/{categorie} : {str(e)[:80]}")
    else:
        print(f"  ⚠️  Serper : clé manquante")

    # ── Tentative 3 : homepage du domaine officiel ──
    try:
        homepage = f"https://{domaine}/"
        r2 = requests.get(homepage, headers=_headers, timeout=12, verify=False)
        if r2.status_code == 200 and len(r2.text) > 500 and not _est_page_maintenance(r2.text):
            print(f"  ✅ Homepage OK : {homepage}")
            return _nettoyer_html(r2.text), homepage
    except Exception as e:
        print(f"  ⚠️  Homepage {domaine} : {str(e)[:60]}")

    # ── Tentative 4 : Scrapling JS (gère les sites avec JavaScript) ──
    try:
        from scrapling.fetchers import StealthyFetcher
        fetcher  = StealthyFetcher.configure(huge_tree=True)
        page     = fetcher.fetch(url)
        html_str = str(page.html_content) if hasattr(page, "html_content") else ""
        if html_str and len(html_str) > 500:
            print(f"  ✅ Scrapling OK : {url[:60]}")
            return _nettoyer_html(html_str), url  # ← URL réelle
    except Exception as e:
        print(f"  ⚠️  Scrapling {url[:50]} : {str(e)[:60]}")

    # ── Échec total ──
    msg = f"[{datetime.now():%H:%M}] INACCESSIBLE {code_iso}/{categorie} : {domaine}"
    print(f"  ❌ {msg}")
    _status["errors"].append(msg)
    _update_status()
    return None, url


# ── Extraction LLM → liste structurée ────────────────────────────────────────────

_PROMPT_EXTRACTION = """Tu es un expert en conformité AML/PEP (Personnes Politiquement Exposées).
Voici le contenu d'une page officielle ({categorie}) du pays {pays_nom} ({code_iso}).

MISSION : Extrais UNIQUEMENT les noms de PERSONNES PHYSIQUES (êtres humains réels) qui occupent
ou ont occupé une fonction publique au {pays_nom}.

Retourne UNIQUEMENT un JSON valide, sans texte avant ou après :
[
  {{
    "prenom": "...",
    "nom": "...",
    "fonction": "...",
    "statut_mandat": "actif",
    "date_nomination": "",
    "date_sortie": ""
  }},
  ...
]

RÈGLES ABSOLUES — À RESPECTER IMPÉRATIVEMENT :

✅ INCLURE seulement :
- Ministres, secrétaires d'État, vice-ministres (actuels ET anciens si mentionnés)
- Parlementaires, sénateurs, députés
- Présidents, premiers ministres, chefs d'État
- Directeurs généraux, gouverneurs, ambassadeurs, hauts commissaires
- Magistrats, chefs d'état-major

❌ NE JAMAIS INCLURE (même si mentionnés dans le texte) :
- Noms de régions, provinces, villes (ex: "Région Casablanca", "Kolda", "Dakar")
- Noms d'institutions ou organismes (ex: "Bank Al-Maghrib", "CNIE", "Barreau du Sénégal")
- Associations, syndicats, partis, ONGs
- Services ou directions génériques (ex: "Cabinet militaire", "Autres administrations")
- Personnalités étrangères qui ne sont PAS du {pays_nom}
- Conférences religieuses, églises, mosquées

CHAMPS :
- "prenom" / "nom" = VRAIS PRÉNOMS ET NOMS D'UNE PERSONNE HUMAINE
- "fonction" = titre exact du poste. Si inconnu → ""
- "statut_mandat" = "actif" si en poste actuellement, "ex_pep" si ancien/ancienne, "actif" par défaut
- "date_nomination" = date de prise de poste au format AAAA-MM-JJ si trouvée, sinon ""
- "date_sortie" = date de fin de mandat au format AAAA-MM-JJ si la personne est ex_pep, sinon ""
- Retourne [] si aucune personne éligible trouvée

Contenu de la page ({pays_nom}) :
{contenu}

JSON :"""


def _extraire_premier_json_array(texte: str) -> list:
    """
    Extrait le premier tableau JSON complet même si le LLM a ajouté du texte autour.
    Gère aussi les JSON tronqués (token limit) en sauvegardant les objets complets.
    """
    start = texte.find('[')
    if start == -1:
        return []
    depth, in_str, escape = 0, False, False
    for i, c in enumerate(texte[start:], start):
        if escape:
            escape = False
            continue
        if c == '\\' and in_str:
            escape = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == '[':
            depth += 1
        elif c == ']':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(texte[start:i + 1])
                except json.JSONDecodeError:
                    return []
    # JSON tronqué — récupérer les objets complets avant la coupure
    tronque = texte[start:]
    last_obj = tronque.rfind('},')
    if last_obj > 0:
        candidate = tronque[:last_obj + 1] + ']'
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    return []


_DOMAINES_BLOQUES = {
    "instagram.com", "facebook.com", "twitter.com", "x.com",
    "linkedin.com", "tiktok.com", "youtube.com", "t.me",
}


def _normaliser_guillemets(texte: str) -> str:
    """Remplace les guillemets courbes (U+201C/D, U+2018/9) par des droits."""
    return (texte
            .replace('“', '"').replace('”', '"')
            .replace('‘', "'").replace('’', "'"))


def _llm_extraire_liste_pep(contenu: str, code_iso: str,
                             categorie: str, pays_nom: str) -> list[dict]:
    if not contenu or len(contenu.strip()) < 50:
        return []
    prompt = _PROMPT_EXTRACTION.format(
        categorie=categorie, pays_nom=pays_nom,
        code_iso=code_iso, contenu=contenu[:6000]
    )
    try:
        resp  = llm.invoke(prompt)
        texte = resp.content.strip()
        # Nettoyer backticks markdown + guillemets courbes → droits
        texte = texte.replace("```json", "").replace("```", "").strip()
        texte = _normaliser_guillemets(texte)
        data  = _extraire_premier_json_array(texte)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"  ⚠️  LLM extraction {code_iso}/{categorie} : {e}")
        return []


# ── Base de données ──────────────────────────────────────────────────────────────

import unicodedata as _ud

def _norm(s: str) -> str:
    """Supprime les accents et met en minuscule — 'Région' → 'region'."""
    return _ud.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()

# Mots qui débutent ou composent un nom qui N'EST PAS une personne
_MOTS_NON_PERSONNES = {
    # Organisations de la société civile
    "association", "syndicat", "federation", "confederation", "union",
    "parti", "coalition", "mouvement", "rassemblement", "collectif",
    "ong", "ngo", "fondation", "comite", "commission",
    # Institutions / services
    "bank", "banque", "bceao", "bkam", "bct", "bcrg", "giaba", "uemoa", "ecowas",
    "gouvernement", "parlement", "senat", "assemblee",
    "presidence", "primature", "ministere", "direction", "service",
    "centif", "ctrf", "utrf", "ammc", "acaps", "cndp", "cnie",
    "onu", "ua", "ue", "congress", "chambre",
    "cabinet", "secretariat", "administration", "programme", "projet",
    "agence", "office", "bureau", "centre", "conseil",
    # Institutions religieuses / juridiques
    "eglise", "mosquee", "barreau", "tribunal", "cour", "juridiction",
    "diocese", "conference episcopale", "communaute",
    # Régions / lieux
    "region", "province", "wilaya", "departement", "commune", "prefecture",
    "ville", "territoire", "zone", "district", "arrondissement",
    "kolda", "thies", "dakar", "ziguinchor", "louga",  # villes SN
    # Termes génériques
    "autres", "divers", "inconnu", "non precise", "organisme",
    # Arabes — régions et institutions
    "جهة", "ولاية", "إقليم", "مجلس", "وزارة", "إدارة",
}

def _est_personne_valide(p: dict) -> bool:
    """
    Rejette tout ce qui n'est pas un être humain :
    régions, institutions, organismes, abréviations, noms trop génériques.
    Utilise la normalisation des accents pour les comparaisons.
    """
    nom    = (p.get("nom") or "").strip()
    prenom = (p.get("prenom") or "").strip()

    if not nom or len(nom) < 3:
        return False

    # Normalisation sans accents pour comparer
    nom_n    = _norm(nom)
    prenom_n = _norm(prenom)
    texte_n  = (nom_n + " " + prenom_n).strip()

    # 1. Le premier mot du nom est-il un mot de non-personne ?
    premier_mot = nom_n.split()[0] if nom_n.split() else ""
    if premier_mot in _MOTS_NON_PERSONNES:
        return False

    # 2. Le nom contient-il un mot de non-personne ?
    mots_nom = set(nom_n.split())
    if mots_nom & _MOTS_NON_PERSONNES:
        return False

    # 3. Termes arabes de régions/institutions dans le nom complet
    for m_arabe in ["جهة", "ولاية", "إقليم", "مجلس", "وزارة"]:
        if m_arabe in nom or m_arabe in prenom:
            return False

    # 4. Sigle/abréviation sans voyelles (CTRF, BCM, GW…) — les noms africains ont toujours des voyelles (DIOP, FALL, SONKO)
    _VOYELLES = frozenset("AEIOUÉÈÊËÀÂÙÛÎÏÔŒ")
    if nom.isupper() and len(nom) <= 6 and not any(c in _VOYELLES for c in nom):
        return False

    # 5. Phrase entière sans espace (ex: "AutresAdministrations")
    if " " not in nom and len(nom) > 25:
        return False

    # 6. Fonction mentionne un pays étranger → personne étrangère en visite
    fonction_n = _norm(p.get("fonction") or "")
    mots_pays_etrangers = [
        "americain", "americaine", "etats-unis", "usa", "congress", "senate",
        "gambien", "gambienne", "gambie",
        "emirat", "saoudien", "qatari", "israelien",
        "francais", "francaise", "belge", "europeen",
        "chinois", "japonais", "russe",
    ]
    if any(m in fonction_n for m in mots_pays_etrangers):
        return False

    return True


def _deja_en_base(nom_complete: str, code_iso: str) -> bool:
    row = query_one(
        "SELECT id FROM pep WHERE nom_complete = %s AND code_iso = %s",
        (nom_complete.strip(), code_iso)
    )
    return row is not None


_MOIS_FR_TO_NUM = {
    "janvier":"01","février":"02","fevrier":"02","mars":"03","avril":"04",
    "mai":"05","juin":"06","juillet":"07","août":"08","aout":"08",
    "septembre":"09","octobre":"10","novembre":"11","décembre":"12","decembre":"12",
}

def _normaliser_date(date_str: str) -> Optional[str]:
    """
    Convertit "11 juin 2026" → "2026-06-11", "11/06/2026" → "2026-06-11".
    Rejette les dates de l'année en cours si elles ressemblent à des dates d'articles.
    Retourne None si non convertible ou si c'est une date récente d'article.
    """
    if not date_str:
        return None
    s = date_str.strip().lower()
    annee_courante = str(datetime.now().year)

    # Format texte : "11 juin 2026"
    for mois_fr, num in _MOIS_FR_TO_NUM.items():
        if mois_fr in s:
            m = re.search(r'(\d{1,2})\s+' + re.escape(mois_fr) + r'\s+(\d{4})', s)
            if m:
                j, a = m.group(1).zfill(2), m.group(2)
                # Rejeter si c'est cette année (probablement une date d'article, pas de nomination)
                if a == annee_courante:
                    return None
                return f"{a}-{num}-{j}"
            break

    # Format JJ/MM/AAAA ou JJ-MM-AAAA
    m = re.match(r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})', s)
    if m:
        j, mo, a = m.group(1).zfill(2), m.group(2).zfill(2), m.group(3)
        if a == annee_courante:
            return None
        return f"{a}-{mo}-{j}"

    # Format AAAA-MM-JJ
    m = re.match(r'(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})', s)
    if m:
        a, mo, j = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        if a == annee_courante:
            return None
        return f"{a}-{mo}-{j}"

    return None


def _inserer_direct(p: dict, code_iso: str, pays_nom: str, source_url: str) -> bool:
    prenom = (p.get("prenom") or "").strip()
    nom    = (p.get("nom")    or "").strip()
    if not nom:
        return False
    nom_complete = f"{prenom} {nom}".strip() if prenom else nom

    if _deja_en_base(nom_complete, code_iso):
        return False

    fonction       = (p.get("fonction") or "").strip()[:200] or None
    date_nomin     = _normaliser_date(p.get("date_nomination") or "")
    date_sortie    = _normaliser_date(p.get("date_sortie") or "")
    statut_mandat  = p.get("statut_mandat") or "actif"
    if statut_mandat not in ("actif", "ex_pep"):
        statut_mandat = "actif"

    try:
        execute(
            """
            INSERT INTO pep (
                nom, prenom, nom_complete,
                nationalite, code_iso, pays_nom,
                fonction_actuelle, statut_mandat,
                date_nomination, date_sortie_fonction_public,
                source_url,
                date_scraping, date_creation, date_modification,
                annee_verification
            ) VALUES (
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s,
                %s,
                NOW(), NOW(), NOW(),
                %s
            )
            ON CONFLICT (nom_complete, code_iso) DO UPDATE SET
                fonction_actuelle           = EXCLUDED.fonction_actuelle,
                statut_mandat               = EXCLUDED.statut_mandat,
                date_nomination             = COALESCE(EXCLUDED.date_nomination, pep.date_nomination),
                date_sortie_fonction_public = COALESCE(EXCLUDED.date_sortie_fonction_public, pep.date_sortie_fonction_public),
                source_url                  = EXCLUDED.source_url,
                date_modification           = NOW()
            """,
            (
                nom, prenom, nom_complete,
                pays_nom, code_iso, pays_nom,
                fonction, statut_mandat,
                date_nomin, date_sortie,
                source_url,
                datetime.now().year,
            ),
        )
        # Audit obligatoire — traçabilité compliance pour tout INSERT
        try:
            execute("""
                INSERT INTO verification_audit (
                    ts, nom_complet, code_iso,
                    opensanctions,
                    llm_modele, llm_prompt, llm_reponse,
                    est_pep, motif,
                    duree_ms, tavily_appels, os_appels
                ) VALUES (
                    NOW(), %s, %s,
                    %s::jsonb,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s
                )
            """, (
                nom_complete, code_iso,
                json.dumps({"confirmed": False, "source": source_url}),
                "track_b_official_source",
                "", "",
                True,
                f"Scraping direct du site officiel : {source_url[:300]}",
                0, 0, 0,
            ))
        except Exception as _ae:
            print(f"  [Audit] Erreur log Track B {nom_complete} : {_ae}")
        return True
    except Exception as e:
        print(f"  ⚠️  INSERT {nom_complete} : {e}")
        _status["errors"].append(f"INSERT {code_iso} {nom_complete}: {e}")
        _update_status()
        return False


# ── Découverte dynamique Serper : trouve les pages de listing officielles ─────────

_REQUETES_DECOUVERTE: dict[str, list[str]] = {
    # ── Exécutif ────────────────────────────────────────────────────────────────
    "gouvernement": [
        '"{pays}" "composition du gouvernement" liste ministres {annee}',
        '"{pays}" "membres du gouvernement" premier ministre ministre',
        '"{pays}" "conseil des ministres" liste officielle {annee}',
        '"{pays}" gouvernement ministres secrétaires état liste',
        'site officiel gouvernement {pays} ministres {annee}',
    ],
    "presidence": [
        '"{pays}" "cabinet présidentiel" membres composition',
        '"{pays}" "présidence de la République" site officiel',
        '"{pays}" premier ministre gouvernement officiel {annee}',
        'presidence {pays} site:presidence OR site:gouv OR site:gov',
    ],
    # ── Législatif ──────────────────────────────────────────────────────────────
    "parlement": [
        '"{pays}" "assemblée nationale" liste membres députés {annee}',
        '"{pays}" parlement composition membres liste officielle',
        '"{pays}" "chambre des représentants" liste membres',
        '"{pays}" "conseil national" membres composition',
        'assemblee nationale {pays} liste deputes site:assemblee OR site:parlement',
    ],
    "senat": [
        '"{pays}" "sénat" liste sénateurs membres composition {annee}',
        '"{pays}" "conseil de la nation" membres liste',
        '"{pays}" chambre haute parlement sénateurs composition',
    ],
    # ── Judiciaire ──────────────────────────────────────────────────────────────
    "magistrature": [
        '"{pays}" "cour suprême" membres composition liste',
        '"{pays}" "conseil d\'état" membres composition',
        '"{pays}" magistrats hauts responsables judiciaires liste',
        'cour supreme {pays} membres composition site:gouv OR site:gov',
    ],
    "conseil_constitutionnel": [
        '"{pays}" "conseil constitutionnel" membres liste officielle',
        '"{pays}" "cour constitutionnelle" membres composition {annee}',
        'conseil constitutionnel {pays} membres site:gouv OR site:gov',
    ],
    # ── Sécurité / Défense ──────────────────────────────────────────────────────
    "forces_armees": [
        '"{pays}" "chef d\'état-major" armée direction forces armées',
        '"{pays}" "ministre de la défense" officiers généraux état-major',
        '"{pays}" armée nationale haute hiérarchie militaire généraux',
    ],
    "securite_police": [
        '"{pays}" "directeur général police nationale" OR "DG police"',
        '"{pays}" "directeur général gendarmerie" OR "commandant gendarmerie"',
        '"{pays}" "directeur général" douanes OR sécurité intérieure OR renseignement',
        '"{pays}" police gendarmerie direction nationale hauts responsables',
    ],
    # ── Finances publiques ──────────────────────────────────────────────────────
    "banque_centrale": [
        '"{pays}" "banque centrale" gouverneur direction conseil administration',
        '"{pays}" "banque centrale" organes direction membres',
        'banque centrale {pays} direction generale gouverneur',
    ],
    "douanes_impots": [
        '"{pays}" "directeur général des impôts" OR "DGI" direction',
        '"{pays}" "directeur général des douanes" OR "DGD" direction',
        '"{pays}" "trésor public" directeur direction nationale',
        '"{pays}" administration fiscale douanière hauts responsables',
    ],
    # ── Entreprises d\'État (SOEs) ────────────────────────────────────────────────
    "entreprises_etat": [
        '"{pays}" "directeur général" entreprise publique OR société nationale OR paraétatique {annee}',
        '"{pays}" "directeur général" port OR aéroport OR eau OR électricité OR télécom société nationale',
        '"{pays}" entreprises publiques conseil administration directeurs généraux liste',
        '"{pays}" société nationale directeur général PDG liste officielle',
    ],
    # ── Institutions régionales ─────────────────────────────────────────────────
    "institutions_regionales": [
        '"{pays}" représentant commissaire UEMOA OR CEDEAO OR "Union Africaine"',
        '"{pays}" délégué représentant institutions sous-régionales Afrique Ouest',
        '"{pays}" ambassadeur représentant permanent Nations Unies UA CEDEAO',
    ],
    # ── Collectivités locales ────────────────────────────────────────────────────
    "collectivites_locales": [
        '"{pays}" "maires" grandes villes liste officielle {annee}',
        '"{pays}" "président conseil régional" OR "gouverneur région" liste',
        '"{pays}" collectivités locales élus maires préfets liste',
        'maires villes {pays} liste composition {annee}',
    ],
    # ── Partis politiques ────────────────────────────────────────────────────────
    "partis_politiques": [
        '"{pays}" "secrétaire général" OR "président" parti politique liste {annee}',
        '"{pays}" partis politiques dirigeants responsables liste officielle',
        '"{pays}" formation politique leadership direction nationale',
    ],
    # ── Diplomatie ───────────────────────────────────────────────────────────────
    "ambassadeurs": [
        '"{pays}" liste ambassadeurs représentants diplomatiques {annee}',
        '"{pays}" ministère affaires étrangères ambassadeurs accrédités',
        '"{pays}" corps diplomatique ambassadeurs résidents liste',
    ],
    # ── Conseil économique et social ─────────────────────────────────────────────
    "conseil_economique": [
        '"{pays}" "conseil économique et social" membres composition liste',
        '"{pays}" "conseil économique social environnemental" membres',
        'CESE OR CES {pays} membres composition direction liste',
    ],
}

_CACHE_URLS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "discovered_urls_cache.json")

def _charger_cache_urls() -> dict:
    try:
        with open(_CACHE_URLS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _sauvegarder_cache_urls(cache: dict) -> None:
    try:
        with open(_CACHE_URLS_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _decouvrir_urls_listing_serper(code_iso: str, pays_nom: str) -> dict[str, list[str]]:
    """
    Pour chaque catégorie, cherche sur Serper les pages de listing officielles.
    - Charge d'abord le cache (URLs déjà découvertes et fonctionnelles)
    - Interroge Serper pour les catégories non encore cachées
    - Vérifie que chaque URL répond (HTTP 200) avant de la garder
    - Sauvegarde les nouvelles URLs fonctionnelles dans le cache
    Retourne : { "parlement": ["https://assemblee-nationale.bj/..."], ... }
    """
    serper_key = os.getenv("serper_dev_aoi_key", "")
    from search_tools import est_source_officielle

    annee  = datetime.now().year
    cache  = _charger_cache_urls()
    cache_pays = cache.get(code_iso, {})
    resultats: dict[str, list[str]] = {}
    cache_modifie = False
    _headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
                "Accept-Language": "fr-FR,fr;q=0.9"}

    def _url_accessible(url: str) -> bool:
        try:
            r = requests.get(url, headers=_headers, timeout=8, verify=False)
            return r.status_code == 200 and len(r.content) > 300
        except Exception:
            return False

    config_pays   = _CONFIG_PAYS.get(code_iso, {})
    inactives     = set(config_pays.get("categories_inactives", []))
    req_specifiques = config_pays.get("requetes_specifiques", {})
    contexte      = config_pays.get("contexte", "democratie")
    if contexte == "junte":
        print(f"  [Config] {code_iso} — contexte JUNTE : partis/parlement classique ignorés")

    for categorie, requetes_defaut in _REQUETES_DECOUVERTE.items():
        # ── Ignorer les catégories inactives pour ce pays ──
        if categorie in inactives:
            continue

        # Utiliser requêtes spécifiques si disponibles, sinon défaut
        requetes = req_specifiques.get(categorie, requetes_defaut)

        # ── 1. Vérifier le cache ──
        urls_cache = [u for u in cache_pays.get(categorie, []) if _url_accessible(u)]
        if urls_cache:
            resultats[categorie] = urls_cache
            print(f"  [Cache] {code_iso}/{categorie} : {len(urls_cache)} URL(s) en cache ✅")
            continue

        if not serper_key:
            continue

        # ── 2. Découverte Serper ──
        urls_trouvees: list[str] = []
        for q_template in requetes:
            q = q_template.format(pays=pays_nom, annee=annee)
            try:
                r = requests.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                    json={"q": q, "hl": "fr", "num": 10},
                    timeout=10,
                )
                if r.status_code != 200:
                    continue
                for item in r.json().get("organic", []):
                    url = item.get("link", "")
                    if url and est_source_officielle(url) and url not in urls_trouvees:
                        # Vérifier accessibilité avant de garder
                        if _url_accessible(url):
                            urls_trouvees.append(url)
                if urls_trouvees:
                    break  # première requête productive suffit
            except Exception:
                continue
            time.sleep(0.5)

        if urls_trouvees:
            resultats[categorie] = urls_trouvees[:5]
            # Sauvegarder dans le cache pour réutilisation future
            if code_iso not in cache:
                cache[code_iso] = {}
            cache[code_iso][categorie] = urls_trouvees[:5]
            cache_modifie = True
            print(f"  [Découverte Serper] {code_iso}/{categorie} : {len(urls_trouvees)} URL(s) → {urls_trouvees[0][:70]}")

    if cache_modifie:
        _sauvegarder_cache_urls(cache)
        print(f"  [Cache] URLs sauvegardées dans discovered_urls_cache.json")

    return resultats


# ── TRACK B : collecte depuis sites officiels ────────────────────────────────────

def collecter_track_b(code_iso: str, pays_nom: str) -> list[dict]:
    """
    Scrape les sites officiels et retourne un lot brut de PEP candidats.
    N'insère RIEN en base — le pipeline B+A s'en charge après vérification.
    Chaque dict contient les clés LLM + '_source_url' + '_categorie'.
    """
    sources_fixe = SOURCES_TRACK_B.get(code_iso, {})
    lot: list[dict] = []

    # ── Étape 0 : découverte Serper — pages de listing officielles dynamiques ──
    print(f"  [Track B] Découverte Serper — pages listing officielles {pays_nom}...")
    urls_serper = _decouvrir_urls_listing_serper(code_iso, pays_nom)

    # Fusionner : hardcodé + Serper (Serper complète les catégories absentes)
    sources_finales: dict[str, list[str]] = {}
    for cat, url_fixe in sources_fixe.items():
        sources_finales[cat] = [url_fixe] + [u for u in urls_serper.get(cat, []) if u != url_fixe]
    for cat, urls_s in urls_serper.items():
        if cat not in sources_finales:
            sources_finales[cat] = urls_s

    # ── Étape 1 : scraping de chaque source ──
    for categorie, urls in sources_finales.items():
        for url in urls:
            print(f"\n  [Track B] {code_iso}/{categorie} → {url[:60]}")
            _update_status(track="B", country=code_iso, category=categorie, inserted_last=0)

            contenu, url_reelle = _scraper_avec_fallback(url, code_iso, categorie, pays_nom)
            if not contenu:
                continue

            personnes = _llm_extraire_liste_pep(contenu, code_iso, categorie, pays_nom)
            personnes_valides = [p for p in personnes if _est_personne_valide(p)]
            print(f"  → LLM : {len(personnes)} extraites, {len(personnes_valides)} valides")

            for p in personnes_valides:
                p["_source_url"] = url_reelle
                p["_categorie"]  = categorie
                lot.append(p)

            time.sleep(2)
            if contenu:
                break  # URL suivante de la même catégorie seulement si échec

    # Dédoublonner par (nom_complet)
    vus: set[str] = set()
    lot_unique = []
    for p in lot:
        key = f"{p.get('prenom','')} {p.get('nom','')}".strip().lower()
        if key not in vus:
            vus.add(key)
            lot_unique.append(p)

    print(f"  → Track B {code_iso} : {len(lot_unique)} candidats PEP uniques à vérifier")
    return lot_unique


# ── Checkpoint ───────────────────────────────────────────────────────────────────

_CHECKPOINT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "verification_checkpoint.json")

def _charger_checkpoint() -> set[str]:
    try:
        with open(_CHECKPOINT_PATH, encoding="utf-8") as f:
            return set(json.load(f).get("verifies", []))
    except Exception:
        return set()

def _sauvegarder_checkpoint(verifies: set[str]) -> None:
    try:
        with open(_CHECKPOINT_PATH, "w", encoding="utf-8") as f:
            json.dump({"verifies": list(verifies),
                       "updated": datetime.now().isoformat()}, f, ensure_ascii=False)
    except Exception:
        pass


# ── Pipeline B+A : vérification par lot avant INSERT ─────────────────────────────

def pipeline_lot(lot: list[dict], code_iso: str, pays_nom: str,
                 checkpoint: set[str], throttle_s: int = 5,
                 max_verif: int = 0, _cpt: list = None) -> tuple[int, set[str]]:
    """
    Pour chaque PEP brut du lot (issu de Track B) :
      1. Vérifie via verifier_pep() (Track A)
      2. Si confirmé PEP → verifier_pep() a déjà inséré en base
         → on UPDATE avec les données Track B (fonction officielle, source_url)
      3. Si non confirmé → ignoré
      4. Checkpoint sauvegardé après chaque PEP (reprise si crash)
    Throttle 30s entre appels pour respecter les quotas API.
    """
    from pep_agent import verifier_pep

    inserted = 0
    total    = len(lot)

    for idx, p in enumerate(lot, 1):
        if max_verif and _cpt is not None and _cpt[0] >= max_verif:
            print(f"  [QUOTA] Limite {max_verif} vérifications/jour atteinte — reprise demain via checkpoint")
            break

        prenom = (p.get("prenom") or "").strip()
        nom    = (p.get("nom")    or "").strip()
        if not nom:
            continue

        nom_complet   = f"{prenom} {nom}".strip() if prenom else nom
        chk_key       = f"{code_iso}:{nom_complet}"
        source_url_b  = p.get("_source_url", "")
        fonction_b    = (p.get("fonction") or "").strip()
        statut_b      = p.get("statut_mandat") or "actif"
        date_nomin_b  = _normaliser_date(p.get("date_nomination") or "")
        date_sortie_b = _normaliser_date(p.get("date_sortie") or "")

        if chk_key in checkpoint:
            print(f"  ⏭️  [{idx}/{total}] Déjà vérifié : {nom_complet}")
            continue

        print(f"\n  [{idx}/{total}] Vérification B+A : {nom_complet}")
        _update_status(track="B+A", country=code_iso,
                       category=f"vérif {idx}/{total}: {nom_complet[:35]}",
                       inserted_last=0)
        try:
            rapport = verifier_pep(prenom, nom)
            # Capturer le modèle LLM utilisé pour affichage live dans le dashboard
            try:
                import pep_agent as _pa
                _status["llm_actif"] = _pa._audit_llm.get("modele", "")
            except Exception:
                pass
            if _cpt is not None:
                _cpt[0] += 1
                _status["verif_total"] = _cpt[0]

            if rapport and getattr(rapport, "est_pep", False):
                # verifier_pep() a déjà inséré — on enrichit avec données Track B
                try:
                    execute("""
                        UPDATE pep SET
                            fonction_actuelle           = COALESCE(NULLIF(%s,''), fonction_actuelle),
                            statut_mandat               = COALESCE(NULLIF(%s,''), statut_mandat),
                            date_nomination             = COALESCE(%s, date_nomination),
                            date_sortie_fonction_public = COALESCE(%s, date_sortie_fonction_public),
                            source_url                  = COALESCE(NULLIF(%s,''), source_url),
                            date_modification           = NOW()
                        WHERE nom_complete = %s AND code_iso = %s
                    """, (fonction_b, statut_b, date_nomin_b, date_sortie_b,
                          source_url_b, nom_complet, code_iso))
                except Exception as e_up:
                    print(f"  ⚠️  UPDATE Track B data : {e_up}")

                inserted += 1
                _status["inserted_total"] += 1
                _status["inserted_last"]   = 1
                _update_status()
                print(f"  ✅ PEP confirmé + inséré : {nom_complet}")
            else:
                print(f"  ⬜ Non-PEP : {nom_complet}")

        except Exception as e:
            msg = f"pipeline_lot {code_iso} {nom_complet[:30]}: {e}"
            print(f"  ⚠️  {msg}")
            _status["errors"].append(msg)
            _update_status()

        checkpoint.add(chk_key)
        _sauvegarder_checkpoint(checkpoint)

        if idx < total:
            print(f"  ⏳ Throttle {throttle_s}s avant prochain PEP...")
            time.sleep(throttle_s)

    return inserted, checkpoint


# ── TRACK A : découverte via Wikidata + OpenSanctions + Tavily + Serper ─────────

def _wikidata_noms_pep(code_iso: str, pays_nom: str) -> list[str]:
    """
    Interroge Wikidata SPARQL — politiciens du pays (gratuit, sans quota).
    Retourne des noms "Prénom Nom" en français/anglais.
    """
    query = f"""
    SELECT DISTINCT ?personLabel WHERE {{
      ?country wdt:P297 "{code_iso}".
      ?position wdt:P17 ?country.
      ?person wdt:P31 wd:Q5;
              wdt:P39 ?position.
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,en". }}
    }}
    LIMIT 300
    """
    try:
        r = requests.get(
            "https://query.wikidata.org/sparql",
            params={"query": query, "format": "json"},
            headers={"User-Agent": "ScreenEdge-PEP-Collector/1.0 (screenedge-africa@compliance.com)"},
            timeout=30,
        )
        if r.status_code == 200:
            bindings = r.json().get("results", {}).get("bindings", [])
            noms = []
            for item in bindings:
                label = item.get("personLabel", {}).get("value", "")
                if " " in label.strip() and not label.startswith("Q"):
                    noms.append(label.strip())
            return noms
        print(f"  → Wikidata HTTP {r.status_code}")
        return []
    except Exception as e:
        print(f"  → Wikidata erreur : {e}")
        return []


def _dump_noms_pep(code_iso: str, pays_nom: str) -> list[str]:
    """
    Canal 0b — Dump local OpenSanctions (SQLite).
    Gratuit, illimité, <50ms. Disponible uniquement si le dump est présent (VPS).
    """
    try:
        import sqlite3, os as _os
        _db = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "opensanctions_pep.sqlite")
        if not _os.path.exists(_db):
            return []
        conn = sqlite3.connect(_db)
        c    = conn.cursor()
        rows = c.execute(
            "SELECT DISTINCT n.valeur FROM noms n "
            "JOIN entites e ON n.entity_id = e.id "
            "WHERE e.pays LIKE ?",
            (f"%{code_iso.lower()}%",),
        ).fetchall()
        conn.close()
        noms = []
        for row in rows:
            val = row[0].strip().title()
            if " " in val and len(val) > 4:
                noms.append(val)
        return noms
    except Exception as e:
        print(f"  → Dump local erreur : {e}")
        return []


def _decouvrir_noms_track_a(code_iso: str, pays_nom: str) -> list[str]:
    """
    Découvre des noms PEP via 5 canaux :
    0.  Wikidata SPARQL — base structurée, gratuit, sans quota
    0b. Dump local OpenSanctions — SQLite local, gratuit, illimité (VPS only)
    1.  OpenSanctions API — base mondiale PEP
    2.  Tavily — recherche "gouvernement {pays} {annee}"
    3.  Serper — "liste ministres {pays}"
    Retourne une liste dédupliquée de "Prénom Nom".
    """
    annee = datetime.now().year
    noms: set[str] = set()

    # ── Canal 0 : Wikidata SPARQL ─────────────────────────────────────────────
    print(f"  [Track A] Wikidata → {pays_nom}...")
    noms_wd = _wikidata_noms_pep(code_iso, pays_nom)
    noms.update(noms_wd)
    print(f"  → Wikidata : {len(noms_wd)} noms")

    # ── Canal 0b : Dump local OpenSanctions ───────────────────────────────────
    # Si dump présent → même source que l'API mais plus complet (762k vs 100 résultats)
    # → on saute Canal 1 pour économiser le quota API (réservé à la vérification)
    noms_dump = _dump_noms_pep(code_iso, pays_nom)
    if noms_dump:
        noms.update(noms_dump)
        print(f"  → Dump local OS : {len(noms_dump)} noms (Canal 1 API ignoré — quota préservé)")
    else:
        # ── Canal 1 : OpenSanctions API (fallback si dump absent) ─────────────
        print(f"  [Track A] OpenSanctions API → {pays_nom} (dump absent)...")
        try:
            import requests as req_os
            api_key = os.getenv("open_sanction_apikey", "")
            headers = {"Accept": "application/json"}
            if api_key:
                headers["Authorization"] = f"ApiKey {api_key}"
            params  = {"country": code_iso.lower(), "topics": "role.pep", "limit": 100}
            r = req_os.get("https://api.opensanctions.org/search/default",
                           params=params, headers=headers, timeout=15)
            if r.status_code == 200:
                resultats = r.json().get("results", [])
                for ent in resultats:
                    props = ent.get("properties", {})
                    noms_ent = props.get("name", [])
                    for n in noms_ent:
                        if " " in n.strip():
                            noms.add(n.strip())
                print(f"  → OpenSanctions : {len(noms)} noms")
            else:
                print(f"  → OpenSanctions HTTP {r.status_code}")
        except Exception as e:
            print(f"  → OpenSanctions erreur : {e}")
        time.sleep(30)  # throttle OpenSanctions (seulement si API appelée)

    # ── Canal 2 : Tavily ──────────────────────────────────────────────────────
    print(f"  [Track A] Tavily → gouvernement {pays_nom} {annee}...")
    try:
        from langchain_tavily import TavilySearch
        tavily = TavilySearch(max_results=10, search_depth="advanced")
        q = f"gouvernement {pays_nom} ministres liste {annee} OR {annee-1}"
        res = tavily.invoke({"query": q})
        if res:
            # Demander au LLM d'extraire les noms
            noms_tavily = _extraire_noms_depuis_texte(str(res), pays_nom)
            noms.update(noms_tavily)
            print(f"  → Tavily : {len(noms_tavily)} noms")
    except Exception as e:
        print(f"  → Tavily erreur : {e}")

    # ── Canal 3 : Serper ──────────────────────────────────────────────────────
    serper_key = os.getenv("serper_dev_aoi_key", "")
    if serper_key:
        print(f"  [Track A] Serper → liste ministres {pays_nom}...")
        try:
            import requests as req_s
            r = req_s.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                json={"q": f"liste ministres {pays_nom} {annee}", "hl": "fr", "num": 10},
                timeout=10,
            )
            if r.status_code == 200:
                items = r.json().get("organic", [])
                texte = "\n".join(
                    f"{it.get('title','')} {it.get('snippet','')}" for it in items
                )
                noms_serper = _extraire_noms_depuis_texte(texte, pays_nom)
                noms.update(noms_serper)
                print(f"  → Serper : {len(noms_serper)} noms")
        except Exception as e:
            print(f"  → Serper erreur : {e}")

    return list(noms)


def _extraire_noms_depuis_texte(texte: str, pays_nom: str) -> list[str]:
    """LLM extrait les noms propres PEP depuis un texte libre."""
    if not texte or len(texte) < 50:
        return []
    prompt = f"""Voici un texte sur le gouvernement du {pays_nom}.
Extrais les noms complets des personnes mentionnées (ministres, présidents, directeurs, etc.).
Retourne UNIQUEMENT un JSON valide, sans texte avant ou après :
["Prénom Nom", "Prénom Nom", ...]

Texte :
{texte[:3000]}

JSON :"""
    try:
        resp  = llm.invoke(prompt)
        texte_resp = resp.content.strip()
        match = re.search(r'\[.*\]', texte_resp, re.DOTALL)
        if match:
            noms = json.loads(match.group(0))
            return [n.strip() for n in noms if isinstance(n, str) and " " in n.strip()]
    except Exception:
        pass
    return []


def collecter_track_a(code_iso: str, pays_nom: str,
                      max_verif: int = 0, _cpt: list = None) -> int:
    """
    Découvre les noms via 3 canaux, filtre ceux déjà en base,
    puis lance verifier_pep sur chaque nouveau nom.
    """
    from pep_agent import verifier_pep

    noms_decouverts = _decouvrir_noms_track_a(code_iso, pays_nom)
    noms_nouveaux   = [n for n in noms_decouverts if not _deja_en_base(n, code_iso)]
    print(f"  [Track A] {len(noms_decouverts)} découverts, {len(noms_nouveaux)} nouveaux à vérifier")

    inserted = 0
    for nom_complet in noms_nouveaux:
        if max_verif and _cpt is not None and _cpt[0] >= max_verif:
            print(f"  [QUOTA] Limite {max_verif} vérifications/jour atteinte — reprise demain via checkpoint")
            break
        parts = nom_complet.strip().split(None, 1)
        prenom = parts[0]
        nom    = parts[1] if len(parts) > 1 else ""
        if not nom:
            continue

        _update_status(
            track="A", country=code_iso,
            category=f"verification:{nom_complet[:40]}",
            inserted_last=0,
        )

        try:
            rapport = verifier_pep(prenom, nom)
            if _cpt is not None:
                _cpt[0] += 1
                _status["verif_total"] = _cpt[0]
            if rapport and getattr(rapport, "est_pep", False):
                inserted += 1
                _status["inserted_total"] += 1
                _status["inserted_last"]   = 1
                _update_status()
                print(f"  ✅ PEP confirmé : {nom_complet}")
            else:
                print(f"  ⬜ Non-PEP : {nom_complet}")
        except Exception as e:
            msg = f"Track A {code_iso} {nom_complet[:30]}: {e}"
            print(f"  ⚠️  {msg}")
            _status["errors"].append(msg)
            _update_status()

        time.sleep(10)  # respecter les rate limits Tavily + OpenSanctions

    return inserted


# ── Point d'entrée principal ─────────────────────────────────────────────────────

def alimenter_base_pep(pays_list: Optional[list] = None,
                       max_verif: int = 0) -> None:
    """
    Pipeline par pays :
      - Mode B+A (défaut) : Track B scrape → lot brut → Track A vérifie → INSERT
      - Mode B only       : Track B scrape → INSERT direct (rapide, non vérifié)
    Checkpoint automatique → reprise si crash.
    """
    cibles = pays_list or PAYS_PERIMETRE
    ref    = _charger_referentiel()
    _cpt   = [0]  # compteur partagé de vérifications (mutable)

    checkpoint = _charger_checkpoint()

    _update_status(
        running=True,
        inserted_total=0, inserted_last=0,
        verif_total=0, max_verif=max_verif,
        countries_done=0, countries_total=len(cibles),
        errors=[], track="", country="", category="",
    )

    print(f"\n{'='*60}")
    print(f"ScreenEdge — Collecte PEP : {len(cibles)} pays")
    print(f"Mode : B+A (vérification pipeline complète avant INSERT)")
    if max_verif:
        print(f"Limite : {max_verif} vérifications max cette session")
    print(f"Checkpoint : {len(checkpoint)} PEP déjà vérifiés")
    print(f"{'='*60}")

    try:
        for i, code_iso in enumerate(cibles):
            if max_verif and _cpt[0] >= max_verif:
                print(f"\n[QUOTA] Limite {max_verif} vérifications atteinte — arrêt. Relancer demain.")
                break
            pays_nom = ref.get(code_iso, {}).get("pays", code_iso)
            print(f"\n{'─'*50}")
            print(f"[{i+1}/{len(cibles)}] {code_iso} — {pays_nom}")
            print(f"{'─'*50}")

            # ── Track B : scrape → lot brut (pas d'INSERT) ──
            lot_brut = collecter_track_b(code_iso, pays_nom)

            # ── Canal 0b : enrichissement dump OpenSanctions ──
            # 10 noms du dump ajoutés au lot — vérifiés normalement (pas d'INSERT direct)
            from opensanctions_local import noms_candidats_dump
            dump_candidats = noms_candidats_dump(code_iso, exclure=checkpoint, limite=10)
            if dump_candidats:
                # Dédoublonner avec les noms déjà dans lot_brut
                noms_lot = {f"{p.get('prenom','')} {p.get('nom','')}".strip().lower() for p in lot_brut}
                dump_nouveaux = [
                    p for p in dump_candidats
                    if f"{p['prenom']} {p['nom']}".strip().lower() not in noms_lot
                ]
                lot_brut.extend(dump_nouveaux)
                print(f"  [Dump 0b] {len(dump_nouveaux)} candidats ajoutés depuis OpenSanctions dump")

            # Pipeline B+A : Track B scrape → verifier_pep → INSERT si confirmé
            if lot_brut:
                n, checkpoint = pipeline_lot(
                    lot_brut, code_iso, pays_nom, checkpoint, throttle_s=5,
                    max_verif=max_verif, _cpt=_cpt
                )
                print(f"  Pipeline B+A : {n} PEP vérifiés et insérés")
            else:
                print(f"  Aucun candidat Track B pour {code_iso} — Track A seul")

                # Track A : découverte complémentaire (OpenSanctions + Tavily + Serper)
                if not (max_verif and _cpt[0] >= max_verif):
                    n_a = collecter_track_a(code_iso, pays_nom, max_verif=max_verif, _cpt=_cpt)
                    print(f"  Track A découverte : {n_a} PEP supplémentaires")

            _update_status(countries_done=i + 1)

        total = _status["inserted_total"]
        _update_status(running=False, track="", country="", category="", inserted_last=0)

        print(f"\n{'='*60}")
        print(f"✅ Collecte terminée — {total} PEP insérés")
        print(f"{'='*60}")

    except Exception as _crash_err:
        import traceback as _tb
        _update_status(
            running=False, track="", country="", category="",
            last_crash={
                "ts":        datetime.now().isoformat(),
                "erreur":    str(_crash_err)[:500],
                "traceback": _tb.format_exc()[:1000],
            }
        )
        print(f"\n⛔ CRASH — {_crash_err}")
        raise


# ── CLI ──────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collecteur PEP ScreenEdge Africa")
    parser.add_argument("--pays", type=str, default="",
                        help="Liste de codes ISO séparés par virgule, ex: MA,SN,CI")
    parser.add_argument("--max-verif", type=int, default=0,
                        help="Limite de vérifications IA par session (0 = illimité). Ex: --max-verif 5")
    args = parser.parse_args()

    pays_list = [p.strip().upper() for p in args.pays.split(",") if p.strip()] or None

    alimenter_base_pep(pays_list=pays_list, max_verif=args.max_verif)
