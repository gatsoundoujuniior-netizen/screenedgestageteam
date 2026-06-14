"""
app.py — ScreenEdge Africa
Interface visuelle de l'agent PEP.
Lancer : streamlit run app.py
"""

import streamlit as st
import sys, os, json
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

st.set_page_config(
    page_title="ScreenEdge Africa — Agent PEP",
    page_icon="🛡️",
    layout="wide"
)

st.markdown("""
<style>
.pep-yes  { background:#ff4b4b; color:white; padding:14px 24px; border-radius:8px; font-size:1.5rem; font-weight:bold; text-align:center; }
.pep-no   { background:#21c45d; color:white; padding:14px 24px; border-radius:8px; font-size:1.5rem; font-weight:bold; text-align:center; }
.step-ok  { background:#1e3a2f; color:#a6e3a1; border-radius:8px; padding:10px 14px; margin:5px 0; font-family:monospace; font-size:.85rem; }
.step-run { background:#2a2a3e; color:#f9e2af; border-radius:8px; padding:10px 14px; margin:5px 0; font-family:monospace; font-size:.85rem; }
.step-err { background:#3a1e1e; color:#f38ba8; border-radius:8px; padding:10px 14px; margin:5px 0; font-family:monospace; font-size:.85rem; }
.badge    { background:#313244; color:#89dceb; padding:3px 10px; border-radius:20px; font-size:.75rem; margin-left:6px; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────────

st.markdown("## 🛡️ ScreenEdge Africa — Agent PEP")
st.caption("Identification autonome des Personnes Politiquement Exposées")
st.divider()

# ── Formulaire — Prénom + Nom seulement ──────────────────────────────────────────

with st.form("pep_form"):
    col1, col2 = st.columns(2)
    with col1:
        prenom = st.text_input("Prénom", placeholder="ex: Patrice")
    with col2:
        nom = st.text_input("Nom", placeholder="ex: Talon")

    submitted = st.form_submit_button("🔍 Identifier & Vérifier", use_container_width=True, type="primary")

# ── Pipeline ──────────────────────────────────────────────────────────────────────

if submitted and prenom and nom:
    st.divider()

    # ── Vérification base de données en premier ──────────────────────────────────
    from dotenv import load_dotenv as _ldenv; _ldenv(override=True)
    from db_utils import query_one as _qone
    nom_complet_recherche = f"{prenom} {nom}".strip()
    existant = _qone("""
        SELECT nom_complete, pays_nom, code_iso, fonction_actuelle,
               statut_mandat, source_url, date_nomination, date_creation
        FROM pep
        WHERE nom_complete ILIKE %s OR nom_complete ILIKE %s
        LIMIT 1
    """, (nom_complet_recherche, f"{nom} {prenom}"))

    if existant and not st.session_state.get(f"forcer_maj_{nom_complet_recherche}"):
        from datetime import date as _date
        date_verif = existant["date_creation"]
        jours_depuis = (datetime.now().date() - date_verif.date()).days if date_verif else 999

        if jours_depuis <= 30:
            fraicheur_label = f"🟢 Récent ({jours_depuis}j)"
        elif jours_depuis <= 90:
            fraicheur_label = f"🟡 Modéré ({jours_depuis}j)"
        else:
            fraicheur_label = f"🔴 Ancien ({jours_depuis}j) — mise à jour recommandée"

        st.success("✅ Personne déjà connue dans la base PEP")
        col_a, col_b = st.columns(2)
        with col_a:
            st.metric("Personne", existant["nom_complete"])
            st.metric("Pays", f"{existant['pays_nom']} ({existant['code_iso']})")
            st.metric("Statut", existant["statut_mandat"] or "—")
        with col_b:
            st.metric("Fonction", (existant["fonction_actuelle"] or "—")[:60])
            st.metric("Date nomination", str(existant["date_nomination"] or "—"))
            st.metric("Dernière vérification", fraicheur_label)
        if existant["source_url"]:
            st.markdown(f"**Source :** [{existant['source_url']}]({existant['source_url']})")

        st.warning("⚠️ Les informations peuvent avoir changé (nouvelle fonction, fin de mandat…)")
        if st.button("🔄 Relancer une vérification complète (mise à jour)", type="secondary"):
            st.session_state[f"forcer_maj_{nom_complet_recherche}"] = True
            st.rerun()
        st.stop()

    col_steps, col_result = st.columns([1, 1])

    with col_steps:
        st.markdown("### ⚙️ Pipeline")
        s0 = st.empty()
        s1 = st.empty()
        s2 = st.empty()
        s3 = st.empty()
        s4 = st.empty()

    with col_result:
        st.markdown("### 📋 Résultat")
        result_zone = st.empty()

    from dotenv import load_dotenv
    load_dotenv(override=True)

    from langchain_groq import ChatGroq
    from langchain_tavily import TavilySearch
    from db_utils import query_one, execute

    llm    = ChatGroq(model="llama-3.1-8b-instant", temperature=0.1,
                      api_key=os.getenv("groq_api_key"))
    tavily = TavilySearch(max_results=5, search_depth="advanced")

    # ── Sources autorisées : publiques non modifiables (État publie directement)
    # ── Sources interdites : tout ce qui peut être modifié par des tiers
    DOMAINES_INTERDITS = [
        # Encyclopédies collaboratives
        "wikipedia.org", "wikidata.org", "wikimedia.org",
        # Open data / agrégateurs
        "opensanctions.org", "data.europa.eu", "un.org/sc",
        # Médias / presse (interprétation tierce)
        "reuters.com", "bbc.com", "rfi.fr", "lemonde.fr", "afp.com",
        "jeunafrique.com", "africanews.com", "voaafrique.com",
        "allafrica.com", "apanews.net",
        # Réseaux sociaux publics (posts modifiables)
        "facebook.com", "twitter.com", "x.com", "linkedin.com",
        "instagram.com", "tiktok.com", "youtube.com",
    ]

    def filtrer_sources(texte: str) -> str:
        """Supprime les lignes contenant des domaines non officiels."""
        if not texte:
            return texte
        lignes = texte.split("\n")
        lignes_ok = [
            l for l in lignes
            if not any(d in l.lower() for d in DOMAINES_INTERDITS)
        ]
        return "\n".join(lignes_ok) or "Aucun résultat sur sources officielles."

    PAYS_PERIMETRE = {"MA","DZ","TN","LY","SN","CI","ML","BF","NE","TG","BJ","GW","GN"}

    # Sources officielles non modifiables par pays
    # Catégories : Présidence | Gouvernement | Parlement | Banque Centrale | CENTIF | JO
    SOURCES = {
        "MA": [
            "maroc.ma", "gouvernement.ma",                    # Présidence + Gouvernement
            "chambredesrepresentants.ma", "chambredesconseillers.ma",  # Parlement
            "bkam.ma", "utrf.ma",                             # Banque centrale + UTRF
            "bulletinofficiel.ma",                            # Journal Officiel
            "ammc.ma", "acaps.ma",                            # Régulateurs
        ],
        "DZ": [
            "el-mouradia.dz", "premier-ministre.gov.dz",      # Présidence + PM
            "apn.dz", "senat.dz",                             # Parlement
            "bank-of-algeria.dz", "ctrf.gov.dz",              # Banque + CTRF
            "joradp.dz",                                      # Journal Officiel
        ],
        "TN": [
            "carthage.tn", "gouvernement.tn",                 # Présidence + Gouvernement
            "arp.tn",                                         # Parlement
            "bct.gov.tn", "ctaf.gov.tn",                      # Banque + CTAF
            "iort.gov.tn",                                    # Journal Officiel
        ],
        "LY": [
            "gov.ly", "hor.ly",                               # GNU + HoR
            "cbl.gov.ly",                                     # Banque Centrale Libye
        ],
        "SN": [
            "presidence.sn", "gouvernement.sn",               # Présidence + Gouvernement
            "assemblee-nationale.sn",                         # Assemblée nationale
            "centif.sn",                                      # CENTIF
            "bceao.int",                                      # BCEAO (commun UEMOA)
            "jo.gouv.sn",                                     # Journal Officiel
        ],
        "CI": [
            "presidence.ci", "gouv.ci",                       # Présidence + Gouvernement
            "assemblee-nationale.ci", "senat.ci",             # Parlement
            "centif-ci.ci",                                   # CENTIF
            "bceao.int",                                      # BCEAO
        ],
        "ML": [
            "koulouba.ml", "primature.gov.ml",                # Présidence + PM
            "bceao.int",                                      # BCEAO
        ],
        "BF": [
            "gouvernement.gov.bf",                            # Gouvernement
            "centif.bf",                                      # CENTIF
            "bceao.int",                                      # BCEAO
            "fasonet.bf",                                     # Journal Officiel BF
        ],
        "NE": [
            "presidence.ne", "gouv.ne",                       # Présidence + Gouvernement
            "centif.ne",                                      # CENTIF
            "bceao.int",                                      # BCEAO
        ],
        "TG": [
            "presidence.tg", "gouv.tg",                       # Présidence + Gouvernement
            "assemblee-nationale.tg",                         # Parlement
            "centif.tg",                                      # CENTIF
            "bceao.int",                                      # BCEAO
        ],
        "BJ": [
            "presidence.bj", "gouv.bj",                       # Présidence + Gouvernement
            "assemblee-nationale.bj",                         # Parlement
            "centif.bj",                                      # CENTIF
            "bceao.int",                                      # BCEAO
            "journalofficiel.bj",                             # Journal Officiel
        ],
        "GW": [
            "gov.gw",                                         # Gouvernement
            "bceao.int",                                      # BCEAO
        ],
        "GN": [
            "presidence.gov.gn", "gouvernement.gov.gn",       # Présidence + Gouvernement
            "bcrg.org",                                       # Banque Centrale Guinée
        ],
    }

    # ── Étape 0 : Identification du pays ─────────────────────────────────────────
    s0.markdown('<div class="step-run">⏳ Étape 1 — Identification de la personne...</div>', unsafe_allow_html=True)

    PROMPT_ID = """Réponds UNIQUEMENT en JSON.
PERSONNE : {prenom} {nom}
Codes disponibles : MA DZ TN LY SN CI ML BF NE TG BJ GW GN
{{
  "code_iso": "code ISO2 ou XX si inconnu",
  "pays_nom": "nom pays en français",
  "fonction_probable": "fonction ou null"
}}"""

    try:
        r = llm.invoke(PROMPT_ID.format(prenom=prenom, nom=nom))
        c = r.content.strip()
        start = c.find("{")
        depth, end = 0, start
        for i, ch in enumerate(c[start:], start):
            if ch == "{": depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        id_data = json.loads(c[start:end])
        code_iso = id_data.get("code_iso", "XX")
        pays_nom = id_data.get("pays_nom", "Inconnu")
        s0.markdown(f'<div class="step-ok">✅ Étape 1 — {pays_nom} ({code_iso}) identifié</div>', unsafe_allow_html=True)
    except Exception as e:
        code_iso, pays_nom = "XX", "Inconnu"
        s0.markdown(f'<div class="step-err">⚠️ Étape 1 — Identification échouée</div>', unsafe_allow_html=True)

    # ── GARDE 1 : Hors périmètre géographique ────────────────────────────────────
    if code_iso not in PAYS_PERIMETRE:
        s1.markdown('<div class="step-err">🚫 Hors périmètre — pays non couvert (13 pays Maghreb + UEMOA + Guinée)</div>', unsafe_allow_html=True)
        with result_zone.container():
            st.markdown('<div class="pep-no">⛔ HORS PÉRIMÈTRE</div>', unsafe_allow_html=True)
            st.warning(f"**{prenom} {nom}** — pays non identifié ou hors couverture géographique. L'agent couvre uniquement le Maghreb (MA, DZ, TN, LY) et l'Afrique de l'Ouest (SN, CI, ML, BF, NE, TG, BJ, GW, GN).")
        st.stop()

    # ── Étape 1 : Critères PEP ───────────────────────────────────────────────────
    s1.markdown('<div class="step-run">⏳ Étape 2 — Chargement périmètre PEP...</div>', unsafe_allow_html=True)
    try:
        row = query_one(
            "SELECT pays, def_pep, loi_ref, statut_gafi, vigilance FROM referentiel_pep WHERE UPPER(code_iso)=%s",
            (code_iso,)
        )
        if row:
            criteres = f"LOI: {row['loi_ref'] or 'N/A'} | GAFI: {row['statut_gafi'].upper()}\n\n{row['def_pep'] or 'GAFI R12'}"
            s1.markdown(f'<div class="step-ok">✅ Étape 2 — Périmètre {row["pays"]} chargé <span class="badge">{row["statut_gafi"].upper()}</span></div>', unsafe_allow_html=True)
        else:
            criteres = "Fallback GAFI R12."
            s1.markdown('<div class="step-ok">✅ Étape 2 — Fallback GAFI R12</div>', unsafe_allow_html=True)
    except Exception as e:
        criteres = "Fallback GAFI R12."
        s1.markdown(f'<div class="step-err">⚠️ Étape 2 — DB timeout, GAFI R12</div>', unsafe_allow_html=True)

    # ── Étape 2 : Recherche sources officielles ──────────────────────────────────
    s2.markdown('<div class="step-run">⏳ Étape 3 — Recherche sources officielles...</div>', unsafe_allow_html=True)
    try:
        sites = SOURCES.get(code_iso, [])
        site_filter = " OR ".join([f"site:{s}" for s in sites])
        requetes = [
            f'"{prenom} {nom}" {site_filter}'.strip(),
            f'"{prenom} {nom}" nomination officielle {pays_nom} 2024 OR 2025 OR 2026',
        ]
        resultats = []
        for q in requetes:
            if q.strip():
                try:
                    res = tavily.invoke({"query": q})
                    if res: resultats.append(str(res))
                except Exception: pass
        brut = "\n\n---\n\n".join(resultats) if resultats else "Aucun résultat."
        resultats_recherche = filtrer_sources(brut)
        s2.markdown(f'<div class="step-ok">✅ Étape 3 — {len(resultats)} résultats (sources officielles filtrées)</div>', unsafe_allow_html=True)
    except Exception as e:
        resultats_recherche = ""
        s2.markdown(f'<div class="step-err">❌ Étape 3 — {str(e)[:50]}</div>', unsafe_allow_html=True)

    # ── Étape 3 : Qualification ──────────────────────────────────────────────────
    s3.markdown('<div class="step-run">⏳ Étape 4 — Qualification par le LLM...</div>', unsafe_allow_html=True)

    PROMPT_Q = """Tu es expert AML/PPE. Réponds UNIQUEMENT en JSON.
PERSONNE : {prenom} {nom} ({pays})
PÉRIMÈTRE PEP : {criteres}
INFORMATIONS : {resultats}
RÈGLES : fonction dans le périmètre → est_pep=true | doute → true | rien → false
{{
  "est_pep": true ou false,
  "fonction": "titre exact ou null",
  "date_nomination": "JJ/MM/AAAA ou null",
  "source_url": "URL officielle ou non disponible",
  "source_type": "site_gouvernement ou journal_officiel ou reseau_social_officiel ou inconnu",
  "raisonnement": "une phrase en français"
}}"""

    try:
        r2 = llm.invoke(PROMPT_Q.format(
            prenom=prenom, nom=nom, pays=pays_nom,
            criteres=criteres, resultats=resultats_recherche[:2000]
        ))
        c2 = r2.content.strip()
        if "```json" in c2: c2 = c2.split("```json")[1].split("```")[0].strip()
        elif "```" in c2:   c2 = c2.split("```")[1].split("```")[0].strip()
        # Extraire uniquement le premier objet JSON valide
        start = c2.find("{")
        depth, end = 0, start
        for i, ch in enumerate(c2[start:], start):
            if ch == "{": depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        q_data = json.loads(c2[start:end])
        est_pep      = bool(q_data.get("est_pep", False))
        fonction     = q_data.get("fonction") or ""
        date_nom     = q_data.get("date_nomination") or "N/A"
        source_url   = q_data.get("source_url") or "non disponible"
        source_type  = q_data.get("source_type") or "inconnu"
        raisonnement = q_data.get("raisonnement") or ""

        # ── GARDE 2 : Contradiction est_pep=True sans fonction ───────────────────
        if est_pep and not fonction.strip():
            est_pep = False
            raisonnement = "Aucune fonction publique officielle identifiée — non classé PEP."

        # ── GARDE 3 : Source non officielle détectée ─────────────────────────────
        if any(d in source_url.lower() for d in DOMAINES_INTERDITS):
            source_url = "non disponible"
            source_type = "inconnu"

        # Convertir date DD/MM/AAAA → YYYY-MM-DD pour PostgreSQL
        if date_nom and date_nom != "N/A":
            try:
                from datetime import datetime as dt
                date_nom_pg = dt.strptime(date_nom, "%d/%m/%Y").strftime("%Y-%m-%d")
            except Exception:
                date_nom_pg = None
        else:
            date_nom_pg = None

        s3.markdown(f'<div class="step-ok">✅ Étape 4 — est_pep={est_pep} | {fonction or "non-PEP"}</div>', unsafe_allow_html=True)
    except Exception as e:
        est_pep, fonction, date_nom = False, "", "N/A"
        source_url, source_type = "non disponible", "inconnu"
        raisonnement = f"Erreur : {str(e)}"
        s3.markdown(f'<div class="step-err">❌ Étape 4 — Erreur LLM</div>', unsafe_allow_html=True)

    # ── Étape 4 : Stockage ───────────────────────────────────────────────────────
    if est_pep:
        s4.markdown('<div class="step-run">⏳ Étape 5 — Stockage compliance_db...</div>', unsafe_allow_html=True)
        try:
            execute("""
                INSERT INTO pep (
                    nom, prenom, nom_complete, nationalite,
                    code_iso, pays_id, pays_nom,
                    fonction_actuelle, date_nomination, source_url, date_scraping
                )
                SELECT %s,%s,%s,%s, p.code_iso2,p.id,p.nom_fr, %s,%s,%s, NOW()
                FROM pays p WHERE p.code_iso2=%s
                ON CONFLICT DO NOTHING
            """, (nom, prenom, f"{prenom} {nom}", code_iso,
                  fonction, date_nom_pg,
                  source_url, code_iso))
            s4.markdown(f'<div class="step-ok">✅ Étape 5 — Stocké dans compliance_db.pep ({pays_nom})</div>', unsafe_allow_html=True)
        except Exception as e:
            s4.markdown(f'<div class="step-err">⚠️ Étape 5 — {str(e)[:70]}</div>', unsafe_allow_html=True)
    else:
        s4.markdown('<div class="step-ok">✅ Étape 5 — Non-PEP, aucun stockage</div>', unsafe_allow_html=True)

    # ── Résultat ─────────────────────────────────────────────────────────────────
    with result_zone.container():
        if est_pep:
            st.markdown('<div class="pep-yes">🚨 PEP CONFIRMÉ</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="pep-no">✅ NON PEP</div>', unsafe_allow_html=True)
        st.markdown("")
        col_a, col_b = st.columns(2)
        with col_a:
            st.metric("Personne", f"{prenom} {nom}")
            st.metric("Pays identifié", f"{pays_nom} ({code_iso})")
        with col_b:
            st.metric("Fonction", fonction or "—")
            st.metric("Nomination", date_nom)
        if est_pep and source_url != "non disponible":
            st.markdown(f"**Source :** [{source_url}]({source_url})")
            st.markdown(f'<span class="badge">{source_type}</span>', unsafe_allow_html=True)
        st.info(f"💬 {raisonnement}")
        st.caption(f"Vérifié le {datetime.now().strftime('%d/%m/%Y à %H:%M')}")

elif submitted:
    st.warning("Renseigne le prénom et le nom.")

st.divider()
st.caption("ScreenEdge Africa — Agent PEP v2.0 | Junior Stevy Gatsoundou | Superviseur : Hazim Sebbata")
