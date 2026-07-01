import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

SCRIPT = """
import os, requests
from dotenv import load_dotenv
load_dotenv('/root/screen_edge/.env')

api_key = os.getenv("serper_dev_aoi_key", "")
print("Clé Serper:", "OK (" + api_key[:8] + "...)" if api_key else "ABSENTE")
print("Toutes les clés Serper dans env:", [k for k in os.environ if 'serper' in k.lower()])

queries = [
    '"Faure Essozimina Gnassingbe" president OR ministre Togo',
    '"Faure Gnassingbe" president OR ministre Togo',
    'Faure Gnassingbe president Togo',
]

for q in queries:
    r = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": q, "hl": "fr", "num": 5},
        timeout=8,
    )
    items = r.json().get("organic", [])
    print(f"\\n--- Query: {q[:70]} ---")
    print(f"  HTTP {r.status_code} | {len(items)} résultats organiques")
    for item in items[:3]:
        print(f"  - {item.get('title','')[:60]}")
        print(f"    {item.get('link','')[:70]}")
"""

sftp = ssh.open_sftp()
with sftp.open("/tmp/_test_serper.py", "w") as f:
    f.write(SCRIPT)
sftp.close()

_, stdout, _ = ssh.exec_command("cd /root/screen_edge && python3 /tmp/_test_serper.py 2>&1", timeout=30)
print(stdout.read().decode("utf-8", errors="replace"))
ssh.close()
