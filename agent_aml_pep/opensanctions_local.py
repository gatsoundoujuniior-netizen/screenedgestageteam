"""
opensanctions_local.py — Dump local OpenSanctions (remplace l'API, quota illimité)
Utilise targets.simple.csv (données déjà agrégées — pas besoin de passer par FtM).

Principe : tout le monde dans le dataset 'peps' est un PEP par définition.
La présence dans la base suffit à confirmer le statut PEP.

Usage MVP : gratuit (CC 4.0 NC).
Usage production commerciale : licence payante requise (opensanctions.org/licensing).
"""

import csv, io, json, os, sqlite3, requests
from datetime import datetime

_DIR       = os.path.dirname(os.path.abspath(__file__))
_DB_PATH   = os.path.join(_DIR, "opensanctions_pep.sqlite")
_META_PATH = os.path.join(_DIR, "opensanctions_meta.json")

_INDEX_URL = "https://data.opensanctions.org/datasets/latest/index.json"


# ── Vérification fraîcheur ────────────────────────────────────────────────────────

def _infos_distantes() -> tuple:
    """Retourne (updated_at, url_csv) depuis l'index OpenSanctions."""
    try:
        r = requests.get(_INDEX_URL, timeout=15,
                         headers={"User-Agent": "ScreenEdge-PEP/1.0"})
        if r.status_code != 200:
            return "", ""
        for ds in r.json().get("datasets", []):
            if ds.get("name") == "peps":
                updated = ds.get("updated_at", "")
                url = ""
                for res in ds.get("resources", []):
                    if res.get("name") == "targets.simple.csv":
                        url = res.get("url", "")
                        break
                return updated, url
        return "", ""
    except Exception as e:
        print("  [OS-Local] Index erreur : " + str(e))
        return "", ""


def _meta_locale() -> dict:
    try:
        with open(_META_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _sauver_meta(updated_at: str):
    with open(_META_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "updated_at":    updated_at,
            "telecharge_le": datetime.now().isoformat(),
        }, f, indent=2)


# ── Construction SQLite depuis CSV ────────────────────────────────────────────────

def _construire_db(csv_path: str):
    """
    Parse targets.simple.csv et construit le SQLite.
    Tous les enregistrements = PEPs confirmés (dataset peps par définition).
    """
    print("  [OS-Local] Construction SQLite depuis CSV...")
    conn = sqlite3.connect(_DB_PATH)
    c    = conn.cursor()

    c.executescript("""
        DROP TABLE IF EXISTS noms;
        DROP TABLE IF EXISTS entites;
        CREATE TABLE entites (
            id          TEXT PRIMARY KEY,
            pays        TEXT,
            date_nais   TEXT,
            source      TEXT
        );
        CREATE TABLE noms (
            entity_id   TEXT,
            valeur      TEXT COLLATE NOCASE
        );
        CREATE INDEX IF NOT EXISTS idx_noms ON noms(valeur);
    """)

    nb = 0
    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            eid      = row.get("id", "").strip()
            nom_prin = row.get("name", "").strip()
            aliases  = row.get("aliases", "").strip()
            pays     = row.get("countries", "").strip()
            date_n   = row.get("birth_date", "").strip()
            source   = row.get("dataset", "").strip()

            if not eid or not nom_prin:
                continue

            c.execute(
                "INSERT OR REPLACE INTO entites VALUES (?,?,?,?)",
                (eid, pays, date_n, source),
            )

            # Indexer nom principal + aliases
            tous_noms = [nom_prin]
            if aliases:
                tous_noms += [a.strip() for a in aliases.split(";") if a.strip()]

            for val in tous_noms:
                val_l = val.lower().strip()
                if val_l and len(val_l) > 2:
                    c.execute("INSERT INTO noms VALUES (?,?)", (eid, val_l))

            nb += 1
            if nb % 50_000 == 0:
                conn.commit()
                print("    " + str(nb) + " PEPs charges...")

    conn.commit()
    conn.close()
    print("  [OS-Local] SQLite construit — " + str(nb) + " PEPs indexes")


# ── Téléchargement ────────────────────────────────────────────────────────────────

def telecharger_si_nouveau(forcer: bool = False) -> bool:
    """Télécharge le CSV PEP seulement si nouvelle version disponible."""
    maj, csv_url = _infos_distantes()
    if not csv_url:
        print("  [OS-Local] Impossible de recuperer l URL du CSV")
        return False

    meta = _meta_locale()
    if not forcer and meta.get("updated_at") == maj and os.path.exists(_DB_PATH):
        print("  [OS-Local] Dump a jour (" + maj + ") — aucun telechargement")
        return False

    print("  [OS-Local] Nouvelle version (" + maj + ") -> telechargement CSV...")
    tmp_path = os.path.join(_DIR, "os_pep_tmp.csv")

    try:
        r = requests.get(csv_url, stream=True, timeout=600,
                         headers={"User-Agent": "ScreenEdge-PEP/1.0"})
        r.raise_for_status()

        recu = 0
        with open(tmp_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
                recu += len(chunk)
                if recu % (10 * 1024 * 1024) < 65536:
                    print("    " + str(recu // 1024 // 1024) + " MB recus...")

        print("    Telechargement termine (" + str(recu // 1024 // 1024) + " MB)")
        _construire_db(tmp_path)
        _sauver_meta(maj)
        os.remove(tmp_path)
        return True

    except Exception as e:
        print("  [OS-Local] Erreur : " + str(e))
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return False


# ── Recherche locale ──────────────────────────────────────────────────────────────

def rechercher_opensanctions_local(nom_complet: str, code_iso: str = "") -> dict:
    """
    Recherche dans le dump local.
    Fix matching : AND strict — toutes les parties dans le MÊME nom indexé.
    Tout résultat = PEP confirmé (présence dans le dataset peps).
    """
    if not os.path.exists(_DB_PATH):
        print("  [OS-Local] Dump absent — lancer telecharger_si_nouveau()")
        return {}

    nom_parts = [p.lower() for p in nom_complet.split() if len(p) > 2]
    if not nom_parts:
        return {}

    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    c    = conn.cursor()

    # AND strict : toutes les parties dans le même nom indexé
    placeholders = " AND ".join(["valeur LIKE ?"] * len(nom_parts))
    params       = [f"%{p}%" for p in nom_parts]
    rows = c.execute(
        "SELECT DISTINCT entity_id FROM noms WHERE " + placeholders,
        params,
    ).fetchall()

    entites_pep = []
    for row in rows:
        eid   = row["entity_id"]
        ent_r = c.execute("SELECT * FROM entites WHERE id=?", (eid,)).fetchone()
        if not ent_r:
            continue

        pays_lst = [p.strip() for p in (ent_r["pays"] or "").split(";") if p.strip()]

        # Filtrer par pays si fourni
        if code_iso and code_iso != "XX":
            if code_iso.lower() not in [p.lower() for p in pays_lst]:
                continue

        # Récupérer le nom principal depuis la table noms
        nom_row = c.execute(
            "SELECT valeur FROM noms WHERE entity_id=? ORDER BY LENGTH(valeur) DESC LIMIT 1",
            (eid,)
        ).fetchone()
        nom_affiche = nom_row["valeur"].title() if nom_row else nom_complet

        entites_pep.append({
            "nom":        nom_affiche,
            "pays":       pays_lst,
            "fonctions":  [ent_r["source"]] if ent_r["source"] else [],
            "topics":     ["pep"],
            "is_pep":     True,
            "sanctions":  False,
            "source":     eid,
            "date_debut": "",
            "date_nais":  ent_r["date_nais"] or "",
        })

    conn.close()

    if entites_pep:
        print("  [OS-Local] " + str(len(entites_pep)) + " PEP(s) confirme(s) pour " + nom_complet)
        return {"entites": entites_pep, "source": "opensanctions-local"}

    print("  [OS-Local] Non trouve dans la base PEP locale pour " + nom_complet)
    return {}


def stats_par_pays(pays_list: list) -> dict:
    """Nombre de PEPs dans le dump pour chaque code ISO (ex: ['MA','SN'])."""
    if not os.path.exists(_DB_PATH):
        return {c: 0 for c in pays_list}
    conn = sqlite3.connect(_DB_PATH)
    result = {}
    for code in pays_list:
        row = conn.execute(
            "SELECT COUNT(DISTINCT e.id) FROM entites e WHERE e.pays LIKE ?",
            (f"%{code.lower()}%",)
        ).fetchone()
        result[code] = row[0] if row else 0
    conn.close()
    return result


def noms_candidats_dump(code_iso: str, exclure: set = None, limite: int = 10) -> list[dict]:
    """
    Retourne jusqu'à `limite` candidats PEP du dump pour un pays donné,
    sous forme de dicts {prenom, nom, _source_url, _categorie}.
    Exclut les noms déjà dans le checkpoint (format "CODE:Nom").
    """
    if not os.path.exists(_DB_PATH):
        return []

    exclure = exclure or set()
    # Normaliser les noms exclus pour comparaison insensible à la casse
    exclus_norm = {k.split(":", 1)[1].lower() if ":" in k else k.lower() for k in exclure}

    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Récupérer les entités du pays — prendre plus que nécessaire pour filtrer ensuite
    rows = c.execute(
        """
        SELECT DISTINCT e.id
        FROM entites e
        WHERE e.pays LIKE ?
        LIMIT ?
        """,
        (f"%{code_iso.lower()}%", limite * 5),
    ).fetchall()

    candidats = []
    for row in rows:
        eid = row["id"]
        # Nom le plus long = le plus complet
        nom_row = c.execute(
            "SELECT valeur FROM noms WHERE entity_id=? ORDER BY LENGTH(valeur) DESC LIMIT 1",
            (eid,)
        ).fetchone()
        if not nom_row:
            continue

        nom_complet = nom_row["valeur"].title().strip()
        if nom_complet.lower() in exclus_norm:
            continue

        # Découper en prenom / nom (heuristique : dernier mot = nom de famille)
        parts = nom_complet.split()
        if len(parts) == 1:
            prenom, nom = "", parts[0]
        else:
            prenom = " ".join(parts[:-1])
            nom    = parts[-1]

        candidats.append({
            "prenom":       prenom,
            "nom":          nom,
            "_source_url":  "opensanctions-dump",
            "_categorie":   "dump_pep",
        })

        if len(candidats) >= limite:
            break

    conn.close()
    return candidats


def statut_dump() -> dict:
    meta      = _meta_locale()
    exist     = os.path.exists(_DB_PATH)
    taille_mb = round(os.path.getsize(_DB_PATH) / 1024 / 1024, 1) if exist else 0
    return {
        "present":       exist,
        "updated_at":    meta.get("updated_at", "jamais"),
        "telecharge_le": meta.get("telecharge_le", "jamais"),
        "taille_mb":     taille_mb,
    }


if __name__ == "__main__":
    import sys
    forcer = "--force" in sys.argv
    telecharger_si_nouveau(forcer=forcer)
