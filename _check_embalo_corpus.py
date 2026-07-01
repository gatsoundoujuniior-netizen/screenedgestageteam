import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)
PG = "PGPASSWORD=Akarkababdo@2004 psql -U postgres -d compliance_db"

print("=== Log corpus Embaló (grep) ===")
_, o, _ = ssh.exec_command(
    "grep -i 'embal' /root/screen_edge/logs/corpus_$(date +%Y-%m-%d).log 2>/dev/null | head -60"
)
print(o.read().decode("utf-8", errors="replace"))

print("\n=== Log pep_agent Embaló ===")
_, o, _ = ssh.exec_command(
    "grep -i 'embal' /root/screen_edge/logs/pep_agent_$(date +%Y-%m-%d).log 2>/dev/null | head -80"
)
print(o.read().decode("utf-8", errors="replace"))

print("\n=== Tous les logs dispo ===")
_, o, _ = ssh.exec_command("ls -lh /root/screen_edge/logs/ 2>/dev/null | tail -10")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()
