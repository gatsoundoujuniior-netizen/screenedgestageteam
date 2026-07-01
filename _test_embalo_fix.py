import paramiko, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)
PG = "PGPASSWORD=Akarkababdo@2004 psql -U postgres -d compliance_db"

script = """
import sys
sys.path.insert(0, '/root/screen_edge')
from pep_agent import verifier_pep
r = verifier_pep('Umaro Sissoco', 'Embaló', stocker=False)
print('\\n=== RÉSULTAT ===')
print(f"est_pep       : {r.get('est_pep')}")
print(f"statut_mandat : {r.get('statut_mandat')}")
print(f"fonction      : {r.get('fonction')}")
print(f"code_iso      : {r.get('code_iso')}")
print(f"source_off    : {r.get('source_validee')}")
"""

# Écrire le script sur VPS
sftp = ssh.open_sftp()
with sftp.file('/root/screen_edge/_test_embalo_fix.py', 'w') as f:
    f.write(script)
sftp.close()

print("Test Embaló lancé (max 120s)...")
stdin, stdout, stderr = ssh.exec_command(
    "cd /root/screen_edge && PG_LOCAL=true timeout 120 python3 _test_embalo_fix.py 2>&1",
    timeout=130
)
out = stdout.read().decode("utf-8", errors="replace")
print(out)

# Vérifier ce que le source_health_log a scrapé
print("\n=== source_health_log Embaló (après fix) ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "
SELECT url, domaine, tier, statut
FROM source_health_log
WHERE nom_verifie ILIKE '%Embal%'
ORDER BY created_at DESC LIMIT 15
" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()
