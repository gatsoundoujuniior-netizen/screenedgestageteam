import paramiko, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)
PG = "PGPASSWORD=Akarkababdo@2004 psql -U postgres -d compliance_db"

print("=== Requêtes Tavily pour Embaló ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "SELECT tavily_queries, scrapling_urls, serper_queries FROM verification_audit WHERE nom_complet ILIKE '%Embal%' ORDER BY ts DESC LIMIT 2" 2>&1""")
raw = o.read().decode("utf-8", errors="replace")
print(raw)

print("\n=== source_health_log pour Embaló ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "SELECT url, domaine, tier, statut, http_code FROM source_health_log WHERE nom_verifie ILIKE '%Embal%' ORDER BY created_at DESC LIMIT 20" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()
