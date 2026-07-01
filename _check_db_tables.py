import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)

# Credentials depuis .env
_, o, _ = ssh.exec_command("grep -iE 'postgres|DB_|DATABASE|PG' /root/screen_edge/.env 2>/dev/null | head -10")
print("=== .env DB vars ===")
print(o.read().decode("utf-8", errors="replace"))

# Tables via sudo postgres
_, o, _ = ssh.exec_command("sudo -u postgres psql -d compliance_db -c '\\dt' 2>&1")
print("=== Tables ===")
print(o.read().decode("utf-8", errors="replace"))

# Structure audit_pep_log
_, o, _ = ssh.exec_command("sudo -u postgres psql -d compliance_db -c '\\d audit_pep_log' 2>&1")
print("=== audit_pep_log ===")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()
