import paramiko, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

# Vérifier les fichiers présents
_, o, _ = ssh.exec_command("ls /root/screen_edge/*.py 2>/dev/null | head -20")
print("Fichiers py:", o.read().decode("utf-8", errors="replace"))

# Relancer dashboard
cmd = (
    "cd /root/screen_edge && "
    "nohup python3 -m streamlit run dashboard_pep.py "
    "--server.port 8501 --server.address 0.0.0.0 "
    "> /root/screen_edge/dashboard.log 2>&1 & echo $!"
)
_, o, e = ssh.exec_command(cmd)
time.sleep(3)
pid = o.read().decode("utf-8", errors="replace").strip()
print(f"Dashboard lancé PID: {pid}")

# Vérifier qu'il tourne
_, o, _ = ssh.exec_command("ps aux | grep streamlit | grep -v grep")
print("Process:", o.read().decode("utf-8", errors="replace"))

# Premières lignes du log
time.sleep(4)
_, o, _ = ssh.exec_command("tail -20 /root/screen_edge/dashboard.log")
print("Log:", o.read().decode("utf-8", errors="replace"))

ssh.close()
