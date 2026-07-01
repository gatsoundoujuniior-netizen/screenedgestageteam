import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)
PG = "PGPASSWORD=Akarkababdo@2004 psql -U postgres -d compliance_db"
_, o, _ = ssh.exec_command(f"{PG} -c \"SELECT id, email, role, statut FROM utilisateurs ORDER BY id LIMIT 10\" 2>&1")
print(o.read().decode("utf-8", errors="replace"))
# Check how pep_agent logs to DB
_, o, _ = ssh.exec_command("grep -n 'psycopg2\\|pg_conn\\|INSERT\\|connect\\|DB_\\|PG_' /root/screen_edge/pep_agent.py 2>/dev/null | head -30")
print("=== pep_agent DB conn ===")
print(o.read().decode("utf-8", errors="replace"))
ssh.close()
