import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

cmd = r"""cd /root/screen_edge && python3 -c "
import psycopg2
conn = psycopg2.connect(dbname='compliance_db', user='postgres', password='Akarkababdo@2004', host='localhost')
cur = conn.cursor()

# Avant
cur.execute('SELECT COUNT(*) FROM pep')
avant_pep = cur.fetchone()[0]
cur.execute('SELECT COUNT(*) FROM verification_audit')
avant_audit = cur.fetchone()[0]
print(f'AVANT : {avant_pep} PEP | {avant_audit} lignes audit')

# PEP a supprimer = ceux dont TOUTES les entrees audit sont track_b_official_source
# (pas de vraie verification IA)
cur.execute('''
    SELECT p.nom_complete, p.code_iso, p.source_url
    FROM pep p
    WHERE NOT EXISTS (
        SELECT 1 FROM verification_audit va
        WHERE va.nom_complet = p.nom_complete
          AND va.code_iso = p.code_iso
          AND va.llm_modele != 'track_b_official_source'
    )
''')
a_supprimer = cur.fetchall()
print(f'PEP a supprimer (sans verification IA) : {len(a_supprimer)}')

# Supprimer les entrees audit backfill pour ces PEP
cur.execute('''
    DELETE FROM verification_audit
    WHERE llm_modele = 'track_b_official_source'
''')
print(f'Entrees audit backfill supprimees : {cur.rowcount}')

# Supprimer les PEP non verifies
cur.execute('''
    DELETE FROM pep
    WHERE NOT EXISTS (
        SELECT 1 FROM verification_audit va
        WHERE va.nom_complet = pep.nom_complete
          AND va.code_iso = pep.code_iso
    )
''')
print(f'PEP supprimes : {cur.rowcount}')

conn.commit()

# Apres
cur.execute('SELECT COUNT(*) FROM pep')
apres_pep = cur.fetchone()[0]
cur.execute('SELECT COUNT(*) FROM verification_audit')
apres_audit = cur.fetchone()[0]
print(f'APRES  : {apres_pep} PEP | {apres_audit} lignes audit')
print(f'=> Seuls les PEP verifies via pipeline IA restent en base.')

conn.close()
"
"""
_, o, e = ssh.exec_command(cmd, timeout=60)
print(o.read().decode("utf-8", errors="replace"))
err = e.read().decode("utf-8", errors="replace")
if err.strip(): print("STDERR:", err[:500])
ssh.close()
