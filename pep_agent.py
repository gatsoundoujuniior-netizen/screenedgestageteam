"""
pep_agent.py — ScreenEdge Africa
Pipeline PEP en 5 étapes via LangGraph StateGraph.

Objectif : Input = Nom seulement → agent trouve pays + qualifie PEP + stocke
Sources  : JO, sites gouvernementaux, comptes officiels réseaux sociaux
Périmètre: défini par referentiel_pep (Excel → compliance_db)
"""

import sys, json, re

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
                          extraire_passages_nom, consensus_sources)

tavily_search = TavilySearch(max_results=5, search_depth="advanced")

load_dotenv(override=True)

llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0.1)

PAYS_PERIMETRE = {"MA","DZ","TN","LY","SN","CI","ML","BF","NE","TG","BJ","GW","GN"}

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
    # Format YYYY seulement → on ne peut pas stocker
    if re.fullmatch(r'\d{4}', date_str.strip()):
        return None
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
    urls_officielles_trouvees: list   # URLs officielles extraites du corpus
    urls_media_trouvees: list         # URLs médias extraites du corpus
    # Qualification
    est_pep: bool
    fonction: str
    date_nomination: str
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
    fonction: str | None
    date_nomination: str | None
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

RÈGLE : Si les résultats ne mentionnent pas clairement le pays → code_iso = XX. Ne jamais deviner."""

def node_identify(state: PEPState) -> PEPState:
    """Étape 1 — Tavily cherche d'abord, LLM extrait le pays depuis les résultats."""
    nom_complet = f"{state['prenom']} {state['nom']}"
    print(f"\n[Étape 1] Recherche initiale + identification : {nom_complet}...")

    annee = datetime.now().year

    # Tavily cherche d'abord — LLM n'utilise pas sa mémoire
    resultats_bruts = []
    for q in [
        f'"{nom_complet}" ministre OR président OR directeur gouvernement officiel',
        f'"{nom_complet}" {annee} OR {annee-1} fonction publique',
    ]:
        try:
            r = tavily_search.invoke({"query": q})
            if r: resultats_bruts.append(str(r))
        except Exception:
            continue

    resultats = "\n\n".join(resultats_bruts) if resultats_bruts else "Aucun résultat."

    # LLM extrait le pays depuis ce que Tavily a trouvé
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
        code_iso = data.get("code_iso", "XX")
        pays_nom = data.get("pays_nom", "Inconnu")
        fonction = data.get("fonction_probable") or ""
        print(f"  → {pays_nom} ({code_iso}) | {fonction or 'fonction inconnue'}")
        return {**state, "code_iso": code_iso, "pays_nom": pays_nom,
                "fonction_trouvee": fonction, "resultats_recherche": resultats}
    except Exception as e:
        print(f"  Erreur identification : {e}")
        return {**state, "code_iso": "XX", "pays_nom": "Inconnu",
                "fonction_trouvee": "", "resultats_recherche": resultats}

# ── NOEUD 2 : Charger critères PEP du pays depuis referentiel_pep ────────────────

def node_get_criteria(state: PEPState) -> PEPState:
    """Étape 2 — Charger le périmètre PEP officiel du pays."""
    print(f"\n[Étape 2] Chargement critères PEP pour {state['code_iso']}...")
    if state["code_iso"] == "XX":
        return {**state, "criteres": "Pays non identifié — fallback GAFI R12."}
    try:
        row = query_one(
            "SELECT pays, def_pep, loi_ref, statut_gafi, vigilance, autorite "
            "FROM referentiel_pep WHERE UPPER(code_iso) = %s",
            (state["code_iso"].upper(),)
        )
        if row:
            criteres = f"LOI: {row['loi_ref'] or 'N/A'} | GAFI: {row['statut_gafi'].upper()} | VIGILANCE: {row['vigilance'].upper()}\n\n{row['def_pep'] or 'GAFI R12'}"
            print(f"  Critères chargés — GAFI: {row['statut_gafi']}")
        else:
            criteres = "Pays non trouvé dans referentiel_pep — fallback GAFI R12."
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

    contenu_brut = rechercher_pep(nom_complet, state["pays_nom"], code)

    # Extraire et stocker les URLs par tier AVANT le filtrage du texte
    toutes_urls      = [u.rstrip('.,)') for u in re.findall(r'https?://[^\s\'">,\]]+', contenu_brut)]
    urls_off         = list(set(u for u in toutes_urls if est_source_officielle(u)))
    urls_med         = list(set(u for u in toutes_urls if est_source_secondaire(u)))

    # Texte filtré pour le LLM
    contenu = extraire_passages_nom(contenu_brut, nom_complet)
    nb_mots = len(contenu.split()) if contenu else 0
    print(f"  Résultat : {nb_mots} mots | {len(urls_off)} URLs off | {len(urls_med)} URLs médias")

    return {**state,
            "resultats_recherche": contenu,
            "urls_officielles_trouvees": urls_off,
            "urls_media_trouvees": urls_med}

# ── NOEUD 4 : Qualification PEP ──────────────────────────────────────────────────

PROMPT_QUALIFICATION = """Tu es un expert en conformité AML/PPE francophone. Réponds UNIQUEMENT en JSON valide.

ANNÉE COURANTE : {annee}
PERSONNE À VÉRIFIER : {prenom} {nom} ({pays})

PÉRIMÈTRE PEP OFFICIEL DU PAYS :
{criteres}

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

RÈGLES :
1. Si le nom apparaît dans les données avec une fonction → est_pep selon périmètre
2. Fonction dans le périmètre + en {annee} → est_pep = true, statut_mandat = "actif"
3. Fonction terminée avant {annee} → est_pep = true, statut_mandat = "ex_pep"
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
    print(f"\n[Étape 4] Qualification selon critères {state['code_iso']}...")
    try:
        prompt = PROMPT_QUALIFICATION.format(
            prenom=state["prenom"], nom=state["nom"],
            pays=state["pays_nom"],
            criteres=state["criteres"],
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
            nom_parts = [p.lower() for p in f"{state['prenom']} {state['nom']}".split() if len(p) > 2]
            mots_fonction = [m.lower() for m in fonction.split() if len(m) > 3]

            # Chercher si nom + fonction apparaissent dans le même passage (± 200 chars)
            nom_present_pres_fonction = False
            for i in range(len(corpus) - 200):
                fenetre = corpus[i:i+200].lower()
                if any(p in fenetre for p in nom_parts) and any(m in fenetre for m in mots_fonction):
                    nom_present_pres_fonction = True
                    break

            if not nom_present_pres_fonction and len(corpus) > 100:
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
                # Consensus trouvé → utiliser la fonction validée
                fonction_validee = consensus["fonction"]
                print(f"  Consensus validé : '{fonction_validee}' ({consensus['score']}/{consensus['total']} sources)")
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
                if annee_date not in resultats:
                    # Année non trouvée dans les sources → date inventée → null
                    date_brute = ""
                    print(f"  Date rejetée (non trouvée dans sources) : {data.get('date_nomination')}")

        # Nettoyer aussi le raisonnement des dates inventées
        raisonnement = data.get("raisonnement") or ""
        if date_brute == "" and data.get("date_nomination"):
            # Supprimer toute mention de date dans le raisonnement
            raisonnement = re.sub(
                r'depuis le \d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4}|'
                r'en fonction depuis \d{4}|'
                r'nommé[e]? le \d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4}',
                '', raisonnement
            ).strip()

        return {
            **state,
            "est_pep": est_pep,
            "fonction": fonction_validee,
            "date_nomination": date_brute,
            "source_url": source_url_finale,
            "source_type": data.get("source_type") or "inconnu",
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
                fonction_actuelle, date_nomination, source_url, date_scraping
            )
            SELECT %s, %s, %s, %s,
                   p.code_iso2, p.id, p.nom_fr,
                   %s, %s, %s, NOW()
            FROM pays p WHERE p.code_iso2 = %s
            ON CONFLICT DO NOTHING
        """, (
            state["nom"], state["prenom"],
            f"{state['prenom']} {state['nom']}",
            state["code_iso"],
            state["fonction"],
            convertir_date(state["date_nomination"]),
            state["source_url"],
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

def verifier_pep(prenom: str, nom: str) -> PersonPEPReport:
    print(f"\n{'='*55}")
    print(f"VÉRIFICATION PEP : {prenom} {nom}")
    print(f"{'='*55}")

    state: PEPState = {
        "nom": nom, "prenom": prenom,
        "code_iso": "", "pays_nom": "", "fonction_trouvee": "",
        "criteres": "", "resultats_recherche": "",
        "urls_officielles_trouvees": [], "urls_media_trouvees": [],
        "est_pep": False, "fonction": "", "date_nomination": "",
        "source_url": "", "source_type": "", "raisonnement": "",
        "stockage_status": "",
    }

    result = pipeline_pep.invoke(state)

    rapport = PersonPEPReport(
        nom=nom, prenom=prenom,
        pays=result["pays_nom"], code_iso=result["code_iso"],
        est_pep=result["est_pep"],
        fonction=result["fonction"] or None,
        date_nomination=result["date_nomination"] or None,
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
        print(f"Fonction   : {rapport.fonction}")
        print(f"Source     : {rapport.source_url}")
    print(f"Raisonnement: {rapport.raisonnement}")
    print(f"{'='*55}\n")
    return rapport

if __name__ == "__main__":
    verifier_pep("Patrice", "Talon")
