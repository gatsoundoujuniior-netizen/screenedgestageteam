import paramiko, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

# Vérifier process
_, o, _ = ssh.exec_command("ps aux | grep streamlit | grep -v grep")
procs = o.read().decode("utf-8", errors="replace").strip()
print("Processus streamlit:", procs or "AUCUN")

# Vérifier ligne 415 du fichier sur VPS
_, o, _ = ssh.exec_command("sed -n '413,422p' /root/screen_edge/dashboard_pep.py")
print("\nLignes 413-422 sur VPS:")
print(o.read().decode("utf-8", errors="replace"))

# Log récent
_, o, _ = ssh.exec_command("tail -10 /root/screen_edge/dashboard.log 2>/dev/null || echo 'pas de log'")
print("Log récent:")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()
