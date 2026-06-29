"""
dashboard_pep.py — ScreenEdge Africa
Dashboard analytique PEP : KPIs, répartition par pays, listes GAFI.
Lancer : streamlit run dashboard_pep.py
"""

import sys, json, os, subprocess
sys.stdout.reconfigure(encoding="utf-8")

# ── Logger Tee : terminal + fichier simultanément ────────────────────────────────
class _TeeLogger:
    """Écrit simultanément sur stdout (terminal) et dans un fichier log."""
    def __init__(self, filepath: str, original):
        self._file     = open(filepath, "a", encoding="utf-8", buffering=1)
        self._original = original

    def write(self, msg: str):
        self._original.write(msg)
        self._original.flush()
        self._file.write(msg)

    def flush(self):
        self._original.flush()
        self._file.flush()

    def close(self):
        try:
            self._file.close()
        except Exception:
            pass

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import hmac

# ── Protection par mot de passe ──────────────────────────────────────────────
_DASHBOARD_PWD = os.getenv("DASHBOARD_PASSWORD", "junior45")

def _check_password() -> bool:
    def _verify():
        if hmac.compare_digest(st.session_state.get("_pwd", ""), _DASHBOARD_PWD):
            st.session_state["_auth"] = True
        else:
            st.session_state["_auth"] = False

    if st.session_state.get("_auth"):
        return True

    st.title("ScreenEdge Africa — Accès sécurisé")
    st.text_input("Mot de passe", type="password", key="_pwd", on_change=_verify)
    if "_auth" in st.session_state and not st.session_state["_auth"]:
        st.error("Mot de passe incorrect.")
    st.stop()

_check_password()

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
    """Charge les PEP depuis PostgreSQL avec timeout global de 20s."""
    import concurrent.futures
    def _fetch():
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from db_utils import query_all
        return query_all("""
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
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_fetch)
            rows = future.result(timeout=20)
        return pd.DataFrame(rows) if rows else pd.DataFrame()
    except concurrent.futures.TimeoutError:
        st.warning("⚠️ Base de données inaccessible (timeout 20s) — dashboard en mode hors-ligne.")
        return pd.DataFrame()
    except Exception as e:
        st.warning(f"⚠️ Base de données : {e}")
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
    st.metric("🟠 Plus en fonction", nb_ex_pep)
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

# ── Section : Consommation des APIs ──────────────────────────────────────────────
st.markdown("---")
st.subheader("⚡ Consommation des APIs")

@st.cache_data(ttl=15)
def _charger_api_usage():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from api_tracker import lire_consommation
        return lire_consommation()
    except Exception as e:
        return {}

_api_usage = _charger_api_usage()

if _api_usage:
    _api_cols = st.columns(5)
    # Modèle LLM actif (lu depuis collector_status.json)
    _llm_actif = statut.get("llm_actif", "") if statut else ""

    _api_cfg = [
        ("gemini",        "✨ Gemini",          "gemini-2.5-flash"),
        ("groq_1",        "🤖 Groq",            "llama-4-scout"),
        ("serper",        "🔍 Serper",          ""),
        ("tavily",        "🌐 Tavily",          ""),
        ("opensanctions", "🛡️ OpenSanctions",  ""),
    ]

    for _col, (_key, _lbl, _model_name) in zip(_api_cols, _api_cfg):
        _d = _api_usage.get(_key, {})
        _pct  = _d.get("pct", 0)
        _util = _d.get("utilise", 0)
        _lim  = _d.get("limite", 0)
        _per  = _d.get("periode", "")
        _apls = _d.get("appels", 0)

        if _pct >= 100:
            _badge = "🔴 ÉPUISÉ"
        elif _pct >= 95:
            _badge = "⛔ CRITIQUE"
        elif _pct >= 80:
            _badge = "⚠️ ALERTE"
        else:
            _badge = "✅ OK"

        # Indicateur modèle actif
        _actif_tag = ""
        if _model_name and _llm_actif and _model_name.lower() in _llm_actif.lower():
            _actif_tag = " 🟢 **actif**"
        elif _key == "groq_1" and _llm_actif and "groq" in _llm_actif.lower():
            _actif_tag = " 🟢 **actif**"
        elif _key == "gemini" and _llm_actif and "gemini" in _llm_actif.lower():
            _actif_tag = " 🟡 **fallback actif**"

        with _col:
            st.markdown(f"**{_lbl}** &nbsp; {_badge}{_actif_tag}")
            if _model_name:
                st.caption(f"_{_model_name}_")
            st.progress(min(_pct / 100, 1.0))
            if _key == "gemini":
                st.caption(f"{_util:,} tokens / {_lim:,} {_per} ({_pct}%)")
                st.caption(f"{_apls} appels LLM")
            elif _key == "groq_1":
                st.caption(f"{_util:,} requêtes / {_lim:,} {_per} ({_pct}%)")
            else:
                st.caption(f"{_util:,} requêtes / {_lim:,} {_per} ({_pct}%)")

    # Alerte globale si une API est épuisée ou critique
    _epuises   = [k for k, d in _api_usage.items() if d.get("pct", 0) >= 100]
    _critiques = [k for k, d in _api_usage.items() if 95 <= d.get("pct", 0) < 100]
    _alertes   = [k for k, d in _api_usage.items() if 80 <= d.get("pct", 0) < 95]
    if _epuises:
        st.error(f"🔴 **QUOTA ÉPUISÉ** : {', '.join(e.upper() for e in _epuises)} — le système utilise les outils alternatifs jusqu'à la prochaine période.")
    if _critiques:
        st.warning(f"⛔ **Quota critique** : {', '.join(c.upper() for c in _critiques)} — quelques appels restants, surveiller.")
    if not _epuises and not _critiques and _alertes:
        st.warning(f"⚠️ **Quota bientôt atteint** : {', '.join(a.upper() for a in _alertes)} — pensez à surveiller la consommation.")

    # ── Quota vérifications restantes ────────────────────────────────────────
    try:
        from api_tracker import quota_restant_verifications as _quota_verif
        _qv = _quota_verif()
        _vr = _qv["verifications_restantes"]
        _fl = _qv["facteur_limitant"].upper()
        _tav_d = _qv["tavily"]
        _grq_d = _qv["groq"]

        _qcol1, _qcol2, _qcol3 = st.columns([2, 2, 2])
        with _qcol1:
            if _vr == 0:
                st.error(f"⛔ **0 vérification possible** — quota {_fl} épuisé aujourd'hui")
            elif _vr <= 2:
                st.warning(f"⚠️ **{_vr} vérification(s) restante(s)** — facteur : {_fl}")
            else:
                st.success(f"✅ **{_vr} vérifications** possibles aujourd'hui")
        with _qcol2:
            st.caption(
                f"Tavily : {_tav_d['restant']} appels restants "
                f"({_tav_d['utilise']}/{_tav_d['limite']}) → {_tav_d['verifs']} vérifs"
            )
        with _qcol3:
            st.caption(
                f"Groq : {_grq_d['restant']} appels restants "
                f"({_grq_d['utilise']}/{_grq_d['limite']}) → {_grq_d['verifs']} vérifs"
            )
    except Exception as _eq:
        st.caption(f"Quota vérifications : {_eq}")

else:
    st.info("Aucune donnée de consommation disponible — lancer l'agent pour commencer le suivi.")

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
        statut_filtre = st.selectbox("Filtrer par statut", ["Tous", "Actif", "Plus en fonction"], key="filtre_statut")

    df_liste = df_live.copy()
    if pays_selectionne != "Tous les pays":
        df_liste = df_liste[df_liste["pays_nom"] == pays_selectionne]
    if "statut_mandat" in df_liste.columns:
        if statut_filtre == "Actif":
            df_liste = df_liste[df_liste["statut_mandat"] == "actif"]
        elif statut_filtre == "Plus en fonction":
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
        badge_statut = "🟢 Actif" if statut_val == "actif" else ("🟠 Plus en fonction" if statut_val == "ex_pep" else "⚪")
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
                _fn_db = f"Ancien(ne) {fonction}" if (statut_val == "ex_pep" and fonction) else (fonction or "—")
                _fn_lbl = "Dernière fonction connue" if statut_val == "ex_pep" else "Fonction"
                st.markdown(f"**{_fn_lbl} :** {_fn_db}")
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
        prenom_input = st.text_input("Prénom", placeholder="ex: Macky",
                                     help="Pour les noms communs, entrez tous les prénoms (ex: Mariam Aladji Boni)")
    with col_n:
        nom_input = st.text_input("Nom", placeholder="ex: Sall",
                                  help="Nom de famille complet — plus le nom est précis, moins il y a de risque de confusion avec un homonyme")
    st.caption("💡 **Conseil** : Pour les noms communs (Diallo, Traoré, Koné…), renseignez le nom complet avec tous les prénoms pour éviter toute confusion avec un homonyme.")
    lancer = st.form_submit_button("▶ Lancer la vérification", type="primary")

if lancer:
    if not prenom_input.strip() or not nom_input.strip():
        st.warning("Merci de renseigner le prénom et le nom.")
    else:
        st.session_state["verif_prenom"]    = prenom_input.strip()
        st.session_state["verif_nom"]       = nom_input.strip()
        st.session_state["rapport_scraper"] = None
        st.session_state["scraper_erreur"]  = None
        st.session_state.pop("forcer_maj_verif", None)
        st.rerun()

# ── Vérification base avant de lancer le pipeline ────────────────────────────────
_prenom_v = st.session_state.get("verif_prenom", "")
_nom_v    = st.session_state.get("verif_nom", "")

if _prenom_v and _nom_v and st.session_state.get("rapport_scraper") is None and not st.session_state.get("scraper_erreur"):
    from db_utils import query_one as _qone
    _nom_complet_v = f"{_prenom_v} {_nom_v}"
    _existant = _qone("""
        SELECT nom_complete, pays_nom, code_iso, fonction_actuelle,
               statut_mandat, source_url, date_nomination, date_creation,
               fonctions_interieures
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
                _sm_exist = _existant['statut_mandat'] or ''
                _fn_exist  = _existant['fonction_actuelle'] or ''
                _fn_lbl    = "Dernière fonction connue" if _sm_exist == "ex_pep" else "Fonction"
                _fn_prefix = "Ancien(ne) " if (_sm_exist == "ex_pep" and _fn_exist) else ""
                st.markdown(f"**{_fn_lbl} :** {_fn_prefix}{_fn_exist or '—'}")
                _fi_exist = _existant.get('fonctions_interieures') or ''
                if _fi_exist:
                    st.markdown(f"**Fonctions antérieures :** {_fi_exist}")
                st.markdown(f"**Statut :** {_sm_exist or '—'}")
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
                _logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
                os.makedirs(_logs_dir, exist_ok=True)
                _log_path = os.path.join(_logs_dir, f"pep_{datetime.now().strftime('%Y-%m-%d')}.log")
                _tee = _TeeLogger(_log_path, sys.stdout)
                sys.stdout = _tee
                try:
                    _tee.write(f"\n{'='*60}\n")
                    _tee.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] RECHERCHE : {_prenom_v} {_nom_v}\n")
                    _tee.write(f"{'='*60}\n")
                    rapport = verifier_pep(_prenom_v, _nom_v)
                finally:
                    sys.stdout = _tee._original
                    _tee.close()
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
    badge_st  = "🟢 Actif" if statut_m == "actif" else ("🟠 Plus en fonction" if statut_m == "ex_pep" else "")

    _code_iso_r = getattr(rapport_obj, "code_iso", "") or ""
    _hors_perim = _code_iso_r == "XX" or _code_iso_r not in ["MA","DZ","TN","LY","SN","CI","ML","BF","NE","TG","BJ","GW","GN"]

    badge_pep = (
        "⛔ **Erreur LLM — Vérif. manuelle obligatoire**" if statut_m == "erreur_llm" else
        "🔴 **PEP Actif**" if (est_pep and statut_m == "actif") else
        "🟠 **PEP · Plus en fonction**" if (est_pep and statut_m == "ex_pep") else
        "🟢 **Non-PEP**"
    )

    col_titre, col_badge = st.columns([3, 1])
    with col_titre:
        st.markdown(f"### Résultat : {badge_pep}")
    with col_badge:
        if _hors_perim:
            st.warning("⚠️ Hors périmètre")

    if statut_m == "erreur_llm":
        st.error("⛔ **Quota LLM épuisé** — vérification impossible. Ce résultat n'est PAS fiable. Re-vérifier manuellement avant toute décision de conformité.")

    if _hors_perim:
        _PAYS_COUVERTS = "🇲🇦 Maroc · 🇩🇿 Algérie · 🇹🇳 Tunisie · 🇱🇾 Libye · 🇸🇳 Sénégal · 🇨🇮 Côte d'Ivoire · 🇲🇱 Mali · 🇧🇫 Burkina Faso · 🇳🇪 Niger · 🇹🇬 Togo · 🇧🇯 Bénin · 🇬🇼 Guinée-Bissau · 🇬🇳 Guinée"
        if _code_iso_r == "XX":
            st.info(
                f"🌍 **Pays non identifié (XX)** — L'agent n'a pas pu déterminer la nationalité de cette personne. "
                f"Cela peut arriver si le nom est trop commun, si la personne est peu documentée, ou si elle "
                f"n'appartient pas aux 13 pays couverts.\n\n"
                f"**Périmètre ScreenEdge :** {_PAYS_COUVERTS}\n\n"
                f"Conseil : essayez avec le nom complet, une variante orthographique, ou précisez le pays dans le nom (ex : *Karim Maroc*)."
            )
        else:
            _pays_hors = getattr(rapport_obj, 'pays', '') or _code_iso_r
            st.info(
                f"🌍 **{_pays_hors} (`{_code_iso_r}`) — Hors périmètre** — Ce pays n'est pas couvert par ScreenEdge Africa. "
                f"Le résultat affiché est fourni à titre indicatif mais **aucune insertion en base n'est possible** pour ce pays.\n\n"
                f"**13 pays couverts :** {_PAYS_COUVERTS}"
            )

    with st.container(border=True):
        r1, r2 = st.columns(2)
        with r1:
            st.markdown(f"**Nom complet :** {getattr(rapport_obj, 'prenom', '')} {getattr(rapport_obj, 'nom', '')}")
            _pays_label = getattr(rapport_obj, 'pays', '') or getattr(rapport_obj, 'pays_nom', '') or ("Hors périmètre" if _hors_perim else "Inconnu")
            st.markdown(f"**Pays :** {_pays_label} `{_code_iso_r}`" + (" ⚠️" if _hors_perim else ""))
            _fn_brute = getattr(rapport_obj, 'fonction', '') or getattr(rapport_obj, 'fonction_actuelle', '') or ''
            _fn_label  = f"Ancien(ne) {_fn_brute}" if (statut_m == "ex_pep" and _fn_brute) else (_fn_brute or '—')
            st.markdown(f"**Dernière fonction connue :** {_fn_label}" if statut_m == "ex_pep" else f"**Fonction :** {_fn_label}")
            _fonctions_hist = getattr(rapport_obj, 'fonctions_historiques', None)
            if _fonctions_hist:
                st.markdown(f"**Fonctions antérieures :** {' · '.join(_fonctions_hist)}")
            else:
                st.markdown("**Fonctions antérieures :** —")
            if badge_st:
                st.markdown(f"**Statut mandat :** {badge_st}")
        with r2:
            date_n    = getattr(rapport_obj, "date_nomination", None)
            date_f    = getattr(rapport_obj, "date_fin_mandat", None)
            date_naiss = getattr(rapport_obj, "date_naissance", None)
            lieu_naiss = getattr(rapport_obj, "lieu_naissance", None)
            nb_enf     = getattr(rapport_obj, "nb_enfants", None)
            src    = getattr(rapport_obj, "source_url", None) or ""
            src_t  = getattr(rapport_obj, "source_type", None) or ""
            if date_n:
                st.markdown(f"**Date nomination :** {date_n}")
            if date_f:
                st.markdown(f"**Date fin mandat :** {date_f}")
            if date_naiss:
                st.markdown(f"**Date naissance :** {date_naiss}")
            if lieu_naiss:
                st.markdown(f"**Lieu naissance :** {lieu_naiss}")
            if nb_enf is not None:
                st.markdown(f"**Enfants :** {nb_enf}")
            if src and src != "non disponible":
                st.markdown(f"**Source :** [{src}]({src})")
                if src_t:
                    _label_src = {
                        "officielle":              "✅ Source officielle",
                        "opensanctions_url":       "🔎 OpenSanctions",
                        "opensanctions_confirmed": "🔎 OpenSanctions",
                        "a_verifier_manuellement": "⚠️ À vérifier manuellement",
                    }.get(src_t, src_t)
                    st.caption(_label_src)
            elif src_t == "a_verifier_manuellement":
                st.warning("⚠️ **Source officielle non trouvée** — vérification manuelle requise avant usage compliance")
                _urls_piste = getattr(rapport_obj, "urls_media_trouvees", []) or []
                if _urls_piste:
                    st.caption("Pistes de découverte (non auditables) :")
                    for _u in _urls_piste[:3]:
                        st.caption(f"→ {_u}")
            else:
                st.markdown("**Source :** non disponible")

    raisonnement = getattr(rapport_obj, "raisonnement", None)
    if raisonnement:
        with st.expander("📋 Raisonnement de l'agent"):
            st.text(raisonnement)

# ── Section : Test batch — liste de noms ─────────────────────────────────────────
st.markdown("---")
st.subheader("🧪 Test batch — vérification en liste")
st.caption("Colle une liste de noms (un par ligne : Prénom Nom). L'agent vérifie chaque personne, affiche les résultats, puis tu valides avant insertion en base.")

# Initialiser session state batch
for _k, _v in [
    ("batch_noms_input", ""),
    ("batch_resultats", []),
    ("batch_en_cours", False),
    ("batch_index", 0),
    ("batch_validation", {}),
    ("batch_inseres", []),
]:
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── Formulaire d'entrée ───────────────────────────────────────────────────────────
with st.form("form_batch"):
    _textarea = st.text_area(
        "Liste de noms (un par ligne)",
        placeholder="Macky Sall\nAlassane Ouattara\nMariam Aladji Boni Diallo\nFaure Gnassingbé",
        height=150,
        value=st.session_state["batch_noms_input"],
        help="💡 Pour les noms communs (Diallo, Traoré, Koné…), indiquez le nom complet avec tous les prénoms pour éviter toute confusion avec un homonyme.",
    )
    _col_btn1, _col_btn2 = st.columns([2, 1])
    with _col_btn1:
        _lancer_batch = st.form_submit_button("▶ Lancer la vérification batch", type="primary")
    with _col_btn2:
        _reset_batch = st.form_submit_button("🗑 Réinitialiser")

if _reset_batch:
    for _k in ["batch_resultats", "batch_en_cours", "batch_index", "batch_validation", "batch_inseres", "batch_noms_input"]:
        st.session_state[_k] = [] if "resultats" in _k or "validation" in _k or "inseres" in _k else (False if "cours" in _k else (0 if "index" in _k else ""))
    st.rerun()

if _lancer_batch:
    # Accepte un nom par ligne OU des noms séparés par des virgules
    _raw = _textarea.strip()
    if "," in _raw and "\n" not in _raw:
        _lignes = [l.strip() for l in _raw.split(",") if l.strip()]
    else:
        _lignes = [l.strip() for l in _raw.splitlines() if l.strip()]
    _noms_parsed = []
    for _ligne in _lignes:
        _parties = _ligne.split()
        if len(_parties) >= 2:
            _noms_parsed.append((_parties[0], " ".join(_parties[1:])))
    if not _noms_parsed:
        st.warning("Aucun nom valide (format attendu : Prénom Nom).")
    else:
        st.session_state["batch_noms_input"]  = _textarea
        st.session_state["batch_resultats"]   = []
        st.session_state["batch_validation"]  = {}
        st.session_state["batch_inseres"]     = []
        st.session_state["batch_en_cours"]    = True
        st.session_state["batch_index"]       = 0
        st.session_state["_batch_noms"]       = _noms_parsed
        st.rerun()

# ── Traitement itératif (un par rerun) ───────────────────────────────────────────
if st.session_state.get("batch_en_cours"):
    _noms_todo  = st.session_state.get("_batch_noms", [])
    _idx        = st.session_state["batch_index"]
    _total      = len(_noms_todo)

    if _idx < _total:
        _prenom_b, _nom_b = _noms_todo[_idx]
        st.progress(_idx / _total, text=f"Vérification {_idx+1}/{_total} — {_prenom_b} {_nom_b}…")
        with st.status(f"Analyse de **{_prenom_b} {_nom_b}**…", expanded=False):
            try:
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                from pep_agent import verifier_pep as _vp_batch
                _r = _vp_batch(_prenom_b, _nom_b, stocker=False)
                st.session_state["batch_resultats"].append(_r)
                st.write(f"✅ {_prenom_b} {_nom_b} — {'PEP' if _r.est_pep else 'Non-PEP'}")
            except Exception as _exc_b:
                import traceback
                _r_err = {"prenom": _prenom_b, "nom": _nom_b, "erreur": str(_exc_b)}
                st.session_state["batch_resultats"].append(_r_err)
                st.write(f"❌ Erreur : {_exc_b}")
        st.session_state["batch_index"] += 1
        import time; time.sleep(0.15)
        st.rerun()
    else:
        st.session_state["batch_en_cours"] = False
        st.success(f"✅ Vérification terminée — {_total} personnes analysées.")
        import time; time.sleep(0.15)
        st.rerun()

# ── Affichage des résultats avec validation ───────────────────────────────────────
_resultats_b = st.session_state.get("batch_resultats", [])
if _resultats_b and not st.session_state.get("batch_en_cours"):
    st.markdown(f"**{len(_resultats_b)} résultats — sélectionne les personnes à insérer en base :**")

    _pep_confirms = [r for r in _resultats_b if not isinstance(r, dict) and r.est_pep]
    _non_pep      = [r for r in _resultats_b if not isinstance(r, dict) and not r.est_pep]
    _erreurs_b    = [r for r in _resultats_b if isinstance(r, dict)]

    for _i, _rap in enumerate(_resultats_b):
        if isinstance(_rap, dict):
            st.error(f"❌ **{_rap.get('prenom','')} {_rap.get('nom','')}** — Erreur : {_rap.get('erreur','?')}")
            continue

        _key_chk    = f"batch_chk_{_i}"
        _is_err_llm = (_rap.statut_mandat or "") == "erreur_llm"
        if _key_chk not in st.session_state["batch_validation"]:
            st.session_state["batch_validation"][_key_chk] = _rap.est_pep and not _is_err_llm

        _statut_m_b = _rap.statut_mandat or ""
        _badge_b    = (
            "⛔ Erreur LLM — Vérif. manuelle" if _statut_m_b == "erreur_llm" else
            ("🔴 PEP Actif" if _statut_m_b == "actif"
             else "🟠 PEP · Plus en fonction" if _statut_m_b == "ex_pep"
             else "🟢 Non-PEP") if _rap.est_pep else "🟢 Non-PEP"
        )

        with st.expander(f"{_badge_b}  **{_rap.prenom} {_rap.nom}**  —  {(_rap.fonction or '—')[:50]}  |  {_rap.pays or '?'} `{_rap.code_iso}`"):
            if _is_err_llm:
                st.error("⛔ **Quota LLM épuisé** — vérification impossible. Ce résultat n'est PAS fiable. Re-vérifier manuellement avant toute décision de conformité.")
            _bc1, _bc2 = st.columns([3, 1])
            with _bc1:
                st.markdown(f"**Pays :** {_rap.pays} `{_rap.code_iso}`")
                st.markdown(f"**Fonction :** {_rap.fonction or '—'}")
                st.markdown(f"**Statut mandat :** {_statut_m_b or '—'}")
                _fh = _rap.fonctions_historiques
                st.markdown(f"**Fonctions antérieures :** {' · '.join(_fh) if _fh else '—'}")
                st.markdown(f"**Date naissance :** {_rap.date_naissance or '—'}")
                st.markdown(f"**Lieu naissance :** {_rap.lieu_naissance or '—'}")
                _src_b = _rap.source_url or ""
                if _src_b and _src_b != "non disponible":
                    st.markdown(f"**Source :** [{_src_b}]({_src_b})")
                else:
                    st.markdown("**Source :** —")
                if _rap.raisonnement:
                    st.caption(f"Raisonnement : {_rap.raisonnement}")
            with _bc2:
                _checked = st.checkbox(
                    "Insérer en base",
                    value=st.session_state["batch_validation"].get(_key_chk, _rap.est_pep),
                    key=_key_chk,
                )
                st.session_state["batch_validation"][_key_chk] = _checked

    # ── Bouton d'insertion ────────────────────────────────────────────────────────
    st.markdown("---")
    _nb_selec = sum(1 for k, v in st.session_state["batch_validation"].items() if v)
    _col_ins1, _col_ins2 = st.columns([2, 1])
    with _col_ins1:
        st.caption(f"{_nb_selec} personne(s) sélectionnée(s) pour insertion")
    with _col_ins2:
        _btn_inserer = st.button(
            f"💾 Insérer {_nb_selec} résultat(s) en base",
            type="primary",
            disabled=(_nb_selec == 0),
            key="btn_batch_inserer",
        )

    if _btn_inserer:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from pep_agent import stocker_rapport as _stocker_rapport
        _inseres_ok = []
        _inseres_err = []
        for _i, _rap in enumerate(_resultats_b):
            if isinstance(_rap, dict):
                continue
            _key_chk = f"batch_chk_{_i}"
            if st.session_state["batch_validation"].get(_key_chk):
                _statut_insert = _stocker_rapport(_rap)
                if "Erreur" in _statut_insert:
                    _inseres_err.append(f"{_rap.prenom} {_rap.nom} : {_statut_insert}")
                else:
                    _inseres_ok.append(f"{_rap.prenom} {_rap.nom}")

        if _inseres_ok:
            st.success(f"✅ Inséré en base : {', '.join(_inseres_ok)}")
        if _inseres_err:
            st.error("Erreurs :\n" + "\n".join(_inseres_err))
        st.session_state["batch_validation"] = {}
        st.session_state["batch_resultats"]  = []
        st.cache_data.clear()
        st.rerun()

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

    # ── Bannière crash ────────────────────────────────────────────────────────
    crash = statut.get("last_crash")
    if crash and not en_cours:
        ts_crash  = crash.get("ts", "")[:16].replace("T", " ")
        msg_crash = crash.get("erreur", "erreur inconnue")[:300]
        st.error(f"⛔ **SYSTÈME PLANTÉ** — {ts_crash}\n\n`{msg_crash}`")
        with st.expander("Traceback complet"):
            st.code(crash.get("traceback", ""), language="python")
        if st.button("🗑 Effacer l'alerte", key="btn_clear_crash"):
            statut.pop("last_crash", None)
            with open(STATUS_PATH, "w", encoding="utf-8") as _cf:
                json.dump(statut, _cf, ensure_ascii=False, indent=2)
            st.rerun()

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
        if en_cours:
            _verif = statut.get("verif_total", 0)
            _max_v = statut.get("max_verif", 0)
            _lbl_v = f"Vérifications ({_verif}/{_max_v})" if _max_v else "Vérifications (session)"
            st.metric(_lbl_v, _verif)
            if _max_v:
                st.progress(min(_verif / _max_v, 1.0))
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

# ── Section Dump OpenSanctions + Progression vérifications ──────────────────────
st.markdown("---")
st.subheader("📦 Base OpenSanctions (Dump local) — Couverture par pays")

try:
    from opensanctions_local import statut_dump as _statut_dump, stats_par_pays as _stats_pays
    from db_utils import query_all as _q_dump

    _dump_info = _statut_dump()
    _pays_cibles = list(_PAYS_LABELS.keys())

    _dc1, _dc2, _dc3, _dc4 = st.columns(4)
    with _dc1:
        st.metric("Dump présent", "✅ Oui" if _dump_info["present"] else "❌ Non")
    with _dc2:
        st.metric("Taille", f"{_dump_info['taille_mb']} MB" if _dump_info["present"] else "—")
    with _dc3:
        st.metric("Version OpenSanctions", (_dump_info.get("updated_at") or "—")[:10])
    with _dc4:
        st.metric("Téléchargé le", (_dump_info.get("telecharge_le") or "—")[:10])

    if _dump_info["present"]:
        # Compter PEPs dans le dump par pays
        _dump_counts = _stats_pays(_pays_cibles)

        # Compter PEPs vérifiés dans notre DB par pays
        _db_rows = _q_dump("SELECT code_iso, COUNT(*) as n FROM pep GROUP BY code_iso")
        _db_counts = {r["code_iso"]: r["n"] for r in (_db_rows or [])}

        # Tableau de synthèse
        _table_rows = []
        for code in _pays_cibles:
            dump_n = _dump_counts.get(code, 0)
            db_n   = _db_counts.get(code, 0)
            pct    = round(db_n / dump_n * 100, 1) if dump_n > 0 else 0
            _table_rows.append({
                "Pays":          _PAYS_LABELS.get(code, code),
                "ISO":           code,
                "Dans le dump":  dump_n,
                "Vérifiés (DB)": db_n,
                "Couverture %":  pct,
            })

        _df_cov = pd.DataFrame(_table_rows)
        st.dataframe(
            _df_cov.style.background_gradient(subset=["Couverture %"], cmap="RdYlGn", vmin=0, vmax=100),
            use_container_width=True, hide_index=True
        )

        _total_dump = sum(_dump_counts.values())
        _total_db   = sum(_db_counts.get(c, 0) for c in _pays_cibles)
        _pct_global = round(_total_db / _total_dump * 100, 2) if _total_dump > 0 else 0
        st.progress(min(_total_db / max(_total_dump, 1), 1.0),
                    text=f"Couverture globale : {_total_db} / {_total_dump} PEP vérifiés ({_pct_global} %)")
    else:
        st.info("Dump absent — lancer `python opensanctions_local.py` pour télécharger.")

except Exception as _ex_dump:
    st.caption(f"Stats dump indisponibles : {_ex_dump}")

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
