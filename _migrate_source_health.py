import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)

SQL = """
CREATE TABLE IF NOT EXISTS source_health_log (
    id              SERIAL PRIMARY KEY,
    nom_verifie     TEXT        NOT NULL,
    code_iso        CHAR(2),
    url             TEXT        NOT NULL,
    domaine         TEXT        NOT NULL,
    tier            VARCHAR(20) DEFAULT 'scrapling',
    statut          VARCHAR(20) NOT NULL,
    http_code       INTEGER,
    duree_ms        INTEGER,
    erreur          TEXT,
    est_source_off  BOOLEAN     DEFAULT FALSE,
    created_at      TIMESTAMP   DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_shl_domaine  ON source_health_log(domaine, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shl_statut   ON source_health_log(statut,  created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shl_nom      ON source_health_log(nom_verifie, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shl_off_ko   ON source_health_log(est_source_off, statut, created_at DESC);
"""

PG = "PGPASSWORD=Akarkababdo@2004 psql -U postgres -d compliance_db"
_, o, e = ssh.exec_command(f"{PG} -c \"{SQL}\" 2>&1")
out = o.read().decode("utf-8", errors="replace")
err = e.read().decode("utf-8", errors="replace")
print("Migration:", out or "OK")
if err:
    print("ERR:", err)

# Vérification
_, o, _ = ssh.exec_command(f"{PG} -c \"\\d source_health_log\" 2>&1")
print("\n=== source_health_log ===")
print(o.read().decode("utf-8", errors="replace"))
ssh.close()
