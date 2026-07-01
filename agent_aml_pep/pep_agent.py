"""
pep_agent.py — ScreenEdge Africa
Pipeline PEP en 5 étapes via LangGraph StateGraph.

Objectif : Input = Nom seulement → agent trouve pays + qualifie PEP + stocke
Sources  : JO, sites gouvernementaux, comptes officiels réseaux sociaux
Périmètre: défini par referentiel_pep (Excel → compliance_db)
"""

import os, sys, json, re, unicodedata

from datetime import datetime
from typing import TypedDict

sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_tavily import TavilySearch
from langgraph.graph import StateGraph, END
from pydantic import BaseModel
from db_utils import query_one, execute, get_pg_conn
from search_tools import (rechercher_pep, est_source_officielle, est_source_secondaire,
                          est_source_verification, DOMAINES_INTERDITS,
                          extraire_passages_nom, consensus_sources,
                          filtrer_resultats, annoter_sources,
                          _tavily_invoke, reset_compteur_personne, get_compteur,
                          get_url_logs, reset_url_logs)

tavily_search = TavilySearch(max_results=5, search_depth="advanced")

load_dotenv(override=True)

# ── Log corpus ────────────────────────────────────────────────────────────────────
_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

def _log_corpus(nom_complet: str, code_iso: str, contenu_brut: str, contenu_filtre: str) -> None:
    """Écrit dans logs/corpus_AAAA-MM-JJ.log les stats du corpus extrait par tier."""
    ts       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_path = os.path.join(_LOG_DIR, f"corpus_{date_str}.log")

    entetes  = re.findall(r'={3,}(.*?)={3,}', contenu_brut)
    sections = re.split(r'={3,}.*?={3,}', contenu_brut)

    details = []
    for titre, texte in zip(entetes, sections[1:]):
        chars = len(texte.strip())
        mots  = len(texte.split())
        details.append(f"    {titre.strip()[:60]:<60} : {chars:>7,} chars / {mots:>5,} mots")

    lignes = [
        f"\n{'─'*78}",
        f"[{ts}] {nom_complet} ({code_iso})",
        f"  Brut  : {len(contenu_brut):>8,} chars",
        f"  Filtré: {len(contenu_filtre):>8,} chars / {len(contenu_filtre.split()):,} mots",
        "  ── Détail par source ──",
    ] + details

    with open(log_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lignes) + "\n")

# ── Instances LLM — chaîne de fallback 4 niveaux ────────────────────────────────
_GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

def _make_groq(env_key: str):
    k = os.getenv(env_key)
    if not k:
        return None
    return ChatGroq(model=_GROQ_MODEL, temperature=0.1, api_key=k, max_tokens=4096)

_llm_groq_1 = _make_groq("GROQ_KEY_1") or _make_groq("groq_api_key")
_llm_groq_2 = _make_groq("GROQ_KEY_2")
_llm_groq_3 = _make_groq("GROQ_KEY_3")
_llm_gemini = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash", temperature=0.1,
    google_api_key=os.getenv("GEMINI_API_KEY"),
)

# ── Trackers par compte ───────────────────────────────────────────────────────────
try:
    from api_tracker import (
        tracker_groq_1 as _tg1, tracker_groq_2 as _tg2,
        tracker_groq_3 as _tg3, tracker_gemini as _tracker_gemini,
    )
except ImportError:
    def _tg1(**kw): pass
    def _tg2(**kw): pass
    def _tg3(**kw): pass
    def _tracker_gemini(**kw): pass

_LLM_CHAIN = [
    (_llm_groq_1, _tg1,           "Groq-1 llama-4-scout"),
    (_llm_groq_2, _tg2,           "Groq-2 llama-4-scout"),
    (_llm_groq_3, _tg3,           "Groq-3 llama-4-scout"),
    (_llm_gemini, _tracker_gemini, "Gemini 2.5-flash"),
]
_LLM_CHAIN = [(llm, tr, lbl) for llm, tr, lbl in _LLM_CHAIN if llm is not None]

_actifs = [lbl for _, _, lbl in _LLM_CHAIN]
print(f"LLM chain : {' → '.join(_actifs)}")

_QUOTA_KEYWORDS = ("RateLimitError", "rate_limit", "quota", "429",
                   "RESOURCE_EXHAUSTED", "exceeded")

def _is_quota_error(e: Exception) -> bool:
    return any(k in str(e) for k in _QUOTA_KEYWORDS)

def _is_tpd_error(exc_str: str) -> bool:
    """True si l'erreur est un quota journalier épuisé (TPD / per day / GenerateRequestsPerDay).
    Ces quotas mettent des minutes à se libérer → fallback immédiat sans attente."""
    s = exc_str.lower()
    return ("per day" in s or "tokens per day" in s or "tpd" in s
            or "perrequestsperday" in s or "perdayperproject" in s
            or "generaterequestsperday" in s)

def _extract_retry_tpm(exc_str: str) -> float:
    """Extrait le délai suggéré pour un rate limit minute (TPM/RPM).
    Ne s'applique PAS aux erreurs TPD (quota jour) → retourne 0."""
    if _is_tpd_error(exc_str):
        return 0.0
    m = re.search(r'try again in ([\d.]+)s', exc_str, re.IGNORECASE)
    if m:
        return min(float(m.group(1)) + 1.0, 90.0)
    return 0.0

# ── Capture audit LLM (modèle utilisé pour la qualification) ─────────────────────
_audit_llm: dict = {"modele": "", "prompt": "", "reponse": ""}

def _llm_invoke(prompt):
    """Appel LLM avec fallback automatique Groq-1 → Groq-2 → Groq-3 → Gemini.
    TPM/RPM (rate limit minute) → attend le délai suggéré et retente UNE fois.
    TPD (quota journalier épuisé)  → fallback immédiat, pas d'attente inutile.
    """
    import time as _t
    last_exc = None
    for llm_inst, tracker_fn, label in _LLM_CHAIN:
        for _attempt in range(2):  # max 2 tentatives par instance
            try:
                response = llm_inst.invoke(prompt)
                _audit_llm["modele"] = label
                try:
                    usage = getattr(response, "usage_metadata", None) or {}
                    tin   = usage.get("input_tokens", 0)
                    tout  = usage.get("output_tokens", 0)
                    tracker_fn(tokens_entree=tin, tokens_sortie=tout)
                except Exception:
                    pass
                return response
            except Exception as e:
                last_exc = e
                if _is_quota_error(e):
                    exc_str = str(e)
                    wait = _extract_retry_tpm(exc_str)
                    if wait > 0 and _attempt == 0:
                        # Rate limit minute (TPM/RPM) → attendre et retenter
                        print(f"  [LLM] {label} rate limit minute → attente {wait:.0f}s puis retry...")
                        _t.sleep(wait)
                        continue
                    else:
                        # Quota journalier (TPD) ou 2ème tentative → fallback immédiat
                        if _is_tpd_error(exc_str):
                            # Extraire les vrais chiffres TPD et les persister dans api_usage.json
                            _m = re.search(r'Limit (\d+), Used (\d+)', exc_str)
                            if _m:
                                _lim, _used = int(_m.group(1)), int(_m.group(2))
                                try:
                                    if "Groq-1" in label:
                                        from api_tracker import enregistrer_quota_reel_groq as _erq; _erq(1, _used, _lim)
                                    elif "Groq-2" in label:
                                        from api_tracker import enregistrer_quota_reel_groq as _erq; _erq(2, _used, _lim)
                                    elif "Groq-3" in label:
                                        from api_tracker import enregistrer_quota_reel_groq as _erq; _erq(3, _used, _lim)
                                    elif "Gemini" in label:
                                        from api_tracker import enregistrer_quota_reel_gemini as _erg; _erg(_used, _lim)
                                except Exception:
                                    pass
                            print(f"  [LLM] {label} TPD journalier épuisé → fallback suivant")
                        else:
                            print(f"  [LLM] {label} quota épuisé → fallback suivant")
                        break
                else:
                    raise
    raise last_exc

# ── Score qualité source ──────────────────────────────────────────────────────────
_DOMAINES_OFFICIELS = (
    "presidence.", "presidency.", "assemblee-nationale", "parlement.",
    "gouvernement.", "gouv.", "senat.", "primature.", "elyseee.",
    "diplomatie.", "ministere.", "ministère.",
)

def _source_score(url: str | None) -> int:
    """Retourne un score de qualité de source (plus haut = meilleur)."""
    if not url or url in ("non disponible", ""):
        return 0
    u = url.lower()
    if any(d in u for d in _DOMAINES_OFFICIELS):
        return 3
    if "wikipedia.org" in u or "opensanctions.org" in u:
        return 2
    return 1

PAYS_PERIMETRE = {"MA","DZ","TN","LY","SN","CI","ML","BF","NE","TG","BJ","GW","GN"}

_MOIS_FR = {
    "janvier":"01","février":"02","fevrier":"02","mars":"03","avril":"04",
    "mai":"05","juin":"06","juillet":"07","août":"08","aout":"08",
    "septembre":"09","octobre":"10","novembre":"11","décembre":"12","decembre":"12",
}

def extraire_date_nomination(corpus: str, nom_complet: str) -> str:
    """
    Cherche dans le corpus (tous tiers confondus) une date de nomination/élection
    associée à la personne. Retourne 'JJ/MM/AAAA' ou '' si non trouvée.
    Couvre les formats : '24 mars 2024', '24/03/2024', '2024-03-24'.
    """
    if not corpus or not nom_complet:
        return ""

    nom_parts = [p.lower() for p in nom_complet.split() if len(p) > 2]
    corpus_lower = corpus.lower()

    # Mots-clés qui précèdent une date de nomination
    MOTS_NOM = (
        r"(?:élu|elu|nommé|nomme|investi|prend? ses? fonctions?|"
        r"prise de fonctions?|entrée? en fonctions?|"
        r"investiture|a pris ses fonctions|prêté serment|prete serment|"
        r"depuis le|en poste depuis|accède? au pouvoir|accede au pouvoir)"
    )

    # Pattern 1 : "élu le 24 mars 2024"
    pat1 = re.compile(
        MOTS_NOM + r"[\s\w]{0,20}?(\d{1,2})\s+(" + "|".join(_MOIS_FR) + r")\s+(\d{4})",
        re.IGNORECASE
    )
    # Pattern 2 : "élu le 24/03/2024" ou "nommé le 24-03-2024"
    pat2 = re.compile(
        MOTS_NOM + r"[\s\w]{0,15}?(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})",
        re.IGNORECASE
    )
    # Pattern 3 : format ISO "2024-03-24" près d'un mot-clé
    pat3 = re.compile(
        MOTS_NOM + r"[\s\w]{0,15}?(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})",
        re.IGNORECASE
    )

    candidats = []

    for pat in (pat1, pat2, pat3):
        for m in pat.finditer(corpus_lower):
            # Vérifier que le nom de la personne est proche (±300 chars)
            debut = max(0, m.start() - 300)
            fin   = min(len(corpus_lower), m.end() + 300)
            contexte = corpus_lower[debut:fin]
            if not any(p in contexte for p in nom_parts):
                continue

            try:
                if pat == pat1:
                    j  = m.group(1).zfill(2)
                    mo = _MOIS_FR[m.group(2).lower()]
                    a  = m.group(3)
                elif pat == pat3:         # ISO : AAAA-MM-JJ
                    a  = m.group(1)
                    mo = m.group(2).zfill(2)
                    j  = m.group(3).zfill(2)
                else:                     # pat2 : JJ/MM/AAAA
                    j  = m.group(1).zfill(2)
                    mo = m.group(2).zfill(2)
                    a  = m.group(3)

                annee = int(a)
                if 1950 <= annee <= datetime.now().year:
                    candidats.append(f"{j}/{mo}/{a}")
            except Exception:
                continue

    if not candidats:
        return ""

    # Retenir la date la plus récente (la plus proche de maintenant = nomination actuelle)
    def _sort_key(d):
        try:
            p = d.split("/")
            return (int(p[2]), int(p[1]), int(p[0]))
        except Exception:
            return (0, 0, 0)

    candidats.sort(key=_sort_key, reverse=True)
    return candidats[0]


def extraire_date_fin_mandat(corpus: str, nom_complet: str) -> str:
    """
    Cherche dans le corpus une date de fin de mandat/sortie de fonction.
    Retourne 'JJ/MM/AAAA' ou 'AAAA' ou '' si non trouvée.
    """
    if not corpus or not nom_complet:
        return ""

    # Normaliser pour tolérer les accents manquants (Kaboré → kabore)
    def _n(s):
        return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()
    nom_parts = [_n(p) for p in nom_complet.split() if len(p) > 2]
    corpus_lower = _n(corpus)

    MOTS_FIN = (
        r"(?:renversé|destitué|démissionné|a quitté|quitté le pouvoir|"
        r"fin de mandat|a terminé|a achevé|n'est plus|n est plus|"
        r"ancien président|ex.président|former president|left office|"
        r"putsch|coup d.état|arrêté|exilé|décédé|mort|"
        r"jusqu'en|jusqu.en|jusqu.au|until|de \d{4} [àa]|from \d{4} to)"
    )

    pat1 = re.compile(
        MOTS_FIN + r"[\s\w]{0,30}?(\d{1,2})\s+(" + "|".join(_MOIS_FR) + r")\s+(\d{4})",
        re.IGNORECASE
    )
    pat2 = re.compile(
        MOTS_FIN + r"[\s\w]{0,20}?(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})",
        re.IGNORECASE
    )
    pat3 = re.compile(
        MOTS_FIN + r"[\s\S]{0,60}?(\d{4})",
        re.IGNORECASE
    )
    # Pattern spécial : "de AAAA à AAAA" ou "from AAAA to AAAA"
    pat4 = re.compile(
        r"(?:de |from )(\d{4})\s*(?:à|à|au|to)\s*(\d{4})",
        re.IGNORECASE
    )

    candidats = []

    for pat in (pat1, pat2):
        for m in pat.finditer(corpus_lower):
            debut = max(0, m.start() - 300)
            fin   = min(len(corpus_lower), m.end() + 300)
            if not any(p in corpus_lower[debut:fin] for p in nom_parts):
                continue
            try:
                if pat == pat1:
                    j  = m.group(1).zfill(2)
                    mo = _MOIS_FR[m.group(2).lower()]
                    a  = m.group(3)
                else:
                    j  = m.group(1).zfill(2)
                    mo = m.group(2).zfill(2)
                    a  = m.group(3)
                annee = int(a)
                if 1950 <= annee <= datetime.now().year:
                    candidats.append(f"{j}/{mo}/{a}")
            except Exception:
                continue

    # Pattern année seule
    for pat in (pat3,):
        for m in pat.finditer(corpus_lower):
            debut = max(0, m.start() - 300)
            fin   = min(len(corpus_lower), m.end() + 300)
            if not any(p in corpus_lower[debut:fin] for p in nom_parts):
                continue
            try:
                a = m.group(1)
                annee = int(a)
                if 1950 <= annee <= datetime.now().year:
                    candidats.append(a)
            except Exception:
                continue

    # Pattern "de AAAA à AAAA" — retenir la 2e année (fin)
    for m in pat4.finditer(corpus_lower):
        debut = max(0, m.start() - 300)
        fin   = min(len(corpus_lower), m.end() + 300)
        if not any(p in corpus_lower[debut:fin] for p in nom_parts):
            continue
        try:
            a = m.group(2)
            annee = int(a)
            if 1950 <= annee <= datetime.now().year:
                candidats.append(a)
        except Exception:
            continue

    if not candidats:
        return ""

    def _sort_key(d):
        try:
            if "/" in d:
                p = d.split("/")
                return (int(p[2]), int(p[1]), int(p[0]))
            return (int(d), 0, 0)
        except Exception:
            return (0, 0, 0)

    candidats.sort(key=_sort_key, reverse=True)
    annee_courante = datetime.now().year

    # Vérifier s'il existe une nomination récente (année courante ou après la date candidate)
    # qui annule la fin de mandat détectée — ex: Kaba "de 2012 à 2016" + "nommée... 2026"
    MOTS_NOMINATION = ["nommé", "nomme", "reconduit", "investi", "élu", "elu",
                       "appointed", "designated", "prend ses fonctions", "entre en fonctions"]
    corpus_n = _n(corpus)
    for c in candidats:
        annee_c = int(c.split("/")[-1] if "/" in c else c)
        if annee_c >= annee_courante:
            continue  # ignorer l'année courante comme date de FIN
        # Vérifier qu'aucune nomination plus récente n'existe dans le corpus
        nomination_plus_recente = False
        for mot_nom in MOTS_NOMINATION:
            idx = corpus_n.find(mot_nom)
            while idx != -1:
                fenetre = corpus_n[max(0, idx-100):idx+200]
                annees_trouvees = re.findall(r'\b(20\d{2})\b', fenetre)
                for ay in annees_trouvees:
                    if int(ay) > annee_c and any(p in corpus_n[max(0,idx-300):idx+300] for p in nom_parts):
                        nomination_plus_recente = True
                        break
                if nomination_plus_recente:
                    break
                idx = corpus_n.find(mot_nom, idx + 1)
            if nomination_plus_recente:
                break
        if not nomination_plus_recente:
            return c
    return ""


def filtrer_sources(texte: str) -> str:
    """Supprime les lignes contenant des domaines non officiels."""
    if not texte:
        return texte
    lignes = texte.split("\n")
    return "\n".join(
        l for l in lignes
        if not any(d in l.lower() for d in DOMAINES_INTERDITS)
    ) or "Aucun résultat sur sources officielles."

_MOIS_FR = {
    "janvier":1,"février":2,"fevrier":2,"mars":3,"avril":4,"mai":5,"juin":6,
    "juillet":7,"août":8,"aout":8,"septembre":9,"octobre":10,"novembre":11,"décembre":12,"decembre":12,
}

def convertir_date(date_str: str) -> str | None:
    """Convertit toute représentation de date vers YYYY-MM-DD pour PostgreSQL."""
    if not date_str or str(date_str).strip() in ("N/A", "null", "None", ""):
        return None
    s = str(date_str).strip()
    # Format YYYY seulement
    if re.fullmatch(r'\d{4}', s):
        return f"{s}-01-01"
    # Format DD/MM/YYYY
    try:
        return datetime.strptime(s, "%d/%m/%Y").strftime("%Y-%m-%d")
    except Exception:
        pass
    # Format YYYY-MM-DD déjà correct
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except Exception:
        pass
    # Format texte français "1er mai 1958", "25 mars 1980", "8 avril 1954"
    m = re.search(r'(\d{1,2})\w*\s+(\w+)\s+(\d{4})', s, re.IGNORECASE)
    if m:
        jour, mois_txt, annee = m.group(1), m.group(2).lower(), m.group(3)
        mois_num = _MOIS_FR.get(mois_txt)
        if mois_num:
            return f"{annee}-{mois_num:02d}-{int(jour):02d}"
    # Année seule dans un texte plus long
    m2 = re.search(r'\b(\d{4})\b', s)
    if m2:
        return f"{m2.group(1)}-01-01"
    return None

# ── State ───────────────────────────────────────────────────────────────────────

class PEPState(TypedDict):
    nom: str
    prenom: str
    # Extrait par l'agent
    code_iso: str
    pays_nom: str
    fonction_trouvee: str
    # Critères
    criteres: str
    # Recherche
    resultats_recherche: str
    corpus_brut: str                  # corpus non filtré (tous tiers) — utilisé par GC5
    urls_officielles_trouvees: list   # URLs officielles extraites du corpus
    urls_media_trouvees: list         # URLs médias extraites du corpus
    opensanctions_confirmed: bool     # Tier 3 a confirmé PEP
    _votes_pays: int                  # Score de confiance identification pays (0=inconnu, 2=1 source, 4+=certain)
    # Qualification
    est_pep: bool
    statut_mandat: str
    fonction: str
    fonctions_historiques: list
    date_nomination: str
    date_fin_mandat: str
    date_naissance: str
    lieu_naissance: str
    nb_enfants: int | None
    statut_matrimonial: str
    source_url: str
    source_type: str
    raisonnement: str
    # Stockage
    stockage_status: str
    dry_run: bool          # si True → node_store ne fait rien (validation manuelle)

# ── Output ──────────────────────────────────────────────────────────────────────

class PersonPEPReport(BaseModel):
    nom: str
    prenom: str
    pays: str
    code_iso: str
    est_pep: bool
    statut_mandat: str
    fonction: str | None
    fonctions_historiques: list[str] | None = None
    date_nomination: str | None
    date_fin_mandat: str | None
    date_naissance: str | None = None
    lieu_naissance: str | None = None
    nb_enfants: int | None = None
    statut_matrimonial: str | None = None
    source_url: str
    source_type: str
    raisonnement: str
    date_verification: str
    urls_media_trouvees: list[str] = []

# ── NOEUD 1 : Recherche Tavily d'abord → LLM extrait le pays depuis les résultats ──

PROMPT_IDENTIFICATION = """Tu es un expert en conformité AML/PPE francophone.

PERSONNE : {prenom} {nom}

RÉSULTATS DE RECHERCHE SUR SOURCES OFFICIELLES :
{resultats_recherche}

En analysant UNIQUEMENT les résultats ci-dessus (pas ta mémoire), réponds en JSON :
{{
  "code_iso": "code ISO2 du pays DANS LEQUEL CETTE PERSONNE EXERCE/A EXERCÉ SA FONCTION (n'importe quel code ISO2 mondial, ex: MA, CG, CM, NG, CD, etc.). Si impossible à déterminer → XX",
  "pays_nom": "nom du pays en français",
  "fonction_probable": "fonction publique trouvée dans les résultats ou null"
}}

RÈGLES STRICTES :
- RÈGLE ABSOLUE ANTI-SUBSTITUTION (identification pays) : Chercher LE PAYS associé à {prenom} {nom} spécifiquement, pas celui d'une autre personne portant le même nom de famille. Ex : "Dominique Ouattara" (Première dame CI) ≠ "Alassane Ouattara" (Président CI). MAIS : si {prenom} {nom} est l'épouse/conjoint/enfant d'un PEP identifié dans le corpus → le code_iso EST celui du PEP de référence (c'est autorisé et attendu pour les proches).
- PROCHE DE PEP : si les résultats indiquent que {prenom} {nom} est "épouse de [NOM]", "fils de [NOM]", "Première dame de [PAYS]" → code_iso = pays du PEP de référence. Ex : "Marème Faye Sall, épouse de Macky Sall (Sénégal)" → code_iso = SN. "Hadiza Bazoum, épouse du président du Niger" → code_iso = NE.
- code_iso = pays du GOUVERNEMENT auquel APPARTIENT la personne (où elle exerce/a exercé son mandat)
- Si les résultats indiquent "président du Congo" → code_iso = "CG" ; "président du Cameroun" → "CM" ; "président du Maroc" → "MA" ; etc.
- Si les résultats mentionnent "ancien président de [pays]", "ex-président de [pays]" → extraire CE pays
- ATTENTION : si une personne étrangère a simplement VISITÉ un pays ou participé à un sommet dans ce pays, ce pays n'est PAS son code_iso
- ATTENTION : si l'article est publié par un média marocain/algérien mais parle d'un dirigeant congolais → code_iso = CG, pas MA/DZ
- INSTITUTIONS AFRICAINES SUPRANATIONALES DU PÉRIMÈTRE (BAD, BCEAO, UEMOA, BOAD) : utiliser le PAYS SIÈGE comme code_iso — ces institutions font partie du périmètre de surveillance AML ScreenEdge Africa :
  • Président/DG de la BAD (Banque Africaine de Développement, siège Abidjan, Côte d'Ivoire) → CI
  • Gouverneur/Président de la BCEAO (siège Dakar, Sénégal) → SN
  • Président/Commission UEMOA (siège Ouagadougou, Burkina Faso) → BF
  • Président/DG de la BOAD (Banque Ouest Africaine de Développement, siège Lomé, Togo) → TG
  La nationalité de la personne est ignorée pour ces 4 institutions — seul le pays siège compte.
- AUTRES ORGANISATIONS INTERNATIONALES (ONU, UA, CEDEAO, FMI, Banque Mondiale, BID, CUA, etc.) : le code_iso doit être la NATIONALITÉ de la personne. Exemple : Président de la CEDEAO nigérian basé à Abuja → code_iso = NG. Si nationalité non déterminable → code_iso = XX
- Si les résultats ne permettent pas de déterminer le pays du mandat → code_iso = XX"""

def node_identify(state: PEPState) -> PEPState:
    """Étape 1 — Vote multi-tiers pour identifier le pays : Tavily + Serper toujours, rescue si nécessaire."""
    nom_complet = f"{state['prenom']} {state['nom']}"
    print(f"\n[Étape 1] Recherche initiale + identification : {nom_complet}...")

    annee = datetime.now().year
    votes_code: dict = {}
    votes_fn:   dict = {}
    resultats_bruts = []

    # ── Tier A — Tavily 4 queries → LLM vote (+2) ────────────────────────────────
    for q in [
        f'"{nom_complet}" ministre OR président OR directeur gouvernement officiel',
        f'"{nom_complet}" {annee} OR {annee-1} fonction publique',
        f'"{nom_complet}" ancien président OR ex-président OR chef état nationalité',
        f'site:fr.wikipedia.org {nom_complet}',
    ]:
        try:
            r = _tavily_invoke(tavily_search, q, f"identify: {q[:40]}")
            if r: resultats_bruts.append(str(r))
        except Exception:
            continue

    resultats = "\n\n".join(resultats_bruts) if resultats_bruts else "Aucun résultat."

    try:
        response = _llm_invoke(PROMPT_IDENTIFICATION.format(
            prenom=state["prenom"], nom=state["nom"],
            resultats_recherche=resultats[:6000]
        ))
        content = response.content.strip()
        if "```json" in content: content = content.split("```json")[1].split("```")[0]
        elif "```" in content: content = content.split("```")[1].split("```")[0]
        start = content.find("{")
        depth, end = 0, start
        for i, ch in enumerate(content[start:], start):
            if ch == "{": depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0: end = i + 1; break
        data = json.loads(content[start:end])
        iso_ta = data.get("code_iso", "XX").upper()
        fn_ta  = data.get("fonction_probable") or ""
        if iso_ta in PAYS_PERIMETRE:
            votes_code[iso_ta] = votes_code.get(iso_ta, 0) + 2
            if fn_ta: votes_fn.setdefault(iso_ta, fn_ta)
            print(f"  → Tavily : vote {iso_ta} (+2) | {fn_ta or 'fonction inconnue'}")
        else:
            print(f"  → Tavily : pays non identifié")
    except Exception:
        pass

    # ── Tier B — Serper TOUJOURS → LLM vote (+2) ─────────────────────────────────
    try:
        from search_tools import rechercher_google as _serper
        serper_txt, _, _m = _serper(nom_complet, "Afrique", "XX")
        if serper_txt:
            resp_sr = _llm_invoke(PROMPT_IDENTIFICATION.format(
                prenom=state["prenom"], nom=state["nom"],
                resultats_recherche=serper_txt[:6000]
            ))
            c_sr = resp_sr.content.strip()
            if "```json" in c_sr: c_sr = c_sr.split("```json")[1].split("```")[0]
            elif "```" in c_sr:   c_sr = c_sr.split("```")[1].split("```")[0]
            s_sr = c_sr.find("{"); e_sr = c_sr.rfind("}") + 1
            d_sr = json.loads(c_sr[s_sr:e_sr])
            iso_sr = d_sr.get("code_iso", "XX").upper()
            fn_sr  = d_sr.get("fonction_probable") or ""
            if iso_sr in PAYS_PERIMETRE:
                votes_code[iso_sr] = votes_code.get(iso_sr, 0) + 2
                if fn_sr: votes_fn.setdefault(iso_sr, fn_sr)
                resultats += f"\n\n[SERPER ID]\n{serper_txt[:6000]}"
                print(f"  → Serper : vote {iso_sr} (+2) | {fn_sr or 'fonction inconnue'}")
            else:
                print(f"  → Serper : pays non identifié")
    except Exception as _e_sr:
        print(f"  → Serper identification erreur : {type(_e_sr).__name__}: {_e_sr}")

    # ── Consensus Tier A + B ──────────────────────────────────────────────────────
    code_iso = "XX"
    fonction = ""
    pays_nom = "Inconnu"
    if votes_code:
        best = max(votes_code, key=votes_code.get)
        if votes_code[best] >= 2:
            code_iso = best
            fonction = votes_fn.get(best, "")
            if best in _referentiel_json:
                pays_nom = _referentiel_json[best]["pays"]
            print(f"  → Consensus Tavily+Serper ({votes_code[best]} votes) : {pays_nom} ({code_iso}) | {fonction or 'fonction inconnue'}")

    # ── Rescue — si XX : Tavily sources ciblées → +1 chacune ─────────────────────
    if code_iso == "XX":
        print(f"  → Pays non identifié — rescue identification multi-sources...")
        for q_r, label_r in [
            (f'site:wikipedia.org {state["prenom"]} {state["nom"]}',    "wiki1"),
            (f'site:fr.wikipedia.org {state["prenom"]} {state["nom"]}', "wiki2"),
            (f'site:rfi.fr {nom_complet}',                              "rfi"),
            (f'site:jeuneafrique.com {nom_complet}',                    "ja"),
        ]:
            try:
                r_r = _tavily_invoke(tavily_search, q_r, f"rescue id: {label_r}")
                if not r_r: continue
                txt_r = str(r_r)[:6000]
                resp_r = _llm_invoke(PROMPT_IDENTIFICATION.format(
                    prenom=state["prenom"], nom=state["nom"],
                    resultats_recherche=txt_r
                ))
                c_r = resp_r.content.strip()
                if "```json" in c_r: c_r = c_r.split("```json")[1].split("```")[0]
                elif "```" in c_r:   c_r = c_r.split("```")[1].split("```")[0]
                s_r = c_r.find("{"); e_r = c_r.rfind("}") + 1
                d_r = json.loads(c_r[s_r:e_r])
                iso_r = d_r.get("code_iso", "XX").upper()
                if iso_r in PAYS_PERIMETRE:
                    votes_code[iso_r] = votes_code.get(iso_r, 0) + 1
                    fn_r = d_r.get("fonction_probable") or ""
                    if fn_r: votes_fn.setdefault(iso_r, fn_r)
                    resultats += f"\n\n[RESCUE {label_r}]\n{txt_r}"
                    print(f"  → Rescue {label_r}: vote {iso_r}")
            except Exception:
                continue

        if votes_code:
            best = max(votes_code, key=votes_code.get)
            if votes_code[best] >= 2:
                code_iso = best
                fonction = votes_fn.get(best, fonction)
                if best in _referentiel_json:
                    pays_nom = _referentiel_json[best]["pays"]
                print(f"  → Consensus rescue {votes_code[best]} sources : {pays_nom} ({code_iso}) | {fonction or 'fonction inconnue'}")
            else:
                print(f"  → Rescue insuffisant {votes_code}")

    # ── Phase libre — si encore XX : queries sans site: ──────────────────────────
    if code_iso == "XX":
        print(f"  → Phase libre — queries sans contrainte site:...")
        for q_pl, label_pl in [
            (f'{state["prenom"]} {state["nom"]} président Afrique',                      "libre1"),
            (f'{state["prenom"]} {state["nom"]} ancien chef état Afrique subsaharienne', "libre2"),
        ]:
            try:
                r_pl = _tavily_invoke(tavily_search, q_pl, f"libre: {label_pl}")
                if not r_pl: continue
                txt_pl = str(r_pl)[:6000]
                resp_pl = _llm_invoke(PROMPT_IDENTIFICATION.format(
                    prenom=state["prenom"], nom=state["nom"],
                    resultats_recherche=txt_pl
                ))
                c_pl = resp_pl.content.strip()
                if "```json" in c_pl: c_pl = c_pl.split("```json")[1].split("```")[0]
                elif "```" in c_pl:   c_pl = c_pl.split("```")[1].split("```")[0]
                s_pl = c_pl.find("{"); e_pl = c_pl.rfind("}") + 1
                d_pl = json.loads(c_pl[s_pl:e_pl])
                iso_pl = d_pl.get("code_iso", "XX").upper()
                if iso_pl in PAYS_PERIMETRE:
                    code_iso = iso_pl
                    fonction = d_pl.get("fonction_probable") or fonction
                    if iso_pl in _referentiel_json:
                        pays_nom = _referentiel_json[iso_pl]["pays"]
                    resultats += f"\n\n[LIBRE {label_pl}]\n{txt_pl}"
                    print(f"  → Phase libre trouvé : {pays_nom} ({code_iso}) | {fonction or 'inconnu'}")
                    break
            except Exception:
                continue

    if code_iso == "XX":
        print(f"  → {pays_nom} ({code_iso}) hors périmètre — classé Non-PEP automatiquement")

    _votes_max = max(votes_code.values()) if votes_code else 0
    if _votes_max <= 2 and code_iso != "XX":
        print(f"  → Confiance pays faible ({_votes_max} vote(s)) — pays incertain : {pays_nom} ({code_iso})")
    return {**state, "code_iso": code_iso, "pays_nom": pays_nom,
            "fonction_trouvee": fonction, "resultats_recherche": resultats,
            "_votes_pays": _votes_max}

# ── Chargement du référentiel JSON au démarrage ──────────────────────────────────

_REF_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "referentiel_pep.json")
_referentiel_json: dict = {}

try:
    with open(_REF_JSON_PATH, "r", encoding="utf-8") as _f:
        for _entry in json.load(_f):
            _referentiel_json[_entry["code_iso"].upper()] = _entry
    print(f"Référentiel JSON chargé — {len(_referentiel_json)} pays")
except Exception as _e:
    print(f"Référentiel JSON non disponible : {_e}")

# ── NOEUD 2 : Charger critères PEP du pays depuis referentiel_pep ────────────────

def node_get_criteria(state: PEPState) -> PEPState:
    """Étape 2 — Charger le périmètre PEP officiel du pays depuis le JSON structuré."""
    print(f"\n[Étape 2] Chargement critères PEP pour {state['code_iso']}...")
    if state["code_iso"] == "XX":
        return {**state, "criteres": "Pays non identifié — fallback GAFI R12."}

    code = state["code_iso"].upper()

    # Priorité 1 : JSON structuré (plus lisible pour le LLM)
    if code in _referentiel_json:
        entry = _referentiel_json[code]
        criteres = json.dumps({
            "pays":            entry["pays"],
            "statut_gafi":     entry["statut_gafi"],
            "vigilance":       entry["vigilance"],
            "loi_reference":   entry["loi_reference"],
            "fonctions_pep":   entry["fonctions_pep"],
            "famille_incluse": entry["famille_incluse"],
            "proches_associes":entry["proches_associes"],
            "duree_ex_pep":    entry["duree_ex_pep"],
            "reevaluation":    entry["reevaluation"],
        }, ensure_ascii=False, indent=2)
        print(f"  Critères JSON chargés — GAFI: {entry['statut_gafi']} | {len(entry['fonctions_pep'])} fonctions PEP")
        return {**state, "criteres": criteres}

    # Fallback : base de données PostgreSQL
    try:
        row = query_one(
            "SELECT pays, def_pep, loi_ref, statut_gafi, vigilance, autorite "
            "FROM referentiel_pep WHERE UPPER(code_iso) = %s",
            (code,)
        )
        if row:
            criteres = f"LOI: {row['loi_ref'] or 'N/A'} | GAFI: {row['statut_gafi'].upper()} | VIGILANCE: {row['vigilance'].upper()}\n\n{row['def_pep'] or 'GAFI R12'}"
            print(f"  Critères DB chargés — GAFI: {row['statut_gafi']}")
        else:
            criteres = "Pays non trouvé — fallback GAFI R12."
            print("  Fallback GAFI R12")
    except Exception as e:
        criteres = f"Erreur DB : {e} — fallback GAFI R12."
        print(f"  Erreur DB : {e}")
    return {**state, "criteres": criteres}

# ── NOEUD 3 : Recherche sur sources officielles ──────────────────────────────────

SOURCES_OFFICIELLES = {
    "MA": ["maroc.ma","gouvernement.ma","chambredesrepresentants.ma",
           "chambredesconseillers.ma","bkam.ma","utrf.ma","bulletinofficiel.ma","ammc.ma","acaps.ma"],
    "DZ": ["el-mouradia.dz","premier-ministre.gov.dz","apn.dz",
           "senat.dz","bank-of-algeria.dz","ctrf.gov.dz","joradp.dz"],
    "TN": ["carthage.tn","gouvernement.tn","arp.tn",
           "bct.gov.tn","ctaf.gov.tn","iort.gov.tn"],
    "LY": ["gov.ly","hor.ly","cbl.gov.ly"],
    "SN": ["presidence.sn","gouvernement.sn","assemblee-nationale.sn",
           "centif.sn","bceao.int","jo.gouv.sn"],
    "CI": ["presidence.ci","gouv.ci","assemblee-nationale.ci",
           "senat.ci","centif-ci.ci","bceao.int"],
    "ML": ["koulouba.ml","primature.gov.ml","bceao.int"],
    "BF": ["gouvernement.gov.bf","centif.bf","bceao.int","fasonet.bf"],
    "NE": ["presidence.ne","gouv.ne","centif.ne","bceao.int"],
    "TG": ["presidenceduconseil.gouv.tg","gouv.tg","assemblee-nationale.tg","centif.tg","bceao.int"],
    "BJ": ["presidence.bj","gouv.bj","assemblee-nationale.bj",
           "centif.bj","bceao.int","journalofficiel.bj"],
    "GW": ["gov.gw","bceao.int"],
    "GN": ["presidence.gov.gn","gouvernement.gov.gn","bcrg.org"],
}

def node_search(state: PEPState) -> PEPState:
    """Étape 3 — Recherche via Tavily + Scrapling + fallback gouvernemental."""
    nom_complet = f"{state['prenom']} {state['nom']}"
    code = state["code_iso"]
    print(f"\n[Étape 3] Recherche officielle : {nom_complet} ({code})...")

    # Récupérer duree_ex_pep depuis le JSON critères du pays
    duree_ex_pep = "non précisée"
    try:
        criteres_data = json.loads(state.get("criteres", "{}"))
        duree_ex_pep = criteres_data.get("duree_ex_pep", "non précisée")
    except Exception:
        pass

    # Sauvegarder les résultats de node_identify avant de les écraser
    resultats_identification = state.get("resultats_recherche", "")

    contenu_brut = rechercher_pep(nom_complet, state["pays_nom"], code, duree_ex_pep)

    # Extraire et stocker les URLs par tier AVANT le filtrage du texte
    toutes_urls      = [u.rstrip('.,)') for u in re.findall(r'https?://[^\s\'">,\]]+', contenu_brut)]
    urls_off         = list(set(u for u in toutes_urls if est_source_officielle(u)))
    urls_med         = list(set(u for u in toutes_urls if est_source_secondaire(u)))

    # Texte filtré pour le LLM
    contenu = extraire_passages_nom(contenu_brut, nom_complet)
    nb_mots = len(contenu.split()) if contenu else 0
    print(f"  Résultat : {nb_mots} mots | {len(urls_off)} URLs off | {len(urls_med)} URLs médias")

    # Toujours injecter le résultat d'identification en tête du corpus
    # (contient les snippets Serper/Tavily les plus récents sur la fonction actuelle)
    if resultats_identification and code != "XX":
        mots_id = len(resultats_identification.split())
        if mots_id > 20:
            header_id = f"[RECHERCHE INITIALE — SERPER/TAVILY ACTUEL]\n{resultats_identification}"
            contenu = header_id + "\n\n---\n\n" + contenu if contenu.strip() else header_id
            nb_mots = len(contenu.split())
            print(f"  Enrichi avec résultats identify ({mots_id} mots) → {nb_mots} mots")

    # Si contenu encore insuffisant → recherche ciblée ex-PEP
    if nb_mots < 300:
        print(f"  Contenu insuffisant ({nb_mots} mots) → recherche ciblée ancien dirigeant...")
        try:
            q = f'"{nom_complet}" ancien président OR ancien premier ministre OR ex-chef {state["pays_nom"]}'
            res_extra = _tavily_invoke(tavily_search, q, f"ciblé ex: {q[:40]}")
            if res_extra:
                # Extraire le texte lisible depuis la réponse Tavily
                items = []
                if isinstance(res_extra, list):
                    items = res_extra
                elif isinstance(res_extra, dict):
                    items = res_extra.get("results", [])
                    answer = res_extra.get("answer", "")
                    if answer:
                        items = [{"url": "", "title": "Résumé Tavily", "content": answer}] + items

                if items:
                    parties_extra = []
                    for item in items:
                        url          = item.get("url", "")
                        titre        = item.get("title", "")
                        contenu_item = item.get("content", "") or item.get("snippet", "")
                        parties_extra.append(f"{url}\n{titre}\n{contenu_item}")
                    texte_brut = "\n\n".join(parties_extra)
                else:
                    texte_brut = str(res_extra)
                texte_extra = filtrer_resultats(annoter_sources(texte_brut))
                extra = extraire_passages_nom(texte_extra, nom_complet)
                if not extra or len(extra.split()) < 50:
                    extra = texte_extra[:6000]
                if extra:
                    contenu = contenu + "\n\n---\n\n" + extra
                    nb_mots = len(contenu.split())
                    print(f"  Enrichi → {nb_mots} mots")
        except Exception:
            pass

    # Détecter confirmation OpenSanctions Tier 3 dans le corpus brut
    os_confirmed = "[COMPLIANCE✅]" in contenu_brut and '"is_pep": true' in contenu_brut
    if os_confirmed:
        print(f"  [Tier 3] OpenSanctions PEP confirmé → opensanctions_confirmed=True")

    # Si pays XX + OpenSanctions a un pays du périmètre → corriger code_iso
    code_iso_final = code
    pays_nom_final = state["pays_nom"]
    if os_confirmed and code == "XX":
        # Lire le marqueur structuré [OS_PAYS:XX,ML,...] injecté par search_tools
        _tag_m = re.search(r'\[OS_PAYS:([A-Z,]+)\]', contenu_brut)
        if _tag_m and _tag_m.group(1) != "XX":
            for _iso in _tag_m.group(1).split(","):
                if _iso in PAYS_PERIMETRE:
                    code_iso_final = _iso
                    if _iso in _referentiel_json:
                        pays_nom_final = _referentiel_json[_iso]["pays"]
                    print(f"  [Tier 3] OpenSanctions → pays identifié : {pays_nom_final} ({code_iso_final})")
                    break

    # ── Enrichissement famille/proche ────────────────────────────────────────────────
    _fam_kw = ["épouse", "premiere dame", "première dame", "conjoint", "fils de", "fille de",
               "femme du president", "femme du président", "proche pep"]
    _PAYS_FAM_MAP = {
        "burkina": "BF", "guinee": "GN", "guinea": "GN",
        "nigerien": "NE", "niger ": "NE",
        "mali ": "ML", "malien": "ML",
        "senegal": "SN", "senegalais": "SN",
        "cote d ivoire": "CI", "ivoirien": "CI",
        "togolais": "TG", "togo ": "TG",
        "beninois": "BJ", "benin ": "BJ",
        "marocain": "MA", "maroc ": "MA",
        "algerien": "DZ", "algerie": "DZ",
        "tunisien": "TN", "tunisie": "TN",
        "libyen": "LY", "libye ": "LY",
        "bissau": "GW", "guinee-bissau": "GW",
    }
    def _norm_pays(s):
        return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()
    def _deduire_pays_famille(texte: str) -> str:
        """Extrait le code_iso depuis un texte famille (retourne None si non trouvé)."""
        _t = _norm_pays(texte)
        for _kp, _iso in _PAYS_FAM_MAP.items():
            if _kp in _t:
                return _iso
        return None

    # Vérifier uniquement dans les passages proches du nom (évite pollution du corpus global)
    _contenu_pres_nom = extraire_passages_nom(contenu, nom_complet) or ""
    _has_fam_kw = any(kw in _contenu_pres_nom.lower() for kw in _fam_kw)
    _fam_inclus = (_referentiel_json.get(code_iso_final, {}).get("famille_incluse", False)
                   or code_iso_final == "XX")

    _country_corrected = False
    if _has_fam_kw and code_iso_final in ("XX", "ML", "CI", "SN", "BF", "NE", "TG", "BJ", "GW", "GN"):
        _pass_norm_fam = _norm_pays(_contenu_pres_nom)
        import re as _re_fam
        _kws_pays_joined = '|'.join(_PAYS_FAM_MAP.keys())
        _fam_kws_joined  = r'(?:epouse|premiere dame|conjoint|femme du|fils du)'
        # Chercher dans les deux sens : "épouse…pays" ET "pays…épouse"
        _m_fam = (_re_fam.search(_fam_kws_joined + r'.{0,80}(?:' + _kws_pays_joined + r')', _pass_norm_fam)
                  or _re_fam.search(r'(?:' + _kws_pays_joined + r').{0,80}' + _fam_kws_joined, _pass_norm_fam))
        if _m_fam:
            for _kp, _iso in _PAYS_FAM_MAP.items():
                if _kp in _m_fam.group(0) and _iso != code_iso_final and _iso in _referentiel_json:
                    code_iso_final = _iso
                    pays_nom_final = _referentiel_json[_iso]["pays"]
                    print(f"  Pays corrigé via lien famille dans corpus : {pays_nom_final} ({code_iso_final})")
                    _country_corrected = True
                    break
        # Injecter les passages famille en tête de corpus pour que le LLM les voie en priorité
        if "[LIEN FAMILLE PROCHE GAFI]" not in contenu and _contenu_pres_nom:
            contenu = f"[LIEN FAMILLE PROCHE GAFI — Article R12]\n{_contenu_pres_nom[:1500]}\n\n---\n\n" + contenu
            print(f"  Lien famille injecté en tête du corpus ({code_iso_final})")

    if _fam_inclus and not _has_fam_kw:
        # Pas de mot-clé famille dans le corpus → recherche externe Serper
        try:
            from search_tools import rechercher_google as _sg_fam
            _q_fam = f"{nom_complet} épouse Première dame conjoint"
            _txt_fam, _, _ = _sg_fam(_q_fam, state["pays_nom"], code_iso_final)
            if _txt_fam and len(_txt_fam.split()) > 20:
                _pass_fam = extraire_passages_nom(_txt_fam, nom_complet) or _txt_fam[:2000]
                if _pass_fam and any(kw in _pass_fam.lower() for kw in _fam_kw):
                    contenu += "\n\n[RECHERCHE LIEN FAMILLE/PROCHE GAFI]\n" + _pass_fam[:3000]
                    print(f"  Enrichi lien-famille Serper → {len(contenu.split())} mots")
                    _iso_fam2 = _deduire_pays_famille(_pass_fam)
                    if _iso_fam2 and _iso_fam2 in _referentiel_json and _iso_fam2 != code_iso_final:
                        code_iso_final = _iso_fam2
                        pays_nom_final = _referentiel_json[_iso_fam2]["pays"]
                        print(f"  Pays déduit du lien famille Serper : {pays_nom_final} ({code_iso_final})")
                else:
                    print(f"  Serper famille : aucun lien famille trouvé")
            else:
                print(f"  Serper famille : résultat court ({len((_txt_fam or '').split())} mots)")
        except Exception as _ef:
            print(f"  Serper famille erreur : {_ef}")

    _log_corpus(nom_complet, code, contenu_brut, contenu)

    return {**state,
            "resultats_recherche": contenu,
            "corpus_brut": contenu_brut,
            "urls_officielles_trouvees": urls_off,
            "urls_media_trouvees": urls_med,
            "opensanctions_confirmed": os_confirmed,
            "code_iso": code_iso_final,
            "pays_nom": pays_nom_final}

# ── NOEUD 4 : Qualification PEP ──────────────────────────────────────────────────

PROMPT_QUALIFICATION = """Tu es un expert en conformité AML/PPE francophone. Réponds UNIQUEMENT en JSON valide.

ANNÉE COURANTE : {annee}
DATE D'AUJOURD'HUI : {date_today}
PERSONNE À VÉRIFIER : {prenom} {nom} ({pays})

PÉRIMÈTRE PEP OFFICIEL DU PAYS (JSON structuré) :
{criteres}

Le champ "fonctions_pep" liste EXACTEMENT les titres qui qualifient comme PEP dans ce pays.
Pour décider si la fonction trouvée est dans le périmètre, compare-la sémantiquement à cette liste.
Exemples d'équivalences valides :
  - "Premier ministre" ≈ "Chef du Gouvernement" ≈ "PM"
  - "Président de la République" ≈ "Chef de l'État"
  - "Directeur général" d'une entreprise publique ≈ "Dirigeant entreprise d'État"
Si la fonction trouvée est sémantiquement équivalente à un item de "fonctions_pep" → c'est une PEP.
Si "famille_incluse" = true → les proches (conjoint, enfants, parents) sont aussi PEP.
Si "duree_ex_pep" = "permanente" → une ancienne PEP reste PEP indéfiniment même après la fin du mandat.

RÈGLE FAMILLE INCLUSE (PRIORITÉ ABSOLUE — s'applique si famille_incluse = true) :
Si le corpus mentionne que {prenom} {nom} est l'un des suivants :
→ "épouse de [NOM_PEP]", "Première dame", "femme du président", "conjoint(e) du Premier ministre"
→ "fils de [NOM_PEP]", "fille de [NOM_PEP]", "enfant du chef d'état", "fils du président"
→ même si {prenom} {nom} n'a AUCUNE fonction publique propre
ALORS : est_pep = OBLIGATOIREMENT true, statut_mandat selon le statut du PEP de référence.
fonction = "Proche PEP — [relation] de [Prénom Nom du PEP]" (ex: "Épouse du Président Ibrahim Traoré", "Fils du Président Abdoulaye Wade")
RÈGLE SOURCE PROCHE : 1 source [MEDIA⚠️] suffit pour valider un proche PEP (pas besoin d'[OFFICIEL✅]).
Ne PAS exiger une source gouvernementale directe pour les proches — les médias et Wikipedia suffisent.

RÈGLE CRITIQUE — PREMIÈRE DAME / PROCHE D'EX-PEP :
Si la fonction de {prenom} {nom} est "Première dame", "épouse du président", "conjoint de" ou équivalent :
- Si le mari/époux EST encore en fonction → statut_mandat = "actif"
- Si le mari/époux A ÉTÉ renversé, démis, a démissionné, ou a quitté le pouvoir → statut_mandat = "ex_pep"
- PIÈGE FRÉQUENT : "Première dame du Niger" avec Mohamed Bazoum renversé en 2023 → ex_pep, pas actif
- La fonction de proche suit TOUJOURS le statut du PEP de référence (mari/parent)

DONNÉES TROUVÉES SUR SOURCES OFFICIELLES :
{resultats}

RÈGLE ABSOLUE ANTI-SUBSTITUTION ET ANTI-EXPANSION DE NOM :
Tu qualifies EXCLUSIVEMENT {prenom} {nom}. Si le corpus parle davantage d'une autre personne (ex: le mari, le père), ignorer leurs fonctions pour le champ "fonction" — sauf pour appliquer la règle famille_incluse. Ne JAMAIS retourner le nom d'une autre personne dans "fonction" comme si c'était celle de {prenom} {nom}.
RÈGLE CRITIQUE ANTI-EXPANSION : Si le corpus mentionne une personne dont le nom complet est DIFFÉRENT de "{prenom} {nom}" (ex: corpus parle d'"Alassane Ouattara" mais la personne cherchée est "Amadou Ouattara", ou corpus parle d'"Amadou Toumani Touré" mais cherché est "Oumar Touré") → est_pep = false. Un prénom ne peut PAS être requalifié comme deuxième prénom d'un autre PEP. La correspondance doit être EXACTE : même prénom (1ère position) + même nom.
Exception unique : si le corpus indique EXPLICITEMENT "{prenom} {nom}" comme alias confirmé de "[AUTRE NOM]" → est_pep = true.

INSTRUCTIONS :
Utilise TOUTES les informations disponibles pour déterminer si {prenom} {nom} est une PEP.
Les sources sont annotées par niveau de fiabilité :
- [OFFICIEL✅] → Source gouvernementale directe — poids maximum pour valider est_pep
- [MEDIA⚠️]   → Média fiable (AFP, RFI, Reuters) — poids moyen, confirme mais ne valide pas seul
- [WIKI🔍]    → Wikipedia — SOURCE PRIMAIRE pour les champs bio (naissance, matrimonial, enfants, fonctions historiques). Poids faible pour est_pep seul.

RÈGLE DE DÉCISION :
- 1 source [OFFICIEL✅] → suffit pour valider est_pep = true
- 2+ sources [MEDIA⚠️] sans [OFFICIEL✅] → est_pep = true avec source_validee = false
- Wikipedia seul → est_pep = false (insuffisant pour PEP) MAIS utiliser Wikipedia pour tous les champs bio

RÈGLE WIKIPEDIA POUR LES CHAMPS BIO :
Wikipedia contient la biographie complète (section introductive). Elle est LA source principale pour :
- date_naissance, lieu_naissance (ville précise), nb_enfants, statut_matrimonial, fonctions_historiques.
La section "=== TIER 2 — WIKIPEDIA ===" dans les données ci-dessous doit être lue EN ENTIER pour ces champs.

RÈGLE ABSOLUE NOMINATION RÉCENTE :
Si les données mentionnent une nomination, reconduction ou investiture en {annee} (année courante) ET cette date est POSTÉRIEURE à {date_today} → impossible, ignorer.
Si nomination confirmée AVANT {date_today} → statut_mandat = "actif" OBLIGATOIREMENT.
Exemple : "nommée ministre le 23 janvier {annee}" avec {date_today} en juin {annee} → actif.

RÈGLE ABSOLUE : La fonction retournée doit être celle de {prenom} {nom} EXCLUSIVEMENT.
Si plusieurs personnes dans les données, ignorer toutes sauf {prenom} {nom}.

RÈGLE ABSOLUE — FONCTION PEP vs RÔLE DE PARTI (PRIORITÉ MAXIMALE) :
Le champ "fonction" doit OBLIGATOIREMENT être une fonction PUBLIQUE ou GOUVERNEMENTALE.
Fonctions valides : Président de la République, Premier ministre, Ministre, Député, Sénateur, Gouverneur, Président d'assemblée, Directeur général banque centrale, Préfet, Ambassadeur, etc.
INTERDIT dans "fonction" — rôles de parti politique uniquement :
→ "Président du Parti X", "Secrétaire général du Parti Y", "Secrétaire exécutif du RHDP", "Président du FPI", "Président du Parena", etc.
Ces rôles vont UNIQUEMENT dans "fonctions_historiques", JAMAIS dans "fonction".
Si la personne est chef de parti sans fonction gouvernementale active :
→ "fonction" = dernière fonction gouvernementale connue + statut_mandat = "ex_pep"
Exemple CORRECT   : Ancien PM (2000-2003) + actuellement Président du FPI → fonction = "Premier ministre", statut_mandat = "ex_pep"
Exemple INTERDIT  : fonction = "Président du Front Populaire Ivoirien", statut_mandat = "actif" ← JAMAIS

RÈGLE FONCTION LA PLUS RÉCENTE (PRIORITÉ ABSOLUE) :
Si une fonction gouvernementale porte une date de fin explicite (ex: "Premier ministre (2011-2017)", "Prime Minister of Morocco (2011-2017)"),
cette fonction EST TERMINÉE. Ne JAMAIS retourner une fonction avec date de fin comme la fonction courante.
Cherche OBLIGATOIREMENT une fonction GOUVERNEMENTALE plus récente dans TOUTES les données (député, ministre actuel, directeur banque centrale...).
Exemples :
- OpenSanctions : "Prime Minister of Morocco (2011-2017)" → TERMINÉE en 2017
  + Wikipedia/Serper mentionne "député" → fonction = "Député", statut_mandat = "actif"
- Ancien Premier ministre (2011-2017) + actuellement député (2021-) → fonction = "Député", statut_mandat = "actif"
- Ancien ministre + actuellement directeur banque centrale → fonction = "Directeur banque centrale", statut_mandat = "actif"
- Ancien Premier ministre + actuellement Président du Parti X → fonction = "Premier ministre", statut_mandat = "ex_pep" (rôle de parti ignoré)
- Si la SEULE fonction connue a une date de fin et aucune autre fonction gouvernementale trouvée → statut_mandat = "ex_pep"

RÈGLE CHANGEMENT DE TITRE PAR RÉFORME :
Si les sources mentionnent qu'une réforme constitutionnelle ou institutionnelle a remplacé un titre officiel (ex: "Président du Conseil" remplace "Président de la République"), utiliser OBLIGATOIREMENT le NOUVEAU titre même s'il est moins fréquent dans les sources.
Le titre le plus récent prime sur le titre le plus connu historiquement.
Exemples :
- Sources : "Président de la République du Togo" (ancien) + "Président du Conseil des ministres depuis mai 2025" (réforme) → fonction = "Président du Conseil des ministres" (titre COMPLET, jamais abrégé)
- Si une réforme récente (dans les 2 dernières années) a changé l'intitulé → nouveau titre COMPLET OBLIGATOIRE

RÈGLE CRITIQUE — STATUT ACTIF vs EX_PEP :
- "ancien premier ministre", "former prime minister", "ex-président" associé à {prenom} {nom} → vérifier si une AUTRE fonction PEP est active avant de dire ex_pep
- Si une nouvelle fonction PEP active est trouvée → statut_mandat = "actif" avec la nouvelle fonction
- En cas de doute sur le statut → statut_mandat = "actif" (principe de précaution compliance)
- PIÈGE PASSÉ COMPOSÉ BIOGRAPHIQUE : "a occupé", "a exercé", "a été élu", "est devenu" dans un contexte biographique (ex: "Il a été élu président en 2020") NE signifie PAS que la fonction est terminée. C'est du français biographique standard pour décrire une fonction ENCORE EN COURS. Ne conclure ex_pep que si tu trouves EXPLICITEMENT : une date de fin, "a quitté", "a démissionné", "a été renversé", "successeur nommé", "n'est plus en fonction".

RÈGLE CRITIQUE — DATE DE FIN DE MANDAT :
Si les données indiquent une date de fin de mandat explicite (ex: "jusqu'au 24 mai 2026", "term ended May 24 2026", "mandat se termine le...") :
- Comparer cette date EXACTE à DATE D'AUJOURD'HUI ({date_today})
- Si date_fin < {date_today} → le mandat EST TERMINÉ → statut_mandat = "ex_pep"
- ATTENTION : une date de fin en {annee} peut très bien être PASSÉE si {date_today} est après cette date
- Exemple EXACT : date_fin = "24/05/2026", date_today = "29/06/2026" → 24/05 < 29/06 → ex_pep
- Ne pas confondre "terminé en {annee}" (= peut être passé) avec "pas encore terminé"

RÈGLE CRITIQUE — RÉÉLECTION / NOUVEAU MANDAT :
Si les données mentionnent une date de fin de PREMIER MANDAT mais aussi une réélection ou un NOUVEAU mandat débutant après cette date :
- La fin du premier mandat ne signifie PAS que la personne a quitté la fonction
- Si réélection confirmée (même implicitement par "second mandat", "réélu", "investi pour un nouveau mandat") → statut_mandat = "actif"
- PIÈGE FRÉQUENT : "Président de 2020 à 2025" + "réélu en 2025 pour un second mandat" → actif en 2026
- Ne conclure ex_pep que si les données indiquent explicitement qu'un SUCCESSEUR a pris ses fonctions ou que la personne a quitté le pouvoir définitivement

RÈGLES :
1. Si le nom apparaît dans les données avec une fonction → est_pep selon périmètre
2. Fonction dans le périmètre + date_fin SUPÉRIEURE à {date_today} (ou pas de date_fin) → est_pep = true, statut_mandat = "actif"
3. Toutes les fonctions connues avec date_fin INFÉRIEURE à {date_today} ET aucune nouvelle fonction → est_pep = true, statut_mandat = "ex_pep"
4. Nom absent ou aucune fonction → est_pep = false
5. Source officielle obligatoire pour valider → source_validee = true seulement si URL officielle

EXTRACTION BIOGRAPHIQUE OBLIGATOIRE :
Cherche ACTIVEMENT dans TOUTES les données (corpus principal ET extraits bio ci-dessous) les informations suivantes :
- fonction (TITRE COMPLET) : si le corpus principal contient un titre abrégé (ex: "Président du Conseil") MAIS que les extraits biographiques ci-dessous mentionnent un titre plus complet pour la même fonction (ex: "Président du Conseil des ministres"), utiliser OBLIGATOIREMENT la version la plus complète des extraits bio. La version complète prime sur l'abréviation.
- date_naissance : "né le JJ mois AAAA", "born on", "né(e) à ... le ...", "date de naissance"
- lieu_naissance : VILLE PRÉCISE uniquement — jamais le pays, jamais la région. Si le texte dit "né à Ouidah" → "Ouidah". Si "né au Dahomey" seulement → null (trop vague). Si "né à Kozah" mais texte mentionne aussi "Afagnan" pour cette personne → vérifier lequel est la ville réelle de naissance.
- nb_enfants : "père/mère de N enfants", "a N enfants", "has N children", "père de"
- fonctions_historiques : TOUTES les fonctions passées avec période — ne pas limiter à 2 ou 3. Inclure : anciens postes ministériels, postes de direction de parti politique, postes de directeur général, candidatures élues, secrétaire général, gouverneur, inspecteur général. Chercher dans les extraits bio ET dans le corpus principal.
- statut_matrimonial : chercher mention DIRECTE ou INDIRECTE — "marié(e)", "polygame", "ses deux épouses", "ses X femmes", "ses épouses", "marié à [prénom]", "son épouse [nom]", "époux/épouse de", "divorcé(e)", "veuf/veuve", "célibataire". Si la personne a plusieurs épouses mentionnées → "polygame". Chercher en priorité dans les extraits bio ci-dessous.
Ces champs sont CRITIQUES pour la conformité compliance. Ne pas les ignorer même si la priorité PEP est remplie.

EXTRAITS BIOGRAPHIQUES ET CARRIÈRE (passages du corpus complet mentionnant naissance, mariage, famille ET fonctions passées) :
{bio_passages}

Réponds UNIQUEMENT avec ce JSON :
{{
  "est_pep": true ou false,
  "fonction": "titre constitutionnel COMPLET et OFFICIEL le plus récent en français (ex: 'Président du Conseil des ministres', jamais abrégé en 'Président du Conseil') ou null",
  "fonctions_historiques": ["liste COMPLÈTE des fonctions passées avec période si connue, ex: 'Premier ministre (2011-2017)'"] ou [],
  "date_nomination": "JJ/MM/AAAA ou null",
  "date_naissance": "JJ/MM/AAAA ou AAAA ou null",
  "lieu_naissance": "VILLE précise ou null (jamais pays ou région seuls)",
  "nb_enfants": nombre entier ou null,
  "statut_matrimonial": "marié(e) / polygame / célibataire / divorcé(e) / veuf(ve) ou null",
  "source_officielle_url": "URL officielle ou non disponible",
  "source_media_url": "URL média de recoupement ou null",
  "source_type": "journal_officiel ou site_gouvernement ou agence_presse_etat ou inconnu",
  "source_validee": true ou false,
  "statut_mandat": "actif ou ex_pep",
  "raisonnement": "une phrase en français — INTERDICTION de citer des dates non présentes dans les données"
}}

RÈGLE ABSOLUE SUR LES DATES : Ne jamais inventer une date. Si la date n'apparaît pas explicitement dans les données fournies → ne pas la mentionner. Écrire uniquement ce qui est dans les données."""

def _extract_bio_passages(corpus: str) -> str:
    """Extrait les passages biographiques pertinents du corpus complet (au-delà des 8000 premiers chars)."""
    if not corpus or len(corpus) < 2000:
        return "(aucun extrait bio supplémentaire)"
    keywords = [
        # Bio personnelle
        "épouse", "épouses", "ses femmes", "ses deux femmes", "polygame", "polygamie",
        "marié", "mariée", "mariage", "célibataire", "divorcé", "veuf", "veuve",
        "né à", "né le", "née à", "née le", "date de naissance", "naissance",
        "born in", "born on", "nació", "enfants", "père de", "mère de", "fils de", "fille de",
        # Nomination récente — critique pour détecter une reconfirmation en année courante
        "nommé", "nommée", "reconduit", "reconduite", "investi", "investie",
        "prend ses fonctions", "entre en fonctions", "appointed", "sworn in",
        # Carrière / fonctions historiques
        "ancien ", "ancienne ", "a été ", "a exercé", "a occupé",
        "former ", "previously ", "secrétaire général", "secretary general",
        "inspecteur", "directeur général", "candidat ", "parti politique",
        "de 19", "de 20",  # périodes "de 2010 à 2015"
        "premier ministre", "ministre de", "président de l", "président du",
        "conseil des ministres",  # titre constitutionnel complet (ex: Président du Conseil des ministres)
        "chef de gouvernement", "vice-président", "gouverneur",
    ]
    passages = []
    seen_buckets = set()
    cl = corpus.lower()
    for kw in keywords:
        idx = cl.find(kw)
        while idx != -1:
            bucket = idx // 400
            if bucket not in seen_buckets:
                start = max(0, idx - 200)
                end   = min(len(corpus), idx + 500)
                passages.append(corpus[start:end].strip())
                seen_buckets.add(bucket)
                seen_buckets.add(bucket - 1)
                seen_buckets.add(bucket + 1)
            idx = cl.find(kw, idx + 1)
    if not passages:
        return "(aucun passage bio trouvé dans le corpus)"
    return "\n---\n".join(passages[:20])[:8000]

def _extraire_fonctions_historiques(prenom: str, nom: str, corpus: str) -> list[str]:
    """Appel LLM dédié : extrait uniquement les fonctions passées depuis le corpus Wikipedia."""
    if not corpus or len(corpus) < 500:
        return []
    extrait = corpus[:12000]
    prompt = (
        f"Tu es un expert AML. Extrait TOUTES les fonctions et postes passés de {prenom} {nom} "
        f"mentionnés dans le texte ci-dessous.\n\n"
        f"RÈGLES STRICTES :\n"
        f"- Ne retourner QUE les fonctions PASSÉES (terminées), pas la fonction actuelle.\n"
        f"- Inclure : ministres, secrétaires généraux, directeurs généraux, responsables de parti, "
        f"gouverneurs, candidats élus, tout poste officiel ou politique antérieur.\n"
        f"- Format de chaque fonction : 'Titre (AAAA-AAAA)' ou 'Titre (AAAA)' si une seule date connue, "
        f"ou 'Titre' si aucune date trouvée.\n"
        f"- Si aucune fonction passée trouvée → retourner [].\n"
        f"- Ne jamais inventer. Ne retourner que ce qui est explicitement dans le texte.\n\n"
        f"TEXTE :\n{extrait}\n\n"
        f"Réponds UNIQUEMENT avec un JSON array : "
        f'["Fonction 1 (AAAA-AAAA)", "Fonction 2 (AAAA)", ...] ou []'
    )
    try:
        resp = _llm_invoke(prompt)
        content = resp.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        idx_start = content.find("[")
        idx_end   = content.rfind("]")
        if idx_start != -1 and idx_end != -1:
            parsed = json.loads(content[idx_start:idx_end+1])
            return [f for f in parsed if isinstance(f, str) and f.strip()]
    except Exception:
        pass
    return []


def node_qualify(state: PEPState) -> PEPState:
    """Étape 4 — Qualifier PEP selon le périmètre du referentiel_pep."""
    def _norm(s):
        return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()

    print(f"\n[Étape 4] Qualification selon critères {state['code_iso']}...")

    if state["code_iso"] == "XX":
        print(f"  REJETÉ : pays hors périmètre ScreenEdge Africa (13 pays couverts)")
        return {**state, "est_pep": False, "raisonnement": "Pays hors périmètre — ScreenEdge Africa couvre MA, DZ, TN, LY, SN, CI, ML, BF, NE, TG, BJ, GW, GN uniquement."}

    # Recharger critères si pays corrigé par OpenSanctions après node_get_criteria (XX → pays connu)
    criteres_actifs = state["criteres"]
    if state["code_iso"] != "XX" and "fallback GAFI" in criteres_actifs:
        code_uc = state["code_iso"].upper()
        if code_uc in _referentiel_json:
            entry = _referentiel_json[code_uc]
            criteres_actifs = json.dumps({
                "pays":            entry["pays"],
                "statut_gafi":     entry["statut_gafi"],
                "vigilance":       entry["vigilance"],
                "loi_reference":   entry["loi_reference"],
                "fonctions_pep":   entry["fonctions_pep"],
                "famille_incluse": entry["famille_incluse"],
                "proches_associes":entry["proches_associes"],
                "duree_ex_pep":    entry["duree_ex_pep"],
                "reevaluation":    entry["reevaluation"],
            }, ensure_ascii=False, indent=2)
            print(f"  Critères rechargés via OpenSanctions : {entry['statut_gafi']} | {len(entry['fonctions_pep'])} fonctions PEP")

    try:
        # Utiliser corpus_brut (non filtré) — extraire_passages_nom() supprime les passages
        # bio sans mots de fonction (ex: "marié avec...", "père de trois enfants")
        bio_passages = _extract_bio_passages(
            state.get("corpus_brut") or state.get("resultats_recherche", "")
        )
        prompt = PROMPT_QUALIFICATION.format(
            prenom=state["prenom"], nom=state["nom"],
            pays=state["pays_nom"],
            criteres=criteres_actifs,
            resultats=state["resultats_recherche"][:8000],
            bio_passages=bio_passages,
            annee=datetime.now().year,
            date_today=datetime.now().strftime("%d/%m/%Y")
        )
        response = _llm_invoke(prompt)
        # Capturer prompt + réponse pour l'audit
        _audit_llm["prompt"]  = prompt[:6000]
        _audit_llm["reponse"] = response.content[:3000] if response else ""
        content = response.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        start = content.find("{"); end = content.rfind("}") + 1
        data = json.loads(content[start:end])
        est_pep = bool(data.get("est_pep", False))
        # Mémoriser le raisonnement brut du LLM avant que les garde-codes le modifient
        _raison_llm_initial = (data.get("raisonnement") or "").lower()
        print(f"  est_pep={est_pep} | {data.get('fonction') or 'non-PEP'}")
        est_pep               = bool(data.get("est_pep", False))
        fonction              = data.get("fonction") or ""
        # Vérification corpus : si le LLM a extrait un titre tronqué, chercher la suite dans le corpus
        if fonction:
            _corpus_verif = (state.get("corpus_brut") or "") + " " + bio_passages
            _m = re.search(
                re.escape(fonction) + r'\s+(des\s+ministres)',
                _corpus_verif, re.IGNORECASE
            )
            if _m:
                fonction = fonction + " " + _m.group(1)
                print(f"  [Titre complet corpus] → {fonction!r}")
        fonctions_historiques = [f for f in (data.get("fonctions_historiques") or []) if f and isinstance(f, str)]
        # Appel LLM dédié si le prompt principal n'a rien extrait
        if not fonctions_historiques:
            corpus_brut = state.get("corpus_brut") or state.get("resultats_recherche", "")
            fonctions_historiques = _extraire_fonctions_historiques(
                state["prenom"], state["nom"], corpus_brut
            )
            if fonctions_historiques:
                print(f"  [CRA] {len(fonctions_historiques)} fonctions historiques extraites par appel dédié")
        source_off_url        = data.get("source_officielle_url") or ""
        source_med_url        = data.get("source_media_url") or ""
        source_validee        = bool(data.get("source_validee", False))
        statut_mandat         = data.get("statut_mandat") or "actif"
        date_naissance        = data.get("date_naissance") or ""
        lieu_naissance        = data.get("lieu_naissance") or ""
        nb_enfants            = data.get("nb_enfants")
        statut_matrimonial    = data.get("statut_matrimonial") or ""

        # ── ENRICHISSEMENT WIKIPEDIA : champs bio vides sur PEP confirmé ─────
        # Déclenché si est_pep=True MAIS fonctions_historiques ou naissance manquants
        # (source officielle n'a souvent que l'info actuelle, pas la biographie)
        _bio_incomplet = (
            est_pep and
            (not fonctions_historiques
             or not date_naissance.strip()
             or not lieu_naissance.strip())
        )
        if _bio_incomplet:
            try:
                import requests as _rq
                _WIKI_UA = {"User-Agent": "ScreenEdge/1.0 (compliance@screenedge.ai)"}
                _nom_complet = f"{state['prenom']} {state['nom']}"
                # Nom court = premier prénom seulement + nom (ex: "Faure Gnassingbé" au lieu de "Faure Essozimina Gnassingbé")
                _prenom_court = state['prenom'].split()[0]
                _nom_court = f"{_prenom_court} {state['nom']}"
                _nom_variantes = list(dict.fromkeys([_nom_complet, _nom_court]))
                _wiki_text = ""
                # Essai 1 : URL directe fr puis en, avec variantes du nom
                for _nom_wiki_v in _nom_variantes:
                    if _wiki_text:
                        break
                    for _lang in ("fr", "en"):
                        _slug = _nom_wiki_v.replace(" ", "_")
                        try:
                            _rw = _rq.get(
                                f"https://{_lang}.wikipedia.org/w/api.php",
                                params={"action": "query", "titles": _slug,
                                        "prop": "extracts", "explaintext": True,
                                        "exsectionformat": "plain", "format": "json", "redirects": 1},
                                headers=_WIKI_UA,
                                timeout=12
                            )
                            for _p in _rw.json().get("query", {}).get("pages", {}).values():
                                _txt = _p.get("extract", "") or ""
                                if _txt and len(_txt) > 300 and str(_p.get("pageid", "")) != "-1":
                                    _wiki_text = _txt
                                    print(f"  [Wiki-bio] {_lang}.wikipedia '{_nom_wiki_v}' → {len(_wiki_text)} chars")
                                    break
                        except Exception:
                            pass
                        if _wiki_text:
                            break
                # Essai 2 : recherche Wikipedia avec nom court (meilleur match titre)
                if not _wiki_text:
                    try:
                        _rs = _rq.get(
                            "https://fr.wikipedia.org/w/api.php",
                            params={"action": "query", "list": "search",
                                    "srsearch": _nom_court, "srlimit": 5, "format": "json"},
                            headers=_WIKI_UA,
                            timeout=10
                        )
                        # Match : prénom court ET nom tous présents dans le titre
                        _parts_min = [p.lower() for p in _nom_court.split() if len(p) > 2]
                        for _sr in _rs.json().get("query", {}).get("search", []):
                            _stitle = _sr.get("title", "")
                            _stitle_low = _stitle.lower()
                            if all(p in _stitle_low for p in _parts_min):
                                try:
                                    _rw2 = _rq.get(
                                        "https://fr.wikipedia.org/w/api.php",
                                        params={"action": "query", "titles": _stitle.replace(" ", "_"),
                                                "prop": "extracts", "explaintext": True,
                                                "exsectionformat": "plain", "format": "json", "redirects": 1},
                                        headers=_WIKI_UA,
                                        timeout=12
                                    )
                                    for _p2 in _rw2.json().get("query", {}).get("pages", {}).values():
                                        _txt2 = _p2.get("extract", "") or ""
                                        if _txt2 and len(_txt2) > 300:
                                            _wiki_text = _txt2
                                            print(f"  [Wiki-bio] recherche → '{_stitle}' ({len(_wiki_text)} chars)")
                                            break
                                except Exception:
                                    pass
                            if _wiki_text:
                                break
                    except Exception:
                        pass

                if _wiki_text:
                    _nom_wiki = _nom_complet
                    # Fonctions historiques
                    if not fonctions_historiques:
                        fonctions_historiques = _extraire_fonctions_historiques(
                            state["prenom"], state["nom"], _wiki_text
                        )
                        if fonctions_historiques:
                            print(f"  [Wiki-bio] {len(fonctions_historiques)} fonctions historiques extraites")
                    # Date/lieu naissance si manquants
                    if not date_naissance.strip() or not lieu_naissance.strip():
                        _pb = (
                            f"Extrait date_naissance et lieu_naissance de {_nom_wiki} "
                            f"depuis ce texte Wikipedia.\n"
                            f"Réponds UNIQUEMENT en JSON : "
                            f'{{\"date_naissance\": \"JJ/MM/AAAA ou null\", \"lieu_naissance\": \"VILLE ou null\"}}\n\n'
                            f"TEXTE :\n{_wiki_text[:6000]}"
                        )
                        try:
                            _rb = _llm_invoke(_pb)
                            _cb = _rb.content.strip()
                            if "```" in _cb:
                                _cb = _cb.split("```json")[1].split("```")[0] if "```json" in _cb else _cb.split("```")[1].split("```")[0]
                            _db = json.loads(_cb[_cb.find("{"):_cb.rfind("}")+1])
                            if not date_naissance.strip():
                                date_naissance = _db.get("date_naissance") or ""
                            if not lieu_naissance.strip():
                                lieu_naissance = _db.get("lieu_naissance") or ""
                            if date_naissance or lieu_naissance:
                                print(f"  [Wiki-bio] né le {date_naissance} à {lieu_naissance}")
                        except Exception:
                            pass
            except Exception as _we:
                print(f"  [Wiki-bio] Erreur fetch : {_we}")

        # ── GARDE CODE 0 : Vérifier que la fonction est attribuée au bon nom ────
        # Évite la confusion avec homonymes / membres de famille
        if est_pep and fonction.strip():
            corpus = state.get("resultats_recherche", "")
            nom_parts = [_norm(p) for p in f"{state['prenom']} {state['nom']}".split() if len(p) > 2]
            mots_fonction = [_norm(m) for m in fonction.split() if len(m) > 3]

            # Chercher si nom + fonction apparaissent dans le même passage (± 500 chars)
            nom_present_pres_fonction = False
            corpus_lower = _norm(corpus)
            for i in range(len(corpus_lower) - 500):
                fenetre = corpus_lower[i:i+500]
                if any(p in fenetre for p in nom_parts) and any(m in fenetre for m in mots_fonction):
                    nom_present_pres_fonction = True
                    break

            # Fallback : nom présent quelque part dans la page ET fonction aussi
            if not nom_present_pres_fonction:
                nom_dans_page     = any(p in corpus_lower for p in nom_parts)
                fonction_dans_page = any(m in corpus_lower for m in mots_fonction)
                if nom_dans_page and fonction_dans_page:
                    nom_present_pres_fonction = True

            if (not nom_present_pres_fonction
                    and len(corpus.split()) > 300
                    and not state.get("opensanctions_confirmed", False)):
                est_pep = False
                data["raisonnement"] = (
                    f"Fonction '{fonction}' trouvée dans le corpus mais non attribuée "
                    f"directement à {state['prenom']} {state['nom']} — possible confusion."
                )
                print(f"  REJETÉ : fonction non attribuée directement au nom cherché")

        # ── GARDE CODE 0b : Nom commun sans discriminant biographique ────────────
        # Si ≤ 2 parties de nom ET aucune info biographique (date/lieu naissance)
        # → flag "à vérifier" sans rejeter (faux négatif GAFI plus dangereux)
        # Stocké dans _gc0b_flag — ajouté au raisonnement final après tous les GCs
        _gc0b_flag = ""
        if est_pep and not state.get("opensanctions_confirmed", False):
            _parts_sig = [_norm(p) for p in f"{state['prenom']} {state['nom']}".split() if len(p) > 2]
            _a_discriminant = bool(date_naissance.strip() or lieu_naissance.strip())
            if len(_parts_sig) <= 2 and not _a_discriminant:
                _gc0b_flag = (
                    "[NOM POTENTIELLEMENT AMBIGU — aucun discriminant biographique trouvé. "
                    "Confirmer date de naissance OU lieu de naissance avant insertion.]"
                )
                print(f"  [GC0b] Nom ambigu ({state['prenom']} {state['nom']}) — discriminant manquant")

        # ── GARDE CODE 0c : Anti-homonyme — le nom complet cherché doit être l'entité principale ─
        # Cas cible : "Amadou Ouattara" → corpus parle d'"Alassane Amadou Ouattara" (Alassane = PEP)
        if est_pep and not state.get("opensanctions_confirmed", False):
            _prenom0 = _norm(state["prenom"].split()[0])
            _nom0    = _norm(state["nom"].split()[0])
            _corp0   = _norm(state.get("resultats_recherche", ""))
            # Exclure les titres/fonctions des "autres prénoms" pour éviter les faux positifs
            _STOP_GC0C = {"president", "ministre", "chef", "ancien", "general", "directeur",
                          "gouverneur", "premier", "colonel", "vice", "ex", "feu", "ambassadeur"}
            _autres_prenoms = re.findall(
                r'\b([a-z]{3,})\s+(?:[a-z]+\s+)?' + re.escape(_nom0) + r'\b', _corp0
            )
            _autres = [p for p in _autres_prenoms
                       if p != _prenom0 and not _prenom0.startswith(p) and not p.startswith(_prenom0)
                       and p not in _STOP_GC0C]
            # Chercher si prenom0 apparaît comme PREMIER prénom (pas prénom intermédiaire)
            # Ex: "alassane amadou ouattara" → amadou est précédé par "e " (alpha+espace) → non-direct
            _match_direct = False
            for _m in re.finditer(re.escape(_prenom0) + r'\s+(?:[a-z]+\s+)?' + re.escape(_nom0) + r'\b', _corp0):
                _s = _m.start()
                if _s >= 2 and _corp0[_s - 1] == ' ' and _corp0[_s - 2].isalpha():
                    continue  # Embedded dans un nom plus long (ex: "alassane amadou ouattara")
                _match_direct = True
                break
            if (not _match_direct
                    and len(_autres) >= 4
                    and len(_corp0.split()) > 300
                    and not (date_naissance.strip() or lieu_naissance.strip())):
                est_pep = False
                _dominant = max(set(_autres), key=_autres.count) if _autres else "?"
                data["raisonnement"] = (
                    f"'{state['prenom']} {state['nom']}' non trouvé en tête dans le corpus — "
                    f"le nom '{state['nom']}' est principalement associé à '{_dominant}' ({len(_autres)}× occurrences). "
                    f"Homonyme probable : vérifier manuellement."
                )
                print(f"  REJETÉ [GC0c] : '{state['prenom']} {state['nom']}' absent en tête — homonyme probable (dominant: {_dominant})")

        # ── NETTOYAGE FONCTION : supprimer articles/prénoms parasites ──────────
        if fonction:
            # Supprimer "Le ", "La ", "Les ", prénom inclus par erreur
            fonction = re.sub(r'^(le |la |les |l\')', '', fonction, flags=re.IGNORECASE).strip()
            # Si la fonction contient le prénom de la personne → extraire juste le titre
            for mot in state["prenom"].split():
                if len(mot) > 2 and mot.lower() in fonction.lower():
                    fonction = re.sub(re.escape(mot), '', fonction, flags=re.IGNORECASE).strip()
            fonction = re.sub(r'\s+', ' ', fonction).strip()

        # ── GARDE CODE 1 : est_pep sans fonction → forcé False ───────────────────
        if est_pep and not fonction.strip():
            est_pep = False
            data["raisonnement"] = "Aucune fonction publique identifiée."

        # ── GARDE CODE 2 : URLs stockées proprement dans le state ───────────────
        urls_off = state.get("urls_officielles_trouvees", [])
        urls_med = state.get("urls_media_trouvees", [])
        print(f"  URLs state — off:{len(urls_off)} media:{len(urls_med)}")

        # Vérifier si l'URL retournée par le LLM est officielle
        source_off_verifiee = est_source_officielle(source_off_url)

        # Si LLM retourne non-officielle → utiliser la meilleure URL officielle du state
        if not source_off_verifiee and urls_off:
            source_off_url      = urls_off[0]
            source_off_verifiee = True
            print(f"  URL officielle du state : {source_off_url[:60]}")
        source_med_verifiee = not any(d in source_med_url.lower() for d in DOMAINES_INTERDITS) \
                              if source_med_url else False

        # Si est_pep=True mais AUCUNE source officielle
        if est_pep and not source_off_verifiee:
            nb_tier2 = len(urls_med)
            nb_wiki  = state.get("resultats_recherche", "").count("[WIKI🔍]")

            if nb_tier2 >= 2:
                # 2+ sources médias convergent → accepté avec confiance réduite
                print(f"  ACCEPTÉ via {nb_tier2} sources Tier 2 (pas d'officielle disponible)")
                data["raisonnement"] = (data.get("raisonnement") or "") + \
                    f" [Validé par {nb_tier2} sources médias — source officielle inaccessible]"
            elif nb_tier2 == 1 and nb_wiki >= 1:
                # 1 média + Wikipedia → accepté avec confiance faible
                print(f"  ACCEPTÉ via média + Wikipedia (source officielle inaccessible)")
                data["raisonnement"] = (data.get("raisonnement") or "") + \
                    " [Validé par 1 média + Wikipedia — vérifier source officielle]"
            elif state.get("opensanctions_confirmed", False):
                # OpenSanctions Tier 3 confirme PEP → source compliance de référence
                print(f"  ACCEPTÉ via OpenSanctions Tier 3 (source officielle inaccessible)")
                data["raisonnement"] = (data.get("raisonnement") or "") + \
                    " [Validé par OpenSanctions Tier 3 — source officielle inaccessible]"
            else:
                est_pep = False
                data["raisonnement"] = (
                    f"Information insuffisante — aucune source officielle ni consensus médias."
                )
                print(f"  REJETÉ : sources insuffisantes")

        # URL finale = source officielle (prioritaire) ou média si officielle manque
        source_url_finale = source_off_url if source_off_verifiee else "non disponible"

        print(f"  est_pep={est_pep} | source_off={'✅' if source_off_verifiee else '❌'} | {fonction or 'non-PEP'}")

        # ── GARDE CODE 3 : Consensus multi-sources ────────────────────────────
        # Si une fonction est trouvée, la valider par consensus (min 2 sources)
        fonction_validee = fonction
        if est_pep and fonction.strip():
            print(f"  Vérification consensus multi-sources...")
            consensus = consensus_sources(
                f"{state['prenom']} {state['nom']}",
                state["pays_nom"],
                state["code_iso"],
                _LLM_CHAIN[0][0],
                min_sources=2
            )
            if consensus["confiant"]:
                fonc_consensus = (consensus["fonction"] or "").strip().rstrip(".")
                # Ignorer si le consensus retourne une valeur vide ou non informative
                VALEURS_NULLES = {"", "inconnu", "null", "none", "n/a", "non disponible"}
                if fonc_consensus.lower() not in VALEURS_NULLES:
                    fonction_validee = fonc_consensus
                    print(f"  Consensus validé : '{fonction_validee}' ({consensus['score']}/{consensus['total']} sources)")
                else:
                    print(f"  Consensus retourné invalide ('{consensus['fonction']}') → fonction initiale conservée")
            elif consensus["total"] > 0 and not consensus["confiant"]:
                # Sources consultées mais pas de consensus → garder la fonction initiale avec avertissement
                print(f"  Pas de consensus clair ({consensus['total']} source(s)) → fonction initiale conservée")
            # Si 0 sources → pas de changement

        # ── GARDE CODE 4 : Validation date en code ───────────────────────────
        # La date ne doit venir que des sources — si absente dans les données → null
        date_brute = data.get("date_nomination") or ""
        resultats  = state.get("resultats_recherche", "")

        if date_brute:
            # Vérifier que la date existe réellement dans les résultats de recherche
            date_chiffres = re.sub(r'[^0-9]', '', date_brute)  # "22/01/2026" → "22012026"
            if len(date_chiffres) >= 4:
                annee_date = date_chiffres[-4:]
                # Construire plusieurs formes possibles de la date pour la recherche
                formes_date = [date_brute]  # forme originale ex: "24/03/2024"
                if len(date_chiffres) == 8:
                    j, m, a = date_chiffres[:2], date_chiffres[2:4], date_chiffres[4:]
                    formes_date += [
                        f"{j}/{m}/{a}", f"{j}-{m}-{a}", f"{j}.{m}.{a}",
                        f"{a}-{m}-{j}", f"{a}/{m}/{j}",  # format ISO
                        f"{int(j)} {a}", f"{a}",          # mention partielle
                    ]
                # La date est valide si au moins une forme est trouvée dans les sources
                # Pour les années seules (ex: "1987"), vérifier directement sans contrainte len>=6
                if len(date_chiffres) == 4:
                    date_dans_sources = annee_date in resultats
                else:
                    date_dans_sources = any(f in resultats for f in formes_date if len(f) >= 6)
                # Exclure aussi la date du jour (LLM hallucination fréquente)
                aujourd_hui = datetime.now().strftime("%d/%m/%Y")
                if date_brute == aujourd_hui or not date_dans_sources:
                    date_brute = ""
                    print(f"  Date rejetée (non trouvée dans sources) : {data.get('date_nomination')}")

        # Nettoyer aussi le raisonnement des dates inventées
        raisonnement = data.get("raisonnement") or ""
        if date_brute == "" and data.get("date_nomination"):
            raisonnement = re.sub(
                r'depuis le \d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4}|'
                r'en fonction depuis \d{4}|'
                r'nommé[e]? le \d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4}',
                '', raisonnement
            ).strip()

        # Rescue regex — si LLM n'a pas trouvé de date valide, chercher dans corpus tous tiers
        if not date_brute and est_pep:
            nom_complet_gc4 = f"{state['prenom']} {state['nom']}"
            date_regex = extraire_date_nomination(resultats, nom_complet_gc4)
            if date_regex:
                date_brute = date_regex
                print(f"  Date nomination extraite par regex (corpus multi-tiers) : {date_brute}")

        # Rescue OpenSanctions date_debut — si encore vide, lire depuis corpus_brut
        if not date_brute and est_pep:
            corpus_brut_gc4 = state.get("corpus_brut", "")
            m_os = re.search(r'"date_debut":\s*"(\d{4}[^"]*)"', corpus_brut_gc4)
            if m_os:
                raw_d = m_os.group(1).strip()
                try:
                    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw_d):
                        date_brute = datetime.strptime(raw_d, "%Y-%m-%d").strftime("%d/%m/%Y")
                    elif re.fullmatch(r'\d{4}', raw_d):
                        date_brute = raw_d  # convertir_date gère AAAA → AAAA-01-01
                    if date_brute:
                        print(f"  Date nomination extraite depuis OpenSanctions (date_debut) : {date_brute}")
                except Exception:
                    pass

        if not date_brute:
            raisonnement += " [Date de nomination non trouvée dans les sources disponibles]"

        # ── GARDE CODE 5 : Signal ex-PEP → re-qualification ciblée ─────────────
        # Le code détecte les indices de fin de mandat dans le corpus.
        # Si trouvé → on re-soumet au LLM avec le signal mis en évidence.
        # Le LLM juge si le signal concerne vraiment la personne (évite les faux positifs).
        MOTS_FIN_MANDAT = [
            # Français
            "renversé", "destitué", "coup d'état", "coup d etat",
            "démissionné", "a démissionné", "a quitté le pouvoir",
            "ancien président", "ancien premier ministre",
            "ex-président", "ex-premier ministre",
            "n'est plus en fonction", "a été remplacé", "lui a succédé",
            "fin de mandat", "a quitté ses fonctions",
            "quitté la présidence", "fin de son mandat",
            "décédé", "mort en", "en exil",
            "emprisonné", "placé en détention",
            # Anglais (résultats Tavily souvent en anglais)
            "former president", "former prime minister", "former minister",
            "left office", "resigned", "was ousted", "was overthrown",
            "end of term", "was replaced", "succeeded by",
            "in exile", "arrested", "detained", "under arrest",
            "house arrest",
        ]
        statut_mandat = data.get("statut_mandat") or statut_mandat
        signaux_trouves = []

        def _norm(s):
            return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()

        # Scan toujours si pays en périmètre — attrape aussi les faux négatifs (est_pep=False)
        # Utilise corpus_brut (non filtré) pour ne pas rater les signaux exclus par extraire_passages_nom[:5]
        if state["code_iso"] != "XX" and statut_mandat != "ex_pep":
            corpus_check = _norm((state.get("corpus_brut") or state.get("resultats_recherche", "")) or "")
            nom_parts    = [_norm(p) for p in [state["prenom"], state["nom"]] if len(p) > 2]
            for mot in MOTS_FIN_MANDAT:
                mot_norm = _norm(mot)  # normaliser le mot-clé comme le corpus
                idx = corpus_check.find(mot_norm)
                while idx != -1:
                    fenetre = corpus_check[max(0, idx-300):idx+300]
                    if any(p in fenetre for p in nom_parts):
                        raw_corpus = state.get("corpus_brut") or state.get("resultats_recherche", "")
                        passage = raw_corpus[max(0, idx-400):idx+400].strip()
                        signaux_trouves.append(f'"{mot}" → ...{passage}...')
                        break
                    idx = corpus_check.find(mot_norm, idx + 1)

        if signaux_trouves:
            signal_txt = "\n".join(f"  - {s}" for s in signaux_trouves[:3])
            label_gc5  = "re-qualification" if est_pep else "faux négatif ?"
            print(f"  [Garde-code 5] {len(signaux_trouves)} signal(s) fin de mandat → {label_gc5}...")
            try:
                if est_pep:
                    # PEP confirmé → vérifier si le statut doit passer à ex_pep
                    # Prompt renforcé : distingue "{nom} est ancien" vs "ancien [autre] près de {nom}"
                    # IMPORTANT : passer fonction_validee pour distinguer ancienne vs nouvelle fonction
                    prompt_gc5 = (
                        f"ANNÉE COURANTE : {datetime.now().year}\n"
                        f"PERSONNE ANALYSÉE : {state['prenom']} {state['nom']}\n"
                        f"FONCTION ACTUELLEMENT IDENTIFIÉE (la plus récente) : {fonction_validee or 'non déterminée'}\n\n"
                        f"Passages associant '{state['nom']}' à des termes de fin de mandat :\n{signal_txt}\n\n"
                        f"Réponds en 2 champs JSON :\n"
                        f"1. 'signal_sur_fonction_actuelle' : true si le signal de fin de mandat concerne "
                        f"PRÉCISÉMENT la FONCTION ACTUELLEMENT IDENTIFIÉE ('{fonction_validee}'), "
                        f"false si le signal concerne une ANCIENNE fonction différente.\n"
                        f"   Exemples :\n"
                        f"   - fonction='Secrétaire général PJD' + signal='ancien premier ministre' → signal_sur_fonction_actuelle = false (le signal parle de PM, pas de SG)\n"
                        f"   - fonction='Président' + signal='ancien président' → signal_sur_fonction_actuelle = true\n"
                        f"   - fonction='Premier ministre' + signal='ancien premier ministre' → signal_sur_fonction_actuelle = true\n"
                        f"2. 'raison' : une phrase expliquant pourquoi le signal concerne ou non la fonction actuelle.\n\n"
                        f"Règle finale : ex_pep = true UNIQUEMENT si signal_sur_fonction_actuelle = true ET la fonction actuelle est clairement terminée avant {datetime.now().year}.\n"
                        f"Si signal_sur_fonction_actuelle = false → ex_pep = false (le signal parle d'une ancienne fonction, pas de l'actuelle).\n\n"
                        f"Réponds UNIQUEMENT en JSON : {{\"signal_sur_fonction_actuelle\": true ou false, \"ex_pep\": true ou false, \"raison\": \"une phrase\"}}"
                    )
                    resp_gc5 = _llm_invoke(prompt_gc5)
                    content_gc5 = resp_gc5.content.strip()
                    if "```json" in content_gc5:
                        content_gc5 = content_gc5.split("```json")[1].split("```")[0]
                    elif "```" in content_gc5:
                        content_gc5 = content_gc5.split("```")[1].split("```")[0]
                    gc5_data = json.loads(content_gc5[content_gc5.find("{"):content_gc5.rfind("}")+1])
                    signal_sur_actuelle = gc5_data.get("signal_sur_fonction_actuelle", True)
                    if gc5_data.get("ex_pep") is True and signal_sur_actuelle is not False:
                        statut_mandat = "ex_pep"
                        raisonnement  = gc5_data.get("raison", raisonnement)
                        print(f"  [Garde-code 5] Confirmé ex-PEP : {gc5_data.get('raison', '')}")
                    elif signal_sur_actuelle is False:
                        print(f"  [Garde-code 5] Signal concerne une ancienne fonction → statut conservé : {statut_mandat}")
                    else:
                        print(f"  [Garde-code 5] Signal non confirmé → statut conservé : {statut_mandat}")
                else:
                    # Faux négatif : LLM n'a pas trouvé de fonction → vérification approfondie
                    _gc5_votes = state.get("_votes_pays", 4)
                    _gc5_alerte_pays = (
                        f"\n⚠️  ALERTE : Le pays d'identification est INCERTAIN ({_gc5_votes} vote(s) seulement). "
                        f"Sois TRÈS prudent — n'élève PAS à PEP sauf preuve explicite et indiscutable.\n"
                    ) if _gc5_votes <= 2 else ""
                    prompt_gc5 = (
                        f"ANNÉE COURANTE : {datetime.now().year}\n"
                        f"PAYS : {state['pays_nom']}\n"
                        f"PERSONNE : {state['prenom']} {state['nom']}\n\n"
                        f"Des passages contiennent des indices sur le statut de cette personne :\n{signal_txt}\n\n"
                        f"CRITÈRES PEP DU PAYS (extrait) :\n{state['criteres'][:600]}\n\n"
                        f"{_gc5_alerte_pays}"
                        f"RÈGLES STRICTES :\n"
                        f"- was_pep = true UNIQUEMENT si les passages décrivent EXPLICITEMENT que "
                        f"'{state['prenom']} {state['nom']}' a EUX-MÊMES occupé la fonction "
                        f"(ex: '{state['nom']} a quitté la présidence', '{state['nom']}, ancien premier ministre')\n"
                        f"- PIÈGE À ÉVITER : si une AUTRE personne est citée comme 'ancien président' "
                        f"ou 'former president' dans le même passage que '{state['nom']}', "
                        f"ce n'est PAS une preuve que '{state['nom']}' est PEP → was_pep = false\n"
                        f"- Si was_pep = true → la personne reste PEP indéfiniment (duree_ex_pep='permanente')\n"
                        f"- En cas de doute → was_pep = false\n\n"
                        f"Réponds UNIQUEMENT en JSON :\n"
                        f"{{\"was_pep\": true ou false, "
                        f"\"statut_mandat\": \"actif si encore en poste en {datetime.now().year}, ex_pep si a quitté\", "
                        f"\"fonction\": \"titre officiel en français ou null\", "
                        f"\"raison\": \"une phrase précisant la fonction et le statut actuel\"}}"
                    )
                    resp_gc5 = _llm_invoke(prompt_gc5)
                    content_gc5 = resp_gc5.content.strip()
                    if "```json" in content_gc5:
                        content_gc5 = content_gc5.split("```json")[1].split("```")[0]
                    elif "```" in content_gc5:
                        content_gc5 = content_gc5.split("```")[1].split("```")[0]
                    gc5_data = json.loads(content_gc5[content_gc5.find("{"):content_gc5.rfind("}")+1])
                    if gc5_data.get("was_pep") is True:
                        est_pep          = True
                        statut_mandat    = gc5_data.get("statut_mandat", "ex_pep")
                        fonction_gc5     = gc5_data.get("fonction") or "ancienne fonction publique"
                        fonction_validee = fonction_gc5
                        raisonnement     = gc5_data.get("raison", raisonnement)
                        if source_url_finale == "non disponible" and urls_med:
                            source_url_finale = urls_med[0]
                        print(f"  [Garde-code 5] Faux négatif corrigé → ex-PEP : {gc5_data.get('raison', '')}")
                    else:
                        print(f"  [Garde-code 5] Faux négatif non confirmé → Non-PEP conservé")
            except Exception as e:
                print(f"  [Garde-code 5] Erreur re-qualification : {e}")

        # ── Extraction date fin de mandat (ex-PEP uniquement) ─────────────────
        # NB: statut_mandat peut avoir été corrigé par GC5 juste avant → relire
        date_fin_mandat = ""
        if statut_mandat == "ex_pep" or (est_pep and statut_mandat == "ex_pep"):
            corpus_fin = state.get("corpus_brut") or state.get("resultats_recherche", "")
            nom_complet_fin = f"{state['prenom']} {state['nom']}"
            # 1. Regex sur corpus
            date_fin_mandat = extraire_date_fin_mandat(corpus_fin, nom_complet_fin)
            if date_fin_mandat:
                print(f"  Date fin mandat extraite (regex) : {date_fin_mandat}")
            # 2. Fallback OpenSanctions endDate / positionEnd
            if not date_fin_mandat:
                m_end = re.search(
                    r'"(?:endDate|positionEnd)":\s*"(\d{4}[^"]*)"',
                    state.get("corpus_brut", "")
                )
                if m_end:
                    raw_end = m_end.group(1).strip()
                    try:
                        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw_end):
                            date_fin_mandat = datetime.strptime(raw_end, "%Y-%m-%d").strftime("%d/%m/%Y")
                        elif re.fullmatch(r'\d{4}', raw_end):
                            date_fin_mandat = raw_end
                        if date_fin_mandat:
                            print(f"  Date fin mandat extraite (OpenSanctions endDate) : {date_fin_mandat}")
                    except Exception:
                        pass

        source_type_gc6 = None  # surchargé par GC6 si Wikipedia trouvé ou "a_verifier"

        # ── GARDE CODE 6 : Corpus vide + haute fonction identifiée → LLM mémoire ──
        # Déclenché si Tavily a échoué (corpus quasi-vide) mais node_identify a trouvé
        # une haute fonction dans un pays du périmètre.
        # Dernier filet de sécurité 0-faux-négatif pour les ex-dirigeants historiques.
        FONCTIONS_HAUTES_GC6 = ["president", "premier ministre", "chef"]
        fonction_id_norm_gc6 = _norm(state.get("fonction_trouvee", "") or "")
        corpus_mots_gc6 = len(state.get("resultats_recherche", "").split())
        fonction_gc6_identifiee = (state.get("fonction_trouvee") or "").strip()

        # Se déclenche si :
        #  - corpus < 200 mots (sources Tavily quasiment vides)
        #  - ou OpenSanctions a confirmé
        #  - ou fonction identifiée dans corpus suffisant mais sources officielles inaccessibles
        gc6_sources_inaccessibles = bool(fonction_gc6_identifiee) and corpus_mots_gc6 > 300

        # GC6 ne se déclenche PAS si le LLM a explicitement identifié
        # le candidat comme non-politicien (sportif, association civile, etc.)
        # → évite les faux positifs par collision de nom avec un homonyme PEP historique
        _non_pep_explicite = any(kw in _raison_llm_initial for kw in [
            "joueur", "footballeur", "athlète", "sportif",
            "aucune fonction correspondant",
            "n'apparait pas avec une fonction",
            "n'est pas identifi",
            "aucune fonction publique",
            "association de soutien", "organisation non gouvernementale",
            "société civile", "ong ",
            "pas une personnalité politique",
            "aucune source", "aucune information",
        ])
        if _non_pep_explicite:
            print(f"  [GC6 BLOQUÉ] LLM a rejeté explicitement — pas de GC6 pour éviter faux positif homonyme")

        if (not est_pep
                and not _non_pep_explicite
                and state["code_iso"] != "XX"
                and (corpus_mots_gc6 < 200 or state.get("opensanctions_confirmed", False)
                     or gc6_sources_inaccessibles)):
            mode_gc6 = ("sources_inaccessibles"
                        if gc6_sources_inaccessibles and corpus_mots_gc6 >= 200
                        else "corpus_vide")
            print(f"  [Garde-code 6] {mode_gc6} ({corpus_mots_gc6} mots) + "
                  f"pays {state['code_iso']} → LLM mémoire générale...")
            try:
                if mode_gc6 == "sources_inaccessibles":
                    question_gc6 = (
                        f"FONCTION IDENTIFIÉE PAR LE CORPUS : {fonction_gc6_identifiee}\n\n"
                        f"En utilisant ta connaissance générale des dirigeants de {state['pays_nom']} :\n\n"
                        f"1. {state['prenom']} {state['nom']} occupe-t-il ou a-t-il occupé la "
                        f"fonction de {fonction_gc6_identifiee} (ou une fonction similaire) "
                        f"en {state['pays_nom']} ?\n"
                        f"2. Est-il encore en poste en {datetime.now().year} ?\n\n"
                        f"RÈGLE : Si tu n'es pas certain à > 80% → was_pep = false.\n\n"
                    )
                else:
                    question_gc6 = (
                        f"En utilisant ta connaissance générale des dirigeants de {state['pays_nom']} :\n\n"
                        f"1. {state['prenom']} {state['nom']} a-t-il été Président, Premier Ministre "
                        f"ou toute autre haute fonction publique de {state['pays_nom']} ?\n"
                        f"2. S'il l'a été, est-il toujours en poste en {datetime.now().year} ?\n\n"
                        f"RÈGLE : Si tu n'es pas certain à > 80% → was_pep = false.\n\n"
                    )

                prompt_gc6 = (
                    f"Tu es un expert AML/PEP avec connaissance encyclopédique des dirigeants africains.\n"
                    f"PERSONNE : {state['prenom']} {state['nom']}\n"
                    f"PAYS IDENTIFIÉ : {state['pays_nom']} ({state['code_iso']})\n"
                    f"FONCTION PROBABLE : {state.get('fonction_trouvee')}\n\n"
                    f"NOTE : Les sources officielles sont inaccessibles pour cette personne.\n"
                    + question_gc6 +
                    f"Réponds UNIQUEMENT en JSON :\n"
                    f"{{\"was_pep\": true ou false, "
                    f"\"still_in_office\": true ou false, "
                    f"\"fonction_exacte\": \"titre officiel en français\", "
                    f"\"confidence\": \"high ou medium ou low\"}}"
                )
                resp_gc6 = _llm_invoke(prompt_gc6)
                content_gc6 = resp_gc6.content.strip()
                if "```json" in content_gc6:
                    content_gc6 = content_gc6.split("```json")[1].split("```")[0]
                elif "```" in content_gc6:
                    content_gc6 = content_gc6.split("```")[1].split("```")[0]
                gc6_data = json.loads(content_gc6[content_gc6.find("{"):content_gc6.rfind("}")+1])

                gc6_confirmed = gc6_data.get("was_pep", gc6_data.get("was_head_of_state"))
                if (gc6_confirmed is True
                        and gc6_data.get("confidence") in ("high", "medium")):
                    est_pep       = True
                    statut_mandat = "actif" if gc6_data.get("still_in_office") else "ex_pep"
                    fonction_gc6  = (gc6_data.get("fonction_exacte")
                                     or fonction_gc6_identifiee
                                     or "ancienne fonction publique")
                    fonction_validee = fonction_gc6
                    print(f"  [Garde-code 6] Confirmé {'actif' if gc6_data.get('still_in_office') else 'ex-PEP'} "
                          f"(confiance: {gc6_data.get('confidence')})")

                    # ── Recherche URL Wikipedia pour auditabilité compliance ──
                    wiki_url_gc6 = ""
                    try:
                        nom_gc6 = f"{state['prenom']} {state['nom']}"
                        print(f"  [Garde-code 6] Recherche URL Wikipedia (auditabilité)...")
                        res_wiki_gc6 = _tavily_invoke(
                            tavily_search,
                            f'site:fr.wikipedia.org OR site:wikipedia.org "{nom_gc6}"',
                            f"GC6 Wikipedia {nom_gc6}"
                        )
                        if isinstance(res_wiki_gc6, list):
                            for item in res_wiki_gc6:
                                url_w = item.get("url", "")
                                if "wikipedia.org/wiki/" in url_w:
                                    wiki_url_gc6 = url_w
                                    break
                    except Exception:
                        pass

                    if wiki_url_gc6:
                        source_url_finale = wiki_url_gc6
                        source_type_gc6   = "wiki_gc6"
                        print(f"  [Garde-code 6] URL Wikipedia : {wiki_url_gc6}")
                        raisonnement = (
                            f"{state['prenom']} {state['nom']} a exercé la fonction de "
                            f"{fonction_gc6} en {state['pays_nom']} "
                            f"[LLM mémoire confirmée — source Wikipedia]"
                        )
                    else:
                        source_type_gc6 = "a_verifier_manuellement"
                        print(f"  [Garde-code 6] Aucune URL Wikipedia — marqué à vérifier manuellement")
                        raisonnement = (
                            f"{state['prenom']} {state['nom']} a exercé la fonction de "
                            f"{fonction_gc6} en {state['pays_nom']} "
                            f"[À VÉRIFIER MANUELLEMENT — aucune source accessible au moment de la vérification]"
                        )
                else:
                    print(f"  [Garde-code 6] Non confirmé "
                          f"(was_pep={gc6_confirmed}, "
                          f"confidence={gc6_data.get('confidence')})")
            except Exception as e:
                print(f"  [Garde-code 6] Erreur : {e}")

        # ── FALLBACK WIKIPEDIA GÉNÉRAL ────────────────────────────────────────────
        # Si est_pep=True mais source_url toujours "non disponible" (ex: validé par
        # OpenSanctions sans URL officielle accessible), chercher une URL Wikipedia
        # pour fournir une source auditable au compliance officer.
        source_type_final = source_type_gc6 or data.get("source_type") or "inconnu"
        if est_pep and source_url_finale == "non disponible":
            try:
                prenom_w = state['prenom']
                nom_w    = state['nom']
                nom_wiki = f"{prenom_w} {nom_w}"
                print(f"  [Fallback Wikipedia] Recherche URL auditable pour {nom_wiki}...")
                wiki_url_found = ""
                # Essai 1 — sans guillemets (tolérant aux accents manquants)
                for query_w in [
                    f"site:fr.wikipedia.org {prenom_w} {nom_w}",
                    f"site:wikipedia.org {prenom_w} {nom_w}",
                    f"{nom_wiki} wikipedia",
                ]:
                    if wiki_url_found:
                        break
                    res_wiki = _tavily_invoke(
                        tavily_search,
                        query_w,
                        f"Fallback Wikipedia {nom_wiki}"
                    )
                    if isinstance(res_wiki, list):
                        for item in res_wiki:
                            url_w = item.get("url", "")
                            if "wikipedia.org/wiki/" in url_w:
                                wiki_url_found = url_w
                                break
                if wiki_url_found:
                    source_url_finale = wiki_url_found
                    source_type_final = "wiki_fallback"
                    print(f"  [Fallback Wikipedia] URL trouvée : {wiki_url_found}")
                elif state.get("opensanctions_confirmed"):
                    # OpenSanctions a confirmé → extraire l'entity ID du corpus pour URL directe
                    os_entity_url = ""
                    try:
                        m_id = re.search(r'"source":\s*"(Q[^"]+|[a-z]{2}-[^"]+|osv-[^"]+)"',
                                         state.get("corpus_brut", ""))
                        if m_id:
                            os_entity_url = f"https://www.opensanctions.org/entities/{m_id.group(1)}/"
                        else:
                            # Fallback : URL de recherche OpenSanctions
                            q = f"{prenom_w}+{nom_w}".replace(" ", "+")
                            os_entity_url = f"https://www.opensanctions.org/search/?q={q}"
                    except Exception:
                        q = f"{prenom_w}+{nom_w}".replace(" ", "+")
                        os_entity_url = f"https://www.opensanctions.org/search/?q={q}"
                    source_url_finale = os_entity_url
                    source_type_final = "opensanctions_url"
                    print(f"  [Fallback OpenSanctions] URL auditable : {os_entity_url}")
                else:
                    source_type_final = "a_verifier_manuellement"
                    if urls_med:
                        print(f"  [Fallback Media] Piste découverte (non auditable) : {urls_med[0][:70]}")
                    print(f"  [Fallback] Aucune source officielle auditée — vérification manuelle requise")
            except Exception as e:
                print(f"  [Fallback Wikipedia] Erreur : {e}")

        if _gc0b_flag:
            raisonnement = (raisonnement or "") + " " + _gc0b_flag

        return {
            **state,
            "est_pep": est_pep,
            "fonction": fonction_validee,
            "fonctions_historiques": fonctions_historiques,
            "date_nomination": date_brute,
            "date_fin_mandat": date_fin_mandat,
            "source_url": source_url_finale,
            "source_type": source_type_final,
            "statut_mandat": statut_mandat,
            "raisonnement": raisonnement,
            "date_naissance": date_naissance,
            "lieu_naissance": lieu_naissance,
            "nb_enfants": nb_enfants,
            "statut_matrimonial": statut_matrimonial,
        }
    except Exception as e:
        _err_str  = str(e)
        _is_quota = any(k in _err_str for k in ("RESOURCE_EXHAUSTED", "RateLimitError", "rate_limit", "quota"))
        print(f"  {'[QUOTA LLM] ' if _is_quota else ''}Erreur qualify : {_err_str[:200]}")
        _rai_err = (
            "VERIFICATION IMPOSSIBLE - quota LLM epuise. "
            "A RE-VERIFIER MANUELLEMENT avant toute decision de conformite. "
            f"Detail : {_err_str[:300]}"
            if _is_quota else f"Erreur pipeline : {_err_str[:300]}"
        )
        return {**state, "est_pep": False,
                "statut_mandat": "erreur_llm" if _is_quota else "",
                "fonction": "", "fonctions_historiques": [],
                "date_nomination": "", "source_url": "non disponible", "source_type": "inconnu",
                "raisonnement": _rai_err,
                "date_naissance": "", "lieu_naissance": "", "nb_enfants": None,
                "statut_matrimonial": ""}

# ── NOEUD 5 : Stockage ───────────────────────────────────────────────────────────

def node_store(state: PEPState) -> PEPState:
    """Étape 5 — Stocker la PEP dans compliance_db.pep avec lien pays."""
    if state.get("dry_run"):
        print(f"\n[Étape 5] Dry-run — stockage ignoré (validation manuelle requise)")
        return {**state, "stockage_status": "dry_run"}
    print(f"\n[Étape 5] Stockage dans compliance_db...")
    try:
        _fonctions_hist = state.get("fonctions_historiques") or []
        _fonctions_str  = " · ".join(_fonctions_hist) if _fonctions_hist else None
        _nb_enf = state.get("nb_enfants")
        _nb_enf = int(_nb_enf) if _nb_enf is not None else None

        # ── Anti-doublon : chercher un enregistrement existant avec parties du nom communes ──
        _nom_complet_new = f"{state['prenom']} {state['nom']}"
        _parts_new = [p.lower() for p in _nom_complet_new.split() if len(p) > 2]
        from db_utils import query_all
        _candidats = query_all(
            "SELECT nom_complete, source_url, date_modification FROM pep WHERE code_iso = %s AND nom_complete != %s",
            (state["code_iso"], _nom_complet_new)
        )
        for _row in (_candidats or []):
            _nc = _row["nom_complete"] or ""
            _parts_exist = [p.lower() for p in _nc.split() if len(p) > 2]
            _commun = sum(1 for p in _parts_new if any(p in pe or pe in p for pe in _parts_exist))
            if _commun >= 2:
                print(f"  [Anti-doublon] '{_nom_complet_new}' ≈ '{_nc}' ({_commun} parties communes)")
                _score_exist = _source_score(_row.get("source_url"))
                _score_new   = _source_score(state["source_url"])
                _dt_mod = _row.get("date_modification")
                _age_jours = (datetime.now().replace(tzinfo=None) - _dt_mod.replace(tzinfo=None)).days if _dt_mod else 999
                if _score_new < _score_exist and _age_jours < 30:
                    print(f"  → Source existante meilleure (score {_score_exist} > {_score_new}) et récente ({_age_jours}j) — pas d'écrasement")
                    return {**state, "storage_status": f"Déjà à jour — source existante meilleure ('{_nc}', {_age_jours}j)"}
                # Décider quelle source_url conserver
                _src_final = state["source_url"] if _score_new >= _score_exist else (_row.get("source_url") or state["source_url"])
                execute("""
                    UPDATE pep SET
                        nom_complete             = %s,
                        prenom                   = %s,
                        nom                      = %s,
                        fonction_actuelle        = %s,
                        date_nomination          = COALESCE(%s, date_nomination),
                        date_naissance           = COALESCE(%s, date_naissance),
                        lieu_naissance           = COALESCE(%s, lieu_naissance),
                        statut_matrimonial       = COALESCE(NULLIF(%s, ''), statut_matrimonial),
                        source_url               = %s,
                        statut_mandat            = %s,
                        date_scraping            = NOW(),
                        date_modification        = NOW()
                    WHERE code_iso = %s AND nom_complete = %s
                """, (
                    _nom_complet_new,
                    state["prenom"], state["nom"],
                    state["fonction"],
                    convertir_date(state["date_nomination"]),
                    convertir_date(state.get("date_naissance") or "") or None,
                    state.get("lieu_naissance") or None,
                    state.get("statut_matrimonial") or None,
                    _src_final,
                    state.get("statut_mandat", "actif"),
                    state["code_iso"], _nc,
                ))
                print(f"  Mis à jour (fusion) : {_nom_complet_new} | source score {_score_new} | {_src_final}")
                return {**state, "storage_status": f"Mis à jour (fusion doublon '{_nc}')"}

        # ── Vérifier si l'enregistrement exact existe déjà (même nom_complete) ──
        _exist_exact = query_one(
            "SELECT source_url, date_modification FROM pep WHERE nom_complete = %s AND code_iso = %s",
            (_nom_complet_new, state["code_iso"])
        )
        _score_new_e = _source_score(state["source_url"])
        if _exist_exact:
            _score_exist_e = _source_score(_exist_exact.get("source_url"))
            _dt_mod_e = _exist_exact.get("date_modification")
            _age_e = (datetime.now().replace(tzinfo=None) - _dt_mod_e.replace(tzinfo=None)).days if _dt_mod_e else 999
            if _score_new_e < _score_exist_e and _age_e < 30:
                print(f"  Source existante meilleure (score {_score_exist_e} > {_score_new_e}) et récente ({_age_e}j) — pas de mise à jour")
                return {**state, "storage_status": f"Déjà à jour — source existante meilleure ({_age_e}j)"}
            _src_upsert = state["source_url"] if _score_new_e >= _score_exist_e else (_exist_exact.get("source_url") or state["source_url"])
        else:
            _src_upsert = state["source_url"]

        execute("""
            INSERT INTO pep (
                nom, prenom, nom_complete, nationalite,
                code_iso, pays_id, pays_nom,
                fonction_actuelle, date_nomination, date_sortie_fonction_public,
                date_naissance, lieu_naissance, statut_matrimonial, enfants, fonctions_interieures,
                source_url, date_scraping, statut_mandat
            )
            SELECT %s, %s, %s, %s,
                   p.code_iso2, p.id, p.nom_fr,
                   %s, %s, %s,
                   %s, %s, %s, %s, %s,
                   %s, NOW(), %s
            FROM pays p WHERE p.code_iso2 = %s
            ON CONFLICT (nom_complete, code_iso) DO UPDATE SET
                fonction_actuelle            = EXCLUDED.fonction_actuelle,
                date_nomination              = COALESCE(EXCLUDED.date_nomination, pep.date_nomination),
                date_sortie_fonction_public  = COALESCE(EXCLUDED.date_sortie_fonction_public, pep.date_sortie_fonction_public),
                date_naissance               = COALESCE(EXCLUDED.date_naissance, pep.date_naissance),
                lieu_naissance               = COALESCE(EXCLUDED.lieu_naissance, pep.lieu_naissance),
                statut_matrimonial           = COALESCE(EXCLUDED.statut_matrimonial, pep.statut_matrimonial),
                enfants                      = COALESCE(EXCLUDED.enfants, pep.enfants),
                fonctions_interieures        = COALESCE(EXCLUDED.fonctions_interieures, pep.fonctions_interieures),
                source_url                   = EXCLUDED.source_url,
                statut_mandat                = EXCLUDED.statut_mandat,
                date_scraping                = EXCLUDED.date_scraping,
                date_modification            = NOW()
        """, (
            state["nom"], state["prenom"],
            _nom_complet_new,
            state["code_iso"],
            state["fonction"],
            convertir_date(state["date_nomination"]),
            convertir_date(state.get("date_fin_mandat", "")),
            convertir_date(state.get("date_naissance") or "") or None,
            state.get("lieu_naissance") or None,
            state.get("statut_matrimonial") or None,
            _nb_enf,
            _fonctions_str,
            _src_upsert,
            state.get("statut_mandat", "actif"),
            state["code_iso"],
        ))
        status = f"Stocké : {state['prenom']} {state['nom']} | {state['pays_nom']} | {state['fonction']}"
        print(f"  {status}")
    except Exception as e:
        status = f"Erreur : {str(e)}"
        print(f"  {status}")
    return {**state, "stockage_status": status}

def node_skip(state: PEPState) -> PEPState:
    print(f"\n[Étape 5] Non-PEP — pas de stockage.")
    return {**state, "stockage_status": "Non-PEP — aucun stockage"}

def router(state: PEPState) -> str:
    return "store" if state.get("est_pep") else "skip"

# ── Graph ────────────────────────────────────────────────────────────────────────

graph = StateGraph(PEPState)
graph.add_node("identify",     node_identify)
graph.add_node("get_criteria", node_get_criteria)
graph.add_node("search",       node_search)
graph.add_node("qualify",      node_qualify)
graph.add_node("store",        node_store)
graph.add_node("skip",         node_skip)

graph.set_entry_point("identify")
graph.add_edge("identify",     "get_criteria")
graph.add_edge("get_criteria", "search")
graph.add_edge("search",       "qualify")
graph.add_conditional_edges("qualify", router, {"store": "store", "skip": "skip"})
graph.add_edge("store", END)
graph.add_edge("skip",  END)

pipeline_pep = graph.compile()
print("Pipeline PEP — 5 étapes : identify → get_criteria → search → qualify → store")

# ── Interface ────────────────────────────────────────────────────────────────────

import time as _time

# Délai minimum entre deux personnes en mode batch (secondes)
# Protège les quotas : Tavily (~24 appels/personne), Serper (2500/mois), OpenSanctions (2000/mois)
_DELAI_INTER_PERSONNES = 30  # secondes

def verifier_pep_batch(candidats: list[tuple[str, str]]) -> list[PersonPEPReport]:
    """
    Vérifie une liste de candidats avec un délai entre chaque personne
    pour respecter les quotas API (Tavily, Serper, OpenSanctions).

    Déduplication à deux niveaux :
      1. Doublon dans le batch courant → résultat réutilisé sans appel API.
      2. Déjà vérifié dans les 24h (verification_audit) → résultat caché retourné.

    Args:
        candidats : liste de tuples (prenom, nom)

    Returns:
        liste de PersonPEPReport dans le même ordre
    """
    from db_utils import query_one as _qone_dd
    rapports = []
    total = len(candidats)
    _cache_batch: dict[str, PersonPEPReport] = {}

    for i, (prenom, nom) in enumerate(candidats, 1):
        print(f"\n{'▶'*55}")
        print(f"  CANDIDAT {i}/{total} : {prenom} {nom}")
        print(f"{'▶'*55}")

        _cle = f"{prenom.strip().lower()}|{nom.strip().lower()}"

        # Doublon intra-batch
        if _cle in _cache_batch:
            print(f"  [Dédup] {prenom} {nom} déjà traité dans ce batch — résultat réutilisé")
            rapports.append(_cache_batch[_cle])
            continue

        # Vérification récente en base (24h, hors erreurs LLM)
        _nom_complet = f"{prenom} {nom}"
        try:
            _recent = _qone_dd("""
                SELECT code_iso, est_pep, motif FROM verification_audit
                WHERE nom_complet = %s
                  AND ts > NOW() - INTERVAL '24 hours'
                  AND (motif IS NULL OR motif::text NOT LIKE '%%erreur_llm%%')
                ORDER BY ts DESC LIMIT 1
            """, (_nom_complet,))
            if _recent:
                _iso = _recent["code_iso"] or "XX"
                _pays = _referentiel_json.get(_iso, {}).get("pays", "Pays non identifié")
                print(f"  [Dédup] {_nom_complet} déjà vérifié dans les 24h "
                      f"(pays={_iso}, pep={_recent['est_pep']}) — sauté")
                _rapp = PersonPEPReport(
                    nom=nom, prenom=prenom,
                    pays=_pays, code_iso=_iso,
                    est_pep=_recent["est_pep"],
                    statut_mandat="inconnu",
                    fonction=None, fonctions_historiques=None,
                    date_nomination=None, date_fin_mandat=None,
                    source_url="", source_type="audit_cache",
                    raisonnement=f"[CACHE 24H] {(_recent.get('motif') or '')[:200]}",
                    date_verification=datetime.now().strftime("%d/%m/%Y %H:%M"),
                )
                _cache_batch[_cle] = _rapp
                rapports.append(_rapp)
                continue
        except Exception as _e:
            print(f"  [Dédup] Vérification audit : {_e}")

        rapport = verifier_pep(prenom, nom)
        _cache_batch[_cle] = rapport
        rapports.append(rapport)
        if i < total:
            print(f"\n  ⏳ Pause {_DELAI_INTER_PERSONNES}s entre candidats (quota API)...")
            _time.sleep(_DELAI_INTER_PERSONNES)
    return rapports


_PROMPT_NOM_NORMALISATION = """Tu es un expert en personnalités politiques africaines et maghrébines.

On t'a donné : prénom="{prenom}" nom="{nom}"

TÂCHE :
1. Identifie si cette combinaison correspond à une personnalité publique connue (chef d'État, ministre, dirigeant).
2. Si oui → retourne son prénom et nom OFFICIELS complets (y compris les prénoms composés ou noms composés manquants).
3. Si non ou incertain → retourne simplement prénom/nom dans le bon ordre onomastique.

RÈGLE CRITIQUE ANTI-SUBSTITUTION (PRIORITÉ ABSOLUE) :
Ne compléter que si {prenom} est le PREMIER PRÉNOM DE LA PERSONNE, pas un prénom intermédiaire ou second prénom.
Si {prenom} correspond à un SECOND prénom d'une personnalité connue (pas son premier) → NE PAS compléter, retourner les valeurs d'entrée telles quelles.
Exemples INTERDITS :
- prénom="amadou" nom="ouattara" → INTERDIT de retourner "Alassane Amadou Ouattara" car "Amadou" est le 2e prénom d'Alassane Ouattara. Retourner {{"prenom": "Amadou", "nom": "Ouattara"}}.
- prénom="oumar" nom="touré" → INTERDIT de retourner "Amadou Toumani Touré" car "Oumar" n'est pas ATT. Retourner {{"prenom": "Oumar", "nom": "Touré"}}.
- prénom="toumani" nom="touré" → INTERDIT de retourner "Amadou Toumani Touré" car "Toumani" est le 2e prénom. Retourner {{"prenom": "Toumani", "nom": "Touré"}}.
Si incertain → retourner les prénoms tels que fournis sans modification.

EXEMPLES VALIDES :
- prénom="faye" nom="bassirou" → {{"prenom": "Bassirou Diomaye", "nom": "Faye"}} (ordre inversé uniquement)
- prénom="benkirane" nom="abdelilah" → {{"prenom": "Abdelilah", "nom": "Benkirane"}} (ordre inversé)
- prénom="sassou" nom="nguesso" → {{"prenom": "Denis", "nom": "Sassou Nguesso"}} (prénom manquant évident)
- prénom="jean" nom="dupont" → {{"prenom": "Jean", "nom": "Dupont"}} (inconnu — retourné tel quel)

Réponds UNIQUEMENT en JSON valide :
{{"prenom": "prénom(s) officiel(s)", "nom": "nom de famille officiel"}}"""

def _normaliser_nom(prenom: str, nom: str) -> tuple[str, str]:
    """Résout le nom canonique complet via LLM — corrige l'ordre ET complète les noms composés."""
    try:
        resp = _llm_invoke(_PROMPT_NOM_NORMALISATION.format(prenom=prenom, nom=nom))
        c = resp.content.strip()
        if "```" in c: c = c.split("```")[1].split("```")[0].lstrip("json").strip()
        s, e = c.find("{"), c.rfind("}") + 1
        d = json.loads(c[s:e])
        p_norm = d.get("prenom", prenom).strip()
        n_norm = d.get("nom", nom).strip()
        # HARD BLOCK anti-substitution : si le premier prénom retourné est différent de l'input
        # ET ce n'est pas simplement un échange nom/prénom → rejeter la normalisation
        def _n(s): return unicodedata.normalize("NFKD", s.split()[0].strip()).encode("ascii", "ignore").decode("ascii").lower()
        _in_p0, _in_n0, _out_p0 = _n(prenom), _n(nom), _n(p_norm)
        if _out_p0 != _in_p0 and _out_p0 != _in_n0:
            print(f"  [Normalisation BLOQUÉE] {prenom} {nom} → {p_norm} {n_norm} : substitution illicite (1er prénom changé)")
            return prenom, nom
        # Corriger doublon : si le nom est déjà dans le prénom, le retirer du prénom
        if n_norm and n_norm.lower() in p_norm.lower():
            p_norm = re.sub(re.escape(n_norm), '', p_norm, flags=re.IGNORECASE).strip()
            print(f"  [Normalisation] doublon détecté → prénom corrigé : {p_norm!r}")
        if p_norm.lower() != prenom.lower() or n_norm.lower() != nom.lower():
            print(f"  [Normalisation] {prenom} {nom} → {p_norm} {n_norm}")
        return p_norm, n_norm
    except Exception:
        return prenom, nom

def _persist_source_logs(nom_complet: str, code_iso: str) -> None:
    """Persiste les logs de santé des sources dans source_health_log.
    Envoie une notification dashboard pour chaque source officielle inaccessible."""
    logs = get_url_logs()
    if not logs:
        return
    try:
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                # 1. Insérer tous les logs dans source_health_log
                for log in logs:
                    cur.execute("""
                        INSERT INTO source_health_log
                            (nom_verifie, code_iso, url, domaine, tier,
                             statut, http_code, duree_ms, erreur, est_source_off)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        log["nom_verifie"], log["code_iso"],
                        log["url"], log["domaine"], log["tier"],
                        log["statut"], log["http_code"],
                        log["duree_ms"], log["erreur"], log["est_source_off"],
                    ))

                # 2. Notification dashboard pour sources officielles KO
                alertes = [
                    l for l in logs
                    if l["est_source_off"]
                    and l["statut"] in ("timeout", "connexion_ko", "http_erreur", "erreur")
                ]
                if alertes:
                    # Notifier tous les utilisateurs actifs
                    cur.execute("SELECT id FROM utilisateurs WHERE statut = 'actif'")
                    user_ids = [r["id"] for r in cur.fetchall()]
                    for alerte in alertes:
                        msg = (f"La source {alerte['domaine']} n'a pas répondu lors de la "
                               f"vérification de {nom_complet} ({code_iso}). "
                               f"Statut : {alerte['statut']}"
                               + (f" — {alerte['erreur'][:120]}" if alerte["erreur"] else ""))
                        for uid in user_ids:
                            cur.execute("""
                                INSERT INTO notifications
                                    (utilisateur_id, type, titre, message,
                                     entite_type, metadata)
                                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                            """, (
                                uid,
                                "source_indisponible",
                                f"Source inaccessible : {alerte['domaine']}",
                                msg,
                                "source_health",
                                json.dumps({
                                    "url":      alerte["url"],
                                    "domaine":  alerte["domaine"],
                                    "statut":   alerte["statut"],
                                    "code_iso": code_iso,
                                    "nom":      nom_complet,
                                }),
                            ))
            conn.commit()
        n_alertes = len(alertes) if alertes else 0
        print(f"  [SourceLog] {len(logs)} URLs loguées | {n_alertes} alerte(s) dashboard")
    except Exception as e:
        print(f"  [SourceLog] Erreur persistance : {e}")


def _log_verification_audit(prenom: str, nom: str, result: dict,
                            rapport: "PersonPEPReport", duree_ms: int) -> None:
    """Écrit une ligne dans verification_audit — traçabilité complète pour audit compliance."""
    try:
        code_iso = result.get("code_iso", "XX")
        _persist_source_logs(f"{prenom} {nom}", code_iso)
        cpt = get_compteur()
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
            f"{prenom} {nom}",
            code_iso,
            json.dumps({"confirmed": result.get("opensanctions_confirmed", False),
                        "source": result.get("source_url", "")}),
            _audit_llm.get("modele", ""),
            _audit_llm.get("prompt", "")[:6000],
            _audit_llm.get("reponse", "")[:3000],
            result.get("est_pep", False),
            (result.get("raisonnement") or "")[:500],
            duree_ms,
            cpt.get("par_personne", 0),
            1 if result.get("opensanctions_confirmed") else 0,
        ))
        print(f"  [Audit] Log vérification enregistré ({duree_ms}ms)")
    except Exception as e:
        print(f"  [Audit] Erreur log : {e}")


def verifier_pep(prenom: str, nom: str, stocker: bool = True) -> PersonPEPReport:
    import time as _time
    _t0 = _time.time()
    # Réinitialiser accumulateurs pour cette vérification
    _audit_llm["modele"] = _actifs[0] if _actifs else ""
    _audit_llm["prompt"] = ""
    _audit_llm["reponse"] = ""
    reset_compteur_personne()
    reset_url_logs()
    prenom, nom = _normaliser_nom(prenom, nom)
    print(f"\n{'='*55}")
    print(f"VÉRIFICATION PEP : {prenom} {nom}")
    print(f"{'='*55}")

    state: PEPState = {
        "nom": nom, "prenom": prenom,
        "code_iso": "", "pays_nom": "", "fonction_trouvee": "",
        "criteres": "", "resultats_recherche": "", "corpus_brut": "",
        "urls_officielles_trouvees": [], "urls_media_trouvees": [],
        "opensanctions_confirmed": False,
        "_votes_pays": 0,
        "est_pep": False, "statut_mandat": "actif", "fonction": "", "fonctions_historiques": [],
        "date_nomination": "", "date_fin_mandat": "",
        "date_naissance": "", "lieu_naissance": "", "nb_enfants": None,
        "statut_matrimonial": "",
        "source_url": "", "source_type": "", "raisonnement": "",
        "stockage_status": "",
        "dry_run": not stocker,
    }

    try:
        result = pipeline_pep.invoke(state)
    except Exception as _exc_pipeline:
        _duree_ms = int((_time.time() - _t0) * 1000)
        _msg_exc = str(_exc_pipeline).lower()
        _est_quota = any(k in _msg_exc for k in ("rate_limit", "quota", "429", "exhausted", "tokens per day"))
        print(f"  [Pipeline] Exception : {_exc_pipeline}")
        if _est_quota:
            print(f"  [Retry Queue] Quota LLM épuisé — mise en file d'attente pour {prenom} {nom}")
            try:
                from db_utils import execute as _exec_rq
                _exec_rq("""
                    INSERT INTO verification_retry_queue (prenom, nom, statut, detail_erreur)
                    VALUES (%s, %s, 'en_attente', %s)
                    ON CONFLICT DO NOTHING
                """, (prenom, nom, str(_exc_pipeline)[:500]))
            except Exception as _e_rq:
                print(f"  [Retry Queue] Erreur INSERT : {_e_rq}")
        return PersonPEPReport(
            nom=nom, prenom=prenom,
            pays="Pays non identifié", code_iso="XX",
            est_pep=False,
            statut_mandat="inconnu",
            fonction=None, fonctions_historiques=None,
            date_nomination=None, date_fin_mandat=None,
            source_url="", source_type="erreur_pipeline",
            raisonnement=f"[ERREUR PIPELINE] {'quota_llm_épuisé' if _est_quota else 'exception'}: {str(_exc_pipeline)[:300]}",
            date_verification=datetime.now().strftime("%d/%m/%Y %H:%M"),
        )
    _duree_ms = int((_time.time() - _t0) * 1000)

    # Pays incertain pour les Non-PEP identifiés avec 1 seule source (votes ≤ 2)
    _pays_final    = result["pays_nom"]
    _code_iso_final = result["code_iso"]
    if not result["est_pep"] and result.get("_votes_pays", 4) <= 2:
        print(f"  → Non-PEP + pays incertain ({result.get('_votes_pays',0)} vote(s)) → pays réinitialisé à XX")
        _pays_final    = "Pays non identifié"
        _code_iso_final = "XX"

    rapport = PersonPEPReport(
        nom=nom, prenom=prenom,
        pays=_pays_final, code_iso=_code_iso_final,
        est_pep=result["est_pep"],
        statut_mandat=result.get("statut_mandat", "actif"),
        fonction=result["fonction"] or None,
        fonctions_historiques=result.get("fonctions_historiques") or None,
        date_nomination=result["date_nomination"] or None,
        date_fin_mandat=result.get("date_fin_mandat") or None,
        date_naissance=result.get("date_naissance") or None,
        lieu_naissance=result.get("lieu_naissance") or None,
        nb_enfants=result.get("nb_enfants"),
        statut_matrimonial=result.get("statut_matrimonial") or None,
        source_url=result["source_url"],
        source_type=result["source_type"],
        raisonnement=result["raisonnement"],
        date_verification=datetime.now().strftime("%d/%m/%Y %H:%M"),
        urls_media_trouvees=result.get("urls_media_trouvees") or [],
    )

    print(f"\n{'='*55}")
    print(f"RÉSULTAT")
    print(f"{'='*55}")
    print(f"PEP        : {'OUI ✅' if rapport.est_pep else 'NON ❌'}")
    print(f"Pays       : {rapport.pays} ({rapport.code_iso})")
    if rapport.est_pep:
        print(f"Statut     : {rapport.statut_mandat}")
        print(f"Fonction   : {rapport.fonction}")
        print(f"Source     : {rapport.source_url}")
    print(f"Raisonnement: {rapport.raisonnement}")
    cpt = get_compteur()
    print(f"Tavily       : {cpt['par_personne']} appels cette vérif | {cpt['total']} au total")
    print(f"{'='*55}\n")

    # Log audit complet → PostgreSQL verification_audit
    _log_verification_audit(prenom, nom, result, rapport, _duree_ms)

    return rapport

def stocker_rapport(rapport: PersonPEPReport) -> str:
    """Stocke manuellement un rapport PEP en base (utilisé après validation batch dashboard)."""
    try:
        from db_utils import query_one, query_all, execute
        _fonctions_hist = rapport.fonctions_historiques or []
        _fonctions_str  = " · ".join(_fonctions_hist) if _fonctions_hist else None
        _nb_enf = int(rapport.nb_enfants) if rapport.nb_enfants is not None else None
        _nom_complet = f"{rapport.prenom} {rapport.nom}"

        # Anti-doublon
        _parts_new = [p.lower() for p in _nom_complet.split() if len(p) > 2]
        _candidats = query_all(
            "SELECT nom_complete, source_url, date_modification FROM pep WHERE code_iso = %s AND nom_complete != %s",
            (rapport.code_iso, _nom_complet)
        )
        for _row in (_candidats or []):
            _nc = _row["nom_complete"] or ""
            _parts_exist = [p.lower() for p in _nc.split() if len(p) > 2]
            _commun = sum(1 for p in _parts_new if any(p in pe or pe in p for pe in _parts_exist))
            if _commun >= 2:
                _score_exist = _source_score(_row.get("source_url"))
                _score_new   = _source_score(rapport.source_url)
                _dt_mod = _row.get("date_modification")
                _age = (datetime.now().replace(tzinfo=None) - _dt_mod.replace(tzinfo=None)).days if _dt_mod else 999
                _src = rapport.source_url if _score_new >= _score_exist else (_row.get("source_url") or rapport.source_url)
                execute("""
                    UPDATE pep SET nom_complete=%s, prenom=%s, nom=%s, fonction_actuelle=%s,
                        date_nomination=COALESCE(%s,date_nomination), date_naissance=COALESCE(%s,date_naissance),
                        lieu_naissance=COALESCE(%s,lieu_naissance),
                        statut_matrimonial=COALESCE(NULLIF(%s,''),statut_matrimonial),
                        source_url=%s, statut_mandat=%s,
                        fonctions_interieures=%s, date_scraping=NOW(), date_modification=NOW()
                    WHERE code_iso=%s AND nom_complete=%s
                """, (_nom_complet, rapport.prenom, rapport.nom, rapport.fonction,
                      convertir_date(rapport.date_nomination or ""),
                      convertir_date(rapport.date_naissance or "") or None,
                      rapport.lieu_naissance,
                      rapport.statut_matrimonial or None,
                      _src,
                      rapport.statut_mandat or "actif", _fonctions_str,
                      rapport.code_iso, _nc))
                return f"Mis à jour (fusion '{_nc}')"

        execute("""
            INSERT INTO pep (
                nom, prenom, nom_complete, nationalite, code_iso, pays_id, pays_nom,
                fonction_actuelle, date_nomination, date_sortie_fonction_public,
                date_naissance, lieu_naissance, statut_matrimonial, enfants, fonctions_interieures,
                source_url, date_scraping, statut_mandat
            )
            SELECT %s,%s,%s,%s, p.code_iso2, p.id, p.nom_fr,
                   %s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s
            FROM pays p WHERE p.code_iso2 = %s
            ON CONFLICT (nom_complete, code_iso) DO UPDATE SET
                fonction_actuelle=EXCLUDED.fonction_actuelle,
                date_nomination=COALESCE(EXCLUDED.date_nomination,pep.date_nomination),
                date_sortie_fonction_public=COALESCE(EXCLUDED.date_sortie_fonction_public,pep.date_sortie_fonction_public),
                date_naissance=COALESCE(EXCLUDED.date_naissance,pep.date_naissance),
                lieu_naissance=COALESCE(EXCLUDED.lieu_naissance,pep.lieu_naissance),
                statut_matrimonial=COALESCE(EXCLUDED.statut_matrimonial,pep.statut_matrimonial),
                enfants=COALESCE(EXCLUDED.enfants,pep.enfants),
                fonctions_interieures=COALESCE(EXCLUDED.fonctions_interieures,pep.fonctions_interieures),
                source_url=EXCLUDED.source_url, statut_mandat=EXCLUDED.statut_mandat,
                date_scraping=EXCLUDED.date_scraping, date_modification=NOW()
        """, (rapport.nom, rapport.prenom, _nom_complet, rapport.code_iso,
              rapport.fonction,
              convertir_date(rapport.date_nomination or ""),
              convertir_date(rapport.date_fin_mandat or ""),
              convertir_date(rapport.date_naissance or "") or None,
              rapport.lieu_naissance,
              rapport.statut_matrimonial or None,
              _nb_enf, _fonctions_str,
              rapport.source_url, rapport.statut_mandat or "actif",
              rapport.code_iso))
        return f"Inséré : {_nom_complet}"
    except Exception as e:
        return f"Erreur : {e}"


def relancer_verifications_impossibles(limite: int = 10) -> list[PersonPEPReport]:
    """
    Relance les vérifications en file d'attente (quota LLM épuisé lors de la collecte).
    À appeler manuellement ou via cron une fois les quotas récupérés.

    Args:
        limite : nombre max de vérifications à relancer en une fois

    Returns:
        liste de PersonPEPReport pour les cas relancés
    """
    from db_utils import query_all as _qall_rq, execute as _exec_rq
    try:
        _en_attente = _qall_rq("""
            SELECT id, prenom, nom, tentatives, max_tentatives
            FROM verification_retry_queue
            WHERE statut = 'en_attente'
              AND (tentatives IS NULL OR tentatives < max_tentatives)
            ORDER BY ts_echec ASC
            LIMIT %s
        """, (limite,))
    except Exception as _e:
        print(f"[Retry Queue] Lecture impossible : {_e}")
        return []

    if not _en_attente:
        print("[Retry Queue] Aucune vérification en attente.")
        return []

    print(f"[Retry Queue] {len(_en_attente)} vérification(s) à relancer...")
    rapports = []
    for row in _en_attente:
        _id, _prenom, _nom = row["id"], row["prenom"], row["nom"]
        try:
            _exec_rq("""
                UPDATE verification_retry_queue
                SET statut='en_cours', tentatives=COALESCE(tentatives,0)+1, ts_retry=NOW()
                WHERE id=%s
            """, (_id,))
        except Exception:
            pass
        try:
            rapport = verifier_pep(_prenom, _nom)
            rapports.append(rapport)
            _exec_rq("UPDATE verification_retry_queue SET statut='termine', ts_retry=NOW() WHERE id=%s", (_id,))
        except Exception as _e_run:
            print(f"[Retry Queue] Échec pour {_prenom} {_nom} : {_e_run}")
            try:
                _exec_rq("""
                    UPDATE verification_retry_queue
                    SET statut='en_attente', detail_erreur=%s, ts_retry=NOW()
                    WHERE id=%s
                """, (str(_e_run)[:500], _id))
            except Exception:
                pass
    return rapports


if __name__ == "__main__":
    verifier_pep("Patrice", "Talon")
