import paramiko, sys, io, textwrap
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

SCRIPT = textwrap.dedent("""
    import sys
    sys.path.insert(0, '/root/screen_edge')
    from pep_agent import verifier_pep
    r = verifier_pep("assimi", "goita", stocker=False)
    print("\\n--- RÉSULTAT ---")
    d = r.model_dump()
    for k in ("nom","prenom","pays","statut_mandat","fonction","source_url","source_type"):
        print(f"  {k}: {d.get(k)}")
""")

sftp = ssh.open_sftp()
with sftp.open("/tmp/_test_sl.py", "w") as f:
    f.write(SCRIPT)
sftp.close()

print("=== Vérification Assimi Goïta ===")
_, stdout, _ = ssh.exec_command(
    "cd /root/screen_edge && python3 /tmp/_test_sl.py 2>&1", timeout=180
)
stdout.channel.settimeout(180)
out = stdout.read().decode("utf-8", errors="replace")
# Afficher uniquement les lignes clés
for line in out.splitlines():
    if any(k in line for k in ["SourceLog","Audit","RÉSULTAT","---","PEP","Statut","statut","fonction",
                                 "source","Scrapling","Tier 1","URLs off","Tier 3","nomination",
                                 "TEST","===","nom","prenom","pays"]):
        print(line)

print("\n\n=== source_health_log (10 dernières lignes) ===")
PG = "PGPASSWORD=Akarkababdo@2004 psql -U postgres -d compliance_db"
_, o, _ = ssh.exec_command(
    f"{PG} -c \"SELECT domaine, statut, http_code, duree_ms, est_source_off, LEFT(erreur,60) "
    f"FROM source_health_log ORDER BY created_at DESC LIMIT 15\" 2>&1"
)
print(o.read().decode("utf-8", errors="replace"))

print("\n=== notifications source_indisponible ===")
_, o, _ = ssh.exec_command(
    f"{PG} -c \"SELECT titre, LEFT(message,100) FROM notifications "
    f"WHERE type='source_indisponible' ORDER BY date_creation DESC LIMIT 5\" 2>&1"
)
print(o.read().decode("utf-8", errors="replace"))

ssh.close()
