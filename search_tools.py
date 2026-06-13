"""
search_tools.py — ScreenEdge Africa
3 tools de recherche pour l'agent PEP.

Hiérarchie des sources :
  Tier 1 — Officielle directe  : gouvernements, JO, banques centrales, CENTIF, agences d'État
  Tier 2 — Secondaire fiable   : AFP, Reuters, RFI, médias spécialisés → recoupement obligatoire
  Tier 3 — Référence compliance: OpenSanctions, OCCRP, FATF → alerte/enrichissement seulement
"""

import sys, re, json, unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

from langchain_tavily import TavilySearch
from dotenv import load_dotenv

load_dotenv(override=True)

tavily = TavilySearch(max_results=10, search_depth="advanced")

# ── Compteur global Tavily ───────────────────────────────────────────────────────
_tavily_compteur = {"total": 0, "par_personne": 0}

def _tavily_invoke(instance, query: str, label: str = "") -> any:
    """Wrapper Tavily avec comptage automatique."""
    _tavily_compteur["total"]       += 1
    _tavily_compteur["par_personne"] += 1
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
        # Tier 1
        "gouvernement.ma", "maroc.ma", "cg.gov.ma", "parlement.ma",
        "chambredesrepresentants.ma", "chambredesconseillers.ma",
        "bkam.ma", "utrf.gov.ma", "ammc.ma", "acaps.ma",
        "jo.gov.ma", "bulletinofficiel.ma",
    ],
    "DZ": [
        "el-mouradia.dz", "premier-ministre.gov.dz",
        "apn.dz", "senat.dz",
        "bank-of-algeria.dz", "ctrf.gov.dz", "joradp.dz",
    ],
    "TN": [
        "carthage.tn", "gouvernement.tn", "arp.tn",
        "bct.gov.tn", "ctaf.gov.tn", "jo.gov.tn",
    ],
    "LY": [
        "gov.ly", "hor.ly", "cbl.gov.ly", "fiulibya.gov.ly",
    ],
    "SN": [
        "presidence.sn", "gouvernement.sn", "assemblee-nationale.sn",
        "centif.sn", "jo.gouv.sn", "aps.sn",
        "bceao.int",
    ],
    "CI": [
        "presidence.ci", "gouv.ci", "assemblee-nationale.ci", "senat.ci",
        "centif-ci.ci", "jo.ci", "aip.ci",
        "bceao.int",
    ],
    "ML": [
        "koulouba.ml", "primature.gov.ml", "amap.ml",
        "bceao.int",
    ],
    "BF": [
        "gouvernement.gov.bf", "sig.gov.bf", "centif.bf",
        "aib.bf", "fasonet.bf",
        "bceao.int",
    ],
    "NE": [
        "presidence.ne", "gouv.ne", "centif.ne", "anp.ne",
        "bceao.int",
    ],
    "TG": [
        "presidence.gouv.tg", "togo.gouv.tg",
        "assemblee-nationale.tg", "centif.tg", "jo.gouv.tg",
        "atop.tg", "bceao.int",
    ],
    "BJ": [
        "presidence.bj", "gouv.bj", "assemblee-nationale.bj",
        "centif.bj", "jo.gouv.bj", "abp.bj",
        "bceao.int",
    ],
    "GW": [
        "gov.gw", "bceao.int",
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
        res = _tavily_invoke(tavily, f'site:wikipedia.org "{nom_complet}" politique gouvernement', "Wikipedia liens officiels")
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
        return contenu[:2000]

    avec_fonction = [p for p in passages if any(m in _normaliser(p) for m in mots_fonction)]
    selection     = avec_fonction if avec_fonction else passages
    resultat      = "\n\n---\n\n".join(selection[:5])

    # Si trop peu de contenu extrait → compléter avec le début du corpus brut
    if len(resultat.split()) < 300:
        resultat += "\n\n---\n\n[CORPUS BRUT]\n" + contenu[:2000]

    return resultat


# ── TOOL 2 : Scrapling structuré — extraction JSON depuis pages officielles ─────

def scraper_json_officiel(nom_complet: str, urls: list[str]) -> dict:
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

    try:
        from scrapling.fetchers import StealthyFetcher
        fetcher = StealthyFetcher()
        use_scrapling = True
    except Exception:
        use_scrapling = False

    import requests
    from bs4 import BeautifulSoup

    for url in urls:
        if not est_source_officielle(url):
            continue
        try:
            # Scrapling en priorité (gère JS), requests en fallback
            if use_scrapling:
                try:
                    page     = fetcher.fetch(url)
                    html_str = str(page.html_content) if hasattr(page, 'html_content') else ""
                    if not html_str:
                        raise ValueError("Scrapling vide")
                    soup = BeautifulSoup(html_str, "html.parser")
                except Exception:
                    r    = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
                    soup = BeautifulSoup(r.text, "html.parser")
            else:
                r    = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
                soup = BeautifulSoup(r.text, "html.parser")

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
                return {"source": url, "texte_brut": extrait[:2000]}

        except Exception as e:
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

    # Tier 2 — toujours interrogé (pas seulement en fallback)
    # Pas de contrainte d'année — couvre aussi les ex-PEP (coups, démissions, retraites passées)
    for site in ["rfi.fr", "afp.com", "jeuneafrique.com", "reuters.com"]:
        try:
            res = _tavily_invoke(tavily, f'site:{site} "{nom_complet}" fonction OR président OR ministre OR ancien', f"media: {site}")
            if res:
                texte = str(res)
                if any(p in texte.lower() for p in nom_parts):
                    resultats_bruts.append(f"[MEDIA TIER2 — {site}]\n{texte}")
                    break
        except Exception:
            continue

    brut    = "\n\n".join(resultats_bruts)
    filtre  = filtrer_resultats(brut)
    annote  = annoter_sources(filtre)        # annoter chaque URL avec son niveau
    extrait = extraire_passages_nom(annote, nom_complet)

    return extrait, list(set(urls_officielles))


# ── TIER 2b : Google Custom Search — complément Tavily ─────────────────────────

def rechercher_google(nom_complet: str, pays_nom: str, code_iso: str) -> tuple[str, list[str]]:
    """
    Serper.dev (Google Search) — Tier 2 complémentaire à Tavily.
    Nécessite serper_dev_aoi_key dans .env. 2500 requêtes/mois gratuites.
    Retourne (texte_corpus_annoté, urls_officielles)
    """
    import os, requests as req_g
    api_key = os.getenv("serper_dev_aoi_key", "")
    if not api_key:
        print(f"  [Tier 2b] Serper — clé manquante → ignoré")
        return "", []

    nom_parts = [p.lower() for p in nom_complet.split() if len(p) > 2]

    # Requêtes principales (fonction/statut) + 1 requête dédiée aux dates de nomination
    requetes_principales = [
        f'"{nom_complet}" président OR ministre {pays_nom}',
        f'"{nom_complet}" ancien président OR ex-président {pays_nom}',
    ]
    requete_date = f'"{nom_complet}" élu OR investi OR nommé OR "prise de fonctions"'

    resultats_bruts  = []
    urls_officielles = []

    # Requêtes principales — break après la 1ère réussie
    for q in requetes_principales:
        try:
            r = req_g.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": q, "hl": "fr", "num": 10},
                timeout=8,
            )
            if r.status_code != 200:
                print(f"  [Tier 2b] Serper HTTP {r.status_code}")
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

            if parties_q:
                resultats_bruts.append("[SERPER/GOOGLE]\n" + "\n\n".join(parties_q))
                break
        except Exception as e:
            print(f"  [Tier 2b] Serper erreur : {e}")
            continue

    # Requête dédiée aux dates — toujours exécutée, résultats ajoutés au corpus
    try:
        r_date = req_g.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": requete_date, "hl": "fr", "num": 10},
            timeout=8,
        )
        if r_date.status_code == 200:
            items_date = r_date.json().get("organic", [])
            parties_date = []
            for item in items_date:
                url     = item.get("link", "")
                titre   = item.get("title", "")
                snippet = item.get("snippet", "")
                texte   = f"{url}\n{titre}\n{snippet}"
                if any(p in texte.lower() for p in nom_parts):
                    parties_date.append(texte)
            if parties_date:
                resultats_bruts.append("[SERPER/DATE]\n" + "\n\n".join(parties_date))
    except Exception:
        pass

    if not resultats_bruts:
        print(f"  [Tier 2b] Serper — 0 résultat pertinent")
        return "", []

    brut    = "\n\n".join(resultats_bruts)
    filtre  = filtrer_resultats(brut)
    annote  = annoter_sources(filtre)
    extrait = extraire_passages_nom(annote, nom_complet)

    nb_off = len(urls_officielles)
    print(f"  [Tier 2b] Serper — {len(extrait.split())} mots | {nb_off} URLs off")
    return extrait, list(set(urls_officielles))


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
                "pays":       props.get("country", [code_iso]),
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

    # Wikipedia via Tavily — thread principal
    print(f"  [Tier 2+] Wikipedia — corpus + liens officiels...")
    res_wiki   = _tavily_invoke(tavily, f'site:wikipedia.org "{nom_complet}"', "Wikipedia corpus")
    texte_wiki = filtrer_resultats(str(res_wiki)) if res_wiki else ""
    extrait_wiki = ""
    if texte_wiki and any(p in texte_wiki.lower() for p in [n.lower() for n in nom_complet.split() if len(n)>2]):
        extrait_wiki = extraire_passages_nom(texte_wiki, nom_complet)
    liens_wiki = extraire_liens_officiels_wikipedia(nom_complet)

    # ── Tier 2b : Google Custom Search — thread principal ────────────────────────
    print(f"  [Tier 2b] Google — recherche web complémentaire...")
    resultats_google, urls_google = rechercher_google(nom_complet, pays_nom, code_iso)

    # ── Tier 1 + Tier 3 : Scrapling & OpenSanctions — en parallèle ──────────────
    urls_pays     = [f"https://{d}" for d in DOMAINES_OFFICIELS_PAR_PAYS.get(code_iso.upper(), [])]
    urls_scraping = list(dict.fromkeys(urls_pays + urls_tavily + urls_google))  # pays en priorité, pas de doublon

    contenu_json  = {}
    contenu_wiki_off = {}
    os_result     = {}

    def _run_scrapling():
        if not urls_scraping:
            return {}
        print(f"  [Tier 1] Scrapling — {len(urls_scraping)} URLs (pays:{len(urls_pays)} + Tavily:{len(urls_tavily)})...")
        return scraper_json_officiel(nom_complet, urls_scraping)

    def _run_wiki_scraping():
        if not liens_wiki:
            return {}
        return scraper_json_officiel(nom_complet, liens_wiki)

    def _run_opensanctions():
        print(f"  [Tier 3] OpenSanctions — recherche {nom_complet}...")
        return rechercher_opensanctions(nom_complet, code_iso)

    with ThreadPoolExecutor(max_workers=3) as pool:
        f_scraping = pool.submit(_run_scrapling)
        f_wiki_off = pool.submit(_run_wiki_scraping)
        f_os       = pool.submit(_run_opensanctions)
        try:
            contenu_json     = f_scraping.result(timeout=45)
        except Exception as e:
            print(f"  [Tier 1] Scrapling timeout : {e}")
        try:
            contenu_wiki_off = f_wiki_off.result(timeout=20)
        except Exception:
            pass
        try:
            os_result        = f_os.result(timeout=15)
        except Exception as e:
            print(f"  [Tier 3] OpenSanctions timeout : {e}")

    # ── Construction corpus unifié — Tier 1 + Tier 2 + Tier 3 ───────────────────
    parties = []

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

    # Tier 2+ — Wikipedia
    if extrait_wiki:
        parties.append(f"=== TIER 2 — WIKIPEDIA [WIKI🔍] ===\n{extrait_wiki[:800]}")
    if contenu_wiki_off.get("nominations"):
        parties.append(
            f"=== TIER 2 — VIA WIKIPEDIA → OFFICIEL [OFFICIEL✅] — {contenu_wiki_off['source']} ===\n"
            + json.dumps(contenu_wiki_off["nominations"], ensure_ascii=False, indent=2)
        )
    elif contenu_wiki_off.get("texte_brut"):
        parties.append(f"=== TIER 2 — VIA WIKIPEDIA → OFFICIEL [OFFICIEL✅] ===\n{contenu_wiki_off['texte_brut']}")

    # Tier 3 — OpenSanctions (complément compliance)
    if os_result.get("entites"):
        entites_str = json.dumps(os_result["entites"], ensure_ascii=False, indent=2)
        parties.append(f"=== TIER 3 — OPENSANCTIONS [COMPLIANCE✅] ===\n{entites_str}")

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
Texte : {extrait[:800]}
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
    "MA": ["https://www.gouvernement.ma/membres-du-gouvernement","https://www.maroc.ma","https://www.chambredesrepresentants.ma"],
    "DZ": ["https://www.premier-ministre.gov.dz/fr/gouvernement/membres-du-gouvernement","https://www.el-mouradia.dz"],
    "TN": ["https://www.gouvernement.tn/gouvernement/membres","https://www.carthage.tn"],
    "LY": ["https://www.gov.ly","https://www.cbl.gov.ly"],
    "SN": ["https://www.gouvernement.sn/membres-du-gouvernement","https://www.presidence.sn","https://www.aps.sn"],
    "CI": ["https://www.gouv.ci/membres-gouvernement","https://www.presidence.ci","https://www.aip.ci"],
    "ML": ["https://www.primature.gov.ml","https://www.koulouba.ml","https://www.amap.ml"],
    "BF": ["https://www.gouvernement.gov.bf","https://www.sig.gov.bf","https://www.aib.bf"],
    "NE": ["https://www.gouv.ne/gouvernement","https://www.presidence.ne","https://www.anp.ne"],
    "TG": ["https://www.gouv.tg/gouvernement","https://www.presidence.tg","https://www.republicoftogo.com"],
    "BJ": ["https://www.gouv.bj/gouvernement","https://www.presidence.bj","https://www.abp.bj"],
    "GW": ["https://www.gov.gw"],
    "GN": ["https://www.gouvernement.gov.gn","https://www.presidence.gov.gn","https://www.agpguinee.com"],
}
