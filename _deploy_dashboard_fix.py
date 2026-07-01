import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)
sftp = ssh.open_sftp()

files = [
    (r"C:\Users\pc\Downloads\Screen_edge\agent_aml_pep\api_tracker.py",   "/root/screen_edge/api_tracker.py"),
    (r"C:\Users\pc\Downloads\Screen_edge\agent_aml_pep\dashboard_pep.py", "/root/screen_edge/dashboard_pep.py"),
]
for local, remote in files:
    bak = remote + ".bak"
    _, o, _ = ssh.exec_command(f"cp {remote} {bak}"); o.read()
    sftp.put(local, remote)
    print(f"Upload {remote.split('/')[-1]} OK")
sftp.close()

checks = [
    ("Groq tokens/jour 500k",    "grep -c 'groq_1_tokens_jour' /root/screen_edge/api_tracker.py"),
    ("GROQ_TOKENS_PAR_VERIF",    "grep -c 'GROQ_TOKENS_PAR_VERIF' /root/screen_edge/api_tracker.py"),
    ("groq_aggrege dashboard",   "grep -c 'groq_aggrege' /root/screen_edge/dashboard_pep.py"),
    ("retry_queue dashboard",    "grep -c 'retry_queue' /root/screen_edge/dashboard_pep.py"),
    ("unites tok dashboard",     "grep -c 'tok / ' /root/screen_edge/dashboard_pep.py"),
]
print("\nVerifications :")
for label, cmd in checks:
    _, o, _ = ssh.exec_command(cmd)
    count = o.read().decode().strip()
    print(f"  {'OK' if int(count or 0) > 0 else 'MANQUE'} {label}")

for f in ["api_tracker.py", "dashboard_pep.py"]:
    _, o, e = ssh.exec_command(f"cd /root/screen_edge && python3 -m py_compile {f} && echo OK")
    out = o.read().decode().strip(); err = e.read().decode().strip()
    print(f"  Syntaxe {f}: {'OK' if out=='OK' else 'ERREUR: '+err}")

# Restart Streamlit
_, o, _ = ssh.exec_command("pkill -f 'streamlit run' 2>/dev/null; sleep 1; cd /root/screen_edge && nohup streamlit run dashboard_pep.py --server.port 8501 --server.address 0.0.0.0 > /tmp/streamlit.log 2>&1 &")
o.read()
print("\nStreamlit redemarré")
ssh.close()
