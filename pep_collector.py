"""
pep_collector.py — ScreenEdge Africa
Collecteur autonome de PEP : Track B (sites officiels) + Track A (OpenSanctions + Tavily + Serper)

Track B : site officiel → HTML → LLM JSON → INSERT direct (fast, ~30 min)
Track A : OpenSanctions + Tavily + Serper → découverte noms → verifier_pep (continu)

Lancer :
  python pep_collector.py                    # les deux tracks, 13 pays
  python pep_collector.py --track-b-only     # Track B uniquement
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
    "countries_done":  0,
    "countries_total": len(PAYS_PERIMETRE),
    "errors":          [],
    "last_update":     "",
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
        "presidence":      "https://www.presidence.ci/gouvernement",
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
        "presidence":      "https://www.presidence.gouv.tg",
        "conseil":         "https://www.presidence.gouv.tg/conseil-des-ministres",
    },
    "BJ": {
        "gouvernement":    "https://www.gouv.bj",
        "parlement":       "https://www.assemblee-nationale.bj",
    },
    "GW": {
        # Tous les domaines inaccessibles → Serper fallback uniquement
    },
    "GN": {
        "gouvernement":    "https://www.gouvernement.gov.gn/gouvernement/composition",
        "banque_centrale": "https://www.bcrg-guinee.org/gouvernance",
        # presidence.gov.gn → HTTP 403, bcrg.org → chemin 404 → remplacés
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
        return True
    except Exception as e:
        print(f"  ⚠️  INSERT {nom_complete} : {e}")
        _status["errors"].append(f"INSERT {code_iso} {nom_complete}: {e}")
        _update_status()
        return False


# ── TRACK B : collecte depuis sites officiels ────────────────────────────────────

def collecter_track_b(code_iso: str, pays_nom: str) -> list[dict]:
    """
    Scrape les sites officiels et retourne un lot brut de PEP candidats.
    N'insère RIEN en base — le pipeline B+A s'en charge après vérification.
    Chaque dict contient les clés LLM + '_source_url' + '_categorie'.
    """
    sources = SOURCES_TRACK_B.get(code_iso, {})
    lot: list[dict] = []

    for categorie, url in sources.items():
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

    print(f"  → Track B {code_iso} : {len(lot)} candidats PEP à vérifier")
    return lot


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
                 checkpoint: set[str], throttle_s: int = 5) -> tuple[int, set[str]]:
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


# ── TRACK A : découverte via OpenSanctions + Tavily ─────────────────────────────

def _decouvrir_noms_track_a(code_iso: str, pays_nom: str) -> list[str]:
    """
    Découvre des noms PEP via 3 canaux :
    1. OpenSanctions bulk — base mondiale PEP
    2. Tavily — recherche "gouvernement {pays} {annee}"
    3. Serper — "liste ministres {pays}"
    Retourne une liste dédupliquée de "Prénom Nom".
    """
    annee = datetime.now().year
    noms: set[str] = set()

    # ── Canal 1 : OpenSanctions ───────────────────────────────────────────────
    print(f"  [Track A] OpenSanctions → {pays_nom}...")
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

    time.sleep(30)  # throttle OpenSanctions

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


def collecter_track_a(code_iso: str, pays_nom: str) -> int:
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
                       track_b_only: bool = False) -> None:
    """
    Pipeline par pays :
      - Mode B+A (défaut) : Track B scrape → lot brut → Track A vérifie → INSERT
      - Mode B only       : Track B scrape → INSERT direct (rapide, non vérifié)
    Checkpoint automatique → reprise si crash.
    """
    cibles = pays_list or PAYS_PERIMETRE
    ref    = _charger_referentiel()

    checkpoint = _charger_checkpoint() if not track_b_only else set()

    _update_status(
        running=True,
        inserted_total=0, inserted_last=0,
        countries_done=0, countries_total=len(cibles),
        errors=[], track="", country="", category="",
    )

    print(f"\n{'='*60}")
    print(f"ScreenEdge — Collecte PEP : {len(cibles)} pays")
    print(f"Mode : {'B uniquement (INSERT direct)' if track_b_only else 'B+A (vérification avant INSERT)'}")
    if not track_b_only:
        print(f"Checkpoint : {len(checkpoint)} PEP déjà vérifiés")
    print(f"{'='*60}")

    for i, code_iso in enumerate(cibles):
        pays_nom = ref.get(code_iso, {}).get("pays", code_iso)
        print(f"\n{'─'*50}")
        print(f"[{i+1}/{len(cibles)}] {code_iso} — {pays_nom}")
        print(f"{'─'*50}")

        # ── Track B : scrape → lot brut (pas d'INSERT) ──
        lot_brut = collecter_track_b(code_iso, pays_nom)

        if track_b_only:
            # Mode rapide : INSERT direct sans vérification
            n = 0
            for p in lot_brut:
                ok = _inserer_direct(p, code_iso, pays_nom, p.get("_source_url", ""))
                if ok:
                    n += 1
                    _status["inserted_total"] += 1
                    _status["inserted_last"]   = 1
                    _update_status()
            print(f"  Track B (direct) : {n} PEP insérés")
        else:
            # Mode B+A : vérification avant INSERT
            if lot_brut:
                n, checkpoint = pipeline_lot(
                    lot_brut, code_iso, pays_nom, checkpoint, throttle_s=5
                )
                print(f"  Pipeline B+A : {n} PEP vérifiés et insérés")
            else:
                print(f"  Aucun candidat extrait par Track B pour {code_iso}")

        _update_status(countries_done=i + 1)

    total = _status["inserted_total"]
    _update_status(running=False, track="", country="", category="", inserted_last=0)

    print(f"\n{'='*60}")
    print(f"✅ Collecte terminée — {total} PEP insérés")
    print(f"{'='*60}")


# ── CLI ──────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collecteur PEP ScreenEdge Africa")
    parser.add_argument("--track-b-only", action="store_true",
                        help="Lancer uniquement le Track B (sites officiels)")
    parser.add_argument("--pays", type=str, default="",
                        help="Liste de codes ISO séparés par virgule, ex: MA,SN,CI")
    args = parser.parse_args()

    pays_list = [p.strip().upper() for p in args.pays.split(",") if p.strip()] or None

    alimenter_base_pep(pays_list=pays_list, track_b_only=args.track_b_only)
