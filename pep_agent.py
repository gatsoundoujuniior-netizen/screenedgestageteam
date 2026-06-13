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
from langchain_tavily import TavilySearch
from langgraph.graph import StateGraph, END
from pydantic import BaseModel
from db_utils import query_one, execute
from search_tools import (rechercher_pep, est_source_officielle, est_source_secondaire,
                          est_source_verification, DOMAINES_INTERDITS,
                          extraire_passages_nom, consensus_sources,
                          filtrer_resultats, annoter_sources,
                          _tavily_invoke, reset_compteur_personne, get_compteur)

tavily_search = TavilySearch(max_results=5, search_depth="advanced")

load_dotenv(override=True)

llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0.1)

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
    # Retenir la plus récente — exclure l'année courante (contenu récent sans rapport avec la fin de mandat)
    annee_courante = datetime.now().year
    for c in candidats:
        annee_c = int(c.split("/")[-1] if "/" in c else c)
        if annee_c < annee_courante:
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

def convertir_date(date_str: str) -> str | None:
    """Convertit DD/MM/AAAA ou AAAA vers YYYY-MM-DD pour PostgreSQL."""
    if not date_str or date_str in ("N/A", "null", "None", ""):
        return None
    # Format YYYY seulement → stocker comme 01/01/AAAA (ex-PEP historiques)
    if re.fullmatch(r'\d{4}', date_str.strip()):
        return f"{date_str.strip()}-01-01"
    # Format DD/MM/YYYY
    try:
        return datetime.strptime(date_str.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except Exception:
        pass
    # Format YYYY-MM-DD déjà correct
    try:
        datetime.strptime(date_str.strip(), "%Y-%m-%d")
        return date_str.strip()
    except Exception:
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
    # Qualification
    est_pep: bool
    statut_mandat: str
    fonction: str
    date_nomination: str
    date_fin_mandat: str
    source_url: str
    source_type: str
    raisonnement: str
    # Stockage
    stockage_status: str

# ── Output ──────────────────────────────────────────────────────────────────────

class PersonPEPReport(BaseModel):
    nom: str
    prenom: str
    pays: str
    code_iso: str
    est_pep: bool
    statut_mandat: str
    fonction: str | None
    date_nomination: str | None
    date_fin_mandat: str | None
    source_url: str
    source_type: str
    raisonnement: str
    date_verification: str

# ── NOEUD 1 : Recherche Tavily d'abord → LLM extrait le pays depuis les résultats ──

PROMPT_IDENTIFICATION = """Tu es un expert en conformité AML/PPE francophone.

PERSONNE : {prenom} {nom}

RÉSULTATS DE RECHERCHE SUR SOURCES OFFICIELLES :
{resultats_recherche}

En analysant UNIQUEMENT les résultats ci-dessus (pas ta mémoire), réponds en JSON :
{{
  "code_iso": "code ISO2 du pays trouvé dans les résultats (MA/DZ/TN/LY/SN/CI/ML/BF/NE/TG/BJ/GW/GN) ou XX si absent",
  "pays_nom": "nom du pays en français",
  "fonction_probable": "fonction publique trouvée dans les résultats ou null"
}}

RÈGLES :
- code_iso = pays où la personne a exercé une fonction publique (actuelle OU passée/historique)
- Si les résultats mentionnent "ancien président de [pays]", "ex-président de [pays]" → extraire ce pays
- Si les résultats ne mentionnent aucun pays de la liste → code_iso = XX"""

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
        response = llm.invoke(PROMPT_IDENTIFICATION.format(
            prenom=state["prenom"], nom=state["nom"],
            resultats_recherche=resultats[:2000]
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
        serper_txt, _ = _serper(nom_complet, "Afrique", "XX")
        if serper_txt:
            resp_sr = llm.invoke(PROMPT_IDENTIFICATION.format(
                prenom=state["prenom"], nom=state["nom"],
                resultats_recherche=serper_txt[:2000]
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
                resultats += f"\n\n[SERPER ID]\n{serper_txt[:1500]}"
                print(f"  → Serper : vote {iso_sr} (+2) | {fn_sr or 'fonction inconnue'}")
            else:
                print(f"  → Serper : pays non identifié")
    except Exception:
        pass

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
                txt_r = str(r_r)[:2000]
                resp_r = llm.invoke(PROMPT_IDENTIFICATION.format(
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
                txt_pl = str(r_pl)[:2000]
                resp_pl = llm.invoke(PROMPT_IDENTIFICATION.format(
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

    return {**state, "code_iso": code_iso, "pays_nom": pays_nom,
            "fonction_trouvee": fonction, "resultats_recherche": resultats}

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
    "TG": ["presidence.tg","gouv.tg","assemblee-nationale.tg","centif.tg","bceao.int"],
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

    # Enrichir avec les résultats d'identification si corpus insuffisant
    if nb_mots < 300 and code != "XX" and resultats_identification:
        mots_id = len(resultats_identification.split())
        if mots_id > 20:
            contenu = resultats_identification + "\n\n---\n\n" + contenu if contenu.strip() else resultats_identification
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
                    extra = texte_extra[:2000]  # fallback : tout le texte annoté
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
        pays_os_match = re.search(r'"pays":\s*\[\s*"([a-z]{2})"', contenu_brut)
        if pays_os_match:
            os_iso = pays_os_match.group(1).upper()
            if os_iso in PAYS_PERIMETRE:
                code_iso_final = os_iso
                if os_iso in _referentiel_json:
                    pays_nom_final = _referentiel_json[os_iso]["pays"]
                print(f"  [Tier 3] OpenSanctions → pays identifié : {pays_nom_final} ({code_iso_final})")

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

DONNÉES TROUVÉES SUR SOURCES OFFICIELLES :
{resultats}

INSTRUCTIONS :
Utilise TOUTES les informations disponibles pour déterminer si {prenom} {nom} est une PEP.
Les sources sont annotées par niveau de fiabilité :
- [OFFICIEL✅] → Source gouvernementale directe — poids maximum
- [MEDIA⚠️]   → Média fiable (AFP, RFI, Reuters) — poids moyen, confirme mais ne valide pas seul
- [WIKI🔍]    → Wikipedia — poids faible, confirme identité uniquement

RÈGLE DE DÉCISION :
- 1 source [OFFICIEL✅] → suffit pour valider est_pep = true
- 2+ sources [MEDIA⚠️] sans [OFFICIEL✅] → est_pep = true avec source_validee = false
- Wikipedia seul → est_pep = false (insuffisant)

RÈGLE ABSOLUE : La fonction retournée doit être celle de {prenom} {nom} EXCLUSIVEMENT.
Si plusieurs personnes dans les données, ignorer toutes sauf {prenom} {nom}.

RÈGLE CRITIQUE — STATUT ACTIF vs EX_PEP :
Pour déterminer statut_mandat, cherche dans TOUTES les données des indices de fin de mandat :
- Mots clés fin de mandat : "renversé", "destitué", "coup d'état", "démissionné", "a quitté",
  "ancien président", "ex-président", "n'est plus", "a été remplacé", "successeur",
  "fin de mandat", "départ", "mort", "décédé", "arrested", "detained", "in exile"
- Si l'une de ces expressions est présente ET associée à {prenom} {nom} → statut_mandat = "ex_pep"
- Si les données montrent que la fonction s'est terminée avant {annee} → statut_mandat = "ex_pep"
- Uniquement si toutes les sources confirment qu'il est ENCORE en poste en {annee} → statut_mandat = "actif"
- En cas de doute → statut_mandat = "actif" (principe de précaution compliance — vigilance maximale)

RÈGLES :
1. Si le nom apparaît dans les données avec une fonction → est_pep selon périmètre
2. Fonction dans le périmètre + confirmée encore active en {annee} → est_pep = true, statut_mandat = "actif"
3. Fonction terminée avant {annee} OU indices de fin de mandat → est_pep = true, statut_mandat = "ex_pep"
4. Nom absent ou aucune fonction → est_pep = false
5. Source officielle obligatoire pour valider → source_validee = true seulement si URL officielle

Réponds UNIQUEMENT avec ce JSON :
{{
  "est_pep": true ou false,
  "fonction": "titre exact trouvé en français ou null",
  "date_nomination": "JJ/MM/AAAA ou null",
  "source_officielle_url": "URL officielle ou non disponible",
  "source_media_url": "URL média de recoupement ou null",
  "source_type": "journal_officiel ou site_gouvernement ou agence_presse_etat ou inconnu",
  "source_validee": true ou false,
  "statut_mandat": "actif ou ex_pep",
  "raisonnement": "une phrase en français — INTERDICTION de citer des dates non présentes dans les données"
}}

RÈGLE ABSOLUE SUR LES DATES : Ne jamais inventer une date. Si la date n'apparaît pas explicitement dans les données fournies → ne pas la mentionner. Écrire uniquement ce qui est dans les données."""

def node_qualify(state: PEPState) -> PEPState:
    """Étape 4 — Qualifier PEP selon le périmètre du referentiel_pep."""
    def _norm(s):
        return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()

    print(f"\n[Étape 4] Qualification selon critères {state['code_iso']}...")

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
        prompt = PROMPT_QUALIFICATION.format(
            prenom=state["prenom"], nom=state["nom"],
            pays=state["pays_nom"],
            criteres=criteres_actifs,
            resultats=state["resultats_recherche"][:2500],
            annee=datetime.now().year
        )
        response = llm.invoke(prompt)
        content = response.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        start = content.find("{"); end = content.rfind("}") + 1
        data = json.loads(content[start:end])
        est_pep = bool(data.get("est_pep", False))
        print(f"  est_pep={est_pep} | {data.get('fonction') or 'non-PEP'}")
        est_pep        = bool(data.get("est_pep", False))
        fonction       = data.get("fonction") or ""
        source_off_url = data.get("source_officielle_url") or ""
        source_med_url = data.get("source_media_url") or ""
        source_validee = bool(data.get("source_validee", False))
        statut_mandat  = data.get("statut_mandat") or "actif"

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
                llm,
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
                    prompt_gc5 = (
                        f"ANNÉE COURANTE : {datetime.now().year}\n"
                        f"PERSONNE ANALYSÉE : {state['prenom']} {state['nom']}\n\n"
                        f"Passages du corpus associant '{state['nom']}' à des termes de fin de mandat :\n{signal_txt}\n\n"
                        f"QUESTION : Dans ces passages, {state['prenom']} {state['nom']} LUI-MÊME "
                        f"a-t-il quitté sa propre fonction AVANT {datetime.now().year} ?\n\n"
                        f"RÈGLES — lire attentivement :\n"
                        f"- 'Ancien Président (AAAA–AAAA)' ou 'Ancien Président ... {state['nom']}' avec une date de fin avant {datetime.now().year} → ex_pep = true (signal suffisant à lui seul)\n"
                        f"- 'former president ... from AAAA to AAAA' avec date de fin avant {datetime.now().year} → ex_pep = true\n"
                        f"- 'ancien président {state['nom']}' ou '{state['nom']}, ancien président' → ex_pep = true\n"
                        f"- 'former president {state['nom']}' ou '{state['nom']} left office' → ex_pep = true\n"
                        f"- coup d'état, destitution, renversement, démission, exil, arrestation CONCERNANT {state['nom']} → ex_pep = true\n"
                        f"- '{state['nom']} a succédé à [quelqu'un]' → {state['nom']} a PRIS le pouvoir → ex_pep = false\n"
                        f"- '[quelqu'un d'autre] ancien président... {state['nom']}' → le terme 'ancien' désigne l'AUTRE → ex_pep = false\n"
                        f"- IMPORTANT : si un passage dit explicitement 'Ancien Président (dates)' concernant {state['nom']}, c'est concluant même si d'autres passages l'appellent encore 'Président'\n"
                        f"- En cas de doute → ex_pep = false\n\n"
                        f"Réponds UNIQUEMENT en JSON : {{\"ex_pep\": true ou false, \"raison\": \"une phrase\"}}"
                    )
                    resp_gc5 = llm.invoke(prompt_gc5)
                    content_gc5 = resp_gc5.content.strip()
                    if "```json" in content_gc5:
                        content_gc5 = content_gc5.split("```json")[1].split("```")[0]
                    elif "```" in content_gc5:
                        content_gc5 = content_gc5.split("```")[1].split("```")[0]
                    gc5_data = json.loads(content_gc5[content_gc5.find("{"):content_gc5.rfind("}")+1])
                    if gc5_data.get("ex_pep") is True:
                        statut_mandat = "ex_pep"
                        raisonnement  = gc5_data.get("raison", raisonnement)
                        print(f"  [Garde-code 5] Confirmé ex-PEP : {gc5_data.get('raison', '')}")
                    else:
                        print(f"  [Garde-code 5] Signal non confirmé → statut conservé : {statut_mandat}")
                else:
                    # Faux négatif : LLM n'a pas trouvé de fonction → vérification approfondie
                    prompt_gc5 = (
                        f"ANNÉE COURANTE : {datetime.now().year}\n"
                        f"PAYS : {state['pays_nom']}\n"
                        f"PERSONNE : {state['prenom']} {state['nom']}\n\n"
                        f"Des passages suggèrent que cette personne a occupé une haute fonction publique "
                        f"et l'a quittée :\n{signal_txt}\n\n"
                        f"CRITÈRES PEP DU PAYS (extrait) :\n{state['criteres'][:600]}\n\n"
                        f"RÈGLES :\n"
                        f"- Si les passages associent '{state['nom']}' à 'président', 'premier ministre', "
                        f"'ancien président', 'ex-président', 'former president' ou équivalent → was_pep = true\n"
                        f"- Si was_pep = true → la personne reste PEP indéfiniment (duree_ex_pep='permanente')\n"
                        f"- Extraire le titre de fonction depuis les passages\n"
                        f"- En cas de doute → was_pep = false\n\n"
                        f"Réponds UNIQUEMENT en JSON :\n"
                        f"{{\"was_pep\": true ou false, "
                        f"\"statut_mandat\": \"actif si encore en poste en {datetime.now().year}, ex_pep si a quitté\", "
                        f"\"fonction\": \"titre officiel en français ou null\", "
                        f"\"raison\": \"une phrase précisant la fonction et le statut actuel\"}}"
                    )
                    resp_gc5 = llm.invoke(prompt_gc5)
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

        if (not est_pep
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
                resp_gc6 = llm.invoke(prompt_gc6)
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
                    print(f"  [Fallback Wikipedia] Aucune URL Wikipedia — à vérifier manuellement")
            except Exception as e:
                print(f"  [Fallback Wikipedia] Erreur : {e}")

        return {
            **state,
            "est_pep": est_pep,
            "fonction": fonction_validee,
            "date_nomination": date_brute,
            "date_fin_mandat": date_fin_mandat,
            "source_url": source_url_finale,
            "source_type": source_type_final,
            "statut_mandat": statut_mandat,
            "raisonnement": raisonnement,
        }
    except Exception as e:
        print(f"  Erreur : {e}")
        return {**state, "est_pep": False, "fonction": "", "date_nomination": "",
                "source_url": "non disponible", "source_type": "inconnu",
                "raisonnement": f"Erreur : {str(e)}"}

# ── NOEUD 5 : Stockage ───────────────────────────────────────────────────────────

def node_store(state: PEPState) -> PEPState:
    """Étape 5 — Stocker la PEP dans compliance_db.pep avec lien pays."""
    print(f"\n[Étape 5] Stockage dans compliance_db...")
    try:
        execute("""
            INSERT INTO pep (
                nom, prenom, nom_complete, nationalite,
                code_iso, pays_id, pays_nom,
                fonction_actuelle, date_nomination, date_sortie_fonction_public,
                source_url, date_scraping, statut_mandat
            )
            SELECT %s, %s, %s, %s,
                   p.code_iso2, p.id, p.nom_fr,
                   %s, %s, %s,
                   %s, NOW(), %s
            FROM pays p WHERE p.code_iso2 = %s
            ON CONFLICT (nom_complete, code_iso) DO UPDATE SET
                fonction_actuelle            = EXCLUDED.fonction_actuelle,
                date_nomination              = COALESCE(EXCLUDED.date_nomination, pep.date_nomination),
                date_sortie_fonction_public  = COALESCE(EXCLUDED.date_sortie_fonction_public, pep.date_sortie_fonction_public),
                source_url                   = EXCLUDED.source_url,
                statut_mandat                = EXCLUDED.statut_mandat,
                date_scraping                = EXCLUDED.date_scraping,
                date_modification            = NOW()
        """, (
            state["nom"], state["prenom"],
            f"{state['prenom']} {state['nom']}",
            state["code_iso"],
            state["fonction"],
            convertir_date(state["date_nomination"]),
            convertir_date(state.get("date_fin_mandat", "")),
            state["source_url"],
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

    Args:
        candidats : liste de tuples (prenom, nom)

    Returns:
        liste de PersonPEPReport dans le même ordre
    """
    rapports = []
    total = len(candidats)
    for i, (prenom, nom) in enumerate(candidats, 1):
        print(f"\n{'▶'*55}")
        print(f"  CANDIDAT {i}/{total} : {prenom} {nom}")
        print(f"{'▶'*55}")
        rapport = verifier_pep(prenom, nom)
        rapports.append(rapport)
        if i < total:
            print(f"\n  ⏳ Pause {_DELAI_INTER_PERSONNES}s entre candidats (quota API)...")
            _time.sleep(_DELAI_INTER_PERSONNES)
    return rapports


def verifier_pep(prenom: str, nom: str) -> PersonPEPReport:
    reset_compteur_personne()
    print(f"\n{'='*55}")
    print(f"VÉRIFICATION PEP : {prenom} {nom}")
    print(f"{'='*55}")

    state: PEPState = {
        "nom": nom, "prenom": prenom,
        "code_iso": "", "pays_nom": "", "fonction_trouvee": "",
        "criteres": "", "resultats_recherche": "", "corpus_brut": "",
        "urls_officielles_trouvees": [], "urls_media_trouvees": [],
        "opensanctions_confirmed": False,
        "est_pep": False, "statut_mandat": "actif", "fonction": "", "date_nomination": "",
        "date_fin_mandat": "",
        "source_url": "", "source_type": "", "raisonnement": "",
        "stockage_status": "",
    }

    result = pipeline_pep.invoke(state)

    rapport = PersonPEPReport(
        nom=nom, prenom=prenom,
        pays=result["pays_nom"], code_iso=result["code_iso"],
        est_pep=result["est_pep"],
        statut_mandat=result.get("statut_mandat", "actif"),
        fonction=result["fonction"] or None,
        date_nomination=result["date_nomination"] or None,
        date_fin_mandat=result.get("date_fin_mandat") or None,
        source_url=result["source_url"],
        source_type=result["source_type"],
        raisonnement=result["raisonnement"],
        date_verification=datetime.now().strftime("%d/%m/%Y %H:%M"),
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
    return rapport

if __name__ == "__main__":
    verifier_pep("Patrice", "Talon")
