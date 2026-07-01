import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

cmd = r"""cd /root/screen_edge && python3 -c "
import psycopg2, json
conn = psycopg2.connect(dbname='compliance_db', user='postgres', password='Akarkababdo@2004', host='localhost')
cur = conn.cursor()

# Trouver les PEP sans entree dans verification_audit
cur.execute('''
    SELECT p.nom_complete, p.code_iso, p.source_url
    FROM pep p
    WHERE NOT EXISTS (
        SELECT 1 FROM verification_audit va
        WHERE va.nom_complet = p.nom_complete
          AND va.code_iso = p.code_iso
    )
''')
manquants = cur.fetchall()
print(f'{len(manquants)} PEP sans entree audit')

regularises = 0
for nom_complet, code_iso, source_url in manquants:
    try:
        cur.execute('''
            INSERT INTO verification_audit (
                ts, nom_complet, code_iso,
                opensanctions,
                llm_modele, llm_prompt, llm_reponse,
                est_pep, motif,
                duree_ms, tavily_appels, os_appels
            ) VALUES (
                NOW(), %s, %s,
                %s::jsonb,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s
            )
        ''', (
            nom_complet, code_iso,
            json.dumps({'confirmed': False, 'source': source_url or ''}),
            'track_b_official_source',
            '', '',
            True,
            f'Regularisation audit — scraping direct site officiel : {(source_url or '')[:300]}',
            0, 0, 0,
        ))
        regularises += 1
    except Exception as e:
        print(f'  ERREUR {nom_complet}: {e}')

conn.commit()
print(f'{regularises} entrees audit creees')

# Verifier
cur.execute('SELECT COUNT(*) FROM verification_audit')
print(f'Total verification_audit : {cur.fetchone()[0]}')

cur.execute('SELECT COUNT(*) FROM pep')
print(f'Total pep : {cur.fetchone()[0]}')

conn.close()
"
"""
_, o, e = ssh.exec_command(cmd, timeout=60)
print(o.read().decode("utf-8", errors="replace"))
err = e.read().decode("utf-8", errors="replace")
if err.strip(): print("STDERR:", err[:500])
ssh.close()
