import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

# Log collector
_, o, _ = ssh.exec_command("tail -80 /root/screen_edge/collector.log 2>/dev/null || echo 'PAS DE LOG COLLECTOR'")
print("=== COLLECTOR LOG ===")
print(o.read().decode("utf-8", errors="replace"))

# Etat actuel de la DB
_, o, _ = ssh.exec_command("""cd /root/screen_edge && python3 -c "
import psycopg2
conn = psycopg2.connect(dbname='compliance_db', user='postgres', password='Akarkababdo@2004', host='localhost')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM pep')
print('PEP en base:', cur.fetchone()[0])
cur.execute('SELECT COUNT(*) FROM verification_audit')
print('Audit lignes:', cur.fetchone()[0])
cur.execute(\"SELECT nom_complete, code_iso, statut_mandat FROM pep ORDER BY date_creation DESC LIMIT 10\")
print('Derniers insérés:')
for r in cur.fetchall(): print(' ', r)
conn.close()
"
""")
print("\n=== ETAT DB ===")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()
