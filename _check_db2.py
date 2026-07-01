import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)

PG = "PGPASSWORD=Akarkababdo@2004 psql -U postgres -d compliance_db"

_, o, _ = ssh.exec_command(f"{PG} -c '\\dt' 2>&1")
print("=== Tables ===")
print(o.read().decode("utf-8", errors="replace"))

_, o, _ = ssh.exec_command(f"{PG} -c '\\d audit_pep_log' 2>&1")
print("=== audit_pep_log ===")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()
