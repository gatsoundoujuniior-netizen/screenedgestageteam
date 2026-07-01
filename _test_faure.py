import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

SCRIPT = """import sys
sys.path.insert(0, '/root/screen_edge')
from dotenv import load_dotenv; load_dotenv()
from pep_agent import verifier_pep
r = verifier_pep('Faure', 'Gnassingbe', stocker=False)
print('--- RÉSULTAT ---')
print('est_pep         : ' + str(r.est_pep))
print('statut_mandat   : ' + str(r.statut_mandat))
print('date_naissance  : ' + str(r.date_naissance))
print('lieu_naissance  : ' + str(r.lieu_naissance))
nb = len(r.fonctions_historiques or [])
print('fonctions_hist  : ' + str(nb) + ' entrees')
for f in (r.fonctions_historiques or [])[:5]:
    print('  - ' + str(f)[:80])
"""

sftp = ssh.open_sftp()
with sftp.open("/tmp/_test_faure.py", "w") as f:
    f.write(SCRIPT)
sftp.close()

print("Test Faure Gnassingbé — Wikipedia enrichment fix")
print("="*55)
_, stdout, _ = ssh.exec_command("cd /root/screen_edge && timeout 200 python3 /tmp/_test_faure.py 2>&1", timeout=210)
out = stdout.read().decode("utf-8", errors="replace")
for line in out.split("\n"):
    if any(x in line for x in ["TripleDES", "CryptographyDeprecation", "UserWarning"]):
        continue
    print(line)

ssh.close()
