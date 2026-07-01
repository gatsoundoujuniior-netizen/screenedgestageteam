"""
Test 4 vérifications PEP via verifier_pep() — stocker=False (pas d'insertion DB)
Lance sur VPS via SFTP upload + SSH exec
"""
import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

TESTS = [
    # (prenom, nom, scenario)
    ("Aziz",    "Akhannouch",    "actif — PM Maroc, Tavily+Serper bonne couverture"),
    ("Faure",   "Gnassingbe",    "actif — President Togo, test Wikipedia bio enrichment"),
    ("Patrice", "Talon",         "ex_pep — Benin, mandat termine 24/05/2026, test date_today"),
    ("Brice",   "Oligui Nguema", "actif — Chef de transition Gabon"),
]

REMOTE_SCRIPT = """import sys
sys.path.insert(0, '/root/screen_edge')
from dotenv import load_dotenv; load_dotenv()
from pep_agent import verifier_pep

prenom = 'PRENOM'
nom = 'NOM'
print('=== TEST : ' + prenom + ' ' + nom + ' ===')
try:
    r = verifier_pep(prenom, nom, stocker=False)
    print('--- RESULTAT FINAL ---')
    print('est_pep         : ' + str(r.est_pep))
    print('statut_mandat   : ' + str(r.statut_mandat))
    print('pays            : ' + str(r.pays) + ' (' + str(r.code_iso) + ')')
    print('date_naissance  : ' + str(r.date_naissance))
    print('lieu_naissance  : ' + str(r.lieu_naissance))
    nb = len(r.fonctions_historiques or [])
    print('fonctions_hist  : ' + str(nb) + ' entrees')
    if r.fonctions_historiques:
        for f in (r.fonctions_historiques or [])[:3]:
            print('  - ' + str(f)[:80])
    print('source_url      : ' + str(r.source_url)[:80])
    print('raisonnement    : ' + str(r.raisonnement)[:150])
except Exception as ex:
    import traceback
    print('[ERREUR] ' + str(ex))
    traceback.print_exc()
"""

sftp = ssh.open_sftp()

for i, (prenom, nom, scenario) in enumerate(TESTS, 1):
    print(f"\n{'='*65}")
    print(f"TEST {i}/4 : {prenom} {nom}")
    print(f"Scenario attendu : {scenario}")
    print('='*65)

    script = (REMOTE_SCRIPT
              .replace("PRENOM", prenom)
              .replace("NOM", nom))

    remote_path = f"/tmp/_pep_test_{i}.py"
    with sftp.open(remote_path, "w") as f:
        f.write(script)

    cmd = f"cd /root/screen_edge && timeout 200 python3 {remote_path} 2>&1"
    _, stdout, _ = ssh.exec_command(cmd, timeout=220)
    out = stdout.read().decode("utf-8", errors="replace")

    # Afficher uniquement les lignes pertinentes (pas les traces Scrapling)
    for line in out.split("\n"):
        skip = any(x in line for x in [
            "CryptographyDeprecation", "TripleDES", "UserWarning",
            "warnings.warn", "InsecureRequest", "urllib3",
        ])
        if not skip:
            print(line)

    try:
        sftp.remove(remote_path)
    except Exception:
        pass

sftp.close()
ssh.close()
print("\n[DONE] 4 tests terminés.")
