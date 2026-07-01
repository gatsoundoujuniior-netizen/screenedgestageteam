import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)
PG = "PGPASSWORD=Akarkababdo@2004 psql -U postgres -d compliance_db"

# Check all log files for Embaló
print("=== Grep Embaló dans tous les logs ===")
_, o, _ = ssh.exec_command(
    "grep -ri 'embal' /root/screen_edge/logs/ 2>/dev/null | head -80"
)
print(o.read().decode("utf-8", errors="replace") or "(rien trouvé)")

# Check verification_audit details avec les colonnes JSON
print("\n=== Audit Embaló — colonnes complètes ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "
SELECT
  nom_complet, code_iso, est_pep,
  tavily_appels,
  jsonb_array_length(COALESCE(tavily_queries::jsonb,'[]'::jsonb)) as nb_tavily_queries_stored,
  jsonb_array_length(COALESCE(scrapling_urls::jsonb,'[]'::jsonb)) as nb_scrapling_urls,
  jsonb_array_length(COALESCE(serper_queries::jsonb,'[]'::jsonb)) as nb_serper_queries,
  ts
FROM verification_audit
WHERE nom_complet ILIKE '%Embal%'
ORDER BY ts DESC LIMIT 3
" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

# source_health_log complet
print("\n=== source_health_log Embaló — toutes les URLs ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "
SELECT url, domaine, tier, statut, http_code, longueur_texte, created_at
FROM source_health_log
WHERE nom_verifie ILIKE '%Embal%'
ORDER BY created_at DESC LIMIT 20
" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

# Chercher dans source_health_log RFI / france24 / jeuneafrique
print("\n=== source_health_log — RFI / France24 / JA (tous, 7 derniers jours) ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "
SELECT nom_verifie, url, statut, http_code
FROM source_health_log
WHERE (domaine ILIKE '%rfi%' OR domaine ILIKE '%france24%' OR domaine ILIKE '%jeuneafrique%')
  AND created_at > now() - interval '7 days'
ORDER BY created_at DESC LIMIT 20
" 2>&1""")
print(o.read().decode("utf-8", errors="replace") or "(aucune URL RFI/France24/JA scrapée)")

ssh.close()
