import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

sftp = ssh.open_sftp()

# Backup VPS
_, o, _ = ssh.exec_command("cp /root/screen_edge/pep_agent.py /root/screen_edge/pep_agent.py.bak")
o.read()
print("Backup VPS créé : pep_agent.py.bak")

# Upload le fichier local
sftp.put(
    r"C:\Users\pc\Downloads\Screen_edge\agent_aml_pep\pep_agent.py",
    "/root/screen_edge/pep_agent.py"
)
print("Upload pep_agent.py → VPS OK")

sftp.close()

# Vérifier les fixes clés
checks = [
    ("Anti-substitution identification", "grep -c 'ANTI-SUBSTITUTION' /root/screen_edge/pep_agent.py"),
    ("Règle Première dame statut",       "grep -c 'PREMIÈRE DAME.*PROCHE' /root/screen_edge/pep_agent.py"),
    ("Anti-substitution qualification",  "grep -c 'ignorer leurs fonctions' /root/screen_edge/pep_agent.py"),
    ("Règle réélection nouveau mandat",  "grep -c 'RÉÉLECTION.*NOUVEAU MANDAT' /root/screen_edge/pep_agent.py"),
    ("Règle parti vs gouvernement",      "grep -c 'RÔLE DE PARTI' /root/screen_edge/pep_agent.py"),
]
print("\nVérification post-déploiement :")
for label, cmd in checks:
    _, o, _ = ssh.exec_command(cmd)
    count = o.read().decode("utf-8", errors="replace").strip()
    status = "✅" if int(count or 0) > 0 else "❌"
    print(f"  {status} {label} : {count} occurrences")

# Test syntaxe Python
_, o, e = ssh.exec_command("cd /root/screen_edge && python3 -m py_compile pep_agent.py && echo OK")
out = o.read().decode("utf-8", errors="replace").strip()
err = e.read().decode("utf-8", errors="replace").strip()
print(f"\nSyntaxe Python : {'✅ OK' if out == 'OK' else '❌ ERREUR'}")
if err:
    print(f"  Erreur : {err}")

ssh.close()
