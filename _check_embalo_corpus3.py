import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)
PG = "PGPASSWORD=Akarkababdo@2004 psql -U postgres -d compliance_db"

# Colonnes disponibles dans source_health_log
print("=== Colonnes source_health_log ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "\\d source_health_log" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

# source_health_log pour Embaló
print("\n=== source_health_log Embaló ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "
SELECT url, domaine, tier, statut, http_code
FROM source_health_log
WHERE nom_verifie ILIKE '%Embal%'
ORDER BY created_at DESC LIMIT 20
" 2>&1""")
print(o.read().decode("utf-8", errors="replace") or "(aucun log)")

# Extrait du log corpus pour voir ce que Tavily a retourné
print("\n=== Corpus log Embaló (50 premières lignes autour de l'entrée) ===")
_, o, _ = ssh.exec_command(
    "grep -n 'embal\\|Embal\\|GW\\|Guinée.Bissau\\|rfi\\|france24\\|jeuneafrique\\|tavily\\|Tavily\\|serper\\|Serper' "
    "/root/screen_edge/logs/corpus_2026-06-29.log 2>/dev/null | head -80"
)
print(o.read().decode("utf-8", errors="replace") or "(rien)")

ssh.close()
