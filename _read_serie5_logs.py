import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)
PG = "PGPASSWORD=Akarkababdo@2004 psql -U postgres -d compliance_db"

noms = ["Issoufou Mahamadou","Aminata Touré","Idrissa Seck","Abdoulaye Wade",
        "Moustapha Niasse","Cheick Modibo Diarra","Tiébilé Dramé",
        "Bah Oury","Ibrahim Coulibaly Guindo"]

print("=== verification_audit — série 5 ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "SELECT nom_complet, code_iso, est_pep, statut_mandat, fonction, motif, duree_ms FROM verification_audit ORDER BY ts DESC LIMIT 12" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

print("\n=== source_health_log — série 5 (20 dernières) ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "SELECT nom_verifie, domaine, tier, statut, http_code, duree_ms, est_source_off FROM source_health_log ORDER BY created_at DESC LIMIT 20" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

print("\n=== Tavily quota actuel ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "SELECT date_trunc('day', ts) as jour, SUM(tavily_appels) as total_tavily FROM verification_audit WHERE ts > now() - interval '2 days' GROUP BY 1 ORDER BY 1 DESC" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

print("\n=== Corpus log Ibrahim Coulibaly Guindo ===")
_, o, _ = ssh.exec_command("grep -i 'coulibaly\\|guindo' /root/screen_edge/logs/corpus_$(date +%Y-%m-%d).log 2>/dev/null | tail -20")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()
