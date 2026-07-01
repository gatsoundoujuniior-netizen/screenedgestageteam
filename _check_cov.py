import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

cmd = r"""cd /root/screen_edge && python3 -c "
import sys, os
sys.path.insert(0, '/root/screen_edge')
from db_utils import query_all
from opensanctions_local import stats_par_pays

PAYS = ['MA','DZ','TN','LY','SN','CI','ML','BF','NE','TG','BJ','GW','GN']

# Stats dump
try:
    dump = stats_par_pays(PAYS)
    print('Dump stats:', dump)
except Exception as e:
    print('Dump ERROR:', e)

# Stats verification_audit par pays
try:
    rows_v = query_all('SELECT code_iso, COUNT(*) as nb FROM verification_audit GROUP BY code_iso') or []
    verifs = {(r.get('code_iso') or '').upper(): r['nb'] for r in rows_v}
    print('Verifs par pays:', verifs)
    print('Total verifs:', sum(verifs.values()))
except Exception as e:
    print('Verifs ERROR:', e)

# Stats pep par pays
try:
    rows_i = query_all('SELECT code_iso, COUNT(*) as nb FROM pep GROUP BY code_iso') or []
    inseres = {(r.get('code_iso') or '').upper(): r['nb'] for r in rows_i}
    print('Inseres par pays:', inseres)
    print('Total inseres:', sum(inseres.values()))
except Exception as e:
    print('Inseres ERROR:', e)
"
"""
_, o, e = ssh.exec_command(cmd)
print(o.read().decode("utf-8", errors="replace"))
err = e.read().decode("utf-8", errors="replace")
if err.strip(): print("STDERR:", err[:1000])
ssh.close()
