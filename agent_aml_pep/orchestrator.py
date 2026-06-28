"""
orchestrator.py — Orchestrateur autonome PEP

Lance les tests, détecte les erreurs, diagnostique et corrige automatiquement.

Types d'erreurs gérés :
  QUOTA   — API rate-limit → switch modèle ou outil alternatif
  RESEAU  — SSL/timeout/403 → fallback URL, blacklist domaine
  DATA    — données malformées → fix parsing/conversion
  CODE    — bug Python → analyse LLM + patch fichier

Usage :
  python orchestrator.py                    # 4 cas par défaut
  python orchestrator.py --cas custom       # cas personnalisés
  python orchestrator.py --max-cycles 5     # max 5 cycles correctifs

L'orchestrateur est le seul pilote — aucune intervention humaine requise.
"""

import sys, os, re, json, time, importlib, traceback as tb_module
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(override=True)

# ── Constantes ────────────────────────────────────────────────────────────────────

_DIR = os.path.dirname(os.path.abspath(__file__))
_LOG_DIR = os.path.join(_DIR, "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

_RUNTIME_CFG = os.path.join(_DIR, "orchestrator_runtime.json")

MAX_CYCLES_DEFAUT   = 4
MAX_RETRIES_PAR_CAS = 2
DELAI_ENTRE_CAS     = 15   # secondes

# Modèles Groq — quotas indépendants (100k TPD chacun)
GROQ_MODEL_PRINCIPAL = "llama-3.3-70b-versatile"
GROQ_MODEL_BACKUP    = "llama-3.1-8b-instant"
GROQ_MODEL_MICRO     = "llama-3.1-8b-instant"   # même backup, plus petit contexte

CAS_DEFAUT = [
    ("Macky",    "Sall",       True, "ex_pep", "Ex-PEP récent — quitté avril 2024"),
    ("Roch",     "Kabore",     True, "ex_pep", "Ex-PEP coup d'état jan 2022"),
    ("Alassane", "Ouattara",   True, "actif",  "PEP actif — Président CI depuis 2011"),
    ("Faure",    "Gnassingbe", True, "actif",  "PEP actif — Président TG depuis 2005"),
]

# ── Runtime config (état courant de l'orchestrateur) ─────────────────────────────

def _lire_runtime() -> dict:
    try:
        with open(_RUNTIME_CFG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _ecrire_runtime(cfg: dict):
    with open(_RUNTIME_CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def _runtime_get(key, defaut=None):
    return _lire_runtime().get(key, defaut)

def _runtime_set(key, value):
    cfg = _lire_runtime()
    cfg[key] = value
    _ecrire_runtime(cfg)

# ── Logger ────────────────────────────────────────────────────────────────────────

_TS = datetime.now().strftime("%Y-%m-%d_%H-%M")
_LOG_PATH = os.path.join(_LOG_DIR, f"orchestrator_{_TS}.log")

class _OrchestratorLog:
    def __init__(self, path):
        self._f = open(path, "w", encoding="utf-8", buffering=1)

    def _write(self, level: str, msg: str):
        ts   = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}][{level}] {msg}"
        print(line)
        self._f.write(line + "\n")

    def info(self, msg):  self._write("INFO ", msg)
    def warn(self, msg):  self._write("WARN ", msg)
    def error(self, msg): self._write("ERROR", msg)
    def fix(self, msg):   self._write("FIX  ", msg)
    def sep(self, titre=""):
        self.info("─" * 55 + (f" {titre}" if titre else ""))

    def close(self): self._f.close()

log = _OrchestratorLog(_LOG_PATH)

# ── LLM d'analyse (Claude API > Groq backup) ─────────────────────────────────────

def _llm_analyser(prompt: str) -> str:
    """Appelle le meilleur LLM disponible pour analyser une erreur."""
    # 1. Essayer Claude API (Anthropic)
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=anthropic_key)
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            log.info("  LLM analyse → Claude API (Anthropic)")
            return resp.content[0].text
        except Exception as e:
            log.warn(f"  Claude API indisponible : {e} → fallback Groq")

    # 2. Fallback Groq backup model
    try:
        from langchain_groq import ChatGroq
        model = _runtime_get("groq_model_actif", GROQ_MODEL_BACKUP)
        _llm_b = ChatGroq(model=model, temperature=0)
        resp = _llm_b.invoke(prompt)
        log.info(f"  LLM analyse → Groq {model}")
        return resp.content
    except Exception as e:
        log.error(f"  LLM analyse impossible : {e}")
        return ""

# ── Classification des erreurs ────────────────────────────────────────────────────

def classifier_erreur(erreur_str: str) -> str:
    """Retourne 'QUOTA' | 'RESEAU' | 'DATA' | 'CODE'."""
    e = erreur_str.lower()
    if any(k in e for k in ["429", "ratelimiterror", "rate_limit", "quota", "tokens per day", "tpd"]):
        return "QUOTA"
    if any(k in e for k in ["ssl", "certificate", "connectionerror", "timeout", "httperror", "403", "404",
                              "err_cert", "name_not_resolved", "nodename nor servname"]):
        return "RESEAU"
    if any(k in e for k in ["invalid input syntax", "invalid literal", "date", "type date",
                              "cannot convert", "value error", "valueerror"]):
        return "DATA"
    return "CODE"

# ── HANDLER QUOTA ─────────────────────────────────────────────────────────────────

def handle_quota(erreur_str: str) -> bool:
    """Switch modèle Groq ou désactive l'outil épuisé. Retourne True si fix appliqué."""
    log.fix("QUOTA — Analyse de l'API épuisée…")

    # Groq TPD épuisé
    if "llama-3.3-70b" in erreur_str or "tokens per day" in erreur_str.lower():
        model_actif = _runtime_get("groq_model_actif", GROQ_MODEL_PRINCIPAL)
        if model_actif == GROQ_MODEL_PRINCIPAL:
            log.fix(f"  Groq 70b épuisé → switch vers {GROQ_MODEL_BACKUP}")
            _runtime_set("groq_model_actif", GROQ_MODEL_BACKUP)
            # Patcher le module pep_agent en mémoire
            try:
                import pep_agent
                from langchain_groq import ChatGroq
                pep_agent.llm = ChatGroq(model=GROQ_MODEL_BACKUP, temperature=0.1)
                importlib.reload(pep_agent)
                log.fix(f"  pep_agent.llm → {GROQ_MODEL_BACKUP} ✅")
                return True
            except Exception as e:
                log.error(f"  Échec reload pep_agent : {e}")
                return False
        else:
            log.warn("  Groq backup aussi épuisé → attente 30 min")
            for i in range(30):
                log.info(f"  Attente quota Groq… {30-i} min restantes")
                time.sleep(60)
            # Réinitialiser vers le modèle principal (quota rechargé)
            _runtime_set("groq_model_actif", GROQ_MODEL_PRINCIPAL)
            try:
                import pep_agent
                from langchain_groq import ChatGroq
                pep_agent.llm = ChatGroq(model=GROQ_MODEL_PRINCIPAL, temperature=0.1)
                log.fix(f"  Reset pep_agent.llm → {GROQ_MODEL_PRINCIPAL} après attente ✅")
                return True
            except Exception as e:
                log.error(f"  Échec reset : {e}")
                return False

    # Serper épuisé
    if "serper" in erreur_str.lower():
        log.fix("  Serper épuisé → désactivation Serper (Tavily seul)")
        _runtime_set("serper_disabled", True)
        _patcher_env("SERPER_DISABLED", "true")
        return True

    # Tavily épuisé
    if "tavily" in erreur_str.lower():
        log.fix("  Tavily épuisé → Serper + OpenSanctions seulement")
        _runtime_set("tavily_disabled", True)
        return True

    # OpenSanctions 429
    if "opensanctions" in erreur_str.lower():
        log.fix("  OpenSanctions 429 → augmentation du throttle à 60s")
        try:
            import search_tools
            search_tools._OPENSANCTIONS_MIN_INTERVAL = 60.0
            log.fix("  search_tools._OPENSANCTIONS_MIN_INTERVAL = 60s ✅")
            return True
        except Exception as e:
            log.error(f"  Échec patch throttle : {e}")
            return False

    log.warn("  QUOTA — API inconnue, attente 60s")
    time.sleep(60)
    return True

# ── HANDLER RESEAU ────────────────────────────────────────────────────────────────

_RESEAU_BLACKLIST_FILE = os.path.join(_DIR, "network_blacklist.json")

def _lire_blacklist() -> list:
    try:
        with open(_RESEAU_BLACKLIST_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _ajouter_blacklist(domaine: str):
    bl = _lire_blacklist()
    if domaine not in bl:
        bl.append(domaine)
        with open(_RESEAU_BLACKLIST_FILE, "w", encoding="utf-8") as f:
            json.dump(bl, f, ensure_ascii=False, indent=2)
        log.fix(f"  Domaine ajouté à la blacklist réseau : {domaine}")

def handle_reseau(erreur_str: str) -> bool:
    """Identifie le domaine problématique et applique le fallback."""
    log.fix("RESEAU — Analyse de l'erreur réseau…")

    # Extraire l'URL ou domaine de l'erreur
    url_match = re.search(r'https?://([^\s/\'"]+)', erreur_str)
    domaine = url_match.group(1) if url_match else None

    if not domaine:
        log.warn("  URL non extraite de l'erreur — skip")
        return False

    log.fix(f"  Domaine incriminé : {domaine}")

    # SSL / cert expiré → essayer www prefix ou sans www
    if any(k in erreur_str.lower() for k in ["ssl", "certificate", "cert"]):
        if domaine.startswith("www."):
            domaine_sans_www = domaine[4:]
            log.fix(f"  SSL → test sans www : {domaine_sans_www}")
        else:
            domaine_avec_www = f"www.{domaine}"
            log.fix(f"  SSL → test avec www : {domaine_avec_www}")
        # Ajouter aux domaines sans vérif SSL dans search_tools
        try:
            import search_tools
            if not hasattr(search_tools, "_SSL_IGNORE"):
                search_tools._SSL_IGNORE = set()
            search_tools._SSL_IGNORE.add(domaine)
            log.fix(f"  {domaine} ajouté à _SSL_IGNORE ✅")
            return True
        except Exception as e:
            log.error(f"  Patch SSL ignore : {e}")

    # Timeout ou 403 → blacklister le domaine
    if any(k in erreur_str.lower() for k in ["timeout", "403", "connectionerror"]):
        _ajouter_blacklist(domaine)
        try:
            import search_tools
            if hasattr(search_tools, "DOMAINES_OFFICIELS_PAR_PAYS"):
                for pays, urls in search_tools.DOMAINES_OFFICIELS_PAR_PAYS.items():
                    search_tools.DOMAINES_OFFICIELS_PAR_PAYS[pays] = [
                        u for u in urls if domaine not in u
                    ]
            log.fix(f"  {domaine} retiré de DOMAINES_OFFICIELS_PAR_PAYS ✅")
            return True
        except Exception as e:
            log.error(f"  Patch blacklist : {e}")
            return False

    return False

# ── HANDLER DATA ──────────────────────────────────────────────────────────────────

def handle_data(erreur_str: str, contexte: str = "") -> bool:
    """Corrige les erreurs de parsing/conversion de données."""
    log.fix("DATA — Analyse de l'erreur de données…")

    # Erreur de date PostgreSQL
    date_match = re.search(r'invalid input syntax for type date:\s*"([^"]+)"', erreur_str)
    if date_match:
        valeur_bad = date_match.group(1)
        log.fix(f"  Date invalide détectée : '{valeur_bad}'")

        # Générer un fix ciblé via LLM
        prompt = f"""Tu es expert Python. La fonction convertir_date() dans pep_agent.py
échoue sur la valeur : "{valeur_bad}"

L'erreur PostgreSQL est : {erreur_str[:300]}

Analyse le format de cette date et génère le code Python minimal pour la gérer.
Réponds UNIQUEMENT en JSON :
{{
  "format_detecte": "description du format",
  "regex_pattern": "pattern Python pour matcher ce format",
  "conversion_code": "code Python qui convertit la valeur en YYYY-MM-DD",
  "exemple": "exemple de sortie attendue"
}}"""
        reponse = _llm_analyser(prompt)
        try:
            d = json.loads(reponse[reponse.find("{"):reponse.rfind("}")+1])
            pattern   = d.get("regex_pattern", "")
            conv_code = d.get("conversion_code", "")
            fmt_det   = d.get("format_detecte", "")
            log.fix(f"  Format détecté : {fmt_det}")
            log.fix(f"  Pattern : {pattern}")

            if pattern and conv_code:
                # Ajouter le cas dans convertir_date()
                _ajouter_cas_convertir_date(valeur_bad, pattern, conv_code, fmt_det)
                return True
        except Exception as e:
            log.error(f"  Parse réponse LLM : {e}")

    # Erreur de conversion int/float
    if "invalid literal for int" in erreur_str or "cannot convert" in erreur_str:
        log.fix("  Erreur conversion numérique → fix COALESCE dans le code")
        val_match = re.search(r"literal '([^']+)'", erreur_str)
        if val_match:
            log.fix(f"  Valeur incriminée : {val_match.group(1)}")
        return _patcher_fichier_data(erreur_str)

    return False


def _ajouter_cas_convertir_date(valeur_bad: str, pattern: str, conv_code: str, fmt_det: str):
    """Insère un nouveau cas dans convertir_date() dans pep_agent.py."""
    fichier = os.path.join(_DIR, "pep_agent.py")
    with open(fichier, encoding="utf-8") as f:
        contenu = f.read()

    # Trouver l'ancre d'insertion (avant le fallback "Année seule")
    ancre = "    # Année seule dans un texte plus long"
    if ancre not in contenu:
        log.warn("  Ancre convertir_date non trouvée — skip patch")
        return

    bloc_nouveau = f"""    # Format auto-détecté : {fmt_det}
    if re.search(r'{pattern}', s, re.IGNORECASE):
        try:
            {conv_code}
        except Exception:
            pass
"""
    nouveau_contenu = contenu.replace(ancre, bloc_nouveau + "\n" + ancre)
    with open(fichier, "w", encoding="utf-8") as f:
        f.write(nouveau_contenu)

    log.fix(f"  convertir_date() enrichie pour '{valeur_bad}' ✅")
    # Recharger le module
    try:
        import pep_agent
        importlib.reload(pep_agent)
        log.fix("  pep_agent rechargé ✅")
    except Exception as e:
        log.warn(f"  Reload pep_agent : {e}")


def _patcher_fichier_data(erreur_str: str) -> bool:
    """Fix générique pour erreur de données via LLM."""
    fichier_match = re.search(r'File "([^"]+\.py)"', erreur_str)
    fichier = fichier_match.group(1) if fichier_match else None
    if not fichier or not os.path.exists(fichier):
        return False

    prompt = f"""Erreur de données Python :
{erreur_str[:500]}

Génère un fix minimal. Réponds UNIQUEMENT en JSON :
{{
  "diagnostic": "cause en une phrase",
  "old_code": "code exact à remplacer (copier/coller)",
  "new_code": "code corrigé",
  "fichier": "{os.path.basename(fichier)}"
}}"""
    reponse = _llm_analyser(prompt)
    return _appliquer_patch_llm(reponse, fichier)

# ── HANDLER CODE ──────────────────────────────────────────────────────────────────

def handle_code(erreur_str: str, cas_contexte: str = "") -> bool:
    """Analyse le traceback Python via LLM et applique le patch."""
    log.fix("CODE — Analyse du bug Python via LLM…")

    # Extraire fichier + numéro de ligne du traceback
    fichier_match = re.search(r'File "([^"]+\.py)", line (\d+)', erreur_str)
    if not fichier_match:
        log.warn("  Traceback sans fichier identifiable — analyse générique")
        fichier_path = None
        code_section = ""
    else:
        fichier_path = fichier_match.group(1)
        ligne_num    = int(fichier_match.group(2))
        code_section = _extraire_section_code(fichier_path, ligne_num, contexte=20)

    fichier_nom = os.path.basename(fichier_path) if fichier_path else "inconnu"

    prompt = f"""Tu es expert Python. Analyse cette erreur et génère un patch.

TRACEBACK COMPLET :
{erreur_str[:1500]}

CODE AUTOUR DE L'ERREUR ({fichier_nom} ± 20 lignes) :
{code_section}

CONTEXTE CAS DE TEST : {cas_contexte}

Réponds UNIQUEMENT en JSON valide (pas de markdown) :
{{
  "diagnostic": "cause racine de l'erreur en une phrase",
  "type_erreur": "logique | type | import | index | attribut | autre",
  "fichier": "nom_fichier.py",
  "old_code": "bloc de code EXACT à remplacer (plusieurs lignes si nécessaire)",
  "new_code": "bloc de code corrigé",
  "explication": "pourquoi ce fix résout le problème"
}}"""

    reponse = _llm_analyser(prompt)
    if not reponse:
        log.error("  LLM n'a pas répondu")
        return False

    # Parser la réponse JSON
    try:
        start = reponse.find("{")
        end   = reponse.rfind("}") + 1
        d = json.loads(reponse[start:end])
    except Exception as e:
        log.error(f"  JSON invalide de LLM : {e}")
        log.error(f"  Réponse brute : {reponse[:300]}")
        return False

    diagnostic  = d.get("diagnostic", "?")
    fichier_cib = d.get("fichier", fichier_nom)
    old_code    = d.get("old_code", "")
    new_code    = d.get("new_code", "")
    explication = d.get("explication", "")

    log.fix(f"  Diagnostic : {diagnostic}")
    log.fix(f"  Fix → {fichier_cib}")
    log.fix(f"  Explication : {explication}")

    if not old_code or not new_code or old_code == new_code:
        log.warn("  Patch vide ou identique — abandon")
        return False

    fichier_complet = os.path.join(_DIR, fichier_cib)
    if not os.path.exists(fichier_complet) and fichier_path:
        fichier_complet = fichier_path

    return _appliquer_patch_direct(fichier_complet, old_code, new_code)

# ── Utilitaires de patch ──────────────────────────────────────────────────────────

def _extraire_section_code(fichier: str, ligne: int, contexte: int = 20) -> str:
    try:
        with open(fichier, encoding="utf-8") as f:
            lignes = f.readlines()
        debut = max(0, ligne - contexte - 1)
        fin   = min(len(lignes), ligne + contexte)
        return "".join(f"{debut+i+1:4d}│ {l}" for i, l in enumerate(lignes[debut:fin]))
    except Exception:
        return ""


def _appliquer_patch_direct(fichier: str, old_code: str, new_code: str) -> bool:
    """Remplace old_code par new_code dans le fichier."""
    try:
        with open(fichier, encoding="utf-8") as f:
            contenu = f.read()

        if old_code not in contenu:
            log.warn(f"  old_code introuvable dans {os.path.basename(fichier)} — tentative normalisation")
            # Normaliser les espaces
            old_norm = re.sub(r'[ \t]+', ' ', old_code.strip())
            # Chercher une correspondance approximative
            lignes_f = contenu.splitlines()
            old_lignes = old_code.strip().splitlines()
            if len(old_lignes) == 1:
                match_l = [l for l in lignes_f if re.sub(r'[ \t]+', ' ', l.strip()) == old_norm]
                if match_l:
                    new_contenu = contenu.replace(match_l[0], match_l[0].replace(old_code.strip(), new_code.strip()), 1)
                    with open(fichier, "w", encoding="utf-8") as f:
                        f.write(new_contenu)
                    log.fix(f"  Patch approximatif appliqué ✅ ({os.path.basename(fichier)})")
                    _recharger_module(fichier)
                    return True
            log.error("  Patch impossible — code source introuvable")
            return False

        nouveau_contenu = contenu.replace(old_code, new_code, 1)
        with open(fichier, "w", encoding="utf-8") as f:
            f.write(nouveau_contenu)

        log.fix(f"  Patch appliqué ✅ ({os.path.basename(fichier)})")
        _recharger_module(fichier)
        return True

    except Exception as e:
        log.error(f"  Erreur patch : {e}")
        return False


def _appliquer_patch_llm(reponse_json: str, fichier_hint: str = "") -> bool:
    try:
        start = reponse_json.find("{")
        end   = reponse_json.rfind("}") + 1
        d = json.loads(reponse_json[start:end])
    except Exception:
        return False

    old_code = d.get("old_code", "")
    new_code = d.get("new_code", "")
    fichier  = d.get("fichier", "")

    if not old_code or not new_code:
        return False

    fichier_complet = os.path.join(_DIR, fichier) if fichier else fichier_hint
    if not os.path.exists(fichier_complet):
        fichier_complet = fichier_hint

    log.fix(f"  Diagnostic : {d.get('diagnostic', '?')}")
    return _appliquer_patch_direct(fichier_complet, old_code, new_code)


def _recharger_module(fichier: str):
    nom = os.path.basename(fichier).replace(".py", "")
    try:
        if nom in sys.modules:
            importlib.reload(sys.modules[nom])
            log.fix(f"  Module {nom} rechargé")
    except Exception as e:
        log.warn(f"  Reload {nom} : {e}")


def _patcher_env(key: str, value: str):
    env_path = os.path.join(_DIR, ".env")
    try:
        with open(env_path, encoding="utf-8") as f:
            lignes = f.readlines()
        nouvelle = [l for l in lignes if not l.startswith(f"{key}=")]
        nouvelle.append(f"{key}={value}\n")
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(nouvelle)
    except Exception as e:
        log.warn(f"  Patch .env {key} : {e}")

# ── Évaluation d'un résultat ──────────────────────────────────────────────────────

def evaluer(rapport, attendu_pep: bool, attendu_statut: str) -> tuple[bool, str, str]:
    if isinstance(rapport, dict):
        erreur = rapport.get("erreur", "")
        return False, erreur, classifier_erreur(erreur)

    if attendu_pep and not rapport.est_pep:
        code = getattr(rapport, "code_iso", "") or ""
        if code == "XX":
            raison = "Pays non identifié (XX)"
        else:
            raison = f"Non-PEP retourné (code={code})"
        return False, raison, "CODE"

    if not attendu_pep and rapport.est_pep:
        return False, f"Faux positif : {rapport.fonction}", "CODE"

    if attendu_statut:
        statut = getattr(rapport, "statut_mandat", "") or ""
        if statut != attendu_statut:
            return False, f"Statut attendu={attendu_statut} obtenu={statut}", "CODE"

    stockage = getattr(rapport, "stockage_status", "") or getattr(rapport, "storage_status", "") or ""
    if "Erreur" in stockage:
        return False, stockage, classifier_erreur(stockage)

    return True, "", ""

# ── Exécution d'un cas ────────────────────────────────────────────────────────────

def executer_cas(prenom: str, nom: str, attendu_pep: bool,
                 attendu_statut: str, description: str) -> tuple[bool, dict]:
    """Lance verifier_pep() et retourne (ok, bilan)."""
    try:
        import pep_agent
        rapport = pep_agent.verifier_pep(prenom, nom)
    except Exception as exc:
        erreur = tb_module.format_exc()
        rapport = {"erreur": erreur, "prenom": prenom, "nom": nom}
        log.error(f"  Exception : {str(exc)[:120]}")

    ok, raison, categorie = evaluer(rapport, attendu_pep, attendu_statut)
    return ok, {
        "prenom": prenom, "nom": nom,
        "description": description,
        "ok": ok,
        "raison": raison,
        "categorie": categorie,
        "rapport": rapport,
        "erreur_str": raison if not ok else "",
    }

# ── Boucle principale ─────────────────────────────────────────────────────────────

def orchestrer(cas: list, max_cycles: int = MAX_CYCLES_DEFAUT):
    log.sep()
    log.info(f"ORCHESTRATEUR — {len(cas)} cas | max {max_cycles} cycles correctifs")
    log.info(f"Log : {_LOG_PATH}")
    log.sep()

    # Réinitialiser runtime config
    _ecrire_runtime({"groq_model_actif": GROQ_MODEL_PRINCIPAL, "cycle": 0})

    cas_en_attente = list(cas)  # tous les cas à traiter
    cas_passes     = []         # cas validés
    historique_fix = []         # trace des corrections appliquées

    for cycle in range(1, max_cycles + 1):
        log.sep(f"CYCLE {cycle}/{max_cycles}")
        _runtime_set("cycle", cycle)

        if not cas_en_attente:
            break

        nouveaux_echecs = []

        for i, (prenom, nom, attendu_pep, attendu_statut, description) in enumerate(cas_en_attente):
            if i > 0:
                time.sleep(DELAI_ENTRE_CAS)

            log.sep(f"{prenom} {nom}")
            log.info(f"Description : {description}")

            ok, bilan = executer_cas(prenom, nom, attendu_pep, attendu_statut, description)

            if ok:
                log.info(f"  PASS ✅")
                cas_passes.append(bilan)
            else:
                log.warn(f"  FAIL [{bilan['categorie']}] : {bilan['raison'][:100]}")
                erreur_str = bilan["erreur_str"] or bilan["raison"]

                # Appliquer le fix approprié
                fix_ok = False
                cat = bilan["categorie"]

                if cat == "QUOTA":
                    fix_ok = handle_quota(erreur_str)
                elif cat == "RESEAU":
                    fix_ok = handle_reseau(erreur_str)
                elif cat == "DATA":
                    fix_ok = handle_data(erreur_str, f"{prenom} {nom}")
                else:  # CODE
                    fix_ok = handle_code(erreur_str, f"{prenom} {nom} — {description}")

                historique_fix.append({
                    "cycle": cycle, "cas": f"{prenom} {nom}",
                    "categorie": cat, "fix_applique": fix_ok,
                    "raison": bilan["raison"][:100],
                })

                if fix_ok:
                    log.fix(f"  Fix appliqué — {prenom} {nom} re-programmé pour cycle {cycle+1}")
                else:
                    log.error(f"  Aucun fix trouvé pour {prenom} {nom}")

                # Toujours remettre en attente pour retester après fix
                nouveaux_echecs.append((prenom, nom, attendu_pep, attendu_statut, description))

        cas_en_attente = nouveaux_echecs

        if not cas_en_attente:
            log.info(f"  Tous les cas passent — arrêt à cycle {cycle}")
            break

        if cycle < max_cycles:
            log.info(f"  {len(cas_en_attente)} cas encore en échec — cycle {cycle+1} dans 5s…")
            time.sleep(5)

    # ── Rapport final ──────────────────────────────────────────────────────────────
    log.sep("RAPPORT FINAL")
    total  = len(cas)
    nb_ok  = len(cas_passes)
    nb_ko  = len(cas_en_attente)

    log.info(f"Résultat : {nb_ok}/{total} PASS | {nb_ko}/{total} FAIL")

    log.info("Cas passés :")
    for b in cas_passes:
        r = b.get("rapport")
        src = getattr(r, "source_url", "?") if r and not isinstance(r, dict) else "?"
        log.info(f"  ✅ {b['prenom']} {b['nom']} | {src[:60]}")

    if cas_en_attente:
        log.warn("Cas toujours en échec :")
        for (p, n, *_) in cas_en_attente:
            log.warn(f"  ❌ {p} {n}")

    log.info(f"Corrections appliquées : {len(historique_fix)}")
    for h in historique_fix:
        statut = "✅" if h["fix_applique"] else "❌"
        log.info(f"  {statut} Cycle {h['cycle']} | [{h['categorie']}] {h['cas']} : {h['raison'][:60]}")

    # Sauvegarder rapport JSON
    rapport_path = os.path.join(_LOG_DIR, f"orchestrator_{_TS}_rapport.json")
    with open(rapport_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": _TS,
            "total": total, "passes": nb_ok, "echecs": nb_ko,
            "historique_corrections": historique_fix,
        }, f, ensure_ascii=False, indent=2)
    log.info(f"Rapport JSON → {rapport_path}")
    log.close()

    return nb_ko == 0

# ── Entrée principale ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Orchestrateur autonome PEP")
    parser.add_argument("--max-cycles", type=int, default=MAX_CYCLES_DEFAUT,
                        help=f"Cycles correctifs max (défaut: {MAX_CYCLES_DEFAUT})")
    parser.add_argument("--cas", choices=["defaut", "custom"], default="defaut")
    args = parser.parse_args()

    liste_cas = CAS_DEFAUT if args.cas == "defaut" else []
    succes = orchestrer(liste_cas, max_cycles=args.max_cycles)
    sys.exit(0 if succes else 1)
