import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)
PG = "PGPASSWORD=Akarkababdo@2004 psql -U postgres -d compliance_db"

# Colonnes utilisateurs
_, o, _ = ssh.exec_command(f"{PG} -c \"SELECT column_name, data_type FROM information_schema.columns WHERE table_name='utilisateurs' ORDER BY ordinal_position\" 2>&1")
print("=== utilisateurs colonnes ===")
print(o.read().decode("utf-8", errors="replace"))

# Admins existants
_, o, _ = ssh.exec_command(f"{PG} -c \"SELECT id, email, role FROM utilisateurs WHERE role IN ('admin','superadmin','ADMIN') LIMIT 5\" 2>&1")
print("=== admins ===")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()
