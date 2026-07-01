import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)
PG = "PGPASSWORD=Akarkababdo@2004 psql -U postgres -d compliance_db"
for table in ["notifications", "verification_audit", "audit_trail"]:
    _, o, _ = ssh.exec_command(f"{PG} -c '\\d {table}' 2>&1")
    print(f"=== {table} ===")
    print(o.read().decode("utf-8", errors="replace"))
ssh.close()
