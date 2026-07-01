import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)
PG = "PGPASSWORD=Akarkababdo@2004 psql -U postgres -d compliance_db"

print("=== verification_audit colonnes disponibles ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "\\d verification_audit" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

print("\n=== verification_audit — série 5 ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "SELECT nom_complet, code_iso, est_pep, motif, duree_ms, tavily_appels FROM verification_audit ORDER BY ts DESC LIMIT 12" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

print("\n=== Log complet Ibrahim Coulibaly Guindo ===")
_, o, _ = ssh.exec_command("grep -A5 -B2 'Coulibaly\\|Guindo\\|votes.*ML\\|vote.*incertain' /root/screen_edge/logs/corpus_$(date +%Y-%m-%d).log 2>/dev/null | tail -40")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()
