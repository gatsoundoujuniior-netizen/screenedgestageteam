"""
search_tools.py — ScreenEdge Africa
3 tools de recherche pour l'agent PEP.

Hiérarchie des sources :
  Tier 1 — Officielle directe  : gouvernements, JO, banques centrales, CENTIF, agences d'État
  Tier 2 — Secondaire fiable   : AFP, Reuters, RFI, médias spécialisés → recoupement obligatoire
  Tier 3 — Référence compliance: OpenSanctions, OCCRP, FATF → alerte/enrichissement seulement
"""

import sys, re, json, unicodedata, time as _time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

from langchain_tavily import TavilySearch
from dotenv import load_dotenv

load_dotenv(override=True)

import os as _os
_LOG_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "logs")
_os.makedirs(_LOG_DIR, exist_ok=True)

# ── Accumulateur de santé des sources (réinitialisé à chaque verifier_pep) ──────
_url_logs: list[dict] = []

def reset_url_logs() -> None:
    global _url_logs
    _url_logs = []

def get_url_logs() -> list[dict]:
    return list(_url_logs)

def _log_url(url: str, tier: str, nom: str, code_iso: str,
             statut: str, http_code=None, duree_ms: int = 0, erreur: str = "") -> None:
    from urllib.parse import urlparse as _up
    domaine = _up(url).netloc.replace("www.", "")
    _url_logs.append({
        "url":          url,
        "domaine":      domaine,
        "tier":         tier,
        "nom_verifie":  nom,
        "code_iso":     code_iso,
        "statut":       statut,          # ok | vide | timeout | connexion_ko | http_erreur | bloque | erreur
        "http_code":    http_code,
        "duree_ms":     duree_ms,
        "erreur":       (erreur or "")[:300],
        "est_source_off": est_source_officielle(url),
    })

def _log_source_erreur(nom_complet: str, source: str, erreur: str) -> None:
    """Ajoute une ligne d'erreur source dans le log corpus du jour."""
    ts       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_path = _os.path.join(_LOG_DIR, f"corpus_{date_str}.log")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"  [{ts}] ⚠ {source} erreur pour {nom_complet!r} : {erreur[:200]}\n")

tavily = TavilySearch(max_results=10, search_depth="advanced")

# ── Tracking API ─────────────────────────────────────────────────────────────────
try:
    from api_tracker import tracker_serper as _tracker_serper
    from api_tracker import tracker_tavily as _tracker_tavily
    from api_tracker import tracker_opensanctions as _tracker_opensanctions
except ImportError:
    def _tracker_serper(**kw): pass
    def _tracker_tavily(**kw): pass
    def _tracker_opensanctions(**kw): pass

# ── OpenSanctions : dump local prioritaire, API en fallback ──────────────────────
try:
    from opensanctions_local import (
        rechercher_opensanctions_local as _os_local,
        statut_dump as _os_statut_dump,
    )
    import os as _os_mod
    _OS_LOCAL_DISPONIBLE = _os_mod.path.exists(
        _os_mod.path.join(_os_mod.path.dirname(_os_mod.path.abspath(__file__)), "opensanctions_pep.sqlite")
    )
except ImportError:
    _os_local = None
    _OS_LOCAL_DISPONIBLE = False

# ── Compteur global Tavily ───────────────────────────────────────────────────────
_tavily_compteur = {"total": 0, "par_personne": 0}

def _tavily_invoke(instance, query: str, label: str = "") -> any:
    """Wrapper Tavily avec comptage automatique."""
    _tavily_compteur["total"]       += 1
    _tavily_compteur["par_personne"] += 1
    _tracker_tavily(nb_appels=1)
    if label:
        print(f"  [Tavily #{_tavily_compteur['total']}] {label[:60]}")
    return instance.invoke({"query": query})

def reset_compteur_personne():
    """Remet à zéro le compteur par personne (appelé au début de chaque verifier_pep)."""
    _tavily_compteur["par_personne"] = 0

def get_compteur() -> dict:
    return dict(_tavily_compteur)

# ── TIER 1 : Sources officielles directes (valident seules) ────────────────────

TIER1_DOMAINES = [
    # Gouvernements / Présidences
    ".gouv.", ".gov.", "gouvernement.", "presidence.", "primature.",
    "el-mouradia.", "koulouba.", "gouv.ci", "gouv.tg", "gouv.ne",
    "gouv.bj", "gov.gw", "gov.ly", "sig.gov.bf",
    # Banques centrales
    "bceao.int", "bkam.ma", "bct.gov.tn", "bank-of-algeria.dz",
    "bcrg.org", "cbl.gov.ly",
    # CENTIF / FIU
    "centif.", "ctrf.gov.dz", "ctaf.gov.tn", "utrf.gov.ma", "fiulibya.gov.ly",
    # Parlements
    "assemblee-nationale.", "chambredesrepresentants.", "chambredesconseillers.",
    "apn.dz", "senat.dz", "arp.tn", "parlement.ma", "ipu.org",
    # Journaux Officiels
    "joradp.dz", "jo.gov.tn", "jo.gov.ma", "jo.gouv.sn", "jo.ci",
    "jo.gouv.tg", "jo.gouv.bj", "fasonet.bf",
    # Régulateurs financiers
    "ammc.ma", "acaps.ma", "cg.gov.ma",
    # Agences de presse d'État (Tier 1 — publient les décrets officiels)
    "aps.sn", "aip.ci", "amap.ml", "aib.bf", "agpguinee.com",
    "anp.ne", "abp.bj", "republicoftogo.com",
    # Institutions régionales
    "giaba.org", "uemoa.int", "ecowas.int", "au.int",
    # Organisations internationales
    "fatf-gafi.org", "worldbank.org", "imf.org", "undp.org",
]

# ── TIER 2 : Sources secondaires fiables (recoupement obligatoire) ──────────────

TIER2_DOMAINES = [
    "afp.com", "reuters.com", "rfi.fr", "bbc.com",
    "jeuneafrique.com", "theafricareport.com", "lemonde.fr",
    "medias24.com", "kapitalis.com",
    "africaguinee.com", "guineematin.com",
]

# ── TIER 3 : Vérification secondaire uniquement ─────────────────────────────────
# Utilisable pour : confirmer existence, biographie, liens vers sources officielles
# Interdit pour  : valider fonction PEP, sourcer une nomination

DOMAINES_SECONDAIRES = [
    "wikipedia.org", "wikidata.org",   # encyclopédie — vérification identité
]

# ── Sources toujours interdites (réseaux sociaux publics) ────────────────────────

DOMAINES_INTERDITS = [
    "facebook.com", "twitter.com", "x.com", "linkedin.com",
    "instagram.com", "tiktok.com", "youtube.com",
    "wikimedia.org",  # fichiers média — inutile pour compliance
]

# Compatibilité avec pep_agent.py
DOMAINES_OFFICIELS = TIER1_DOMAINES

# ── Sources officielles par pays — Tier 1 en priorité ──────────────────────────

DOMAINES_OFFICIELS_PAR_PAYS = {
    "MA": [
        "maroc.ma", "cg.gov.ma", "parlement.ma",
        "chambredesrepresentants.ma", "chambredesconseillers.ma",
        "utrf.gov.ma", "acaps.ma",
    ],
    "DZ": [
        "premier-ministre.gov.dz", "joradp.dz", "apn.dz",
    ],
    "TN": [
        "carthage.tn", "arp.tn", "ctaf.gov.tn",
    ],
    "LY": [
        "cbl.gov.ly",
    ],
    "SN": [
        "presidence.sn", "bceao.int",
    ],
    "CI": [
        "presidence.ci", "gouv.ci", "senat.ci", "aip.ci", "pulse.ci",
        "bceao.int",
    ],
    "ML": [
        "koulouba.ml", "amap.ml",
        "bceao.int",
    ],
    "BF": [
        "gouvernement.gov.bf", "sig.gov.bf", "centif.bf",
        "fasonet.bf", "presidencedufaso.bf",
        "bceao.int",
    ],
    "NE": [
        "centif.ne", "anp.ne",
        "bceao.int",
    ],
    "TG": [
        "presidenceduconseil.gouv.tg", "togo.gouv.tg",
        "assemblee-nationale.tg", "centif.tg", "jo.gouv.tg",
        "atop.tg", "togofirst.com", "bceao.int",
    ],
    "BJ": [
        "presidence.bj", "gouv.bj", "assemblee-nationale.bj",
        "centif.bj", "portailinfo.bj",
        "bceao.int",
    ],
    "GW": [
        "bceao.int",
    ],
    "GN": [
        "presidence.gov.gn", "gouvernement.gov.gn", "bcrg.org",
        "agpguinee.com",
    ],
}

# ── Fonctions utilitaires ────────────────────────────────────────────────────────

def est_source_officielle(url: str) -> bool:
    """Vérifie si l'URL est Tier 1 (valide seule pour PEP)."""
    if not url:
        return False
    url = url.lower()
    if any(d in url for d in DOMAINES_INTERDITS):
        return False
    if any(d in url for d in TIER1_DOMAINES):
        return True
    if re.search(r'\.(gov|gouv|gv)\.[a-z]{2,}', url):
        return True
    return False

def est_source_secondaire(url: str) -> bool:
    """Vérifie si l'URL est Tier 2 (acceptable en recoupement)."""
    if not url:
        return False
    return any(d in url.lower() for d in TIER2_DOMAINES)

def est_source_verification(url: str) -> bool:
    """Vérifie si l'URL est Tier 3 (vérification secondaire — Wikipedia)."""
    if not url:
        return False
    return any(d in url.lower() for d in DOMAINES_SECONDAIRES)

def extraire_liens_officiels_wikipedia(nom_complet: str) -> list[str]:
    """
    Cherche sur Wikipedia pour trouver des liens vers sources officielles.
    Usage : confirmer existence + récupérer URLs officielles citées.
    NE PAS utiliser pour valider une fonction PEP.
    """
    try:
        res = _tavily_invoke(tavily, f'site:fr.wikipedia.org "{nom_complet}" politique gouvernement', "Wikipedia liens officiels")
        if not res:
            res = _tavily_invoke(tavily, f'site:fr.wikipedia.org {nom_complet} politique gouvernement', "Wikipedia liens officiels sans guillemets")
        if not res:
            return []

        # Extraire uniquement les URLs officielles citées dans Wikipedia
        texte = str(res)
        urls  = re.findall(r'https?://[^\s\'">,]+', texte)
        liens_officiels = [u for u in urls if est_source_officielle(u)]
        print(f"  Wikipedia → {len(liens_officiels)} liens officiels extraits")
        return liens_officiels[:5]
    except Exception:
        return []

def filtrer_resultats(texte: str) -> str:
    """
    Supprime uniquement les réseaux sociaux publics (Tier interdit).
    Garde tout le reste — Tier 1, Tier 2, Wikipedia.
    L'agent décide du poids de chaque source.
    """
    if not texte:
        return "Aucun résultat."
    lignes = texte.split("\n")
    lignes_ok = [l for l in lignes if not any(d in l.lower() for d in DOMAINES_INTERDITS)]
    return "\n".join(lignes_ok) or "Aucun résultat."

def annoter_sources(texte: str) -> str:
    """
    Annote chaque URL trouvée avec son niveau de fiabilité.
    Aide le LLM à peser les preuves.
    """
    def remplacer(m):
        url = m.group(0)
        if est_source_officielle(url):
            return f"{url} [OFFICIEL✅]"
        elif est_source_secondaire(url):
            return f"{url} [MEDIA⚠️]"
        elif est_source_verification(url):
            return f"{url} [WIKI🔍]"
        return url
    return re.sub(r'https?://[^\s\'">,]+', remplacer, texte)

def _normaliser(s: str) -> str:
    """Supprime les accents et met en minuscule pour comparaison robuste."""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()


def extraire_passages_nom(contenu: str, nom_complet: str) -> str:
    """Extrait les passages autour du nom avec mots-clés de fonction."""
    if not contenu or not nom_complet:
        return contenu or ""

    # Normalisation accents — "Kaboré" → "kabore", "Gnassingbé" → "gnassingbe"
    nom_parts   = [_normaliser(p) for p in nom_complet.split() if len(p) > 2]
    mots_fonction = [
        'ministre', 'president', 'directeur', 'nomme', 'nomination',
        'decret', 'secretaire', 'ambassadeur', 'conseil des ministres',
        'gouverneur', 'haut commissaire', 'premier ministre', 'chef',
        'minister', 'appointed', 'designated', 'named',
    ]
    # Passages bio : toujours inclus même quand des passages fonction existent
    mots_bio = [
        'ne ', 'nee ', 'naissance', 'born', 'marie', 'epouse', 'epoux',
        'polygame', 'celibataire', 'enfant', 'fils', 'fille', 'pere de',
        'mere de', 'father', 'mother', 'married', 'wife', 'husband',
    ]

    lignes   = contenu.split("\n")
    passages = []

    for i, ligne in enumerate(lignes):
        ligne_norm = _normaliser(ligne)
        if any(p in ligne_norm for p in nom_parts):
            debut    = max(0, i - 3)
            fin      = min(len(lignes), i + 4)
            contexte = "\n".join(lignes[debut:fin])
            passages.append(contexte)

    if not passages:
        return contenu[:6000]

    avec_fonction = [p for p in passages if any(m in _normaliser(p) for m in mots_fonction)]
    avec_bio      = [p for p in passages if any(m in _normaliser(p) for m in mots_bio)]
    # Garder fonction + bio : les passages bio ne doivent jamais être sacrifiés
    if avec_fonction:
        seen = set()
        selection = []
        for p in avec_fonction[:40] + avec_bio[:10]:
            k = p[:80]
            if k not in seen:
                seen.add(k)
                selection.append(p)
    else:
        selection = passages
    resultat      = "\n\n---\n\n".join(selection[:50])

    # Si trop peu de contenu extrait → compléter avec le début du corpus brut
    if len(resultat.split()) < 300:
        resultat += "\n\n---\n\n[CORPUS BRUT]\n" + contenu[:6000]

    return resultat


# ── TOOL 2 : Scrapling structuré — extraction JSON depuis pages officielles ─────

def scraper_json_officiel(nom_complet: str, urls: list[str], code_iso: str = "") -> dict:
    """
    Scrapling lit une page officielle et extrait les données structurées
    (tableaux, listes) en JSON — pas du texte brut.

    Retourne : {
        "source": url,
        "nominations": [{"nom": ..., "fonction": ...}],
        "texte_brut": ...  (si pas de structure trouvée)
    }
    """
    if not urls:
        return {}

    nom_parts = [p.lower() for p in nom_complet.split() if len(p) > 2]

    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    from bs4 import BeautifulSoup

    # DynamicFetcher en priorité (JS + HTML), StealthyFetcher en fallback, requests en dernier
    _dynamic_fetcher  = None
    _stealthy_fetcher = None
    try:
        from scrapling.fetchers import DynamicFetcher
        _dynamic_fetcher = DynamicFetcher()
    except Exception:
        pass
    try:
        from scrapling.fetchers import StealthyFetcher
        _stealthy_fetcher = StealthyFetcher()
    except Exception:
        pass

    def _fetch_page(url: str) -> tuple:
        """Fetch HTML — DynamicFetcher → StealthyFetcher → requests.
        Retourne (html, statut, http_code, erreur)."""
        # 1. DynamicFetcher
        if _dynamic_fetcher:
            try:
                page = _dynamic_fetcher.fetch(url, wait=2000, ignore_https_errors=True)
                html = str(page.html_content) if hasattr(page, 'html_content') else ""
                if html and len(html) > 500:
                    return html, "ok", 200, ""
            except Exception:
                pass
        # 2. StealthyFetcher
        if _stealthy_fetcher:
            try:
                page = _stealthy_fetcher.fetch(url)
                html = str(page.html_content) if hasattr(page, 'html_content') else ""
                if html and len(html) > 500:
                    return html, "ok", 200, ""
            except Exception:
                pass
        # 3. requests simple
        try:
            r = requests.get(url, timeout=10, verify=False, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code >= 500:
                return "", "http_erreur", r.status_code, f"HTTP {r.status_code}"
            if r.status_code == 403:
                return r.text, "bloque", 403, "HTTP 403 Forbidden"
            if len(r.text) < 500:
                return r.text, "vide", r.status_code, "contenu trop court"
            return r.text, "ok", r.status_code, ""
        except Exception as _fe:
            _fe_s = str(_fe).lower()
            if "timeout" in _fe_s or "timed out" in _fe_s:
                return "", "timeout", None, str(_fe)[:200]
            if "connection" in _fe_s or "refused" in _fe_s or "resolve" in _fe_s or "name or service" in _fe_s:
                return "", "connexion_ko", None, str(_fe)[:200]
            return "", "erreur", None, str(_fe)[:200]

    for url in urls:
        # Wikipedia — déjà chargé par _run_wiki_api() dans rechercher_pep() → skip ici
        # pour ne pas bloquer le scraping des URLs médias qui suivent dans la liste
        if "wikipedia.org/wiki/" in url:
            continue

        _can_scrape = (
            est_source_officielle(url)
            or est_source_secondaire(url)
            or any(d in url.lower() for d in ["britannica.com", "notreafrik.com"])
        )
        if not _can_scrape:
            continue
        _tier_scrape = "scrapling" if est_source_officielle(url) else "scrapling_media"
        _t_url = _time.time()
        try:
            html_str, _statut_url, _http_url, _erreur_url = _fetch_page(url)
            _duree_url = int((_time.time() - _t_url) * 1000)
            _log_url(url, _tier_scrape, nom_complet, code_iso, _statut_url, _http_url, _duree_url, _erreur_url)
            if not html_str or len(html_str) < 200:
                continue
            soup     = BeautifulSoup(html_str, "html.parser")

            nominations = []

            # ── Extraction tableaux ────────────────────────────────────────────
            for table in soup.find_all("table"):
                rows = table.find_all("tr")
                for row in rows:
                    cols = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                    if len(cols) >= 2:
                        nom_col = cols[0]
                        fct_col = cols[1] if len(cols) > 1 else ""
                        if any(p in nom_col.lower() for p in nom_parts):
                            nominations.append({"nom": nom_col, "fonction": fct_col, "source": url})

            # ── Extraction listes ──────────────────────────────────────────────
            MOTS_FCT_SPLIT = [
                "Président", "Premier ministre", "Prime Minister", "President",
                "Ministre", "Minister", "Directeur", "Director",
                "Gouverneur", "Governor", "Secrétaire", "Secretary",
                "Chef ", "Ambassadeur", "Ambassador",
            ]
            for li in soup.find_all(["li", "p", "div"]):
                texte = li.get_text(strip=True)
                if len(texte) < 5 or len(texte) > 500:
                    continue
                if any(p in texte.lower() for p in nom_parts):
                    # Pattern "Nom, Fonction" ou "Nom : Fonction" ou "Nom\nFonction"
                    match = re.split(r',\s*|:\s*|–\s*|-\s*|\n', texte, maxsplit=1)
                    if len(match) == 2 and match[1].strip():
                        nominations.append({
                            "nom":      match[0].strip(),
                            "fonction": match[1].strip(),
                            "source":   url
                        })
                    else:
                        # Nom+fonction collés sans séparateur → chercher mot-clé de fonction
                        fct_trouvee = ""
                        idx_fct = -1
                        for kw in MOTS_FCT_SPLIT:
                            idx = texte.find(kw)
                            if 0 < idx < len(texte) - 3:
                                if idx_fct == -1 or idx < idx_fct:
                                    idx_fct = idx
                                    fct_trouvee = texte[idx:].strip()
                        if fct_trouvee and idx_fct > 2:
                            nominations.append({
                                "nom":      texte[:idx_fct].strip(),
                                "fonction": fct_trouvee[:120],
                                "source":   url
                            })
                        else:
                            nominations.append({"nom": texte, "fonction": "", "source": url})

            # ── Si page index (liste de Conseils des Ministres) → suivre liens ──
            texte_page = soup.get_text(separator="\n", strip=True)
            est_index  = texte_page.count("CONSEIL DES MINISTRES") > 10

            if est_index:
                print(f"  Page index détectée ({texte_page.count('CONSEIL DES MINISTRES')} CdM) → suivi des liens récents")
                annee_cible = datetime.now().year
                liens_articles = []
                for a in soup.find_all("a", href=True):
                    href  = a["href"]
                    texte_lien = a.get_text(strip=True)
                    # Liens vers articles de l'année en cours ou précédente
                    if any(str(y) in texte_lien or str(y) in href for y in [annee_cible, annee_cible-1]):
                        full_url = href if href.startswith("http") else f"https://{url.split('/')[2]}{href}"
                        liens_articles.append(full_url)

                # Lire les articles récents avec Scrapling (JS) ou requests
                for lien in list(set(liens_articles))[:5]:
                    try:
                        txt2 = ""
                        if use_scrapling:
                            try:
                                p2   = fetcher.fetch(lien)
                                html2 = str(p2.html_content) if hasattr(p2, 'html_content') else ""
                                if html2:
                                    s2   = BeautifulSoup(html2, "html.parser")
                                    txt2 = s2.get_text(separator="\n", strip=True)
                            except Exception:
                                pass
                        if not txt2:
                            r2   = requests.get(lien, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
                            s2   = BeautifulSoup(r2.text, "html.parser")
                            txt2 = s2.get_text(separator="\n", strip=True)

                        if any(p in txt2.lower() for p in nom_parts):
                            texte_page = txt2
                            url        = lien
                            soup       = BeautifulSoup(txt2, "html.parser") if txt2 else soup
                            print(f"  → Nom trouvé dans article : {lien[:80]}")
                            break
                    except Exception:
                        continue

            # ── Extraction par phrases de nomination (regex) ──────────────────
            patterns_nomination = [
                # "en qualité de FONCTION"
                r'(?:' + '|'.join(re.escape(p) for p in nom_parts) + r')[^.]{0,80}(?:en qualité de|comme|nommé[e]?\s+(?:au poste de|à la tête de|directeur|ministre)?)\s+([^,.\n]{5,80})',
                # "FONCTION, nommé par"
                r'([A-ZÀ-Ÿ][a-zà-ÿ\s]{5,60})(?:,\s*nommé[e]?\s+' + '|'.join(re.escape(p) for p in nom_parts) + r')',
                # "Mme/M. Nom Prenom, FONCTION"
                r'(?:Mme|M\.|Dr\.?|Pr\.?)\s+' + r'\s+'.join(re.escape(p.title()) for p in nom_parts[:2]) + r'\s*[,–-]\s*([^,.\n]{5,80})',
            ]
            for pattern in patterns_nomination:
                try:
                    matches = re.findall(pattern, texte_page, re.IGNORECASE)
                    for m in matches:
                        fonction_extraite = m.strip() if isinstance(m, str) else m[0].strip()
                        if len(fonction_extraite) > 4:
                            nominations.append({
                                "nom":      nom_complet,
                                "fonction": fonction_extraite,
                                "source":   url,
                                "methode":  "regex_phrase"
                            })
                except Exception:
                    continue

            if nominations:
                # Filtrer UNIQUEMENT les entrées où le nom cherché est présent
                nominations_filtrees = [
                    n for n in nominations
                    if any(p in (n.get("nom","") + n.get("fonction","")).lower()
                           for p in nom_parts)
                ]
                selection = nominations_filtrees if nominations_filtrees else nominations[:5]
                # Continuer sur URL suivante si aucune entrée avec fonction
                has_fonction = any(n.get("fonction","").strip() for n in selection)
                if not has_fonction:
                    print(f"  Scrapling {url[:50]} : nominations sans fonction → URL suivante...")
                    continue
                print(f"  Scrapling JSON : {len(selection)} entrées pertinentes (/{len(nominations)} total) depuis {url}")
                return {
                    "source":         url,
                    "nominations":    selection[:10],
                    "personne_cible": nom_complet,
                }

            # Si pas de structure → texte brut autour du nom
            extrait = extraire_passages_nom(texte_page, nom_complet)
            if extrait and any(p in extrait.lower() for p in nom_parts):
                return {"source": url, "texte_brut": extrait[:6000]}

        except Exception as e:
            _duree_url = int((_time.time() - _t_url) * 1000)
            _log_url(url, "scrapling", nom_complet, code_iso, "erreur", None, _duree_url, str(e)[:200])
            print(f"  Scrapling erreur {url[:50]} : {e}")
            continue

    return {}


# ── TOOL 1 : Tavily — recherche ciblée site: ────────────────────────────────────

def recherche_tavily(nom_complet: str, pays_nom: str, code_iso: str, duree_ex_pep: str = "non précisée"):
    """
    Recherche autonome — l'agent trouve seul, sans qu'on lui dise où chercher.

    Ordre Hazim :
    1. Recherche libre → Tavily cherche partout, filtre les résultats non officiels
    2. Si insuffisant → cibler les sources prédéfinies du pays (fallback)
    """
    annee     = datetime.now().year
    nom_parts = [p.lower() for p in nom_complet.split() if len(p) > 2]

    resultats_bruts  = []
    urls_officielles = []

    # ── NIVEAU 1 : Recherche autonome libre ───────────────────────────────────
    # L'agent cherche sans contrainte de site — il trouve seul
    requetes_libres = [
        f'"{nom_complet}" fonction officielle {pays_nom} {annee} OR {annee-1}',
        f'"{nom_complet}" ministre OR président OR directeur général {pays_nom}',
        f'"{nom_complet}" nommé OR nomination gouvernement {pays_nom} {annee} OR {annee-1}',
        f'"{nom_complet}" actuellement OR "en poste" OR "fonction actuelle" {pays_nom} {annee}',
    ]

    for q in requetes_libres:
        try:
            res = _tavily_invoke(tavily, q, f"libre: {q[:40]}")
            if res:
                texte = str(res)
                if any(p in texte.lower() for p in nom_parts):
                    resultats_bruts.append(f"[RECHERCHE LIBRE]\n{texte}")
                    urls = re.findall(r'https?://[^\s\'">,]+', texte)
                    urls_officielles += [u for u in urls if est_source_officielle(u)]
        except Exception:
            continue

    # ── NIVEAU 2 : Cibler sources prédéfinies si résultats insuffisants ───────
    # Fallback uniquement — on ne dit pas à l'agent où chercher en premier
    if len(urls_officielles) < 2:
        sites_pays = DOMAINES_OFFICIELS_PAR_PAYS.get(code_iso.upper(), [])
        for site in sites_pays[:4]:
            try:
                res = _tavily_invoke(tavily, f'site:{site} "{nom_complet}"', f"fallback: {site}")
                if res:
                    texte = str(res)
                    if any(p in texte.lower() for p in nom_parts):
                        resultats_bruts.append(f"[FALLBACK — {site}]\n{texte}")
                        urls = re.findall(r'https?://[^\s\'">,]+', texte)
                        urls_officielles += [u for u in urls if est_source_officielle(u)]
                        break
            except Exception:
                continue

        # Requête historique — ex-PEP (renversés, démissionnaires, retraités)
        # Toujours lancée si duree_ex_pep = "permanente" (obligation GAFI R12)
        # Sinon seulement en fallback (peu de résultats au niveau 1)
        if duree_ex_pep == "permanente" or len(urls_officielles) < 1:
            try:
                res = _tavily_invoke(tavily, f'"{nom_complet}" ancien OR ex-président OR ex-ministre OR renversé OR démission {pays_nom}', "historique ex-pep")
                if res:
                    texte = str(res)
                    if any(p in texte.lower() for p in nom_parts):
                        resultats_bruts.append(f"[HISTORIQUE EX-PEP]\n{texte}")
            except Exception:
                pass

    # Tier 2 médias — si peu de sources officielles, interroger tous les médias + extraire URLs pour Scrapling
    _SITES_MEDIA_T2 = ["rfi.fr", "france24.com", "jeuneafrique.com", "afp.com"]
    _corpus_thin = len(urls_officielles) < 2
    _media_hits = 0
    for site in _SITES_MEDIA_T2:
        try:
            res = _tavily_invoke(tavily, f'site:{site} "{nom_complet}" président OR ministre OR actuel {annee}', f"media: {site}")
            if res:
                texte = str(res)
                if any(p in texte.lower() for p in nom_parts):
                    resultats_bruts.append(f"[MEDIA TIER2 — {site}]\n{texte}")
                    # Extraire les URLs articles pour Scrapling profond (plein article, pas juste snippet)
                    for _mu in re.findall(r'https?://[^\s\'">,\]]+', texte):
                        _mu = _mu.rstrip('.,)')
                        if site in _mu and _mu not in urls_officielles:
                            urls_officielles.append(_mu)
                    _media_hits += 1
                    if not _corpus_thin and _media_hits >= 1:
                        break  # 1 média suffit pour les pays bien couverts en sources officielles
        except Exception:
            continue

    brut    = "\n\n".join(resultats_bruts)
    filtre  = filtrer_resultats(brut)
    annote  = annoter_sources(filtre)        # annoter chaque URL avec son niveau
    extrait = extraire_passages_nom(annote, nom_complet)

    return extrait, list(set(urls_officielles))


# ── TIER 2b : Google Custom Search — complément Tavily ─────────────────────────

def rechercher_google(nom_complet: str, pays_nom: str, code_iso: str) -> tuple[str, list[str], list[str]]:
    """
    Serper.dev (Google Search) — Tier 2 complémentaire à Tavily.
    Recherche par nom → retourne snippets + URLs officielles + URLs médias.
    Les URLs médias sont passées à Scrapling pour récupérer le plein article (pas juste le snippet).
    Retourne (texte_corpus_annoté, urls_officielles, urls_medias)
    """
    import os, requests as req_g
    api_key = os.getenv("serper_dev_aoi_key", "")
    _serper_key_2 = os.getenv("serper_dev_aoi_key_2", "")
    _serper_key_3 = os.getenv("serper_dev_aoi_key_3", "")
    if not api_key:
        print(f"  [Tier 2b] Serper — clé manquante → ignoré")
        return "", [], []

    nom_parts = [p.lower() for p in nom_complet.split() if len(p) > 2]

    _DOMAINES_MEDIA_FIABLES = {
        "rfi.fr", "afp.com", "jeuneafrique.com", "reuters.com", "lemonde.fr",
        "lefigaro.fr", "bbc.com", "france24.com", "apanews.net", "africanews.com",
        "voaafrique.com", "britannica.com", "notreafrik.com", "weforum.org", "dw.com",
        "afrique-sur7.fr", "afrik.com",
        "telquel.ma", "le360.ma", "medias24.com", "hespress.com", "map.ma",
        "leral.net", "pressafrik.com", "dakaractu.com", "seneweb.com",
        "aip.ci", "fratmat.info", "koaci.com", "connectionivoirienne.net",
        "beninwebtv.com", "la-croix.com", "24haubenin.com", "matinal.bj",
        "togoinfos.com", "icilome.com", "togotribune.com",
        "maliweb.net", "malikactu.net", "malijet.com",
        "burkina24.com", "lefaso.net", "fasonet.bf",
        "actuniger.com", "nigerdiaspora.net", "tamtaminfo.com",
        "guineeconakry.info", "africaguinee.com", "guineematin.com",
    }

    def _est_media_fiable(url: str) -> bool:
        return any(d in url.lower() for d in _DOMAINES_MEDIA_FIABLES)

    # Nom court = premier prénom + nom (sans prénom intermédiaire)
    # Ex: "Faure Essozimina Gnassingbé" → "Faure Gnassingbé"
    _parts_nom = nom_complet.split()
    _nom_court = f"{_parts_nom[0]} {_parts_nom[-1]}" if len(_parts_nom) > 2 else nom_complet

    requetes_principales = [
        f'"{nom_complet}" président OR ministre {pays_nom}',
        f'"{nom_complet}" ancien président OR ex-président {pays_nom}',
    ]
    # Fallback sans prénom intermédiaire (ex: "Faure Essozimina Gnassingbé" → "Faure Gnassingbé")
    requetes_fallback = [
        f'"{_nom_court}" président OR ministre {pays_nom}',
        f'{_nom_court} président OR ministre {pays_nom}',
    ] if _nom_court != nom_complet else []

    resultats_bruts  = []
    urls_officielles = []
    urls_medias      = []

    def _run_serper_queries(queries: list) -> None:
        for q in queries:
            try:
                r = req_g.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                    json={"q": q, "hl": "fr", "num": 10},
                    timeout=8,
                )
                _tracker_serper(nb_appels=1)
                if r.status_code != 200:
                    # Cascade fallback clé-2 → clé-3 si quota épuisé (400, 429, 403)
                    _fallback_ok = False
                    if r.status_code in (400, 429, 403):
                        for _fb_num, _fb_key in [("2", _serper_key_2), ("3", _serper_key_3)]:
                            if not _fb_key:
                                continue
                            _rf = req_g.post(
                                "https://google.serper.dev/search",
                                headers={"X-API-KEY": _fb_key, "Content-Type": "application/json"},
                                json={"q": q, "hl": "fr", "num": 10},
                                timeout=8,
                            )
                            if _rf.status_code == 200:
                                r = _rf
                                print(f"  [Tier 2b] Serper clé-{_fb_num} fallback OK")
                                _fallback_ok = True
                                break
                            else:
                                print(f"  [Tier 2b] Serper clé-{_fb_num} HTTP {_rf.status_code}")
                    if not _fallback_ok:
                        print(f"  [Tier 2b] Serper HTTP {r.status_code} — toutes clés épuisées")
                        continue
                items = r.json().get("organic", [])
                if not items:
                    continue
                parties_q = []
                for item in items:
                    url     = item.get("link", "")
                    titre   = item.get("title", "")
                    snippet = item.get("snippet", "")
                    texte   = f"{url}\n{titre}\n{snippet}"
                    if any(p in texte.lower() for p in nom_parts):
                        parties_q.append(texte)
                        if est_source_officielle(url):
                            urls_officielles.append(url)
                        elif _est_media_fiable(url) and url not in urls_medias:
                            urls_medias.append(url)
                if parties_q:
                    resultats_bruts.append("[SERPER/GOOGLE]\n" + "\n\n".join(parties_q))
            except Exception as e:
                print(f"  [Tier 2b] Serper erreur : {e}")
                continue

    _run_serper_queries(requetes_principales)

    # Fallback nom court si nom complet avec guillemets retourne 0
    if not resultats_bruts and requetes_fallback:
        print(f"  [Tier 2b] Serper fallback → '{_nom_court}'")
        _run_serper_queries(requetes_fallback)

    if not resultats_bruts:
        print(f"  [Tier 2b] Serper — 0 résultat pertinent")
        return "", [], []

    brut    = "\n\n".join(resultats_bruts)
    filtre  = filtrer_resultats(brut)
    annote  = annoter_sources(filtre)
    extrait = extraire_passages_nom(annote, nom_complet)

    urls_medias = list(dict.fromkeys(urls_medias))[:5]
    print(f"  [Tier 2b] Serper — {len(extrait.split())} mots | {len(urls_officielles)} URLs off | {len(urls_medias)} URLs médias → Scrapling")
    return extrait, list(set(urls_officielles)), urls_medias


# ── TIER 3 : OpenSanctions — base mondiale PEP/sanctions ────────────────────────

_opensanctions_last_call: float = 0.0
_OPENSANCTIONS_MIN_INTERVAL = 30.0  # secondes minimum entre deux appels (quota 2000 req/mois)

def rechercher_opensanctions(nom_complet: str, code_iso: str = "") -> dict:
    """
    Interroge l'API OpenSanctions avec clé API.
    Retourne les entités PEP/sanctions trouvées pour ce nom.
    Throttling global : min 6s entre appels (limite API gratuite).
    Retry automatique sur 429 : 3 tentatives, backoff exponentiel 1s→2s→4s.
    """
    global _opensanctions_last_call
    import os, time, requests as req_os

    # Throttling — attendre si dernier appel trop récent
    elapsed = time.time() - _opensanctions_last_call
    if elapsed < _OPENSANCTIONS_MIN_INTERVAL:
        attente = _OPENSANCTIONS_MIN_INTERVAL - elapsed
        print(f"  [Tier 3] OpenSanctions throttle — attente {attente:.1f}s")
        time.sleep(attente)
    _opensanctions_last_call = time.time()
    api_key = os.getenv("open_sanction_apikey", "")
    nom_parts = [p.lower() for p in nom_complet.split() if len(p) > 2]
    try:
        params = {"q": nom_complet, "limit": 10, "fuzzy": "true"}
        if code_iso and code_iso != "XX":
            params["countries"] = code_iso.lower()
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"ApiKey {api_key}"

        r = None
        for tentative in range(3):
            r = req_os.get(
                "https://api.opensanctions.org/search/default",
                params=params,
                timeout=10,
                headers=headers,
            )
            _tracker_opensanctions(nb_appels=1)
            if r.status_code == 429:
                delai = 2 ** tentative  # 1s, 2s, 4s
                print(f"  [Tier 3] OpenSanctions 429 — attente {delai}s (tentative {tentative+1}/3)")
                time.sleep(delai)
                continue
            break

        if r is None or r.status_code != 200:
            print(f"  [Tier 3] OpenSanctions HTTP {r.status_code if r else '?'}")
            return {}
        data = r.json()
        resultats = data.get("results", [])
        # Fallback nom court si 0 résultat avec nom complet (prénom intermédiaire)
        _parts_os = nom_complet.split()
        if not resultats and len(_parts_os) > 2:
            _nom_court_os = f"{_parts_os[0]} {_parts_os[-1]}"
            print(f"  [Tier 3] OpenSanctions fallback → '{_nom_court_os}'")
            params["q"] = _nom_court_os
            r2 = req_os.get(
                "https://api.opensanctions.org/search/default",
                params=params, timeout=10, headers=headers,
            )
            _tracker_opensanctions(nb_appels=1)
            if r2.status_code == 200:
                resultats = r2.json().get("results", [])
        if not resultats:
            print(f"  [Tier 3] OpenSanctions — 0 résultat pour {nom_complet}")
            return {}

        FONCTIONS_PEP = [
            "president", "premier ministre", "prime minister", "ministre",
            "minister", "gouverneur", "governor", "directeur général",
            "secrétaire général", "chef", "ambassadeur", "ambassador",
            "chairman", "chairperson", "member of", "conseil",
        ]
        entites_pep = []
        for ent in resultats:
            props  = ent.get("properties", {})
            topics = ent.get("topics", [])
            nom_ent = " ".join(props.get("name", []) + props.get("alias", []))
            if not any(p in nom_ent.lower() for p in nom_parts):
                continue
            fonctions = props.get("position", props.get("role", []))
            # Détecter PEP via topics OU via fonctions (OpenSanctions met souvent topics=[])
            is_pep_topics = "pep" in topics or "role.pep" in topics
            is_pep_fcts   = any(
                any(kw in f.lower() for kw in FONCTIONS_PEP)
                for f in fonctions
            )
            # Extraire date de début de fonction (startDate ou date — pas birthDate)
            date_debut_raw = props.get("startDate", props.get("positionStart", []))
            date_debut = date_debut_raw[0] if date_debut_raw else None
            entite = {
                "nom":        " ".join(props.get("name", [nom_complet])),
                "pays":       (props.get("country") or props.get("citizenship") or props.get("nationality") or ([code_iso] if code_iso != "XX" else ["XX"])),
                "fonctions":  fonctions,
                "topics":     topics,
                "is_pep":     is_pep_topics or is_pep_fcts,
                "sanctions":  "sanction" in topics,
                "source":     ent.get("id", ""),
                "date_debut": date_debut,
            }
            entites_pep.append(entite)

        if entites_pep:
            nb_pep = sum(1 for e in entites_pep if e["is_pep"])
            print(f"  [Tier 3] OpenSanctions — {len(entites_pep)} entités ({nb_pep} PEP) pour {nom_complet}")
            return {"entites": entites_pep, "source": "opensanctions.org"}
        else:
            print(f"  [Tier 3] OpenSanctions — 0 entité correspondante pour {nom_complet}")
            return {}
    except Exception as e:
        print(f"  [Tier 3] OpenSanctions erreur : {e}")
        _log_source_erreur(nom_complet, "OpenSanctions", str(e))
        return {}


# ── Interface principale ─────────────────────────────────────────────────────────

def rechercher_pep(nom_complet: str, pays_nom: str, code_iso: str, duree_ex_pep: str = "non précisée") -> str:
    """
    Recherche 3 tiers en parallèle :
      Tier 1 — Scrapling direct (sites officiels connus + URLs trouvées par Tavily)
      Tier 2 — Tavily (recherche web libre + médias)
      Tier 3 — OpenSanctions (base PEP/sanctions mondiale)
    Tavily tourne en thread principal (counter non thread-safe).
    Scrapling + OpenSanctions tournent en parallèle dans des threads séparés.
    """
    # ── Tier 2 : Tavily — thread principal ───────────────────────────────────────
    print(f"\n  [Tier 2] Tavily — recherche web libre + médias...")
    resultats_tavily, urls_tavily = recherche_tavily(nom_complet, pays_nom, code_iso, duree_ex_pep)
    print(f"  → {len(urls_tavily)} URLs officielles Tavily | {len(resultats_tavily.split())} mots")

    # Wikipedia — URL + slug construits directement (API appelée en parallèle de Scrapling)
    nom_parts    = [n.lower() for n in nom_complet.split() if len(n) > 2]
    _wiki_slug   = "_".join(p.capitalize() for p in nom_complet.strip().split())
    _wiki_url    = f"https://fr.wikipedia.org/wiki/{_wiki_slug}"
    extrait_wiki = ""
    texte_wiki   = ""

    # Britannica + notreafrik + Jeune Afrique — slug court (premier prénom + nom, sans accents)
    import unicodedata as _ud2
    def _to_bio_slug(text: str, title_case: bool = False) -> str:
        nfkd = _ud2.normalize("NFKD", text)
        ascii_t = nfkd.encode("ascii", "ignore").decode("ascii")
        parts = ascii_t.split()
        if title_case:
            return "-".join(p.capitalize() for p in parts)
        return "-".join(p.lower() for p in parts)
    _parts_nc      = nom_complet.split()
    _nom_court_bio = f"{_parts_nc[0]} {_parts_nc[-1]}" if len(_parts_nc) > 2 else nom_complet
    _bio_slug_low  = _to_bio_slug(_nom_court_bio, title_case=False)   # faure-gnassingbe
    _bio_slug_cap  = _to_bio_slug(_nom_court_bio, title_case=True)    # Faure-Gnassingbe
    _britannica_url   = f"https://www.britannica.com/biography/{_bio_slug_cap}"
    _notreafrik_url   = f"https://notreafrik.com/{_bio_slug_low}"
    _jeuneafrique_url = f"https://www.jeuneafrique.com/personnalites/{_bio_slug_low}/"

    # ── Tier 2b : Google Custom Search — thread principal ────────────────────────
    print(f"  [Tier 2b] Google — recherche web complémentaire...")
    resultats_google, urls_google, urls_google_media = rechercher_google(nom_complet, pays_nom, code_iso)

    # Extraire les slugs Wikipedia trouvés par Serper — ajoutés en priorité à la liste de l'API Wiki
    _wiki_slugs_serper = []
    for _u in urls_google:
        if "wikipedia.org/wiki/" in _u:
            _s = _u.split("/wiki/")[-1].split("#")[0]
            if _s and _s not in _wiki_slugs_serper:
                _wiki_slugs_serper.append(_s)

    # ── Découverte dynamique du site officiel gouvernemental ─────────────────────
    print(f"  [Découverte] Site officiel gouvernement {pays_nom}...")
    _res_disc = _tavily_invoke(
        tavily,
        f"site officiel gouvernement {pays_nom} composition membres ministres 2025",
        f"découverte site {code_iso}"
    )
    urls_discovery = []
    if _res_disc:
        import re as _re
        for _u in _re.findall(r'https?://[^\s\'"<>]+', str(_res_disc)):
            _u = _u.rstrip(".,;)")
            if est_source_officielle(_u) and _u not in urls_discovery:
                urls_discovery.append(_u)
    if urls_discovery:
        print(f"  [Découverte] {len(urls_discovery)} URLs officielles trouvées dynamiquement : {urls_discovery[:3]}")
    else:
        print(f"  [Découverte] Aucune URL officielle nouvelle trouvée")

    # ── Phase 1 : OpenSanctions API — toujours l'API pour la vérification (traçabilité audit) ──
    os_result = {}
    print(f"  [Tier 3] OpenSanctions API — vérification {nom_complet}...")
    try:
        os_result = rechercher_opensanctions(nom_complet, code_iso)
    except Exception as e:
        print(f"  [Tier 3] OpenSanctions erreur : {e}")

    # Extraire UNIQUEMENT les URLs sources officielles citées par OpenSanctions (pas la page OS elle-même)
    urls_opensanctions = []
    for ent in os_result.get("entites", []):
        for prop_url in ent.get("sourceUrl", []):
            if prop_url and prop_url.startswith("http") and "opensanctions.org" not in prop_url:
                urls_opensanctions.append(prop_url)

    # ── Phase 2 : Scrapling avec TOUTES les URLs — gouvernement + Tavily + Serper + OpenSanctions + Wikipedia ──
    # Certains domaines officiels ne fonctionnent pas avec www. (ex: presidence.bj, assemblee-nationale.bj)
    _DOMAINES_SANS_WWW = {
        "presidence.bj", "assemblee-nationale.bj", "presidence.sn",
        "assemblee-nationale.sn", "presidence.mr",
    }
    urls_pays = [
        f"https://{d}" if d in _DOMAINES_SANS_WWW else f"https://www.{d}"
        for d in DOMAINES_OFFICIELS_PAR_PAYS.get(code_iso.upper(), [])
    ]

    # URLs médias Serper ajoutées EN FIN de liste — Scrapling tente officiel d'abord
    urls_scraping = list(dict.fromkeys(
        urls_pays + urls_discovery + urls_tavily + urls_google + urls_opensanctions
        + [_wiki_url, _britannica_url, _notreafrik_url, _jeuneafrique_url] + urls_google_media
    ))
    if urls_pays:
        print(f"  [URLs off] {len(urls_pays)} sites officiels : {', '.join(u.replace('https://www.','').replace('https://','')[:35] for u in urls_pays)}")
    print(f"  [Bio sources] britannica/{_bio_slug_cap} | notreafrik/{_bio_slug_low} | jeuneafrique/personnalites/{_bio_slug_low}")
    if urls_google_media:
        print(f"  [Serper médias] {len(urls_google_media)} articles médias injectés dans Scrapling : {urls_google_media[0][:60]}")

    contenu_json = {}

    def _run_scrapling():
        if not urls_scraping:
            return {}
        print(f"  [Tier 1] Scrapling — {len(urls_scraping)} URLs (pays:{len(urls_pays)} + Tavily:{len(urls_tavily)} + OS:{len(urls_opensanctions)})...")
        return scraper_json_officiel(nom_complet, urls_scraping, code_iso=code_iso)

    def _run_wiki_api():
        """Wikipedia API texte + extraction des liens officiels.
        Essaie plusieurs permutations du nom pour gérer les noms inversés."""
        try:
            import requests as _rq
            from bs4 import BeautifulSoup as _BS

            # Générer toutes les permutations du nom à tester
            _parts = [p.capitalize() for p in nom_complet.strip().split() if len(p) > 1]
            _slugs_a_tester = []
            _slugs_a_tester.append("_".join(_parts))                        # ordre original
            if len(_parts) >= 2:
                _slugs_a_tester.append("_".join(reversed(_parts)))          # ordre inversé
            if len(_parts) == 3:
                _slugs_a_tester.append(f"{_parts[2]}_{_parts[0]}_{_parts[1]}")  # dernier en premier
                _slugs_a_tester.append(f"{_parts[1]}_{_parts[2]}_{_parts[0]}")  # variante 3
            # Ajouter les slugs trouvés par Serper en tête de liste (déjà validés par Google)
            _slugs_a_tester = _wiki_slugs_serper + _slugs_a_tester
            # Dédoublonner en gardant l'ordre
            _seen = set()
            _slugs_uniq = [s for s in _slugs_a_tester if not (s in _seen or _seen.add(s))]

            texte     = ""
            slug_ok   = _wiki_slug

            # Étape 1 : essayer les permutations du nom
            for _slug in _slugs_uniq:
                try:
                    _rw = _rq.get(
                        "https://fr.wikipedia.org/w/api.php",
                        params={
                            "action": "query", "titles": _slug,
                            "prop": "extracts", "explaintext": True,
                            "exsectionformat": "plain", "format": "json", "redirects": 1,
                        },
                        timeout=10, headers={"User-Agent": "PEPAgent/1.0"},
                    )
                    _pages = _rw.json().get("query", {}).get("pages", {})
                    _page  = next(iter(_pages.values()))
                    if "-1" in _pages or _page.get("missing") is not None:
                        continue
                    _texte = _page.get("extract", "") or ""
                    if _texte and len(_texte) > 200:
                        texte   = _texte
                        slug_ok = _slug
                        if _slug != _wiki_slug:
                            print(f"  [Wiki slug] '{_wiki_slug}' → '{_slug}' (permutation trouvée)")
                        break
                except Exception:
                    continue

            # Étape 2 : si permutations échouent → recherche Wikipedia comme Google
            if not texte:
                try:
                    _rs = _rq.get(
                        "https://fr.wikipedia.org/w/api.php",
                        params={
                            "action": "query", "list": "search",
                            "srsearch": nom_complet, "srlimit": 5,
                            "format": "json",
                        },
                        timeout=10, headers={"User-Agent": "PEPAgent/1.0"},
                    )
                    _hits = _rs.json().get("query", {}).get("search", [])
                    for _hit in _hits:
                        _titre = _hit.get("title", "")
                        _titre_norm = _titre.lower()
                        # Vérifier que le résultat concerne bien cette personne
                        if not any(p.lower() in _titre_norm for p in _parts if len(p) > 2):
                            continue
                        _slug_found = _titre.replace(" ", "_")
                        _rw2 = _rq.get(
                            "https://fr.wikipedia.org/w/api.php",
                            params={
                                "action": "query", "titles": _slug_found,
                                "prop": "extracts", "explaintext": True,
                                "exsectionformat": "plain", "format": "json", "redirects": 1,
                            },
                            timeout=10, headers={"User-Agent": "PEPAgent/1.0"},
                        )
                        _pages2 = _rw2.json().get("query", {}).get("pages", {})
                        _page2  = next(iter(_pages2.values()))
                        _texte2 = _page2.get("extract", "") or ""
                        if _texte2 and len(_texte2) > 200:
                            texte   = _texte2
                            slug_ok = _slug_found
                            print(f"  [Wiki search] '{nom_complet}' → '{_titre}' (recherche Wikipedia)")
                            break
                except Exception:
                    pass

            if not texte:
                return "", []

            # Extraire liens officiels depuis la page HTML Wikipedia
            _url_ok = f"https://fr.wikipedia.org/wiki/{slug_ok}"
            try:
                _rh = _rq.get(_url_ok, timeout=8, verify=False,
                               headers={"User-Agent": "Mozilla/5.0 (compatible; PEPAgent/1.0)"})
                if _rh.status_code == 200:
                    _soup  = _BS(_rh.text, "html.parser")
                    _links = [a.get("href","") for a in _soup.find_all("a", href=True)]
                    _off   = [l for l in _links if l.startswith("http") and est_source_officielle(l)
                              and "wikipedia.org" not in l and "wikimedia.org" not in l]
                    _off   = list(dict.fromkeys(_off))[:5]
                    if _off:
                        print(f"  [Wiki liens] {len(_off)} URLs officielles extraites de Wikipedia : {_off[:3]}")
                    return texte, _off
            except Exception:
                pass
            return texte, []
        except Exception as _ew:
            print(f"  [Tier 2+] Wikipedia API erreur : {_ew}")
            _log_source_erreur(nom_complet, "Wikipedia", str(_ew))
            return "", []

    # Phase 2a : Wikipedia en premier (rapide) pour récupérer ses liens officiels
    urls_wiki_off = []
    with ThreadPoolExecutor(max_workers=1) as pool_w:
        f_wiki = pool_w.submit(_run_wiki_api)
        try:
            _wiki_result = f_wiki.result(timeout=15)
            texte_wiki, urls_wiki_off = _wiki_result if isinstance(_wiki_result, tuple) else (_wiki_result, [])
            if texte_wiki:
                print(f"  [Tier 2+] Wikipedia API — {len(texte_wiki)} chars / {len(texte_wiki.split())} mots")
            else:
                print(f"  [Tier 2+] Wikipedia API — 0 chars (aucun article trouvé pour {nom_complet!r})")
                _log_source_erreur(nom_complet, "Wikipedia", f"0 chars — aucun article pour {nom_complet!r}")
        except Exception as _ew:
            texte_wiki, urls_wiki_off = "", []
            print(f"  [Tier 2+] Wikipedia timeout/erreur : {_ew}")
            _log_source_erreur(nom_complet, "Wikipedia", f"timeout/erreur : {_ew}")

    # Injecter les URLs officielles Wikipedia dans Scrapling AVANT de lancer
    if urls_wiki_off:
        urls_scraping = list(dict.fromkeys(urls_scraping + urls_wiki_off))
        print(f"  [Wiki liens] {len(urls_wiki_off)} URLs injectées dans Scrapling")

    # Phase 2b : Scrapling avec toutes les URLs (pays + OS + Wiki liens)
    with ThreadPoolExecutor(max_workers=1) as pool_s:
        f_scraping = pool_s.submit(_run_scrapling)
        try:
            contenu_json = f_scraping.result(timeout=45)
        except Exception as e:
            print(f"  [Tier 1] Scrapling timeout : {e}")

    # ── Construction corpus unifié — Wikipedia en tête (titres complets), puis Tier 1, Tier 2, Tier 3 ──
    parties = []

    # Wikipedia EN PREMIER — contient les titres constitutionnels complets
    if texte_wiki:
        parties.append(f"=== TIER 2 — WIKIPEDIA [WIKI🔍] ===\n{texte_wiki[:20000]}")
    elif extrait_wiki:
        parties.append(f"=== TIER 2 — WIKIPEDIA [WIKI🔍] ===\n{extrait_wiki[:20000]}")

    # Tier 1 — Scrapling (source officielle directe, poids maximal)
    if contenu_json.get("nominations"):
        parties.append(
            f"=== TIER 1 — SCRAPLING OFFICIEL [OFFICIEL✅] — {contenu_json['source']} ===\n"
            + json.dumps(contenu_json["nominations"], ensure_ascii=False, indent=2)
        )
        texte_brut_nom = "\n".join(
            f"{n.get('nom','')} {n.get('fonction','')}".strip()
            for n in contenu_json["nominations"] if n.get("nom")
        )
        if texte_brut_nom.strip():
            parties.append(f"=== TIER 1 — SCRAPLING CORPUS BRUT [OFFICIEL✅] ===\n{texte_brut_nom}")
    elif contenu_json.get("texte_brut"):
        parties.append(f"=== TIER 1 — SCRAPLING OFFICIEL (texte) [OFFICIEL✅] — {contenu_json['source']} ===\n{contenu_json['texte_brut']}")

    # Tier 2 — Tavily (recherche web)
    if resultats_tavily.strip():
        parties.append(f"=== TIER 2 — TAVILY RECHERCHE WEB ===\n{resultats_tavily}")

    # Tier 2b — Google Custom Search
    if resultats_google.strip():
        parties.append(f"=== TIER 2b — GOOGLE SEARCH ===\n{resultats_google}")

    # Tier 3 — OpenSanctions (complément compliance)
    if os_result.get("entites"):
        # Marqueur structuré pour extraction pays sans regex fragile
        _os_pays = []
        for _ent in os_result["entites"]:
            for _p in (_ent.get("pays") or []):
                if isinstance(_p, str) and len(_p) == 2 and _p.upper() not in _os_pays:
                    _os_pays.append(_p.upper())
        _os_pays_tag = f"[OS_PAYS:{','.join(_os_pays) if _os_pays else 'XX'}]"
        entites_str = json.dumps(os_result["entites"], ensure_ascii=False, indent=2)
        parties.append(f"=== TIER 3 — OPENSANCTIONS [COMPLIANCE✅] ===\n{_os_pays_tag}\n{entites_str}")

    if not parties:
        parties.append("Aucun résultat trouvé sur les sources Tier 1/2/3.")

    return "\n\n".join(parties)


# ── Consensus multi-sources ─────────────────────────────────────────────────────

def consensus_sources(nom_complet: str, pays_nom: str, code_iso: str,
                      llm, min_sources: int = 2) -> dict:
    """
    Consulte plusieurs sources indépendantes et retourne la fonction
    validée par consensus.

    Retourne :
    {
        "fonction": fonction retenue (None si pas de consensus),
        "score":    nombre de sources qui confirment,
        "total":    nombre de sources consultées,
        "details":  [{"source": url, "fonction": f}, ...]
    }
    """
    nom_parts    = [p.lower() for p in nom_complet.split() if len(p) > 2]
    sites_pays   = DOMAINES_OFFICIELS_PAR_PAYS.get(code_iso.upper(), [])
    annee        = datetime.now().year

    resultats_par_source = []

    # Interroger chaque source — demander la fonction ACTUELLE en {annee}
    for site in sites_pays[:6]:
        q = f'site:{site} "{nom_complet}" {annee} OR {annee-1}'
        try:
            res = _tavily_invoke(tavily, q, f"consensus: {site}")
            if not res:
                continue
            texte = str(res)
            if not any(p in texte.lower() for p in nom_parts):
                continue

            extrait = extraire_passages_nom(texte, nom_complet)
            if not extrait:
                continue

            # Détecter l'année mentionnée dans l'extrait
            annees_trouvees = re.findall(r'20\d{2}', extrait)
            annee_source    = max((int(a) for a in annees_trouvees), default=0)

            prompt_mini = f"""Source : {site} (année détectée : {annee_source or 'inconnue'})
Texte : {extrait[:6000]}
Année courante : {annee}

Quelle est la fonction ACTUELLE de {nom_complet} en {annee} selon ce texte ?
Réponds avec SEULEMENT le titre/fonction en français, ou "inconnu"."""

            resp = llm.invoke(prompt_mini)
            fonction_brute = resp.content.strip().lower()

            if fonction_brute not in ("inconnu", "", "non mentionné", "non disponible"):
                resultats_par_source.append({
                    "source":       f"site:{site}",
                    "fonction":     resp.content.strip(),
                    "annee_source": annee_source,
                })

        except Exception:
            continue

    if not resultats_par_source:
        return {"fonction": None, "score": 0, "poids": 0, "total": 0, "details": [], "confiant": False}

    def normaliser(f: str) -> str:
        mots = f.lower().split()
        return " ".join(mots[:4]) if mots else ""

    # Pondérer par récence : source de l'année courante = poids 3, précédente = 2, plus ancien = 1
    poids_par_fonction: dict = {}
    for r in resultats_par_source:
        cle    = normaliser(r["fonction"])
        poids  = 3 if r["annee_source"] == annee else (2 if r["annee_source"] == annee - 1 else 1)
        poids_par_fonction[cle] = poids_par_fonction.get(cle, 0) + poids

    # Fonction avec le plus grand poids pondéré
    fonction_consensus = max(poids_par_fonction, key=poids_par_fonction.get)
    score_pondere      = poids_par_fonction[fonction_consensus]
    score_brut         = sum(1 for r in resultats_par_source if normaliser(r["fonction"]) == fonction_consensus)

    fonction_complete = next(
        (r["fonction"] for r in sorted(resultats_par_source,
                                        key=lambda x: x["annee_source"], reverse=True)
         if normaliser(r["fonction"]) == fonction_consensus),
        fonction_consensus
    )

    print(f"  Consensus pondéré : {score_brut} source(s) | poids={score_pondere} → '{fonction_complete}'")

    # Confiant si poids pondéré >= seuil (une source récente 2026 vaut 3 points)
    seuil  = min_sources * 2
    confiant = score_pondere >= seuil or (score_brut >= min_sources)

    return {
        "fonction": fonction_complete if confiant else None,
        "score":    score_brut,
        "poids":    score_pondere,
        "total":    len(resultats_par_source),
        "details":  resultats_par_source,
        "confiant": confiant,
    }


# ── URLs prédéfinies (fallback Tool 3) ──────────────────────────────────────────

URLS_GOUVERNEMENTALES = {
    "MA": ["https://maroc.ma/fr", "https://www.cg.gov.ma/fr", "https://www.chambredesrepresentants.ma/fr", "https://www.bkam.ma/fr"],
    "DZ": ["https://www.bank-of-algeria.dz/fr"],                          # premier-ministre.gov.dz + el-mouradia.dz inaccessibles
    "TN": ["https://www.carthage.tn", "https://www.arp.tn"],              # gouvernement.tn inaccessible
    "LY": ["https://www.cbl.gov.ly"],                                     # gov.ly inaccessible
    "SN": ["https://www.presidence.sn/fr/institutions/le-gouvernement/", "http://www.assemblee-nationale.sn", "https://www.bceao.int/gouvernance"],
    "CI": ["https://www.gouv.ci/gouvernement"],
    "ML": ["https://www.koulouba.ml"],                                    # primature.gov.ml inaccessible
    "BF": ["https://www.gouvernement.gov.bf", "https://www.sig.gov.bf/gouvernement"],  # IncompleteRead — Scrapling peut mieux gérer
    "NE": ["https://www.gouv.ne"],                                        # /gouvernement → 404, root OK
    "TG": ["https://presidenceduconseil.gouv.tg", "https://www.togofirst.com"],
    "BJ": ["https://www.gouv.bj", "https://www.presidence.bj", "https://www.assemblee-nationale.bj"],  # /gouvernement → 404
    "GW": [],                                                             # gov.gw inaccessible — Serper uniquement
    "GN": ["https://www.gouvernement.gov.gn/gouvernement/composition", "https://www.bcrg-guinee.org"],
}
