import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

sftp = ssh.open_sftp()

# Backup
_, o, _ = ssh.exec_command("cp /root/screen_edge/search_tools.py /root/screen_edge/search_tools.py.bak")
o.read()
print("Backup search_tools.py.bak créé")

# Upload
sftp.put(
    r"C:\Users\pc\Downloads\Screen_edge\agent_aml_pep\search_tools.py",
    "/root/screen_edge/search_tools.py"
)
print("Upload search_tools.py → VPS OK")
sftp.close()

# Vérifications
checks = [
    ("Scraping media guard fix",   "grep -c '_can_scrape' /root/screen_edge/search_tools.py"),
    ("france24 dans médias T2",    "grep -c 'france24.com' /root/screen_edge/search_tools.py"),
    ("corpus_thin (no break GW)",  "grep -c '_corpus_thin' /root/screen_edge/search_tools.py"),
    ("scrapling_media tier log",   "grep -c 'scrapling_media' /root/screen_edge/search_tools.py"),
]
print()
for label, cmd in checks:
    _, o, _ = ssh.exec_command(cmd)
    count = o.read().decode("utf-8", errors="replace").strip()
    print(f"  {'✅' if int(count or 0) > 0 else '❌'} {label} : {count}")

# Syntaxe
_, o, e = ssh.exec_command("cd /root/screen_edge && python3 -m py_compile search_tools.py && echo OK")
out = o.read().decode().strip()
err = e.read().decode().strip()
print(f"\nSyntaxe Python : {'✅ OK' if out == 'OK' else '❌ ' + err}")

ssh.close()
