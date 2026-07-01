import paramiko, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

# Vider l'ancien log et relancer
ssh.exec_command("pkill -f 'dashboard_pep.py' 2>/dev/null; sleep 1")
time.sleep(2)

_, o, e = ssh.exec_command(
    "cd /root/screen_edge && "
    "nohup python3 -m streamlit run dashboard_pep.py "
    "--server.port 8501 --server.address 0.0.0.0 "
    "> /root/screen_edge/dashboard.log 2>&1 &"
)
time.sleep(6)

# Vérifier process
_, o, _ = ssh.exec_command("ps aux | grep streamlit | grep -v grep | awk '{print $1, $2, $11, $12}'")
print("Process:", o.read().decode("utf-8", errors="replace").strip())

# Dernières lignes log
_, o, _ = ssh.exec_command("tail -20 /root/screen_edge/dashboard.log")
print("\nLog:\n", o.read().decode("utf-8", errors="replace"))

ssh.close()
