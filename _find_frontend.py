import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)

# Chercher les fichiers frontend sur le VPS
cmds = [
    ("Structure /root/screen_edge/", "ls /root/screen_edge/"),
    ("Dossiers frontend ?",          "find /root -maxdepth 5 -name '*.jsx' -o -name '*.tsx' -o -name '*.vue' 2>/dev/null | grep -v node_modules | head -30"),
    ("Dossiers React/Vue/Next ?",    "find /root -maxdepth 4 -name 'package.json' 2>/dev/null | grep -v node_modules | head -10"),
    ("App Python Flask/FastAPI ?",   "find /root -maxdepth 4 -name 'app.py' -o -name 'main.py' 2>/dev/null | head -10"),
    ("Fichiers statiques HTML ?",    "find /root -maxdepth 5 -name '*.html' 2>/dev/null | grep -v node_modules | head -10"),
]
for label, cmd in cmds:
    print(f"\n=== {label} ===")
    _, o, _ = ssh.exec_command(cmd)
    print(o.read().decode("utf-8", errors="replace").strip())

ssh.close()
