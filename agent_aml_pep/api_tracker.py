"""
api_tracker.py — Suivi de la consommation des APIs
Lit/écrit api_usage.json dans le même répertoire.
"""
import json, os
from datetime import datetime

_DIR        = os.path.dirname(os.path.abspath(__file__))
_USAGE_FILE = os.path.join(_DIR, "api_usage.json")

LIMITES = {
    "groq_1_appels_jour":          1_000,
    "groq_2_appels_jour":          1_000,
    "groq_3_appels_jour":          1_000,
    "gemini_tokens_jour":      1_000_000,
    "serper_appels_mois":          2_500,
    "tavily_appels_jour":          1_000,   # Adapter selon ton plan : Free=40 | Starter=1000 | Basic=3000
    "opensanctions_appels_mois":   2_000,
}

# Coût d'une vérification complète par API (calibré sur les runs réels)
TAVILY_APPELS_PAR_VERIF = 12
GROQ_APPELS_PAR_VERIF   = 10

SEUIL_ALERTE   = 80
SEUIL_CRITIQUE = 95


def _charger() -> dict:
    try:
        with open(_USAGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _sauver(data: dict):
    try:
        with open(_USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _tracker_groq_n(n: int, tokens_entree: int = 0, tokens_sortie: int = 0):
    """Enregistre une utilisation pour le compte Groq n (1, 2 ou 3)."""
    cle   = f"groq_{n}"
    data  = _charger()
    today = datetime.now().strftime("%Y-%m-%d")
    bloc  = data.get(cle, {})
    if bloc.get("date") != today:
        bloc = {"date": today, "tokens": 0, "appels": 0}
    bloc["tokens"] += tokens_entree + tokens_sortie
    bloc["appels"]  = bloc.get("appels", 0) + 1
    data[cle]       = bloc
    _sauver(data)
    _alerter(f"{cle}_appels", bloc["appels"], LIMITES[f"{cle}_appels_jour"],
             f"requêtes Groq-{n} aujourd'hui")


def tracker_groq_1(tokens_entree: int = 0, tokens_sortie: int = 0):
    _tracker_groq_n(1, tokens_entree, tokens_sortie)

def tracker_groq_2(tokens_entree: int = 0, tokens_sortie: int = 0):
    _tracker_groq_n(2, tokens_entree, tokens_sortie)

def tracker_groq_3(tokens_entree: int = 0, tokens_sortie: int = 0):
    _tracker_groq_n(3, tokens_entree, tokens_sortie)

# Alias rétro-compat (anciens appels tracker_groq → compte 1)
def tracker_groq(tokens_entree: int = 0, tokens_sortie: int = 0):
    tracker_groq_1(tokens_entree, tokens_sortie)


def tracker_gemini(tokens_entree: int = 0, tokens_sortie: int = 0):
    data  = _charger()
    today = datetime.now().strftime("%Y-%m-%d")
    bloc  = data.get("gemini", {})
    if bloc.get("date") != today:
        bloc = {"date": today, "tokens": 0, "appels": 0}
    bloc["tokens"] += tokens_entree + tokens_sortie
    bloc["appels"]  = bloc.get("appels", 0) + 1
    data["gemini"]  = bloc
    _sauver(data)
    _alerter("gemini", bloc["tokens"], LIMITES["gemini_tokens_jour"], "tokens Gemini aujourd'hui")


def tracker_serper(nb_appels: int = 1):
    data = _charger()
    mois = datetime.now().strftime("%Y-%m")
    bloc = data.get("serper", {})
    if bloc.get("mois") != mois:
        bloc = {"mois": mois, "appels": 0}
    bloc["appels"] = bloc.get("appels", 0) + nb_appels
    data["serper"] = bloc
    _sauver(data)
    _alerter("serper", bloc["appels"], LIMITES["serper_appels_mois"], "appels Serper ce mois")


def tracker_tavily(nb_appels: int = 1):
    data  = _charger()
    today = datetime.now().strftime("%Y-%m-%d")
    bloc  = data.get("tavily", {})
    if bloc.get("date") != today:
        bloc = {"date": today, "appels": 0}
    bloc["appels"] = bloc.get("appels", 0) + nb_appels
    data["tavily"] = bloc
    _sauver(data)
    _alerter("tavily", bloc["appels"], LIMITES["tavily_appels_jour"], "appels Tavily aujourd'hui")


def tracker_opensanctions(nb_appels: int = 1):
    data = _charger()
    mois = datetime.now().strftime("%Y-%m")
    bloc = data.get("opensanctions", {})
    if bloc.get("mois") != mois:
        bloc = {"mois": mois, "appels": 0}
    bloc["appels"]        = bloc.get("appels", 0) + nb_appels
    data["opensanctions"] = bloc
    _sauver(data)
    _alerter("opensanctions", bloc["appels"], LIMITES["opensanctions_appels_mois"], "appels OpenSanctions ce mois")


def _alerter(api: str, utilise: int, limite: int, label: str):
    if not limite:
        return
    pct = utilise / limite * 100
    if pct >= 100:
        print(f"  🔴 QUOTA ÉPUISÉ [{api.upper()}] {utilise:,} / {limite:,} {label} — appels ignorés jusqu'à la prochaine période")
    elif pct >= SEUIL_CRITIQUE:
        print(f"  ⛔ QUOTA CRITIQUE [{api.upper()}] {utilise:,} / {limite:,} {label} ({pct:.1f}%)")
    elif pct >= SEUIL_ALERTE:
        print(f"  ⚠️  QUOTA ALERTE [{api.upper()}] {utilise:,} / {limite:,} {label} ({pct:.1f}%)")


def quota_restant_verifications() -> dict:
    """
    Calcule combien de vérifications PEP complètes peuvent encore être lancées aujourd'hui.
    Le facteur limitant est le min(tavily, groq).
    """
    data  = _charger()

    tav       = data.get("tavily", {})
    t_utilise = tav.get("appels", 0)
    t_limite  = LIMITES["tavily_appels_jour"]
    t_restant = max(0, t_limite - t_utilise)
    verifs_tavily = t_restant // TAVILY_APPELS_PAR_VERIF

    g1        = data.get("groq_1", {})
    g_utilise = g1.get("appels", 0)
    g_limite  = LIMITES["groq_1_appels_jour"]
    g_restant = max(0, g_limite - g_utilise)
    verifs_groq = g_restant // GROQ_APPELS_PAR_VERIF

    verifs_max      = min(verifs_tavily, verifs_groq)
    facteur_limitant = "tavily" if verifs_tavily <= verifs_groq else "groq"

    return {
        "verifications_restantes": verifs_max,
        "facteur_limitant":        facteur_limitant,
        "tavily": {
            "utilise":  t_utilise,
            "limite":   t_limite,
            "restant":  t_restant,
            "verifs":   verifs_tavily,
            "pct":      round(t_utilise / t_limite * 100, 1) if t_limite else 0,
        },
        "groq": {
            "utilise":  g_utilise,
            "limite":   g_limite,
            "restant":  g_restant,
            "verifs":   verifs_groq,
            "pct":      round(g_utilise / g_limite * 100, 1) if g_limite else 0,
        },
    }


def lire_consommation() -> dict:
    """Retourne la consommation réelle depuis api_usage.json sans filtrage par date."""
    data = _charger()

    def _pct(used, limit):
        return round(used / limit * 100, 1) if limit else 0

    def _groq_bloc(n):
        b      = data.get(f"groq_{n}", {})
        appels = b.get("appels", 0)
        limite = LIMITES[f"groq_{n}_appels_jour"]
        date   = b.get("date", "—")
        return {
            "label":   f"Groq-{n} (llama-4-scout) — req/jour",
            "utilise": appels,
            "appels":  appels,
            "limite":  limite,
            "pct":     _pct(appels, limite),
            "periode": date,
        }

    gem   = data.get("gemini", {})
    serp  = data.get("serper", {})
    tav   = data.get("tavily", {})
    osanc = data.get("opensanctions", {})

    gm_tokens = gem.get("tokens", 0)
    gm_appels = gem.get("appels", 0)
    s_appels  = serp.get("appels", 0)
    t_appels  = tav.get("appels", 0)
    o_appels  = osanc.get("appels", 0)

    return {
        "groq_1":        _groq_bloc(1),
        "groq_2":        _groq_bloc(2),
        "groq_3":        _groq_bloc(3),
        "gemini": {
            "label":   "Gemini (fallback) — tokens/jour",
            "utilise": gm_tokens,
            "appels":  gm_appels,
            "limite":  LIMITES["gemini_tokens_jour"],
            "pct":     _pct(gm_tokens, LIMITES["gemini_tokens_jour"]),
            "periode": gem.get("date", "—"),
        },
        "serper": {
            "label":   "Serper — requêtes/mois",
            "utilise": s_appels,
            "appels":  s_appels,
            "limite":  LIMITES["serper_appels_mois"],
            "pct":     _pct(s_appels, LIMITES["serper_appels_mois"]),
            "periode": serp.get("mois", "—"),
        },
        "tavily": {
            "label":   "Tavily — requêtes/jour",
            "utilise": t_appels,
            "appels":  t_appels,
            "limite":  LIMITES["tavily_appels_jour"],
            "pct":     _pct(t_appels, LIMITES["tavily_appels_jour"]),
            "periode": tav.get("date", "—"),
        },
        "opensanctions": {
            "label":   "OpenSanctions — requêtes/mois",
            "utilise": o_appels,
            "appels":  o_appels,
            "limite":  LIMITES["opensanctions_appels_mois"],
            "pct":     _pct(o_appels, LIMITES["opensanctions_appels_mois"]),
            "periode": osanc.get("mois", "—"),
        },
    }
