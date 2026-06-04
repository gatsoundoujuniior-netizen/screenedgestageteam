"""
search_tools.py — ScreenEdge Africa
3 tools de recherche pour l'agent PEP.

Hiérarchie des sources :
  Tier 1 — Officielle directe  : gouvernements, JO, banques centrales, CENTIF, agences d'État
  Tier 2 — Secondaire fiable   : AFP, Reuters, RFI, médias spécialisés → recoupement obligatoire
  Tier 3 — Référence compliance: OpenSanctions, OCCRP, FATF → alerte/enrichissement seulement
"""

import sys, re, json
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

from langchain_tavily import TavilySearch
from dotenv import load_dotenv

load_dotenv(override=True)

tavily = TavilySearch(max_results=10, search_depth="advanced")

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
        "presidence.tg", "gouv.tg", "assemblee-nationale.tg",
        "centif.tg", "republicoftogo.com", "jo.gouv.tg",
        "bceao.int",
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
        res = tavily.invoke({
            "query": f'site:wikipedia.org "{nom_complet}" politique gouvernement'
        })
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

def extraire_passages_nom(contenu: str, nom_complet: str) -> str:
    """Extrait les passages autour du nom avec mots-clés de fonction."""
    if not contenu or not nom_complet:
        return contenu or ""

    nom_parts   = [p.lower() for p in nom_complet.split() if len(p) > 2]
    mots_fonction = [
        'ministre', 'président', 'directeur', 'nommé', 'nomination',
        'décret', 'secrétaire', 'ambassadeur', 'conseil des ministres',
        'gouverneur', 'haut commissaire', 'premier ministre', 'chef',
        'minister', 'appointed', 'designated', 'named',
    ]

    lignes   = contenu.split("\n")
    passages = []

    for i, ligne in enumerate(lignes):
        if any(p in ligne.lower() for p in nom_parts):
            debut    = max(0, i - 3)
            fin      = min(len(lignes), i + 4)
            contexte = "\n".join(lignes[debut:fin])
            passages.append(contexte)

    if not passages:
        return contenu[:2000]

    avec_fonction = [p for p in passages if any(m in p.lower() for m in mots_fonction)]
    selection     = avec_fonction if avec_fonction else passages

    return "\n\n---\n\n".join(selection[:5])


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

    for url in urls[:4]:
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
            for li in soup.find_all(["li", "p", "div"]):
                texte = li.get_text(strip=True)
                if len(texte) < 5 or len(texte) > 300:
                    continue
                if any(p in texte.lower() for p in nom_parts):
                    # Pattern "Nom, Fonction" ou "Nom : Fonction"
                    match = re.split(r',\s*|:\s*|–\s*|-\s*', texte, maxsplit=1)
                    if len(match) == 2:
                        nominations.append({
                            "nom":      match[0].strip(),
                            "fonction": match[1].strip(),
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
                # Si aucune après filtre → garder toutes mais marquer
                selection = nominations_filtrees if nominations_filtrees else nominations[:5]
                print(f"  Scrapling JSON : {len(selection)} entrées pertinentes (/{len(nominations)} total) depuis {url}")
                return {
                    "source":      url,
                    "nominations": selection[:10],
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

def recherche_tavily(nom_complet: str, pays_nom: str, code_iso: str):
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
            res = tavily.invoke({"query": q})
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
                res = tavily.invoke({"query": f'site:{site} "{nom_complet}"'})
                if res:
                    texte = str(res)
                    if any(p in texte.lower() for p in nom_parts):
                        resultats_bruts.append(f"[FALLBACK — {site}]\n{texte}")
                        urls = re.findall(r'https?://[^\s\'">,]+', texte)
                        urls_officielles += [u for u in urls if est_source_officielle(u)]
                        break
            except Exception:
                continue

    # Tier 2 — toujours interrogé (pas seulement en fallback)
    for site in ["rfi.fr", "afp.com", "jeuneafrique.com", "reuters.com"]:
        try:
            res = tavily.invoke({"query": f'site:{site} "{nom_complet}" {annee} OR {annee-1}'})
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


# ── Interface principale ─────────────────────────────────────────────────────────

def rechercher_pep(nom_complet: str, pays_nom: str, code_iso: str) -> str:
    """
    Recherche complète en 3 étapes :
    1. Tavily → cherche et extrait passages ciblés
    2. Scrapling → extrait JSON structuré depuis URLs officielles
    3. Fallback → sites gouvernementaux prédéfinis
    """
    # ── Collecte parallèle toutes sources ────────────────────────────────────────
    print(f"\n  [Tool 1] Tavily libre + prédéfini...")
    resultats_tavily, urls_officielles = recherche_tavily(nom_complet, pays_nom, code_iso)
    print(f"  → {len(urls_officielles)} URLs officielles | {len(resultats_tavily.split())} mots")

    # Tool 2 : Scrapling JSON structuré
    contenu_json = {}
    if urls_officielles:
        print(f"  [Tool 2] Scrapling JSON sur {min(4, len(urls_officielles))} URLs...")
        contenu_json = scraper_json_officiel(nom_complet, urls_officielles)

    # Tool 3 : Wikipedia — contenu + liens officiels (poids faible)
    print(f"  [Tool 3] Wikipedia — corpus + liens officiels...")
    res_wiki   = tavily.invoke({"query": f'site:wikipedia.org "{nom_complet}"'})
    texte_wiki = filtrer_resultats(str(res_wiki)) if res_wiki else ""
    if texte_wiki and any(p in texte_wiki.lower() for p in [n.lower() for n in nom_complet.split() if len(n)>2]):
        extrait_wiki = extraire_passages_nom(texte_wiki, nom_complet)
    else:
        extrait_wiki = ""

    liens_wiki       = extraire_liens_officiels_wikipedia(nom_complet)
    contenu_wiki_off = {}
    if liens_wiki:
        contenu_wiki_off = scraper_json_officiel(nom_complet, liens_wiki)

    # ── Construction corpus de comparaison ───────────────────────────────────────
    parties = []

    # Source prioritaire : données JSON officielles
    if contenu_json.get("nominations"):
        parties.append(
            f"=== SOURCE OFFICIELLE DIRECTE (JSON) — {contenu_json['source']} ===\n"
            + json.dumps(contenu_json["nominations"], ensure_ascii=False, indent=2)
        )
    elif contenu_json.get("texte_brut"):
        parties.append(f"=== SOURCE OFFICIELLE (texte) — {contenu_json['source']} ===\n{contenu_json['texte_brut']}")

    # Tavily — passages officiels
    if resultats_tavily.strip():
        parties.append(f"=== TAVILY — SOURCES OFFICIELLES ===\n{resultats_tavily}")

    # Wikipedia — contenu biographique (poids faible [WIKI🔍])
    if extrait_wiki:
        parties.append(f"=== WIKIPEDIA [WIKI🔍] ===\n{extrait_wiki[:800]}")

    # Liens officiels trouvés via Wikipedia
    if contenu_wiki_off.get("nominations"):
        parties.append(
            f"=== VIA WIKIPEDIA → SOURCE OFFICIELLE [OFFICIEL✅] — {contenu_wiki_off['source']} ===\n"
            + json.dumps(contenu_wiki_off["nominations"], ensure_ascii=False, indent=2)
        )
    elif contenu_wiki_off.get("texte_brut"):
        parties.append(f"=== VIA WIKIPEDIA → SOURCE OFFICIELLE [OFFICIEL✅] ===\n{contenu_wiki_off['texte_brut']}")

    if not parties:
        # Fallback gouvernemental si aucune source n'a rien retourné
        print(f"  [Fallback] Sites gouvernementaux prédéfinis...")
        urls_fb = URLS_GOUVERNEMENTALES.get(code_iso.upper(), [])
        fb      = scraper_json_officiel(nom_complet, urls_fb)
        if fb.get("nominations"):
            parties.append(
                f"=== FALLBACK GOUVERNEMENTAL (JSON) ===\n"
                + json.dumps(fb["nominations"], ensure_ascii=False, indent=2)
            )
        elif fb.get("texte_brut"):
            parties.append(f"=== FALLBACK (texte) ===\n{fb['texte_brut']}")
        else:
            parties.append("Aucun résultat trouvé sur les sources officielles.")

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
            res = tavily.invoke({"query": q})
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
