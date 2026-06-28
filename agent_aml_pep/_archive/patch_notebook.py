"""
patch_notebook.py — ScreenEdge Africa
Patch le notebook agent_aml_pep.ipynb :
  - Cellule 1 (index 2) : ajout imports psycopg2 / sshtunnel
  - Cellule 2 (index 4) : ajout assertion creds PostgreSQL
  - Cellule 6 (index 12): remplacement consulter_referentiel (.md → PostgreSQL)
Usage : python patch_notebook.py
"""

import json
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

NB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_aml_pep.ipynb")

with open(NB_PATH, "r", encoding="utf-8") as f:
    nb = json.load(f)

# ── Patch cellule [2] : Imports ────────────────────────────────────────────────
NEW_IMPORTS = """\
# Imports — version TP avec langchain 1.3.1
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call, wrap_tool_call, dynamic_prompt, ModelRequest, ModelResponse
from langchain.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langchain_ollama import ChatOllama
from langchain_tavily import TavilySearch
from langchain_community.document_loaders import PyPDFLoader, WebBaseLoader
from pydantic import BaseModel
from dotenv import load_dotenv
from IPython.display import Markdown, display
import psycopg2
import psycopg2.extras
from sshtunnel import SSHTunnelForwarder
import os

print("✅ Imports OK")
"""

# ── Patch cellule [4] : Variables d'environnement ──────────────────────────────
NEW_ENV = """\
load_dotenv(override=True)

assert os.getenv('TAVILY_API_KEY'),    '❌ TAVILY_API_KEY manquante dans .env'
assert os.getenv('PG_SSH_HOST'),       '❌ PG_SSH_HOST manquante dans .env'
assert os.getenv('PG_SSH_PASSWORD'),   '❌ PG_SSH_PASSWORD manquante dans .env'
assert os.getenv('PG_PASSWORD'),       '❌ PG_PASSWORD manquante dans .env'

print("✅ Variables d'environnement chargées")
print(f"   DB  : {os.getenv('PG_DATABASE')} @ {os.getenv('PG_SSH_HOST')} (SSH tunnel)")
"""

# ── Patch cellule [12] : Tool consulter_referentiel ────────────────────────────
NEW_TOOLS = '''\
import os
import psycopg2
import psycopg2.extras
from sshtunnel import SSHTunnelForwarder

tavily_search_tool = TavilySearch(max_results=5, search_depth=\'advanced\')


def _get_referentiel_db(pays: str) -> dict | None:
    """Requête SELECT dans referentiel_pep via SSH tunnel."""
    tunnel = SSHTunnelForwarder(
        (os.getenv("PG_SSH_HOST"), 22),
        ssh_username=os.getenv("PG_SSH_USER", "root"),
        ssh_password=os.getenv("PG_SSH_PASSWORD"),
        remote_bind_address=("127.0.0.1", 5432),
        set_keepalive=10,
    )
    tunnel.start()
    try:
        conn = psycopg2.connect(
            host="127.0.0.1",
            port=tunnel.local_bind_port,
            database=os.getenv("PG_DATABASE", "compliance_db"),
            user=os.getenv("PG_USER", "postgres"),
            password=os.getenv("PG_PASSWORD"),
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        with conn.cursor() as cur:
            pays_strip = pays.strip()
            if len(pays_strip) == 2:
                cur.execute(
                    "SELECT * FROM referentiel_pep WHERE UPPER(code_iso) = %s",
                    (pays_strip.upper(),),
                )
            else:
                cur.execute(
                    "SELECT * FROM referentiel_pep WHERE pays ILIKE %s",
                    (f"%{pays_strip}%",),
                )
            row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    finally:
        tunnel.stop()


@tool
def consulter_referentiel(pays: str) -> str:
    """Consulte le referentiel officiel AML/PPE ScreenEdge Africa pour un pays donne.
    Doit etre appele EN PREMIER avant toute reponse sur un pays."""
    try:
        r = _get_referentiel_db(pays)

        if r is None:
            return (
                f\'Pays "{pays}" non trouve dans le referentiel compliance_db. \'
                "Appliquer fallback GAFI R12 : vigilance renforcee, "
                "surveillance permanente, source des fonds obligatoire."
            )

        statut    = r.get("statut_gafi", "clean")
        vigilance = r.get("vigilance", "standard")
        updated   = str(r.get("updated_at", ""))[:10]

        rapport = f"""
=== REFERENTIEL AML/PPE — {r.get(\'pays\', \'\').upper()} ({r.get(\'code_iso\', \'\')}) ===

REGION         : {r.get(\'region\', \'\').upper()}
LOI DE REF.    : {r.get(\'loi_ref\') or \'N/A\'}

DEFINITION PEP OFFICIELLE :
{r.get(\'def_pep\') or \'Non disponible\'}

STATUT GAFI    : {statut.replace(\'_\', \' \').upper()}
VIGILANCE      : {vigilance.upper()}
AUTORITE       : {r.get(\'autorite\') or \'N/A\'}
SOURCE URL     : {r.get(\'source_url\') or \'N/A\'}

NOTES          : {r.get(\'notes\') or \'Aucune\'}
MIS A JOUR     : {updated}
""".strip()

        print(f"Referentiel consulte : {r.get(\'pays\')} ({len(rapport)} car.)")

        if statut == "liste_noire":
            rapport += (
                "\\n\\n[INSTRUCTION AUTOMATIQUE — LISTE NOIRE] "
                "Ce pays est en LISTE NOIRE GAFI. Vigilance MAXIMALE obligatoire. "
                "Toute relation commerciale est prohibee. "
                "Appelle verifier_statut_gafi() immediatement."
            )
            print(f"ALERTE LISTE NOIRE : {r.get(\'pays\')}")
        elif statut == "liste_grise":
            rapport += (
                "\\n\\n[INSTRUCTION AUTOMATIQUE — LISTE GRISE] "
                "Ce pays est en LISTE GRISE GAFI. Vigilance RENFORCEE OBLIGATOIRE. "
                "Appelle verifier_statut_gafi() pour confirmer le statut actuel."
            )
            print(f"Liste grise detectee → verification GAFI obligatoire : {r.get(\'pays\')}")
        elif vigilance == "renforcee":
            rapport += (
                "\\n\\n[INSTRUCTION AUTOMATIQUE — VIGILANCE RENFORCEE] "
                "Ce pays necessite une vigilance renforcee malgre un statut Clean GAFI "
                "(instabilite politique / transition). Appelle verifier_statut_gafi() recommande."
            )

        return rapport

    except Exception as e:
        return f"Erreur connexion compliance_db : {str(e)}"


@tool
def search_web(query: str) -> str:
    """Recherche des informations AML/PPE sur le web."""
    return tavily_search_tool.invoke({\'query\': query})


@tool
def lire_pdf_officiel(url: str) -> str:
    """Lit un PDF officiel depuis une URL (CENTIF, BCEAO, BAM, etc.)."""
    try:
        loader = PyPDFLoader(url)
        pages = loader.load()
        contenu = \'\\n\'.join([p.page_content for p in pages[:10]])
        return contenu[:5000]
    except Exception as e:
        return f\'Erreur lecture PDF : {str(e)}\'


@tool
def lire_page_web(url: str) -> str:
    """Lit le contenu d\'une page web officielle (CENTIF, autorites AML)."""
    try:
        loader = WebBaseLoader(url)
        docs = loader.load()
        return docs[0].page_content[:5000]
    except Exception as e:
        return f\'Erreur lecture page web : {str(e)}\'


@tool
def verifier_statut_gafi(pays: str) -> str:
    """Verifie le statut GAFI actuel d\'un pays sur fatf-gafi.org."""
    query = f\'FATF GAFI {pays} grey list black list 2026 site:fatf-gafi.org\'
    return tavily_search_tool.invoke({\'query\': query})


tools_aml = [consulter_referentiel, search_web, lire_pdf_officiel, lire_page_web, verifier_statut_gafi]

print(f\'OK {len(tools_aml)} tools AML/PPE definis\')
for t in tools_aml:
    print(f\'   - {t.name}\')
'''

# ── Application des patches ────────────────────────────────────────────────────

patches = {2: NEW_IMPORTS, 4: NEW_ENV, 12: NEW_TOOLS}

for idx, new_source in patches.items():
    cell = nb["cells"][idx]
    assert cell["cell_type"] == "code", f"La cellule [{idx}] n'est pas une cellule code !"
    old_preview = "".join(cell["source"])[:60].replace("\n", " ")
    cell["source"] = new_source
    cell["outputs"] = []
    cell["execution_count"] = None
    print(f"  [PATCH {idx}] '{old_preview}...' → remplacé")

with open(NB_PATH, "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)

print(f"\n✅ Notebook patché : {NB_PATH}")
print("   → Cellule 2  : imports + psycopg2 + sshtunnel")
print("   → Cellule 4  : assertions creds PostgreSQL")
print("   → Cellule 12 : consulter_referentiel via compliance_db")
