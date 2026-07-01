import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)
PG = "PGPASSWORD=Akarkababdo@2004 psql -U postgres -d compliance_db"

print("=== Série 8 — Résultats en base ===\n")
_, o, _ = ssh.exec_command(f"""{PG} -c "
SELECT
  prenom || ' ' || nom AS nom,
  code_iso,
  statut_mandat,
  LEFT(fonction_actuelle, 55) AS fonction,
  LEFT(source_url, 60) AS source
FROM pep
WHERE nom ILIKE ANY(ARRAY['%Goïta%','%Tiani%','%Traoré%','%Doumbouya%','%Condé%','%Kaboré%','%Bazoum%','%Goita%','%Kabore%','%Conde%'])
ORDER BY date_modification DESC
" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

print("\n=== Audit série 8 — 8 dernières vérifs ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "
SELECT nom_complet, code_iso, est_pep, LEFT(motif,75) motif, duree_ms, tavily_appels
FROM verification_audit
ORDER BY ts DESC LIMIT 8
" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

print("\n=== source_health_log — médias scrapés série 8 ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "
SELECT nom_verifie, domaine, tier, statut
FROM source_health_log
WHERE nom_verifie ILIKE ANY(ARRAY['%Goïta%','%Tiani%','%Traoré%','%Doumbouya%','%Condé%','%Kaboré%','%Bazoum%','%Goita%'])
  AND created_at > now() - interval '2h'
ORDER BY created_at DESC LIMIT 20
" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()
