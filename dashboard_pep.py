"""
dashboard_pep.py — ScreenEdge Africa
Dashboard analytique PEP : KPIs, répartition par pays, listes GAFI.
Lancer : streamlit run dashboard_pep.py
"""

import sys, json, os, subprocess
sys.stdout.reconfigure(encoding="utf-8")

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# ── Gestion du processus collecteur ─────────────────────────────────────────────
_DIR = os.path.dirname(os.path.abspath(__file__))
_PID_FILE    = os.path.join(_DIR, "collector_pid.txt")
_VENV_PYTHON = os.path.join(_DIR, ".venv", "Scripts", "python.exe")
_COLLECTOR   = os.path.join(_DIR, "pep_collector.py")

_PAYS_LABELS = {
    "MA": "🇲🇦 Maroc",
    "DZ": "🇩🇿 Algérie",
    "TN": "🇹🇳 Tunisie",
    "LY": "🇱🇾 Libye",
    "SN": "🇸🇳 Sénégal",
    "CI": "🇨🇮 Côte d'Ivoire",
    "ML": "🇲🇱 Mali",
    "BF": "🇧🇫 Burkina Faso",
    "NE": "🇳🇪 Niger",
    "TG": "🇹🇬 Togo",
    "BJ": "🇧🇯 Bénin",
    "GW": "🇬🇼 Guinée-Bissau",
    "GN": "🇬🇳 Guinée",
}

def _collector_pid() -> int | None:
    try:
        with open(_PID_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return None

def _collector_running() -> bool:
    pid = _collector_pid()
    if not pid:
        return False
    try:
        import subprocess as sp
        r = sp.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                   capture_output=True, text=True)
        return str(pid) in r.stdout
    except Exception:
        return False

def _start_collector(track_b_only: bool = True, pays: str = ""):
    args = [_VENV_PYTHON, _COLLECTOR]
    if track_b_only:
        args.append("--track-b-only")
    if pays:
        args += ["--pays", pays]
    proc = subprocess.Popen(
        args,
        stdout=open(os.path.join(_DIR, "collector_log.txt"), "w", encoding="utf-8"),
        stderr=open(os.path.join(_DIR, "collector_err.txt"), "w", encoding="utf-8"),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    with open(_PID_FILE, "w") as f:
        f.write(str(proc.pid))

def _stop_collector():
    pid = _collector_pid()
    if pid:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                           capture_output=True)
        except Exception:
            pass
    try:
        os.remove(_PID_FILE)
    except Exception:
        pass
    # Marquer le statut comme arrêté
    _spath = os.path.join(_DIR, "collector_status.json")
    if os.path.exists(_spath):
        try:
            with open(_spath) as f:
                s = json.load(f)
            s["running"] = False
            with open(_spath, "w") as f:
                json.dump(s, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

# ── Config page ──────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ScreenEdge — Dashboard PEP",
    page_icon="🛡️",
    layout="wide",
)

# ── Chargement des données ────────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def charger_pep_db():
    """Charge les PEP depuis PostgreSQL — tous les champs."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from db_utils import query_all
        rows = query_all("""
            SELECT
                p.id, p.prenom, p.nom, p.nom_complete,
                p.nationalite, p.code_iso, p.pays_nom,
                p.fonction_actuelle, p.statut_mandat,
                p.date_nomination, p.date_sortie_fonction_public,
                p.date_naissance, p.lieu_naissance,
                p.statut_matrimonial, p.enfants,
                p.formations, p.fonctions_interieures,
                p.source_url, p.date_scraping,
                p.date_creation, p.date_modification,
                p.annee_verification
            FROM pep p
            ORDER BY p.date_scraping DESC NULLS LAST
        """)
        return pd.DataFrame(rows) if rows else pd.DataFrame()
    except Exception as e:
        st.error(f"Erreur connexion base de données : {e}")
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


# ── Chargement ───────────────────────────────────────────────────────────────────
referentiel = charger_referentiel()
df_raw      = charger_pep_db()

if df_raw.empty:
    st.info("⏳ Base de données vide — lancez l'agent pour peupler la base.")

# Enrichir avec statut GAFI depuis le référentiel
def get_gafi(code_iso):
    entry = referentiel.get(str(code_iso).upper(), {})
    return entry.get("statut_gafi", "clean")

def get_vigilance(code_iso):
    entry = referentiel.get(str(code_iso).upper(), {})
    return entry.get("vigilance", "standard")

df = df_raw.copy()
if not df.empty:
    df["statut_gafi"] = df["code_iso"].apply(get_gafi)
    df["vigilance"]   = df["code_iso"].apply(get_vigilance)
else:
    df["statut_gafi"] = pd.Series(dtype=str)
    df["vigilance"]   = pd.Series(dtype=str)

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
col1, col2, col3, col4, col5, col6, col7 = st.columns(7)

total_pep        = len(df)
nb_pays          = df["code_iso"].nunique() if not df.empty else 0
nb_liste_noire   = len(df[df["statut_gafi"] == "liste_noire"]) if not df.empty else 0
nb_liste_grise   = len(df[df["statut_gafi"] == "liste_grise"]) if not df.empty else 0
nb_vigilance_max = len(df[df["vigilance"].isin(["renforcee", "maximale"])]) if not df.empty else 0
nb_actifs        = len(df[df["statut_mandat"] == "actif"]) if not df.empty and "statut_mandat" in df.columns else 0
nb_ex_pep        = len(df[df["statut_mandat"] == "ex_pep"]) if not df.empty and "statut_mandat" in df.columns else 0

with col1:
    st.metric("Total PEP", total_pep)
with col2:
    st.metric("Pays couverts", nb_pays)
with col3:
    st.metric("🟢 Actifs", nb_actifs)
with col4:
    st.metric("🔴 Ex-PEP", nb_ex_pep)
with col5:
    st.metric("Liste Noire GAFI", nb_liste_noire)
with col6:
    st.metric("Liste Grise GAFI", nb_liste_grise)
with col7:
    st.metric("Vigilance renforcée", nb_vigilance_max)

st.markdown("---")

# ── Ligne 2 : Graphiques principaux ──────────────────────────────────────────────
col_a, col_b = st.columns(2)

with col_a:
    st.subheader("PEP par pays")
    if df.empty:
        st.info("Aucune donnée.")
    else:
        pep_par_pays = (
            df.groupby(["pays_nom", "statut_gafi"])
            .size()
            .reset_index(name="count")
        )
        pep_par_pays["label_gafi"] = pep_par_pays["statut_gafi"].map(LABELS_GAFI)
        fig_pays = px.bar(
            pep_par_pays, x="pays_nom", y="count", color="label_gafi",
            color_discrete_map={v: COULEURS_GAFI[k] for k, v in LABELS_GAFI.items()},
            labels={"pays_nom": "Pays", "count": "Nombre de PEP", "label_gafi": "Statut GAFI"},
            text="count",
        )
        fig_pays.update_layout(xaxis_tickangle=-35, legend_title="Statut GAFI",
                               margin=dict(t=20, b=0), plot_bgcolor="rgba(0,0,0,0)")
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

COLS_AFFICHAGE = {
    "prenom":                     "Prénom",
    "nom":                        "Nom",
    "pays_nom":                   "Pays",
    "code_iso":                   "ISO",
    "fonction_actuelle":          "Fonction",
    "statut_mandat":              "Statut mandat",
    "statut_gafi":                "GAFI",
    "date_nomination":            "Date nomination",
    "date_sortie_fonction_public":"Date fin mandat",
    "date_naissance":             "Date naissance",
    "lieu_naissance":             "Lieu naissance",
    "statut_matrimonial":         "Statut matrimonial",
    "enfants":                    "Nb enfants",
    "formations":                 "Formations",
    "fonctions_interieures":      "Fonctions antérieures",
    "source_url":                 "Source URL",
    "date_scraping":              "Dernière vérif.",
}

def _df_affichage(df_in):
    cols = [c for c in COLS_AFFICHAGE if c in df_in.columns]
    out  = df_in[cols].copy()
    if "statut_gafi" in out.columns:
        out["statut_gafi"] = out["statut_gafi"].map(LABELS_GAFI).fillna(out["statut_gafi"])
    return out.rename(columns={c: COLS_AFFICHAGE[c] for c in cols})

# ── Section : Performances de l'agent ────────────────────────────────────────────
st.markdown("---")
st.subheader("📈 Performances de l'agent")

if not df.empty and "date_creation" in df.columns:
    df_perf = df.copy()
    df_perf["date_creation"] = pd.to_datetime(df_perf["date_creation"], errors="coerce", utc=True)
    df_perf = df_perf.dropna(subset=["date_creation"])
    df_perf["jour"]  = df_perf["date_creation"].dt.date
    df_perf["mois"]  = df_perf["date_creation"].dt.to_period("M").astype(str)

    aujourd_hui   = pd.Timestamp.now(tz="UTC").date()
    debut_mois    = aujourd_hui.replace(day=1)
    il_y_a_30j    = aujourd_hui - pd.Timedelta(days=29)

    pep_aujourd_hui = int((df_perf["jour"] == aujourd_hui).sum())
    pep_ce_mois     = int((df_perf["jour"] >= debut_mois).sum())

    # Moyenne journalière sur les 30 derniers jours (jours avec au moins 1 PEP)
    df_30j = df_perf[df_perf["jour"] >= il_y_a_30j]
    par_jour_30j = df_30j.groupby("jour").size()
    moyenne_jour = round(par_jour_30j.mean(), 1) if not par_jour_30j.empty else 0.0
    jours_actifs = int(par_jour_30j.count())

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        st.metric("PEP insérés aujourd'hui", pep_aujourd_hui)
    with kpi2:
        st.metric("PEP insérés ce mois", pep_ce_mois)
    with kpi3:
        st.metric("Moyenne / jour (30j)", f"{moyenne_jour}")
    with kpi4:
        st.metric("Jours actifs (30j)", f"{jours_actifs} / 30")

    perf_col1, perf_col2 = st.columns(2)

    with perf_col1:
        st.markdown("**PEP insérés par jour — 30 derniers jours**")
        # Créer une série complète sur 30 jours (0 si aucun PEP)
        tous_les_jours = pd.date_range(end=aujourd_hui, periods=30, freq="D").date
        par_jour_complet = (
            df_30j.groupby("jour").size()
            .reindex(tous_les_jours, fill_value=0)
            .reset_index()
        )
        par_jour_complet.columns = ["Jour", "PEP insérés"]
        par_jour_complet["Jour"] = par_jour_complet["Jour"].astype(str)
        fig_jour = px.bar(
            par_jour_complet, x="Jour", y="PEP insérés",
            color_discrete_sequence=["#3498db"],
        )
        fig_jour.update_layout(
            margin=dict(t=10, b=0), plot_bgcolor="rgba(0,0,0,0)",
            xaxis_tickangle=-45, xaxis_tickfont_size=10,
        )
        st.plotly_chart(fig_jour, use_container_width=True)

    with perf_col2:
        st.markdown("**PEP insérés par mois — 12 derniers mois**")
        par_mois = (
            df_perf.groupby("mois").size()
            .reset_index(name="PEP insérés")
            .tail(12)
        )
        par_mois.columns = ["Mois", "PEP insérés"]
        fig_mois = px.bar(
            par_mois, x="Mois", y="PEP insérés",
            color_discrete_sequence=["#2ecc71"],
            text="PEP insérés",
        )
        fig_mois.update_layout(
            margin=dict(t=10, b=0), plot_bgcolor="rgba(0,0,0,0)",
            xaxis_tickangle=-30,
        )
        fig_mois.update_traces(textposition="outside")
        st.plotly_chart(fig_mois, use_container_width=True)
else:
    st.info("Aucune donnée de performance disponible.")

st.markdown("---")

tabs = st.tabs(["🔴 Liste Noire", "🟡 Liste Grise", "🟢 Clean", "📋 Toutes les PEP"])

with tabs[0]:
    if df.empty or df[df["statut_gafi"] == "liste_noire"].empty:
        st.info("Aucune PEP en liste noire dans la base.")
    else:
        st.dataframe(_df_affichage(df[df["statut_gafi"] == "liste_noire"]), use_container_width=True)

with tabs[1]:
    if df.empty or df[df["statut_gafi"] == "liste_grise"].empty:
        st.info("Aucune PEP en liste grise dans la base.")
    else:
        st.dataframe(_df_affichage(df[df["statut_gafi"] == "liste_grise"]), use_container_width=True)

with tabs[2]:
    if df.empty or df[df["statut_gafi"] == "clean"].empty:
        st.info("Aucune PEP clean dans la base.")
    else:
        st.dataframe(_df_affichage(df[df["statut_gafi"] == "clean"]), use_container_width=True)

with tabs[3]:
    if df.empty:
        st.info("Aucune PEP dans la base.")
    else:
        st.dataframe(_df_affichage(df), use_container_width=True)

# ── Section : PEP par pays — liste détaillée ─────────────────────────────────────
st.markdown("---")
st.subheader("🌍 PEP par pays — liste détaillée")

def _s(v):
    return "" if (v is None or (isinstance(v, float) and pd.isna(v))) else str(v)

@st.fragment(run_every=30)
def section_liste_pep():
    df_live = charger_pep_db()
    if not df_live.empty and "code_iso" in df_live.columns:
        ref_live = charger_referentiel()
        df_live["statut_gafi"] = df_live["code_iso"].apply(
            lambda c: ref_live.get(str(c).upper(), {}).get("statut_gafi", "clean")
        )

    pays_disponibles = sorted(df_live["pays_nom"].dropna().unique().tolist()) if not df_live.empty and "pays_nom" in df_live.columns else []
    col_filtre1, col_filtre2 = st.columns([2, 2])
    with col_filtre1:
        pays_selectionne = st.selectbox("Filtrer par pays", ["Tous les pays"] + pays_disponibles, key="filtre_pays")
    with col_filtre2:
        statut_filtre = st.selectbox("Filtrer par statut", ["Tous", "Actif", "Ex-PEP"], key="filtre_statut")

    df_liste = df_live.copy()
    if pays_selectionne != "Tous les pays":
        df_liste = df_liste[df_liste["pays_nom"] == pays_selectionne]
    if "statut_mandat" in df_liste.columns:
        if statut_filtre == "Actif":
            df_liste = df_liste[df_liste["statut_mandat"] == "actif"]
        elif statut_filtre == "Ex-PEP":
            df_liste = df_liste[df_liste["statut_mandat"] == "ex_pep"]

    total_liste = len(df_liste)
    st.caption(f"{total_liste} PEP trouvé(s) — actualisation auto toutes les 30 s")

    if df_live.empty:
        st.info("Base vide — aucune donnée à afficher.")
        return
    if df_liste.empty:
        st.info("Aucune PEP pour ces critères.")
        return

    PAR_PAGE = 20
    nb_pages = max(1, (total_liste + PAR_PAGE - 1) // PAR_PAGE)

    _filtre_key = f"{pays_selectionne}_{statut_filtre}"
    if st.session_state.get("_filtre_key_prev") != _filtre_key:
        st.session_state["page_pep"] = 0
        st.session_state["_filtre_key_prev"] = _filtre_key

    page_actuelle = st.session_state.get("page_pep", 0)

    pg_col1, pg_col2, pg_col3 = st.columns([1, 3, 1])
    with pg_col1:
        if st.button("◀ Précédent", disabled=(page_actuelle == 0), key="btn_prev"):
            st.session_state["page_pep"] = page_actuelle - 1
            st.rerun(scope="fragment")
    with pg_col2:
        st.markdown(f"<div style='text-align:center;padding-top:8px'>Page {page_actuelle+1} / {nb_pages}</div>",
                    unsafe_allow_html=True)
    with pg_col3:
        if st.button("Suivant ▶", disabled=(page_actuelle >= nb_pages - 1), key="btn_next"):
            st.session_state["page_pep"] = page_actuelle + 1
            st.rerun(scope="fragment")

    debut   = page_actuelle * PAR_PAGE
    df_page = df_liste.iloc[debut:debut + PAR_PAGE]

    for _, row in df_page.iterrows():
        statut_val   = _s(row.get("statut_mandat"))
        badge_statut = "🟢 Actif" if statut_val == "actif" else ("🔴 Ex-PEP" if statut_val == "ex_pep" else "⚪")
        gafi_val     = _s(row.get("statut_gafi")) or "clean"
        badge_gafi   = {"liste_noire": "🔴 Noire", "liste_grise": "🟡 Grise", "clean": "🟢 Clean"}.get(gafi_val, gafi_val)

        prenom        = _s(row.get("prenom"))
        nom           = _s(row.get("nom"))
        pays_nom      = _s(row.get("pays_nom"))
        code_iso      = _s(row.get("code_iso"))
        fonction      = _s(row.get("fonction_actuelle"))
        date_nom      = _s(row.get("date_nomination"))
        date_fin      = _s(row.get("date_sortie_fonction_public"))
        source        = _s(row.get("source_url"))
        date_naiss    = _s(row.get("date_naissance"))
        lieu_naiss    = _s(row.get("lieu_naissance"))
        matrimonial   = _s(row.get("statut_matrimonial"))
        enfants       = _s(row.get("enfants"))
        formations    = _s(row.get("formations"))
        fonctions_ant = _s(row.get("fonctions_interieures"))

        label = f"{badge_statut}  {prenom} {nom}  —  {fonction[:45]}{'…' if len(fonction)>45 else ''}  |  {pays_nom} `{code_iso}`  |  GAFI: {badge_gafi}"
        with st.expander(label):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**Pays :** {pays_nom} `{code_iso}`")
                st.markdown(f"**Fonction :** {fonction or '—'}")
                st.markdown(f"**Statut mandat :** {badge_statut}")
                st.markdown(f"**Statut GAFI :** {badge_gafi}")
                st.markdown(f"**Date nomination :** {date_nom or '—'}")
                st.markdown(f"**Fin mandat :** {date_fin or '—'}")
                if source and source != "non disponible":
                    st.markdown(f"**Source :** [🔗 lien]({source})")
                else:
                    st.markdown("**Source :** —")
            with c2:
                st.markdown(f"**Date naissance :** {date_naiss or '—'}")
                st.markdown(f"**Lieu naissance :** {lieu_naiss or '—'}")
                st.markdown(f"**Statut matrimonial :** {matrimonial or '—'}")
                st.markdown(f"**Enfants :** {enfants or '—'}")
                st.markdown(f"**Formations :** {formations or '—'}")
                st.markdown(f"**Fonctions antérieures :** {fonctions_ant or '—'}")

section_liste_pep()

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
        st.session_state.pop("forcer_maj_verif", None)
        st.rerun()

# ── Vérification base avant de lancer le pipeline ────────────────────────────────
_prenom_v = prenom_input.strip() if lancer or st.session_state.get("verif_prenom") else st.session_state.get("verif_prenom", "")
_nom_v    = nom_input.strip()    if lancer or st.session_state.get("verif_nom")    else st.session_state.get("verif_nom", "")

if lancer and prenom_input.strip() and nom_input.strip():
    st.session_state["verif_prenom"] = prenom_input.strip()
    st.session_state["verif_nom"]    = nom_input.strip()

_prenom_v = st.session_state.get("verif_prenom", "")
_nom_v    = st.session_state.get("verif_nom", "")

if _prenom_v and _nom_v and st.session_state.get("rapport_scraper") is None and not st.session_state.get("scraper_erreur"):
    from db_utils import query_one as _qone
    _nom_complet_v = f"{_prenom_v} {_nom_v}"
    _existant = _qone("""
        SELECT nom_complete, pays_nom, code_iso, fonction_actuelle,
               statut_mandat, source_url, date_nomination, date_creation
        FROM pep
        WHERE nom_complete ILIKE %s OR nom_complete ILIKE %s
        LIMIT 1
    """, (_nom_complet_v, f"{_nom_v} {_prenom_v}"))

    if _existant and not st.session_state.get("forcer_maj_verif"):
        _date_verif  = _existant["date_creation"]
        _jours       = (datetime.now().date() - _date_verif.date()).days if _date_verif else 999
        _fraicheur   = (f"🟢 Récent ({_jours}j)" if _jours <= 30
                        else f"🟡 Modéré ({_jours}j)" if _jours <= 90
                        else f"🔴 Ancien ({_jours}j) — mise à jour recommandée")

        st.success(f"✅ **{_existant['nom_complete']}** est déjà dans la base PEP")
        with st.container(border=True):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**Pays :** {_existant['pays_nom']} `{_existant['code_iso']}`")
                st.markdown(f"**Fonction :** {_existant['fonction_actuelle'] or '—'}")
                st.markdown(f"**Statut :** {_existant['statut_mandat'] or '—'}")
            with c2:
                st.markdown(f"**Date nomination :** {_existant['date_nomination'] or '—'}")
                st.markdown(f"**Dernière vérification :** {_fraicheur}")
                if _existant["source_url"]:
                    st.markdown(f"**Source :** [{_existant['source_url']}]({_existant['source_url']})")

        st.warning("⚠️ Ces informations peuvent avoir changé (nouvelle fonction, fin de mandat…)")
        if st.button("🔄 Mettre à jour — relancer la vérification complète", type="secondary"):
            st.session_state["forcer_maj_verif"] = True
            st.rerun()

    else:
        # Pas en base (ou mise à jour forcée) → lancer le pipeline
        with st.status(f"Analyse de **{_nom_complet_v}** en cours...", expanded=True) as status_box:
            st.write("Identification du pays et de la nationalité...")
            try:
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                from pep_agent import verifier_pep
                st.write("Recherche multi-sources (Tavily, OpenSanctions, Wikipedia)...")
                rapport = verifier_pep(_prenom_v, _nom_v)
                st.session_state["rapport_scraper"] = rapport
                status_box.update(label=f"Analyse terminée — {_nom_complet_v}", state="complete")
            except Exception as exc:
                st.session_state["scraper_erreur"] = str(exc)
                status_box.update(label=f"Erreur : {exc}", state="error")

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

# ── Section : Collecte Live ──────────────────────────────────────────────────────
st.markdown("---")
st.subheader("📡 Collecte PEP — Live")

STATUS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "collector_status.json")

@st.fragment(run_every=5)
def section_live():
    # Lire le statut écrit par pep_collector.py
    statut = {}
    if os.path.exists(STATUS_PATH):
        try:
            with open(STATUS_PATH, "r", encoding="utf-8") as _f:
                statut = json.load(_f)
        except Exception:
            statut = {}

    en_cours = _collector_running() and statut.get("running", False)

    # ── Boutons Start / Stop ──────────────────────────────────────────────────
    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([2, 1, 1])
    with ctrl_col1:
        pays_selectionnes = st.multiselect(
            "Pays à collecter (tous si vide)",
            options=list(_PAYS_LABELS.keys()),
            format_func=lambda c: _PAYS_LABELS[c],
            placeholder="Tous les pays",
            label_visibility="collapsed",
        )
    with ctrl_col2:
        track_choice = st.selectbox("Track", ["Track B (rapide)", "B + A (complet)"],
                                    label_visibility="collapsed")
    with ctrl_col3:
        if not en_cours:
            if st.button("▶ Démarrer la collecte", type="primary", use_container_width=True):
                pays_str = ",".join(pays_selectionnes)
                _start_collector(
                    track_b_only=(track_choice == "Track B (rapide)"),
                    pays=pays_str,
                )
                st.toast("Collecte démarrée !", icon="🚀")
                st.rerun()
        else:
            if st.button("⏹ Arrêter la collecte", type="secondary", use_container_width=True):
                _stop_collector()
                st.toast("Collecte arrêtée.", icon="⏹")
                st.rerun()

    if en_cours:
        st.success("🟢 Collecte en cours — rafraîchissement auto toutes les 5 s")
    else:
        st.info("⏸️ Collecte arrêtée")

    col_s1, col_s2, col_s3 = st.columns([2, 2, 2])
    with col_s1:
        pass
    with col_s2:
        if en_cours:
            st.metric("PEP insérés (session)", statut.get("inserted_total", 0),
                      delta=statut.get("inserted_last", 0) or None)
    with col_s3:
        if en_cours:
            pays_act  = statut.get("country", "")
            categ_act = statut.get("category", "")
            track     = statut.get("track", "")
            if pays_act:
                st.markdown(f"**Pays :** `{pays_act}` | **Track :** `{track}`")
                if categ_act:
                    st.caption(f"Catégorie : {categ_act}")

    if en_cours:
        pays_done  = statut.get("countries_done", 0)
        pays_total = statut.get("countries_total", 13)
        if pays_total > 0:
            pct = pays_done / pays_total
            st.progress(pct, text=f"{pays_done} / {pays_total} pays traités ({int(pct*100)} %)")
        erreurs = statut.get("errors", [])
        if erreurs:
            with st.expander(f"⚠️ {len(erreurs)} erreur(s) de collecte"):
                for e in erreurs[-5:]:
                    st.caption(e)

    # Derniers PEP insérés — rechargé à chaque fragment tick
    st.markdown("**10 derniers PEP insérés en base :**")
    try:
        from db_utils import query_all as _q
        derniers = _q("""
            SELECT prenom, nom, pays_nom, code_iso,
                   fonction_actuelle, statut_mandat,
                   source_url, date_creation
            FROM pep
            ORDER BY date_creation DESC NULLS LAST
            LIMIT 10
        """)
        if derniers:
            _df = pd.DataFrame(derniers)
            _df.columns = ["Prénom", "Nom", "Pays", "ISO",
                           "Fonction", "Statut", "Source", "Inséré le"]
            st.dataframe(_df, use_container_width=True, hide_index=True)
        else:
            st.caption("Aucun PEP en base pour l'instant.")
    except Exception as _ex:
        st.caption(f"Erreur DB : {_ex}")

section_live()

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
