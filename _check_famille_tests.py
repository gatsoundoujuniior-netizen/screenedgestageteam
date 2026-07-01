import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)
PG = "PGPASSWORD=Akarkababdo@2004 psql -U postgres -d compliance_db"

print("=== Audit — 4 dernières vérifs ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "
SELECT nom_complet, code_iso, est_pep, LEFT(motif,100) motif, duree_ms
FROM verification_audit
ORDER BY ts DESC LIMIT 4
" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

print("\n=== source_health_log — proches PEP ===")
_, o, _ = ssh.exec_command(f"""{PG} -c "
SELECT nom_verifie, domaine, tier, statut
FROM source_health_log
WHERE nom_verifie ILIKE ANY(ARRAY['%Ouattara%','%Sall%','%Bazoum%','%Dominique%','%Marème%','%Hadiza%'])
  AND created_at > now() - interval '2h'
ORDER BY created_at DESC LIMIT 15
" 2>&1""")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()
