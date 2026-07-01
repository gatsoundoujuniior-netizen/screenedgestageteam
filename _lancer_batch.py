import paramiko, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

# Stopper tout collector existant
ssh.exec_command("pkill -f 'pep_collector.py' 2>/dev/null")
time.sleep(2)

# Lancer avec max-verif 5
_, o, _ = ssh.exec_command(
    "cd /root/screen_edge && "
    "nohup python3 -u pep_collector.py --max-verif 5 "
    "> /root/screen_edge/collector.log 2>&1 & echo $!"
)
pid = o.read().decode("utf-8", errors="replace").strip()
print(f"Collector lancé PID: {pid}")

# Attendre que ça démarre
time.sleep(5)

# Tail du log en temps réel — 90 secondes
print("\n=== LOG EN DIRECT ===")
_, o, _ = ssh.exec_command("tail -f /root/screen_edge/collector.log", timeout=90)
try:
    start = time.time()
    while time.time() - start < 90:
        line = o.readline()
        if line:
            print(line, end="", flush=True)
        else:
            time.sleep(0.5)
except Exception:
    pass

print("\n\n=== FIN MONITORING 90s ===")
ssh.close()
