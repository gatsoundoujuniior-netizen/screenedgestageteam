import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)
sftp = ssh.open_sftp()

# Backup + upload api_tracker.py
_, o, _ = ssh.exec_command("cp /root/screen_edge/api_tracker.py /root/screen_edge/api_tracker.py.bak")
o.read()
print("Backup api_tracker.py.bak OK")

sftp.put(
    r"C:\Users\pc\Downloads\Screen_edge\agent_aml_pep\api_tracker.py",
    "/root/screen_edge/api_tracker.py"
)
print("Upload api_tracker.py → VPS OK")

# Upload pep_agent.py aussi
_, o, _ = ssh.exec_command("cp /root/screen_edge/pep_agent.py /root/screen_edge/pep_agent.py.bak")
o.read()
sftp.put(
    r"C:\Users\pc\Downloads\Screen_edge\agent_aml_pep\pep_agent.py",
    "/root/screen_edge/pep_agent.py"
)
print("Upload pep_agent.py → VPS OK")
sftp.close()

# Verifications
checks = [
    ("Limite tokens Groq (500k)",        "grep -c '500_000' /root/screen_edge/api_tracker.py"),
    ("Limite Gemini req/jour (20)",       "grep -c 'gemini_appels_jour' /root/screen_edge/api_tracker.py"),
    ("enregistrer_quota_reel_groq",       "grep -c 'enregistrer_quota_reel_groq' /root/screen_edge/api_tracker.py"),
    ("Capture TPD dans pep_agent",        "grep -c 'enregistrer_quota_reel' /root/screen_edge/pep_agent.py"),
    ("_is_tpd_error dans pep_agent",      "grep -c '_is_tpd_error' /root/screen_edge/pep_agent.py"),
]
print("\nVerification post-deploy :")
for label, cmd in checks:
    _, o, _ = ssh.exec_command(cmd)
    count = o.read().decode("utf-8", errors="replace").strip()
    status = "OK" if int(count or 0) > 0 else "MANQUE"
    print(f"  [{status}] {label} : {count}")

# Syntaxe Python
for f in ["api_tracker.py", "pep_agent.py"]:
    _, o, e = ssh.exec_command(f"cd /root/screen_edge && python3 -m py_compile {f} && echo OK")
    out = o.read().decode().strip()
    err = e.read().decode().strip()
    print(f"  Syntaxe {f}: {'OK' if out == 'OK' else 'ERREUR'}")
    if err:
        print(f"    => {err}")

ssh.close()
