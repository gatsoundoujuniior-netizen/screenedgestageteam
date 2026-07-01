import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)
PG = "PGPASSWORD=Akarkababdo@2004 psql -U postgres -d compliance_db"

print("=== Dernières vérifications (15) ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "SELECT nom_complet, code_iso, est_pep, LEFT(motif,80) as motif, duree_ms, tavily_appels FROM verification_audit ORDER BY ts DESC LIMIT 15" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

print("\n=== Compteurs PEP en base ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "SELECT code_iso, COUNT(*) as nb FROM pep GROUP BY code_iso ORDER BY nb DESC" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

print("\n=== Quota Tavily aujourd'hui ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "SELECT SUM(tavily_appels) as tavily_today, COUNT(*) as verifs_today FROM verification_audit WHERE ts::date = CURRENT_DATE" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

print("\n=== source_health_log : sources KO récentes ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "SELECT domaine, statut, COUNT(*) as nb FROM source_health_log WHERE statut NOT IN ('ok','vide') AND created_at > now() - interval '24h' GROUP BY domaine, statut ORDER BY nb DESC LIMIT 10" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

print("\n=== Streamlit process ===")
_, o, _ = ssh.exec_command("pgrep -a streamlit 2>/dev/null | head -3")
print(o.read().decode("utf-8", errors="replace") or "Aucun process streamlit trouvé")

ssh.close()
