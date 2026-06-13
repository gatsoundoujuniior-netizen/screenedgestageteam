"""
dashboard_pep.py — ScreenEdge Africa
Dashboard analytique PEP : KPIs, répartition par pays, listes GAFI.
Lancer : streamlit run dashboard_pep.py
"""

import sys, json, os
sys.stdout.reconfigure(encoding="utf-8")

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# ── Config page ──────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ScreenEdge — Dashboard PEP",
    page_icon="🛡️",
    layout="wide",
)

# ── Chargement des données ────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def charger_pep_db():
    """Charge les PEP depuis PostgreSQL."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from db_utils import query_all
        rows = query_all("""
            SELECT
                p.prenom, p.nom, p.nom_complete, p.nationalite,
                p.code_iso, p.pays_nom,
                p.fonction_actuelle, p.date_nomination,
                p.date_sortie_fonction_public,
                p.statut_mandat,
                p.source_url, p.date_scraping
            FROM pep p
            ORDER BY p.date_scraping DESC
        """)
        if rows:
            return pd.DataFrame(rows)
        return pd.DataFrame()
    except Exception as e:
        st.warning(f"Base de données non disponible : {e}")
        return pd.DataFrame()


@st.cache_data
def charger_referentiel():
    """Charge referentiel_pep.json."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "referentiel_pep.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {e["code_iso"]: e for e in data}
    except Exception:
        return {}


def demo_data():
    """Données de démo si la DB est vide — pour visualisation."""
    return pd.DataFrame([
        {"prenom":"Aziz",    "nom":"Akhannouch",     "code_iso":"MA","pays_nom":"Maroc",          "fonction_actuelle":"Premier Ministre",             "statut_mandat":"actif",  "date_sortie_fonction_public":None, "source_url":"https://www.maroc.ma", "date_scraping": datetime(2026,6,1)},
        {"prenom":"Aïmene", "nom":"Benabderrahmane","code_iso":"DZ","pays_nom":"Algérie",        "fonction_actuelle":"Premier Ministre",             "statut_mandat":"actif",  "date_sortie_fonction_public":None, "source_url":"https://www.premier-ministre.gov.dz", "date_scraping": datetime(2026,6,1)},
        {"prenom":"Alassane","nom":"Ouattara",       "code_iso":"CI","pays_nom":"Côte d'Ivoire", "fonction_actuelle":"Président de la République",   "statut_mandat":"actif",  "date_sortie_fonction_public":None, "source_url":"https://www.presidence.ci", "date_scraping": datetime(2026,6,1)},
        {"prenom":"Bassirou","nom":"Faye",           "code_iso":"SN","pays_nom":"Sénégal",       "fonction_actuelle":"Président de la République",   "statut_mandat":"actif",  "date_sortie_fonction_public":None, "source_url":"https://www.presidence.sn", "date_scraping": datetime(2026,6,2)},
        {"prenom":"Faure",  "nom":"Gnassingbé",      "code_iso":"TG","pays_nom":"Togo",          "fonction_actuelle":"Président de la République",   "statut_mandat":"actif",  "date_sortie_fonction_public":None, "source_url":"https://www.republique-togo.com", "date_scraping": datetime(2026,6,2)},
        {"prenom":"Alpha",  "nom":"Condé",           "code_iso":"GN","pays_nom":"Guinée",        "fonction_actuelle":"Ancien Président",             "statut_mandat":"ex_pep", "date_sortie_fonction_public":"2021-09-05", "source_url":"https://rfi.fr", "date_scraping": datetime(2026,6,3)},
        {"prenom":"Ibrahim","nom":"Traoré",          "code_iso":"BF","pays_nom":"Burkina Faso",  "fonction_actuelle":"Président de la Transition",   "statut_mandat":"actif",  "date_sortie_fonction_public":None, "source_url":"https://www.gouvernement.gov.bf", "date_scraping": datetime(2026,6,3)},
        {"prenom":"Assimi", "nom":"Goïta",           "code_iso":"ML","pays_nom":"Mali",          "fonction_actuelle":"Président de la Transition",   "statut_mandat":"actif",  "date_sortie_fonction_public":None, "source_url":"https://www.koulouba.ml", "date_scraping": datetime(2026,6,4)},
    ])


# ── Chargement ───────────────────────────────────────────────────────────────────
referentiel = charger_referentiel()
df_raw      = charger_pep_db()

# Fallback démo si DB vide
is_demo = df_raw.empty
if is_demo:
    df_raw = demo_data()
    st.info("Base de données vide — affichage en mode démo avec données d'exemple.")

# Enrichir avec statut GAFI depuis le référentiel
def get_gafi(code_iso):
    entry = referentiel.get(str(code_iso).upper(), {})
    return entry.get("statut_gafi", "clean")

def get_vigilance(code_iso):
    entry = referentiel.get(str(code_iso).upper(), {})
    return entry.get("vigilance", "standard")

df = df_raw.copy()
df["statut_gafi"] = df["code_iso"].apply(get_gafi)
df["vigilance"]   = df["code_iso"].apply(get_vigilance)

# Couleurs GAFI
COULEURS_GAFI = {
    "liste_noire": "#e74c3c",
    "liste_grise":  "#f39c12",
    "clean":        "#27ae60",
}
LABELS_GAFI = {
    "liste_noire": "Liste Noire",
    "liste_grise":  "Liste Grise",
    "clean":        "Clean",
}

# ── Header ───────────────────────────────────────────────────────────────────────
st.markdown("## 🛡️ ScreenEdge Africa — Dashboard PEP")
st.markdown("---")

# ── KPIs ligne 1 ─────────────────────────────────────────────────────────────────
col1, col2, col3, col4, col5 = st.columns(5)

total_pep        = len(df)
nb_pays          = df["code_iso"].nunique()
nb_liste_noire   = len(df[df["statut_gafi"] == "liste_noire"])
nb_liste_grise   = len(df[df["statut_gafi"] == "liste_grise"])
nb_vigilance_max = len(df[df["vigilance"].isin(["renforcee", "maximale"])])

with col1:
    st.metric("Total PEP détectés", total_pep)
with col2:
    st.metric("Pays couverts", nb_pays)
with col3:
    st.metric("PEP — Liste Noire", nb_liste_noire, delta=None)
with col4:
    st.metric("PEP — Liste Grise", nb_liste_grise, delta=None)
with col5:
    st.metric("Vigilance renforcée", nb_vigilance_max)

st.markdown("---")

# ── Ligne 2 : Graphiques principaux ──────────────────────────────────────────────
col_a, col_b = st.columns(2)

with col_a:
    st.subheader("PEP par pays")
    pep_par_pays = (
        df.groupby(["pays_nom", "statut_gafi"])
        .size()
        .reset_index(name="count")
    )
    pep_par_pays["couleur"] = pep_par_pays["statut_gafi"].map(COULEURS_GAFI)
    pep_par_pays["label_gafi"] = pep_par_pays["statut_gafi"].map(LABELS_GAFI)

    fig_pays = px.bar(
        pep_par_pays,
        x="pays_nom", y="count",
        color="label_gafi",
        color_discrete_map={v: COULEURS_GAFI[k] for k, v in LABELS_GAFI.items()},
        labels={"pays_nom": "Pays", "count": "Nombre de PEP", "label_gafi": "Statut GAFI"},
        text="count",
    )
    fig_pays.update_layout(
        xaxis_tickangle=-35,
        legend_title="Statut GAFI",
        margin=dict(t=20, b=0),
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig_pays.update_traces(textposition="outside")
    st.plotly_chart(fig_pays, use_container_width=True)

with col_b:
    st.subheader("Répartition par statut GAFI")
    gafi_count = df["statut_gafi"].value_counts().reset_index()
    gafi_count.columns = ["statut_gafi", "count"]
    gafi_count["label"] = gafi_count["statut_gafi"].map(LABELS_GAFI)
    gafi_count["couleur"] = gafi_count["statut_gafi"].map(COULEURS_GAFI)

    fig_gafi = px.pie(
        gafi_count,
        names="label", values="count",
        color="label",
        color_discrete_map={v: COULEURS_GAFI[k] for k, v in LABELS_GAFI.items()},
        hole=0.45,
    )
    fig_gafi.update_layout(margin=dict(t=20, b=0))
    fig_gafi.update_traces(textinfo="percent+label+value")
    st.plotly_chart(fig_gafi, use_container_width=True)

# ── Ligne 3 : Carte GAFI + fonctions ─────────────────────────────────────────────
col_c, col_d = st.columns(2)

with col_c:
    st.subheader("Carte du périmètre GAFI")
    if referentiel:
        ref_df = pd.DataFrame([
            {
                "pays":        e["pays"],
                "code_iso":    e["code_iso"],
                "statut_gafi": e["statut_gafi"],
                "label_gafi":  LABELS_GAFI.get(e["statut_gafi"], e["statut_gafi"]),
                "nb_fonctions": len(e.get("fonctions_pep", [])),
            }
            for e in referentiel.values()
        ])
        fig_carte = px.choropleth(
            ref_df,
            locations="code_iso",
            color="label_gafi",
            color_discrete_map={v: COULEURS_GAFI[k] for k, v in LABELS_GAFI.items()},
            hover_name="pays",
            hover_data={"nb_fonctions": True, "code_iso": False},
            labels={"label_gafi": "Statut GAFI", "nb_fonctions": "Nb fonctions PEP"},
            scope="africa",
        )
        fig_carte.update_layout(margin=dict(t=20, b=0, l=0, r=0))
        st.plotly_chart(fig_carte, use_container_width=True)
    else:
        st.info("Référentiel JSON non disponible.")

with col_d:
    st.subheader("Top fonctions PEP détectées")
    if "fonction_actuelle" in df.columns:
        fonctions = (
            df["fonction_actuelle"]
            .dropna()
            .str.strip()
            .value_counts()
            .head(10)
            .reset_index()
        )
        fonctions.columns = ["Fonction", "Nb PEP"]
        fig_fonc = px.bar(
            fonctions,
            x="Nb PEP", y="Fonction",
            orientation="h",
            color="Nb PEP",
            color_continuous_scale=["#27ae60", "#f39c12", "#e74c3c"],
            text="Nb PEP",
        )
        fig_fonc.update_layout(
            yaxis=dict(autorange="reversed"),
            coloraxis_showscale=False,
            margin=dict(t=20, b=0),
            plot_bgcolor="rgba(0,0,0,0)",
        )
        fig_fonc.update_traces(textposition="outside")
        st.plotly_chart(fig_fonc, use_container_width=True)

# ── Ligne 4 : Tableau des listes ─────────────────────────────────────────────────
st.markdown("---")

tabs = st.tabs(["🔴 Liste Noire", "🟡 Liste Grise", "🟢 Clean", "📋 Toutes les PEP"])

with tabs[0]:
    df_noire = df[df["statut_gafi"] == "liste_noire"][["nom", "prenom", "pays_nom", "fonction_actuelle", "source_url"]]
    if df_noire.empty:
        st.info("Aucune PEP en liste noire dans la base.")
    else:
        st.dataframe(df_noire.rename(columns={"nom":"Nom","prenom":"Prénom","pays_nom":"Pays","fonction_actuelle":"Fonction","source_url":"Source"}), use_container_width=True)

with tabs[1]:
    df_grise = df[df["statut_gafi"] == "liste_grise"][["nom", "prenom", "pays_nom", "fonction_actuelle", "source_url"]]
    if df_grise.empty:
        st.info("Aucune PEP en liste grise dans la base.")
    else:
        st.dataframe(df_grise.rename(columns={"nom":"Nom","prenom":"Prénom","pays_nom":"Pays","fonction_actuelle":"Fonction","source_url":"Source"}), use_container_width=True)

with tabs[2]:
    df_clean = df[df["statut_gafi"] == "clean"][["nom", "prenom", "pays_nom", "fonction_actuelle", "source_url"]]
    if df_clean.empty:
        st.info("Aucune PEP clean dans la base.")
    else:
        st.dataframe(df_clean.rename(columns={"nom":"Nom","prenom":"Prénom","pays_nom":"Pays","fonction_actuelle":"Fonction","source_url":"Source"}), use_container_width=True)

with tabs[3]:
    cols_affichage = ["prenom", "nom", "pays_nom", "code_iso", "fonction_actuelle", "statut_gafi", "source_url"]
    cols_disponibles = [c for c in cols_affichage if c in df.columns]
    df_all = df[cols_disponibles].copy()
    df_all["statut_gafi"] = df_all["statut_gafi"].map(LABELS_GAFI).fillna(df_all["statut_gafi"])
    st.dataframe(
        df_all.rename(columns={
            "prenom":"Prénom","nom":"Nom","pays_nom":"Pays","code_iso":"ISO",
            "fonction_actuelle":"Fonction","statut_gafi":"GAFI","source_url":"Source"
        }),
        use_container_width=True,
    )

# ── Section : PEP par pays — liste détaillée ─────────────────────────────────────
st.markdown("---")
st.subheader("🌍 PEP par pays — liste détaillée")

pays_disponibles = sorted(df["pays_nom"].dropna().unique().tolist())
col_filtre1, col_filtre2 = st.columns([2, 2])
with col_filtre1:
    pays_selectionne = st.selectbox("Filtrer par pays", ["Tous les pays"] + pays_disponibles)
with col_filtre2:
    statut_filtre = st.selectbox("Filtrer par statut", ["Tous", "Actif", "Ex-PEP"])

df_liste = df.copy()
if pays_selectionne != "Tous les pays":
    df_liste = df_liste[df_liste["pays_nom"] == pays_selectionne]
if "statut_mandat" in df_liste.columns:
    if statut_filtre == "Actif":
        df_liste = df_liste[df_liste["statut_mandat"] == "actif"]
    elif statut_filtre == "Ex-PEP":
        df_liste = df_liste[df_liste["statut_mandat"] == "ex_pep"]

st.caption(f"{len(df_liste)} PEP trouvé(s)")

if df_liste.empty:
    st.info("Aucune PEP pour ces critères.")
else:
    for _, row in df_liste.iterrows():
        statut_val = row.get("statut_mandat", "") if "statut_mandat" in df_liste.columns else ""
        badge_statut = "🟢 Actif" if statut_val == "actif" else ("🔴 Ex-PEP" if statut_val == "ex_pep" else "⚪ Inconnu")
        gafi_val = row.get("statut_gafi", "clean")
        badge_gafi = {"liste_noire": "🔴 Liste Noire", "liste_grise": "🟡 Liste Grise", "clean": "🟢 Clean"}.get(gafi_val, gafi_val)

        date_nom   = row.get("date_nomination", "") or ""
        date_fin   = row.get("date_sortie_fonction_public", "") or ""
        source     = row.get("source_url", "") or ""

        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 2, 2])
            with c1:
                st.markdown(f"**{row.get('prenom','')} {row.get('nom','')}**")
                st.caption(row.get("fonction_actuelle", ""))
            with c2:
                st.markdown(f"🌐 **{row.get('pays_nom', '')}** `{row.get('code_iso', '')}`")
                st.caption(f"GAFI : {badge_gafi}")
            with c3:
                st.markdown(badge_statut)
                if date_nom:
                    st.caption(f"Nomination : {date_nom}")
                if date_fin:
                    st.caption(f"Fin mandat : {date_fin}")
            if source and source != "non disponible":
                st.markdown(f"[🔗 Source]({source})", unsafe_allow_html=False)

# ── Section : Vérifier une personne (scraper) ────────────────────────────────────
st.markdown("---")
st.subheader("🔍 Vérifier une personne")
st.caption("Lance l'agent PEP complet sur un candidat. Durée estimée : 2 à 8 minutes.")

if "rapport_scraper" not in st.session_state:
    st.session_state["rapport_scraper"] = None
if "scraper_erreur" not in st.session_state:
    st.session_state["scraper_erreur"] = None

with st.form("form_verif_pep"):
    col_p, col_n = st.columns(2)
    with col_p:
        prenom_input = st.text_input("Prénom", placeholder="ex: Macky")
    with col_n:
        nom_input = st.text_input("Nom", placeholder="ex: Sall")
    lancer = st.form_submit_button("▶ Lancer la vérification", type="primary")

if lancer:
    if not prenom_input.strip() or not nom_input.strip():
        st.warning("Merci de renseigner le prénom et le nom.")
    else:
        st.session_state["rapport_scraper"] = None
        st.session_state["scraper_erreur"]  = None
        nom_complet_input = f"{prenom_input.strip()} {nom_input.strip()}"
        with st.status(f"Analyse de **{nom_complet_input}** en cours...", expanded=True) as status_box:
            st.write("Identification du pays et de la nationalité...")
            try:
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                from pep_agent import verifier_pep  # noqa: E402
                st.write("Recherche multi-sources (Tavily, OpenSanctions, Wikipedia)...")
                rapport = verifier_pep(prenom_input.strip(), nom_input.strip())
                st.session_state["rapport_scraper"] = rapport
                status_box.update(label=f"Analyse terminée — {nom_complet_input}", state="complete")
            except Exception as exc:
                st.session_state["scraper_erreur"] = str(exc)
                status_box.update(label=f"Erreur lors de l'analyse : {exc}", state="error")

if st.session_state.get("scraper_erreur"):
    st.error(f"Erreur : {st.session_state['scraper_erreur']}")

rapport_obj = st.session_state.get("rapport_scraper")
if rapport_obj is not None:
    est_pep   = getattr(rapport_obj, "est_pep", False)
    badge_pep = "🔴 **PEP CONFIRMÉ**" if est_pep else "🟢 **Non-PEP**"
    statut_m  = getattr(rapport_obj, "statut_mandat", "") or ""
    badge_st  = "🟢 Actif" if statut_m == "actif" else ("🔴 Ex-PEP" if statut_m == "ex_pep" else "")

    st.markdown(f"### Résultat : {badge_pep}")
    with st.container(border=True):
        r1, r2 = st.columns(2)
        with r1:
            st.markdown(f"**Nom complet :** {getattr(rapport_obj, 'prenom', '')} {getattr(rapport_obj, 'nom', '')}")
            st.markdown(f"**Pays :** {getattr(rapport_obj, 'pays_nom', '')} `{getattr(rapport_obj, 'code_iso', '')}`")
            st.markdown(f"**Fonction :** {getattr(rapport_obj, 'fonction_actuelle', '') or '—'}")
            if badge_st:
                st.markdown(f"**Statut mandat :** {badge_st}")
        with r2:
            date_n = getattr(rapport_obj, "date_nomination", None)
            date_f = getattr(rapport_obj, "date_fin_mandat", None)
            src    = getattr(rapport_obj, "source_url", None) or ""
            src_t  = getattr(rapport_obj, "source_type", None) or ""
            if date_n:
                st.markdown(f"**Date nomination :** {date_n}")
            if date_f:
                st.markdown(f"**Date fin mandat :** {date_f}")
            if src and src != "non disponible":
                st.markdown(f"**Source :** [{src}]({src})")
                if src_t:
                    st.caption(f"Type source : `{src_t}`")
            else:
                st.markdown("**Source :** non disponible")

    raisonnement = getattr(rapport_obj, "raisonnement", None)
    if raisonnement:
        with st.expander("📋 Raisonnement de l'agent"):
            st.text(raisonnement)

# ── Ligne 5 : Référentiel pays ───────────────────────────────────────────────────
st.markdown("---")
with st.expander("📚 Référentiel PEP par pays (fonctions définies dans l'Excel)"):
    if referentiel:
        for code, entry in sorted(referentiel.items()):
            gafi   = entry.get("statut_gafi", "clean")
            color  = {"liste_noire":"🔴","liste_grise":"🟡","clean":"🟢"}.get(gafi, "⚪")
            vigil  = entry.get("vigilance", "standard")
            foncs  = entry.get("fonctions_pep", [])
            st.markdown(
                f"**{color} {entry['pays']} ({code})** — GAFI: `{gafi}` | Vigilance: `{vigil}` | {len(foncs)} fonctions PEP"
            )
            if foncs:
                st.caption(" · ".join(foncs))
    else:
        st.info("referentiel_pep.json non disponible.")

# ── Footer ───────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(f"ScreenEdge Africa — Données actualisées le {datetime.now().strftime('%d/%m/%Y %H:%M')} | Périmètre GAFI R12 — 13 pays")
