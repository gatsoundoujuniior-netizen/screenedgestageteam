"""
api_tracker.py — Suivi de la consommation des APIs
Lit/écrit api_usage.json dans le même répertoire.
"""
import json, os
from datetime import datetime

_DIR        = os.path.dirname(os.path.abspath(__file__))
_USAGE_FILE = os.path.join(_DIR, "api_usage.json")

LIMITES = {
    "groq_1_tokens_jour":        500_000,  # Groq free tier: 500k tokens/day (TPD) par compte
    "groq_2_tokens_jour":        500_000,
    "groq_3_tokens_jour":        500_000,
    "gemini_appels_jour":             20,  # Gemini 2.5-flash free: 20 req/jour
    "serper_appels_mois":          2_500,
    "tavily_appels_jour":          1_000,  # Free=40 | Starter=1000 | Basic=3000
    "opensanctions_appels_mois":   2_000,
}

# Coût d'une vérification complète par API (calibré sur les runs réels)
TAVILY_APPELS_PAR_VERIF  = 12
GROQ_TOKENS_PAR_VERIF    = 15_000   # ~15k tokens/verif (identification + qualification)

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
    """Enregistre une utilisation réussie pour le compte Groq n (1, 2 ou 3)."""
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
    _alerter(f"{cle}_tokens", bloc["tokens"], LIMITES[f"{cle}_tokens_jour"],
             f"tokens Groq-{n} aujourd'hui")


def enregistrer_quota_reel_groq(n: int, utilise: int, limite: int):
    """Enregistre les vrais chiffres TPD extraits du message d'erreur Groq (429).
    Appelé quand Groq renvoie 'Limit X, Used Y' dans son erreur TPD.
    Met à jour api_usage.json pour que le dashboard reflète la vraie consommation."""
    cle   = f"groq_{n}"
    data  = _charger()
    today = datetime.now().strftime("%Y-%m-%d")
    bloc  = data.get(cle, {})
    if bloc.get("date") != today:
        bloc = {"date": today, "tokens": 0, "appels": 0}
    # Mettre à jour avec les vrais tokens rapportés par l'API Groq
    bloc["tokens"]      = max(bloc.get("tokens", 0), utilise)
    bloc["tpd_reel"]    = utilise
    bloc["tpd_limite"]  = limite
    bloc["tpd_ts"]      = datetime.now().strftime("%H:%M")
    data[cle]           = bloc
    _sauver(data)
    _alerter(f"{cle}_tokens", utilise, limite, f"tokens Groq-{n} (TPD réel API)")


def enregistrer_quota_reel_gemini(utilise: int, limite: int):
    """Enregistre les vrais chiffres de quota Gemini depuis l'erreur 429."""
    data  = _charger()
    today = datetime.now().strftime("%Y-%m-%d")
    bloc  = data.get("gemini", {})
    if bloc.get("date") != today:
        bloc = {"date": today, "tokens": 0, "appels": 0}
    bloc["appels"]      = max(bloc.get("appels", 0), utilise)
    bloc["tpd_reel"]    = utilise
    bloc["tpd_limite"]  = limite
    bloc["tpd_ts"]      = datetime.now().strftime("%H:%M")
    data["gemini"]      = bloc
    _sauver(data)
    _alerter("gemini_appels", utilise, limite, "requêtes Gemini aujourd'hui")


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
    """Calcule combien de vérifications restantes aujourd'hui (facteur: min tavily, groq)."""
    data = _charger()

    tav       = data.get("tavily", {})
    t_utilise = tav.get("appels", 0)
    t_limite  = LIMITES["tavily_appels_jour"]
    t_restant = max(0, t_limite - t_utilise)
    verifs_tavily = t_restant // TAVILY_APPELS_PAR_VERIF

    # Groq : prendre le compte avec le PLUS de tokens restants (meilleure capacité dispo)
    g_limite = LIMITES["groq_1_tokens_jour"]  # identique pour les 3 comptes
    g_best_restant = 0
    for n in [1, 2, 3]:
        b = data.get(f"groq_{n}", {})
        used = b.get("tpd_reel", b.get("tokens", 0))
        restant = max(0, g_limite - used)
        g_best_restant = max(g_best_restant, restant)
    verifs_groq = g_best_restant // GROQ_TOKENS_PAR_VERIF

    verifs_max       = min(verifs_tavily, verifs_groq)
    facteur_limitant = "tavily" if verifs_tavily <= verifs_groq else "groq"

    return {
        "verifications_restantes": verifs_max,
        "facteur_limitant":        facteur_limitant,
        "tavily": {
            "utilise": t_utilise,
            "limite":  t_limite,
            "restant": t_restant,
            "verifs":  verifs_tavily,
            "pct":     round(t_utilise / t_limite * 100, 1) if t_limite else 0,
        },
        "groq": {
            "utilise": g_limite - g_best_restant,
            "limite":  g_limite,
            "restant": g_best_restant,
            "verifs":  verifs_groq,
            "pct":     round((g_limite - g_best_restant) / g_limite * 100, 1) if g_limite else 0,
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
        tokens = b.get("tokens", 0)
        # tokens_reel : valeur réelle extraite du message d'erreur TPD (plus fiable)
        tokens_reel = b.get("tpd_reel", tokens)
        limite = LIMITES[f"groq_{n}_tokens_jour"]
        date   = b.get("date", "—")
        tpd_ts = b.get("tpd_ts", "")
        return {
            "label":   f"Groq-{n} (llama-4-scout) — tokens/jour",
            "utilise": tokens_reel,
            "appels":  appels,
            "limite":  limite,
            "pct":     _pct(tokens_reel, limite),
            "periode": date,
            "tpd_ts":  tpd_ts,  # heure du dernier hit TPD
        }

    gem   = data.get("gemini", {})
    serp  = data.get("serper", {})
    tav   = data.get("tavily", {})
    osanc = data.get("opensanctions", {})

    gm_appels     = gem.get("appels", 0)
    gm_appels_reel = gem.get("tpd_reel", gm_appels)  # vrais chiffres depuis erreur API
    s_appels      = serp.get("appels", 0)
    t_appels      = tav.get("appels", 0)
    o_appels      = osanc.get("appels", 0)

    return {
        "groq_1":        _groq_bloc(1),
        "groq_2":        _groq_bloc(2),
        "groq_3":        _groq_bloc(3),
        "gemini": {
            "label":   "Gemini 2.5-flash — req/jour",
            "utilise": gm_appels_reel,
            "appels":  gm_appels,
            "limite":  LIMITES["gemini_appels_jour"],
            "pct":     _pct(gm_appels_reel, LIMITES["gemini_appels_jour"]),
            "periode": gem.get("date", "—"),
            "tpd_ts":  gem.get("tpd_ts", ""),
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
