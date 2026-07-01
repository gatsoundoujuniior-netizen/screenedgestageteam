import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)
PG = "PGPASSWORD=Akarkababdo@2004 psql -U postgres -d compliance_db"

# Dernières vérifications audit
print("=== verification_audit (8 dernières) ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "SELECT nom_complet, code_iso, est_pep, motif, duree_ms, tavily_appels FROM verification_audit ORDER BY ts DESC LIMIT 8" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

# source_health_log
print("=== source_health_log (30 dernières) ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "SELECT nom_verifie, domaine, statut, http_code, duree_ms, est_source_off FROM source_health_log ORDER BY created_at DESC LIMIT 30" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

# Notifications alertes
print("=== notifications source_indisponible ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "SELECT titre, LEFT(message, 120) FROM notifications WHERE type='source_indisponible' ORDER BY date_creation DESC LIMIT 10" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

# Logs fichier du jour
print("=== corpus log du jour ===")
_, o, _ = ssh.exec_command("cat /root/screen_edge/logs/corpus_$(date +%Y-%m-%d).log 2>/dev/null | tail -30")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()
