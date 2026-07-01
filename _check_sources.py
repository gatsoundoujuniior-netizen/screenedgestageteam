import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

cmd = """cd /root/screen_edge && python3 -c "
import psycopg2
conn = psycopg2.connect(dbname='compliance_db', user='postgres', password='Akarkababdo@2004', host='localhost')
cur = conn.cursor()

# Origine des PEP : source_url
cur.execute('''
    SELECT
        CASE
            WHEN source_url ILIKE \'%opensanctions%\' THEN \'dump opensanctions\'
            WHEN source_url IS NULL OR source_url = \'\' THEN \'sans source\'
            ELSE \'scraping officiel\'
        END as origine,
        COUNT(*) as nb
    FROM pep
    GROUP BY 1 ORDER BY 2 DESC
''')
print('=== Origine des PEP inseres ===')
for r in cur.fetchall():
    print(f'  {r[0]:30s} : {r[1]}')

# Quelques exemples source_url
cur.execute('SELECT DISTINCT source_url FROM pep ORDER BY source_url LIMIT 15')
print()
print('=== Exemples source_url ===')
for r in cur.fetchall():
    print(f'  {str(r[0])[:100]}')

# Audit : origine des verifications
cur.execute('''
    SELECT
        CASE
            WHEN opensanctions::text ILIKE \'%opensanctions-dump%\' THEN \'candidat dump\'
            WHEN (opensanctions->>\'confirmed\')::boolean = true THEN \'OS confirme\'
            ELSE \'web/scraping\'
        END as source,
        COUNT(*) as nb,
        SUM(CASE WHEN est_pep THEN 1 ELSE 0 END) as nb_pep
    FROM verification_audit
    GROUP BY 1 ORDER BY 2 DESC
''')
print()
print('=== Origine verifications (audit) ===')
print(f'  {\"Source\":30s} | {\"Total\":8s} | {\"PEP\"}')
for r in cur.fetchall():
    print(f'  {str(r[0]):30s} | {r[1]:8d} | {r[2]}')

conn.close()
"
"""
_, o, e = ssh.exec_command(cmd)
print(o.read().decode("utf-8", errors="replace"))
err = e.read().decode("utf-8", errors="replace")
if err.strip(): print("STDERR:", err[:800])
ssh.close()
