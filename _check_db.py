import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

def sql(label, q):
    _, o, e = ssh.exec_command(f"psql -U postgres -d compliance_db -c \"{q}\"")
    r = o.read().decode("utf-8", errors="replace").strip()
    err = e.read().decode("utf-8", errors="replace").strip()
    print(f"\n=== {label} ===")
    print(r if r else f"ERREUR: {err}")

sql("TABLE PEP", "SELECT prenom, nom, code_iso, est_pep, statut_mandat, date_naissance, lieu_naissance FROM pep ORDER BY created_at DESC LIMIT 20")
sql("COUNTS", "SELECT (SELECT COUNT(*) FROM pep) as total_pep, (SELECT COUNT(*) FROM verification_audit) as total_audit")
sql("FAUX POSITIFS RESTANTS", "SELECT prenom, nom, code_iso FROM pep WHERE statut_mandat IS NULL OR fonctions_historiques = '{}'")

ssh.close()
