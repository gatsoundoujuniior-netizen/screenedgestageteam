"""
test_loop.py — Boucle de test supervisée avec retry automatique

Lance les cas de test, évalue les résultats, et réessaie les cas en échec
sans intervention manuelle.

Usage :
    python test_loop.py                  # 4 cas par défaut
    python test_loop.py --max-retries 5  # jusqu'à 5 tentatives par cas
    python test_loop.py --cas custom     # cas définis dans CAS_CUSTOM

Critères de succès pour un cas :
    - est_pep == attendu_pep
    - code_iso != "XX"
    - statut_mandat == attendu_statut (si spécifié)
    - stockage_status ne contient pas "Erreur"
    - source_url != "non disponible" (warning, pas bloquant)
"""

import sys, os, time, argparse, json
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Configuration des cas de test ────────────────────────────────────────────────

CAS_DEFAUT = [
    # (prenom, nom, attendu_pep, attendu_statut, description)
    ("Macky",    "Sall",        True,  "ex_pep", "Ex-PEP récent — quitté avril 2024"),
    ("Roch",     "Kabore",      True,  "ex_pep", "Ex-PEP coup d'état jan 2022"),
    ("Alassane", "Ouattara",    True,  "actif",  "PEP actif — Président CI depuis 2011"),
    ("Faure",    "Gnassingbe",  True,  "actif",  "PEP actif — Président TG depuis 2005"),
]

CAS_CUSTOM = [
    # Ajouter ici des cas supplémentaires si besoin
]

# ── Délais de retry ───────────────────────────────────────────────────────────────

DELAI_RETRY_NORMAL = 30    # secondes — erreur générique
DELAI_RETRY_XX     = 15    # secondes — pays non identifié (souvent transitoire)
DELAI_RETRY_GROQ   = 120   # secondes — quota Groq (429)
DELAI_RETRY_DB     = 10    # secondes — erreur base de données

MAX_RETRIES_DEFAUT = 3

# ── Logger ────────────────────────────────────────────────────────────────────────

_LOG_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE = os.path.join(_LOG_DIR, f"test_loop_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.log")

class _Logger:
    def __init__(self, path):
        self._f = open(path, "w", encoding="utf-8", buffering=1)

    def log(self, msg: str, level: str = "INFO"):
        ts  = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] [{level}] {msg}"
        print(line)
        self._f.write(line + "\n")

    def close(self):
        self._f.close()

log = _Logger(_LOG_FILE)

# ── Évaluation d'un résultat ──────────────────────────────────────────────────────

def evaluer(rapport, attendu_pep: bool, attendu_statut: str | None) -> tuple[bool, str, str]:
    """
    Retourne (ok, raison_echec, categorie_echec).
    categorie_echec : "groq" | "xx" | "statut" | "stockage" | "source" | ""
    """
    # Erreur Python → rapport est un dict avec clé "erreur"
    if isinstance(rapport, dict):
        erreur = rapport.get("erreur", "")
        if "429" in erreur or "RateLimitError" in erreur or "rate_limit" in erreur.lower():
            return False, f"Quota Groq épuisé : {erreur[:120]}", "groq"
        return False, f"Exception : {erreur[:120]}", "exception"

    # PEP attendu mais Non-PEP retourné
    if attendu_pep and not rapport.est_pep:
        code = getattr(rapport, "code_iso", "") or ""
        if code == "XX":
            return False, "Pays non identifié (XX) → identification échouée", "xx"
        return False, f"Non-PEP retourné (code={code})", "statut"

    # Non-PEP attendu mais PEP retourné
    if not attendu_pep and rapport.est_pep:
        return False, f"Faux positif PEP : {rapport.fonction}", "statut"

    # Statut mandat incorrect
    if attendu_statut and attendu_pep:
        statut = getattr(rapport, "statut_mandat", "") or ""
        if statut != attendu_statut:
            return False, f"Statut attendu={attendu_statut} obtenu={statut}", "statut"

    # Erreur de stockage
    stockage = getattr(rapport, "stockage_status", "") or getattr(rapport, "storage_status", "") or ""
    if "Erreur" in stockage:
        return False, f"Erreur stockage : {stockage[:100]}", "stockage"

    # Source manquante (warning non bloquant)
    src = getattr(rapport, "source_url", "") or ""
    if rapport.est_pep and src in ("non disponible", ""):
        log.log(f"  ⚠️  Source manquante pour {rapport.prenom} {rapport.nom} — cas validé quand même", "WARN")

    return True, "", ""


# ── Délai selon catégorie d'échec ─────────────────────────────────────────────────

def delai_pour(categorie: str) -> int:
    return {
        "groq":      DELAI_RETRY_GROQ,
        "xx":        DELAI_RETRY_XX,
        "statut":    DELAI_RETRY_NORMAL,
        "stockage":  DELAI_RETRY_DB,
        "exception": DELAI_RETRY_NORMAL,
    }.get(categorie, DELAI_RETRY_NORMAL)


# ── Exécution d'un cas avec retry ─────────────────────────────────────────────────

def executer_cas(prenom, nom, attendu_pep, attendu_statut, description, max_retries) -> dict:
    """Lance le pipeline pour un cas, réessaie si échec. Retourne le bilan du cas."""
    from pep_agent import verifier_pep

    log.log(f"{'─'*55}")
    log.log(f"CAS : {prenom} {nom} — {description}")

    for tentative in range(1, max_retries + 1):
        if tentative > 1:
            log.log(f"  Tentative {tentative}/{max_retries}…")

        try:
            rapport = verifier_pep(prenom, nom)
        except Exception as exc:
            erreur_str = str(exc)
            rapport = {"erreur": erreur_str, "prenom": prenom, "nom": nom}
            log.log(f"  Exception : {erreur_str[:120]}", "ERROR")

        ok, raison, categorie = evaluer(rapport, attendu_pep, attendu_statut)

        if ok:
            src = getattr(rapport, "source_url", "?") or "?"
            st  = getattr(rapport, "statut_mandat", "?") or "?"
            log.log(f"  PASS — statut={st} | source={src[:60]}")
            return {"cas": f"{prenom} {nom}", "ok": True, "tentatives": tentative, "rapport": rapport}
        else:
            log.log(f"  FAIL [{categorie}] : {raison}", "WARN")
            if tentative < max_retries:
                attente = delai_pour(categorie)
                log.log(f"  → Retry dans {attente}s…")
                time.sleep(attente)

    log.log(f"  ABANDON après {max_retries} tentatives", "ERROR")
    return {"cas": f"{prenom} {nom}", "ok": False, "tentatives": max_retries,
            "raison": raison, "categorie": categorie, "rapport": rapport}


# ── Point d'entrée ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Boucle de test PEP avec retry auto")
    parser.add_argument("--max-retries", type=int, default=MAX_RETRIES_DEFAUT,
                        help=f"Nombre max de tentatives par cas (défaut: {MAX_RETRIES_DEFAUT})")
    parser.add_argument("--cas", choices=["defaut", "custom", "tous"], default="defaut",
                        help="Jeu de cas à tester")
    parser.add_argument("--delai-entre", type=int, default=15,
                        help="Délai (s) entre deux personnes pour respecter les quotas (défaut: 15)")
    args = parser.parse_args()

    cas = CAS_DEFAUT if args.cas in ("defaut", "tous") else []
    if args.cas in ("custom", "tous"):
        cas = cas + CAS_CUSTOM

    log.log(f"{'='*55}")
    log.log(f"TEST LOOP — {len(cas)} cas | max {args.max_retries} tentatives")
    log.log(f"Log : {_LOG_FILE}")
    log.log(f"{'='*55}")
    t_debut = time.time()

    bilans = []
    for i, (prenom, nom, attendu_pep, attendu_statut, description) in enumerate(cas):
        if i > 0:
            log.log(f"  Pause inter-personnes {args.delai_entre}s…")
            time.sleep(args.delai_entre)

        bilan = executer_cas(prenom, nom, attendu_pep, attendu_statut, description, args.max_retries)
        bilans.append(bilan)

    # ── Synthèse ──────────────────────────────────────────────────────────────────
    duree  = int(time.time() - t_debut)
    nb_ok  = sum(1 for b in bilans if b["ok"])
    nb_ko  = len(bilans) - nb_ok

    log.log(f"{'='*55}")
    log.log(f"SYNTHÈSE — {nb_ok}/{len(bilans)} cas réussis | durée {duree//60}m{duree%60}s")
    log.log(f"{'='*55}")

    for b in bilans:
        icone = "PASS" if b["ok"] else "FAIL"
        detail = f"(tentatives: {b['tentatives']})"
        if not b["ok"]:
            detail += f" — {b.get('raison','?')[:80]}"
        log.log(f"  [{icone}] {b['cas']} {detail}")

    # ── Sauvegarder le rapport JSON ───────────────────────────────────────────────
    rapport_path = os.path.join(_LOG_DIR, f"test_loop_{datetime.now().strftime('%Y-%m-%d_%H-%M')}_rapport.json")
    rapport_json = []
    for b in bilans:
        r = b.get("rapport")
        entry = {
            "cas":        b["cas"],
            "ok":         b["ok"],
            "tentatives": b["tentatives"],
        }
        if not b["ok"]:
            entry["raison"]    = b.get("raison", "")
            entry["categorie"] = b.get("categorie", "")
        if r and not isinstance(r, dict):
            entry["est_pep"]       = getattr(r, "est_pep", None)
            entry["code_iso"]      = getattr(r, "code_iso", None)
            entry["statut_mandat"] = getattr(r, "statut_mandat", None)
            entry["fonction"]      = getattr(r, "fonction", None)
            entry["source_url"]    = getattr(r, "source_url", None)
        rapport_json.append(entry)

    with open(rapport_path, "w", encoding="utf-8") as f:
        json.dump(rapport_json, f, ensure_ascii=False, indent=2)
    log.log(f"Rapport JSON : {rapport_path}")

    log.close()

    # Code de sortie : 0 si tout OK, 1 si au moins un échec
    sys.exit(0 if nb_ko == 0 else 1)


if __name__ == "__main__":
    main()
