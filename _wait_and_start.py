import paramiko, time, sys, io, socket
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Attendre que le VPS réponde sur le port 22
for attempt in range(10):
    try:
        s = socket.create_connection(("195.200.14.241", 22), timeout=10)
        s.close()
        print(f"VPS joignable (tentative {attempt+1})")
        break
    except Exception:
        print(f"Tentative {attempt+1}/10 — VPS injoignable, attente 15s...")
        time.sleep(15)
else:
    print("VPS toujours injoignable après 10 tentatives.")
    sys.exit(1)

time.sleep(3)
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

ssh.exec_command("pkill -f 'dashboard_pep.py' 2>/dev/null")
time.sleep(2)

ssh.exec_command(
    "cd /root/screen_edge && "
    "nohup python3 -m streamlit run dashboard_pep.py "
    "--server.port 8501 --server.address 0.0.0.0 "
    "> /root/screen_edge/dashboard.log 2>&1 &"
)
time.sleep(8)

_, o, _ = ssh.exec_command("ps aux | grep streamlit | grep -v grep")
procs = o.read().decode("utf-8", errors="replace").strip()
print("Process streamlit:", procs or "AUCUN")

_, o, _ = ssh.exec_command("tail -15 /root/screen_edge/dashboard.log")
print("\nLog:\n", o.read().decode("utf-8", errors="replace"))

ssh.close()
