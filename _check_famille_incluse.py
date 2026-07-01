import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)

print("=== famille_incluse dans le référentiel JSON ===")
_, o, _ = ssh.exec_command("""python3 -c "
import json
data = json.load(open('/root/screen_edge/referentiel_pep.json'))
if isinstance(data, list):
    for entry in data:
        code = entry.get('code_iso', entry.get('code', '?'))
        fi = entry.get('famille_incluse', entry.get('criteres', {}).get('famille_incluse', '?'))
        print(f'{code}: famille_incluse={fi}')
else:
    for code, v in data.items():
        fi = v.get('famille_incluse', '?')
        print(f'{code}: famille_incluse={fi}')
" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()
